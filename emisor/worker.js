/**
 * Emisor de licencias — AutoFaceless Studio
 *
 * Webhook de LemonSqueezy: cuando alguien compra (o renueva) una suscripción,
 * este worker verifica la firma del webhook, genera una licencia Ed25519 firmada
 * (la misma que valida la app, offline) y se la envía por email al cliente con
 * Resend. Todo automático — el cliente recibe su código en segundos.
 *
 * Secretos (wrangler/dashboard):
 *   LS_SIGNING_SECRET      — el "signing secret" del webhook de LemonSqueezy
 *   LICENSE_PRIVATE_KEY_HEX— la semilla Ed25519 (32 bytes hex) que firma licencias
 *   RESEND_API_KEY         — clave de Resend para enviar el correo
 *   LS_VARIANT_PRO         — (opcional) id de la variante Pro en LemonSqueezy
 *   LS_VARIANT_PREMIUM     — (opcional) id de la variante Premium
 *   EMAIL_FROM             — (opcional) remitente, p.ej. "AutoFaceless <licencias@autofaceless.studio>"
 */

const PUB_HEX = "8df2510279dd9fcb7f348e11872242b96f341c14405d6367c302d63f99dcbda1";
const DIAS_GRACIA = 3;              // días extra tras la renovación
const EVENTOS_EMITIR = new Set(["subscription_created", "subscription_payment_success"]);

// ---------------------------------------------------------------- utilidades
const enc = new TextEncoder();
const hex2b = (h) => Uint8Array.from(h.trim().match(/../g).map((x) => parseInt(x, 16)));
const b2hex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
const b64u = (b) => btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
function json(o, s = 200) { return new Response(JSON.stringify(o), { status: s, headers: { "Content-Type": "application/json" } }); }

// JSON canónico idéntico al de Python (claves ordenadas, compacto)
function canon(datos) {
  return "{" + Object.keys(datos).sort()
    .map((k) => JSON.stringify(k) + ":" + JSON.stringify(datos[k])).join(",") + "}";
}

// ---------------------------------------------------------------- licencia
async function generarLicencia(id, plan, exp, seedHex) {
  const seed = hex2b(seedHex);
  const jwk = { kty: "OKP", crv: "Ed25519", d: b64u(seed), x: b64u(hex2b(PUB_HEX)), key_ops: ["sign"], ext: true };
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "Ed25519" }, false, ["sign"]);
  const pb = enc.encode(canon({ id: String(id), exp: String(exp), plan: String(plan) }));
  const sig = new Uint8Array(await crypto.subtle.sign("Ed25519", key, pb));
  return "AFS1." + b64u(pb) + "." + b64u(sig);
}

// ---------------------------------------------------------------- webhook LS
async function firmaValida(secret, cuerpo, firmaHex) {
  if (!firmaHex) return false;
  const key = await crypto.subtle.importKey("raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  let sig;
  try { sig = hex2b(firmaHex); } catch (_) { return false; }
  return crypto.subtle.verify("HMAC", key, sig, enc.encode(cuerpo));
}

function planDeVariante(env, attrs) {
  const vid = String(attrs.variant_id ?? "");
  if (env.LS_VARIANT_PREMIUM && vid === String(env.LS_VARIANT_PREMIUM)) return "premium";
  if (env.LS_VARIANT_PRO && vid === String(env.LS_VARIANT_PRO)) return "pro";
  // respaldo: por el nombre de la variante/producto
  const nombre = ((attrs.variant_name || "") + " " + (attrs.product_name || "")).toLowerCase();
  return nombre.includes("premium") ? "premium" : "pro";
}

// ---------------------------------------------------------------- email
async function enviarEmail(env, para, codigo, plan) {
  const from = env.EMAIL_FROM || "AutoFaceless Studio <licencias@autofaceless.studio>";
  const nombrePlan = plan === "premium" ? "Premium" : "Pro";
  const html = `
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#0f0f0f">
      <h2 style="color:#c4231b">¡Gracias por unirte a AutoFaceless ${nombrePlan}! 🎬</h2>
      <p>Aquí está tu código de licencia. Actívalo dentro de la app:</p>
      <p style="background:#f4ece6;border:1px solid #e5e5e5;border-radius:8px;padding:14px;
         font-family:ui-monospace,Menlo,monospace;font-size:13px;word-break:break-all">${codigo}</p>
      <p><b>Cómo activarlo:</b></p>
      <ol style="line-height:1.7">
        <li>Abre AutoFaceless Studio.</li>
        <li>Arriba a la derecha, entra a <b>🔑 Claves API / Licencia</b>.</li>
        <li>Pega el código y dale <b>Activar</b>.</li>
      </ol>
      <p style="color:#606060;font-size:13px">Tu licencia se renueva automáticamente con tu suscripción.
      Cada renovación te enviaremos un código fresco a este correo.</p>
      <p style="color:#909090;font-size:12px">¿Dudas? Responde a este correo. — AutoFaceless Studio</p>
    </div>`;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [para], subject: `Tu licencia de AutoFaceless ${nombrePlan}`, html }),
  });
  return r.ok;
}

// ---------------------------------------------------------------- worker
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health")
      return json({ ok: true, servicio: "emisor de licencias" });

    if (request.method !== "POST" || url.pathname !== "/webhook/lemonsqueezy")
      return json({ error: "Ruta desconocida." }, 404);

    const cuerpo = await request.text();
    const firma = request.headers.get("X-Signature");
    if (!await firmaValida(env.LS_SIGNING_SECRET, cuerpo, firma))
      return json({ error: "Firma inválida." }, 401);

    let evento;
    try { evento = JSON.parse(cuerpo); } catch (_) { return json({ error: "JSON inválido." }, 400); }

    const nombreEvento = evento?.meta?.event_name || request.headers.get("X-Event-Name") || "";
    if (!EVENTOS_EMITIR.has(nombreEvento))
      return json({ ok: true, ignorado: nombreEvento });   // evento que no nos interesa: 200 para que LS no reintente

    const attrs = evento?.data?.attributes || {};
    const email = attrs.user_email;
    if (!email) return json({ error: "Sin email en el evento." }, 400);

    const plan = planDeVariante(env, attrs);
    // vence en la próxima renovación + gracia (así cada pago manda un código fresco)
    const base = attrs.renews_at ? new Date(attrs.renews_at) : new Date(Date.now() + 35 * 86400e3);
    base.setDate(base.getDate() + DIAS_GRACIA);
    const exp = base.toISOString().slice(0, 10);   // YYYY-MM-DD

    const codigo = await generarLicencia(email, plan, exp, env.LICENSE_PRIVATE_KEY_HEX);
    const enviado = await enviarEmail(env, email, codigo, plan);
    if (!enviado) return json({ error: "Licencia generada pero el email falló." }, 502);

    return json({ ok: true, plan, exp, email });
  },
};
