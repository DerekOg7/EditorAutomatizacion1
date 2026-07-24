/**
 * Puente + Emisor — AutoFaceless Studio (un solo worker)
 *
 * A) PUENTE de créditos Premium: la app manda su código de licencia, el worker
 *    verifica la firma Ed25519, descuenta del cupo mensual (KV) y reenvía a la
 *    API real con NUESTRAS claves.
 *      /gg/*   → generativelanguage.googleapis.com   (Nano Banana; licencia en ?key=)
 *      /mmx/*  → api.minimax.io                      (voz + video; licencia en Bearer)
 *      /xi/*   → api.elevenlabs.io                   (música + voz; licencia en xi-api-key)
 *      /v1/saldo → cupo restante del mes (JSON)
 *
 * B) EMISOR de licencias: webhook de LemonSqueezy. Al comprar/renovar, verifica
 *    la firma HMAC, genera la licencia Ed25519 firmada y la envía por email
 *    (Resend). Se maneja ANTES del chequeo de licencia (se autentica por HMAC).
 *      /webhook/lemonsqueezy   ·   /health
 *
 * Secretos: GEMINI_API_KEY, MINIMAX_API_KEY, MINIMAX_GROUP_ID, ELEVENLABS_API_KEY,
 *   LS_SIGNING_SECRET, LICENSE_PRIVATE_KEY_HEX, RESEND_API_KEY,
 *   EMAIL_FROM (opcional), LS_VARIANT_PRO / LS_VARIANT_PREMIUM (opcionales).
 * KV binding: CUPOS.
 */

const LLAVE_PUBLICA_HEX =
  "8df2510279dd9fcb7f348e11872242b96f341c14405d6367c302d63f99dcbda1";

const PLANES_PREMIUM = new Set(["premium", "todo", "vip", "owner", "lifetime"]);

// Cupo mensual por licencia
const CUPO_MES = { voz: 90000, imagen: 80, musica: 480, video: 4 };
// Tope diario anti-abuso: un tercio del mes
const CUPO_DIA = { voz: 30000, imagen: 27, musica: 160, video: 2 };
const NOMBRE = { voz: "caracteres de voz", imagen: "imágenes",
                 musica: "segundos de música", video: "clips de video" };

// Emisor
const DIAS_GRACIA = 3;
const EVENTOS_EMITIR = new Set(["subscription_created", "subscription_payment_success"]);

// ---------------------------------------------------------------- utilidades
const enc = new TextEncoder();

function b64uDec(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  s += "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function b64u(b) {
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function hexABytes(hex) {
  const out = new Uint8Array(hex.trim().length / 2);
  for (let i = 0; i < out.length; i++)
    out[i] = parseInt(hex.trim().slice(i * 2, i * 2 + 2), 16);
  return out;
}
function json(objeto, status = 200) {
  return new Response(JSON.stringify(objeto), {
    status, headers: { "Content-Type": "application/json" },
  });
}
// Igual que json() pero permite que un navegador de otro dominio (la landing) lea
// la respuesta. Solo lo necesita /promo, que se llama desde el navegador.
function jsonCORS(objeto, status = 200) {
  return new Response(JSON.stringify(objeto), {
    status, headers: { "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*" },
  });
}

// -------------------------------------------------------------- licencia (verificar)
async function verificarLicencia(codigo) {
  try {
    codigo = (codigo || "").trim().replace(/\s+/g, "");
    const partes = codigo.split(".");
    if (partes.length !== 3 || partes[0] !== "AFS1")
      return { ok: false, razon: "formato" };
    const payload = b64uDec(partes[1]);
    const firma = b64uDec(partes[2]);
    const llave = await crypto.subtle.importKey(
      "raw", hexABytes(LLAVE_PUBLICA_HEX), { name: "Ed25519" }, false, ["verify"]);
    const valida = await crypto.subtle.verify("Ed25519", llave, firma, payload);
    if (!valida) return { ok: false, razon: "firma" };
    const datos = JSON.parse(new TextDecoder().decode(payload));
    const vence = new Date(datos.exp + "T23:59:59Z");
    if (isNaN(vence.getTime())) return { ok: false, razon: "fecha" };
    if (vence < new Date()) return { ok: false, razon: "vencida" };
    if (!PLANES_PREMIUM.has(datos.plan)) return { ok: false, razon: "no_premium" };
    return { ok: true, id: datos.id, plan: datos.plan, exp: datos.exp };
  } catch (e) {
    return { ok: false, razon: "error" };
  }
}

function extraerLicencia(request, url) {
  const h = request.headers;
  const auth = h.get("Authorization") || "";
  if (auth.startsWith("Bearer ")) return auth.slice(7);
  return h.get("X-Licencia") || h.get("xi-api-key") ||
         url.searchParams.get("key") || "";
}

// -------------------------------------------------------------- cupos (KV)
function mesActual() { return new Date().toISOString().slice(0, 7); }
function diaActual() { return new Date().toISOString().slice(0, 10); }

async function leerUso(env, id) {
  const [mes, dia] = await Promise.all([
    env.CUPOS.get(`m:${id}:${mesActual()}`, "json"),
    env.CUPOS.get(`d:${id}:${diaActual()}`, "json"),
  ]);
  return { mes: mes || {}, dia: dia || {} };
}

async function cobrar(env, id, categoria, cantidad) {
  const uso = await leerUso(env, id);
  const usadoMes = uso.mes[categoria] || 0;
  const usadoDia = uso.dia[categoria] || 0;
  if (usadoMes + cantidad > CUPO_MES[categoria])
    return { ok: false, error: `Cupo mensual de ${NOMBRE[categoria]} agotado ` +
      `(${CUPO_MES[categoria]}/mes). Se renueva el día 1, o usa tu propia clave (BYOK).` };
  if (usadoDia + cantidad > CUPO_DIA[categoria])
    return { ok: false, error: `Tope diario de ${NOMBRE[categoria]} alcanzado ` +
      `(${CUPO_DIA[categoria]}/día). Vuelve mañana o usa tu propia clave.` };
  uso.mes[categoria] = usadoMes + cantidad;
  uso.dia[categoria] = usadoDia + cantidad;
  await Promise.all([
    env.CUPOS.put(`m:${id}:${mesActual()}`, JSON.stringify(uso.mes), { expirationTtl: 40 * 86400 }),
    env.CUPOS.put(`d:${id}:${diaActual()}`, JSON.stringify(uso.dia), { expirationTtl: 2 * 86400 }),
  ]);
  return { ok: true };
}

// -------------------------------------------------------------- proxy
async function reenviar(request, destino, headersExtra, bodyTexto) {
  const init = {
    method: request.method,
    headers: { "Content-Type": request.headers.get("Content-Type") || "application/json",
               ...headersExtra },
  };
  if (request.method !== "GET" && request.method !== "HEAD")
    init.body = bodyTexto !== undefined ? bodyTexto : await request.text();
  const r = await fetch(destino, init);
  return new Response(r.body, { status: r.status, headers: r.headers });
}

// ============================================================ EMISOR
function canon(datos) {
  return "{" + Object.keys(datos).sort()
    .map((k) => JSON.stringify(k) + ":" + JSON.stringify(datos[k])).join(",") + "}";
}

async function generarLicencia(id, plan, exp, seedHex) {
  const seed = hexABytes(seedHex);
  const jwk = { kty: "OKP", crv: "Ed25519", d: b64u(seed), x: b64u(hexABytes(LLAVE_PUBLICA_HEX)), key_ops: ["sign"], ext: true };
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "Ed25519" }, false, ["sign"]);
  const pb = enc.encode(canon({ id: String(id), exp: String(exp), plan: String(plan) }));
  const sig = new Uint8Array(await crypto.subtle.sign("Ed25519", key, pb));
  return "AFS1." + b64u(pb) + "." + b64u(sig);
}

async function firmaWebhookValida(secret, cuerpo, firmaHex) {
  if (!firmaHex || !secret) return false;
  const key = await crypto.subtle.importKey("raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  let sig;
  try { sig = hexABytes(firmaHex); } catch (_) { return false; }
  return crypto.subtle.verify("HMAC", key, sig, enc.encode(cuerpo));
}

function planDeVariante(env, attrs) {
  const vid = String(attrs.variant_id ?? "");
  if (env.LS_VARIANT_PREMIUM && vid === String(env.LS_VARIANT_PREMIUM)) return "premium";
  if (env.LS_VARIANT_PRO && vid === String(env.LS_VARIANT_PRO)) return "pro";
  const nombre = ((attrs.variant_name || "") + " " + (attrs.product_name || "")).toLowerCase();
  return nombre.includes("premium") ? "premium" : "pro";
}

async function enviarEmail(env, para, codigo, plan) {
  const from = env.EMAIL_FROM || "AutoFaceless Studio <licencias@autofaceless.studio>";
  // Nombres comerciales: pro -> "Creador en Ascenso", premium -> "Creador Pro".
  const nombrePlan = plan === "premium" ? "Creador Pro" : "Creador en Ascenso";
  // Solo ASCII para que NINGUN cliente de correo muestre caracteres raros.
  // El logo AF va en la cabecera (hospedado en la landing, HTTPS).
  const html = `
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#0f0f0f">
      <div style="text-align:center;padding:8px 0 4px">
        <img src="https://autofaceless.studio/img/icono-192.png" width="60" height="60"
             alt="AutoFaceless Studio"
             style="display:inline-block;border-radius:14px;vertical-align:middle">
        <div style="font:700 17px Arial,sans-serif;margin-top:8px">AutoFaceless
          <span style="color:#c4231b">Studio</span></div>
      </div>
      <h2 style="color:#c4231b;text-align:center;font-size:22px;margin:18px 0 6px">
        Gracias por unirte a ${nombrePlan}</h2>
      <p>Este es tu codigo de licencia. Activalo dentro de la app:</p>
      <p style="background:#f4ece6;border:1px solid #e5ddd3;border-radius:10px;padding:16px;
         font-family:ui-monospace,Menlo,monospace;font-size:13px;word-break:break-all;
         text-align:center">${codigo}</p>
      <p><b>Como activarlo:</b></p>
      <ol style="line-height:1.7">
        <li>Abre AutoFaceless Studio.</li>
        <li>Arriba a la derecha, entra a "Claves API / Licencia".</li>
        <li>Pega el codigo y dale "Activar".</li>
      </ol>
      <p style="color:#606060;font-size:13px">Tu licencia se renueva con tu suscripcion; en cada
      renovacion te llegara un codigo nuevo a este correo.</p>
      <hr style="border:none;border-top:1px solid #eee;margin:18px 0">
      <p style="color:#909090;font-size:12px;text-align:center">Dudas? Responde a este correo.
      &middot; AutoFaceless Studio</p>
    </div>`;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [para], subject: `Tu licencia de AutoFaceless ${nombrePlan}`, html }),
  });
  return r.ok;
}

// --- Promo de lanzamiento: correo -> licencia gratis de "Creador en Ascenso" ---
// Creador en Ascenso es BYOK (el usuario pone sus claves): regalar pruebas NO nos
// cuesta creditos de IA. Solo hay que evitar abuso de envio de correos.
const PROMO_DIAS = 14;      // duracion de la prueba gratis
const PROMO_PLAN = "pro";   // codigo interno de Creador en Ascenso

async function promoAscenso(request, env) {
  if (!env.LICENSE_PRIVATE_KEY_HEX || !env.RESEND_API_KEY)
    return jsonCORS({ error: "La promo no esta configurada todavia." }, 503);
  let b = {};
  try { b = await request.json(); } catch (_) {}
  const email = String(b.email || "").trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || email.length > 120)
    return jsonCORS({ error: "Escribe un correo valido." }, 400);

  // Una promo por correo: si ya se emitio, reenviamos el MISMO codigo (idempotente).
  const emailKey = `promo:${email}`;
  const previo = await env.CUPOS.get(emailKey);

  // Anti-abuso: tope por IP y por hora (solo para correos nuevos).
  if (!previo) {
    const ip = request.headers.get("CF-Connecting-IP") || "?";
    const ipKey = `promoip:${ip}:${new Date().toISOString().slice(0, 13)}`;
    const usos = parseInt(await env.CUPOS.get(ipKey) || "0", 10) || 0;
    if (usos >= 5)
      return jsonCORS({ error: "Demasiadas solicitudes. Intenta mas tarde." }, 429);
    await env.CUPOS.put(ipKey, String(usos + 1), { expirationTtl: 3600 });
  }

  const d = new Date();
  d.setUTCDate(d.getUTCDate() + PROMO_DIAS);
  const exp = d.toISOString().slice(0, 10);   // AAAA-MM-DD
  const id = "promo-" + email;
  const codigo = previo || await generarLicencia(id, PROMO_PLAN, exp, env.LICENSE_PRIVATE_KEY_HEX);

  const enviado = await enviarEmailPromo(env, email, codigo, exp);
  if (!enviado) return jsonCORS({ error: "No pudimos enviar el correo. Reintenta." }, 502);

  if (!previo) await env.CUPOS.put(emailKey, codigo, { expirationTtl: 90 * 86400 });
  return jsonCORS({ ok: true });
}

async function enviarEmailPromo(env, para, codigo, exp) {
  const from = env.EMAIL_FROM || "AutoFaceless Studio <licencias@autofaceless.studio>";
  // Solo ASCII para que NINGUN cliente de correo muestre caracteres raros.
  // El logo AF va en la cabecera (hospedado en la landing, HTTPS).
  const html = `
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#0f0f0f">
      <div style="text-align:center;padding:8px 0 4px">
        <img src="https://autofaceless.studio/img/icono-192.png" width="60" height="60"
             alt="AutoFaceless Studio"
             style="display:inline-block;border-radius:14px;vertical-align:middle">
        <div style="font:700 17px Arial,sans-serif;margin-top:8px">AutoFaceless
          <span style="color:#c4231b">Studio</span></div>
      </div>
      <h2 style="color:#c4231b;text-align:center;font-size:22px;margin:18px 0 6px">
        Tu prueba de Creador en Ascenso, gratis</h2>
      <p>Gracias por probar AutoFaceless Studio. Este es tu codigo para activar
      <b>Creador en Ascenso</b> gratis hasta el <b>${exp}</b>:</p>
      <p style="background:#f4ece6;border:1px solid #e5ddd3;border-radius:10px;padding:16px;
         font-family:ui-monospace,Menlo,monospace;font-size:13px;word-break:break-all;
         text-align:center">${codigo}</p>
      <p><b>Como activarlo:</b></p>
      <ol style="line-height:1.7">
        <li>Descarga y abre AutoFaceless Studio (Mac o Windows).</li>
        <li>Arriba a la derecha, entra a "Claves API / Licencia".</li>
        <li>Pega el codigo y dale "Activar".</li>
      </ol>
      <p style="text-align:center;margin:22px 0">
        <a href="https://autofaceless.studio"
           style="background:#c4231b;color:#fff;text-decoration:none;font:700 15px Arial,sans-serif;
                  padding:13px 26px;border-radius:12px;display:inline-block">Descargar la app</a>
      </p>
      <p style="color:#606060;font-size:13px">Con Creador en Ascenso exportas en 1080p
      sin marca de agua y conectas tus claves de IA. La prueba dura 14 dias; cuando
      quieras seguir, te suscribes desde la app.</p>
      <hr style="border:none;border-top:1px solid #eee;margin:18px 0">
      <p style="color:#909090;font-size:12px;text-align:center">Dudas? Responde a este correo.
      &middot; AutoFaceless Studio</p>
    </div>`;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from, to: [para], subject: "Tu prueba gratis de Creador en Ascenso", html }),
  });
  return r.ok;
}

// fecha de vencimiento a partir de la suscripción (renovación/fin + gracia)
function expDeSub(hastaISO) {
  const base = hastaISO ? new Date(hastaISO) : new Date(Date.now() + 35 * 86400e3);
  base.setDate(base.getDate() + DIAS_GRACIA);
  return base.toISOString().slice(0, 10);
}

// Guarda el estado actual de la suscripción en KV (para la auto-renovación).
async function snapshotSub(env, attrs) {
  const email = attrs.user_email;
  if (!email) return;
  const status = attrs.status || "active";
  const activa = ["active", "on_trial", "past_due", "cancelled"].includes(status);
  const hasta = attrs.ends_at || attrs.renews_at || null;   // ends_at si está cancelada
  await env.CUPOS.put(`sub:${email}`,
    JSON.stringify({ plan: planDeVariante(env, attrs), activa, hasta }),
    { expirationTtl: 400 * 86400 });
}

// Verifica SOLO la firma (sin exigir vigencia ni plan) — para refrescar.
async function verificarFirma(codigo) {
  try {
    codigo = (codigo || "").trim().replace(/\s+/g, "");
    const p = codigo.split(".");
    if (p.length !== 3 || p[0] !== "AFS1") return { ok: false };
    const payload = b64uDec(p[1]);
    const llave = await crypto.subtle.importKey(
      "raw", hexABytes(LLAVE_PUBLICA_HEX), { name: "Ed25519" }, false, ["verify"]);
    if (!await crypto.subtle.verify("Ed25519", llave, b64uDec(p[2]), payload))
      return { ok: false };
    const d = JSON.parse(new TextDecoder().decode(payload));
    return { ok: true, id: d.id, plan: d.plan };
  } catch (e) { return { ok: false }; }
}

async function emisorWebhook(request, env) {
  const cuerpo = await request.text();
  const firma = request.headers.get("X-Signature");
  if (!await firmaWebhookValida(env.LS_SIGNING_SECRET, cuerpo, firma))
    return json({ error: "Firma inválida." }, 401);

  let evento;
  try { evento = JSON.parse(cuerpo); } catch (_) { return json({ error: "JSON inválido." }, 400); }

  const nombreEvento = evento?.meta?.event_name || request.headers.get("X-Event-Name") || "";
  const attrs = evento?.data?.attributes || {};

  // Cualquier evento de suscripción → actualiza el estado en KV (auto-renovación).
  if (nombreEvento.startsWith("subscription")) await snapshotSub(env, attrs);

  // Solo la PRIMERA compra manda el código por correo (las renovaciones se
  // refrescan solas dentro de la app; ya no hay correo cada mes).
  if (nombreEvento === "subscription_created" && attrs.user_email) {
    const plan = planDeVariante(env, attrs);
    const codigo = await generarLicencia(attrs.user_email, plan,
      expDeSub(attrs.ends_at || attrs.renews_at), env.LICENSE_PRIVATE_KEY_HEX);
    await enviarEmail(env, attrs.user_email, codigo, plan);
  }
  return json({ ok: true, evento: nombreEvento });
}

// La app pide un código fresco si la suscripción sigue activa (auto-renovación).
async function refrescarLicencia(request, env) {
  const body = await request.json().catch(() => ({}));
  const v = await verificarFirma(body.codigo || "");
  if (!v.ok) return json({ error: "Licencia inválida." }, 401);
  const sub = await env.CUPOS.get(`sub:${v.id}`, "json");
  if (!sub || !sub.activa) return json({ activa: false });
  const codigo = await generarLicencia(v.id, sub.plan, expDeSub(sub.hasta),
                                       env.LICENSE_PRIVATE_KEY_HEX);
  return json({ activa: true, codigo, plan: sub.plan });
}

// ============================================================ worker
// --- Instalaciones (conteo anónimo) ---
async function incr(env, key, by = 1) {
  const cur = parseInt(await env.CUPOS.get(key) || "0", 10) || 0;
  const nuevo = cur + by;
  await env.CUPOS.put(key, String(nuevo));
  return nuevo;
}

async function pingInstalacion(request, env) {
  let d = {};
  try { d = await request.json(); } catch (e) {}
  const id = String(d.id || "").replace(/[^a-zA-Z0-9]/g, "").slice(0, 64);
  if (!id) return json({ ok: false }, 400);
  const so = ({ mac: "mac", win: "win", linux: "linux" })[d.so] || "otro";
  const ver = String(d.ver || "?").replace(/[^0-9A-Za-z.\-]/g, "").slice(0, 16) || "?";
  const key = `inst:${id}`;
  const ahora = new Date().toISOString();
  const existe = await env.CUPOS.get(key);
  if (!existe) {                       // instalación nueva → cuenta una vez
    await env.CUPOS.put(key, JSON.stringify({ so, ver, primero: ahora, ultimo: ahora }));
    await incr(env, "stat:total");
    await incr(env, `stat:so:${so}`);
    await incr(env, `stat:ver:${ver}`);
  } else {                             // ya contada → solo refresca "último visto"
    let rec = {}; try { rec = JSON.parse(existe); } catch (e) {}
    await env.CUPOS.put(key, JSON.stringify({
      so: rec.so || so, ver, primero: rec.primero || ahora, ultimo: ahora }));
  }
  return json({ ok: true });
}

async function leerStats(request, env, url) {
  // Opcionalmente protegido: si defines el secreto STATS_TOKEN, hay que pasar ?k=…
  if (env.STATS_TOKEN && url.searchParams.get("k") !== env.STATS_TOKEN)
    return json({ error: "no autorizado" }, 401);
  const g = async (k) => parseInt(await env.CUPOS.get(k) || "0", 10) || 0;
  const [total, mac, win, linux, otro] = await Promise.all([
    g("stat:total"), g("stat:so:mac"), g("stat:so:win"), g("stat:so:linux"), g("stat:so:otro")]);
  const versiones = {};
  try {
    const lista = await env.CUPOS.list({ prefix: "stat:ver:" });
    for (const k of lista.keys) versiones[k.name.slice(9)] = await g(k.name);
  } catch (e) {}
  return json({ instalaciones: total, por_sistema: { mac, win, linux, otro },
                por_version: versiones, nota: "conteo anonimo aproximado" });
}

// --- Medidor de exportación (minutos de video exportado al mes) ---
// Tope mensual por plan (min/mes). Los planes de arriba de "pro" son ilimitados.
const CAP_EXPORT = { free: 30, pro: 240 };
const PLANES_ILIMITADOS = new Set(["premium", "owner", "lifetime", "todo", "vip", "beta"]);

async function verificarParaExport(codigo) {
  // Verifica firma Ed25519 + vigencia y devuelve el plan (cualquiera). Una licencia
  // vencida NO cuenta (el usuario cae a Gratis).
  try {
    codigo = (codigo || "").trim().replace(/\s+/g, "");
    const p = codigo.split(".");
    if (p.length !== 3 || p[0] !== "AFS1") return { ok: false };
    const payload = b64uDec(p[1]);
    const llave = await crypto.subtle.importKey(
      "raw", hexABytes(LLAVE_PUBLICA_HEX), { name: "Ed25519" }, false, ["verify"]);
    if (!await crypto.subtle.verify("Ed25519", llave, b64uDec(p[2]), payload))
      return { ok: false };
    const d = JSON.parse(new TextDecoder().decode(payload));
    const vence = new Date((d.exp || "") + "T23:59:59Z");
    if (isNaN(vence.getTime()) || vence < new Date()) return { ok: false, vencida: true };
    return { ok: true, id: d.id, plan: d.plan, exp: d.exp };
  } catch (e) { return { ok: false }; }
}

async function _idExport(request, env, url, body) {
  // Devuelve {plan, id, ilimitado}. Paga → por licencia firmada; Gratis → por id
  // de instalación. La licencia manda (no se puede falsificar).
  const codigo = extraerLicencia(request, url) || body.codigo || "";
  if (codigo) {
    const v = await verificarParaExport(codigo);
    if (v.ok) return { plan: v.plan, id: "lic:" + v.id,
                       ilimitado: PLANES_ILIMITADOS.has(v.plan) };
  }
  const inst = String(body.inst || "").replace(/[^a-zA-Z0-9]/g, "").slice(0, 64);
  if (!inst) return null;
  return { plan: "free", id: "inst:" + inst, ilimitado: false };
}

async function exportarCobrar(request, env, url) {
  let b = {}; try { b = await request.json(); } catch (e) {}
  const minutos = Math.max(0, Math.min(600, Number(b.minutos) || 0));
  const who = await _idExport(request, env, url, b);
  if (!who) return json({ ok: false, error: "falta identificador" }, 400);
  if (who.ilimitado) return json({ ok: true, ilimitado: true });
  const cap = CAP_EXPORT[who.plan] ?? CAP_EXPORT.free;
  const key = `exp:${who.id}:${mesActual()}`;
  const usado = parseFloat(await env.CUPOS.get(key) || "0") || 0;
  if (usado + minutos > cap + 0.001)
    return json({ ok: false, restante: Math.max(0, cap - usado), cap,
                  plan: who.plan, mes: mesActual(), minutos });
  await env.CUPOS.put(key, String(usado + minutos), { expirationTtl: 40 * 86400 });
  return json({ ok: true, restante: Math.max(0, cap - (usado + minutos)), cap, plan: who.plan });
}

async function exportarSaldo(request, env, url) {
  let b = {}; try { b = await request.json(); } catch (e) {}
  const who = await _idExport(request, env, url, b);
  if (!who) return json({ ok: false, error: "falta identificador" }, 400);
  if (who.ilimitado) return json({ ok: true, ilimitado: true, plan: who.plan });
  const cap = CAP_EXPORT[who.plan] ?? CAP_EXPORT.free;
  const usado = parseFloat(await env.CUPOS.get(`exp:${who.id}:${mesActual()}`) || "0") || 0;
  return json({ ok: true, cap, usado, restante: Math.max(0, cap - usado),
                plan: who.plan, mes: mesActual() });
}

async function exportarReembolsar(request, env, url) {
  // Best-effort: si la exportación falló tras cobrar, devuelve los minutos.
  let b = {}; try { b = await request.json(); } catch (e) {}
  const minutos = Math.max(0, Number(b.minutos) || 0);
  const who = await _idExport(request, env, url, b);
  if (!who || who.ilimitado) return json({ ok: true });
  const key = `exp:${who.id}:${mesActual()}`;
  const usado = parseFloat(await env.CUPOS.get(key) || "0") || 0;
  await env.CUPOS.put(key, String(Math.max(0, usado - minutos)), { expirationTtl: 40 * 86400 });
  return json({ ok: true });
}

// --- Pexels compartido: proxy a api.pexels.com con NUESTRA clave, para que nadie
// tenga que configurar la suya. Atado al id de instalación + throttle por hora para
// que no abusen de la clave. ---
async function pexelsProxy(request, env, url) {
  if (!env.PEXELS_API_KEY) return json({ error: "pexels no configurado" }, 503);
  const inst = (request.headers.get("X-Inst") || "").replace(/[^a-zA-Z0-9]/g, "").slice(0, 64);
  if (!inst) return json({ error: "falta id" }, 400);
  const k = `px:${inst}:${new Date().toISOString().slice(0, 13)}`;   // por hora
  const usado = parseInt(await env.CUPOS.get(k) || "0", 10) || 0;
  if (usado >= 400) return json({ error: "límite temporal, intenta más tarde" }, 429);
  await env.CUPOS.put(k, String(usado + 1), { expirationTtl: 3600 });
  const destino = "https://api.pexels.com" + url.pathname.slice(3) + url.search;
  try {
    const r = await fetch(destino, { headers: { Authorization: env.PEXELS_API_KEY } });
    return new Response(r.body, { status: r.status, headers: {
      "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" } });
  } catch (e) {
    return json({ error: "pexels no respondió" }, 502);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ruta = url.pathname;

    // --- Emisor (no usa licencia; se autentica por HMAC) ---
    if (request.method === "GET" && ruta === "/health")
      return json({ ok: true, servicio: "puente+emisor AutoFaceless" });
    if (ruta === "/webhook/lemonsqueezy")
      return emisorWebhook(request, env);
    if (ruta === "/licencia/refrescar")     // auto-renovación (la app pide código fresco)
      return refrescarLicencia(request, env);

    // --- Saludo de instalación (anónimo): cuenta instalaciones reales ---
    if (request.method === "POST" && ruta === "/i")
      return pingInstalacion(request, env);
    if (request.method === "GET" && ruta === "/stats")
      return leerStats(request, env, url);

    // --- Promo de lanzamiento: correo -> licencia gratis de Creador en Ascenso ---
    if (request.method === "POST" && ruta === "/promo")
      return promoAscenso(request, env);

    // --- Medidor de exportación (minutos de video al mes) ---
    if (request.method === "POST" && ruta === "/export/cobrar")
      return exportarCobrar(request, env, url);
    if (request.method === "POST" && ruta === "/export/saldo")
      return exportarSaldo(request, env, url);
    if (request.method === "POST" && ruta === "/export/reembolsar")
      return exportarReembolsar(request, env, url);

    // --- Pexels compartido: imágenes/videos de stock sin que el usuario ponga clave ---
    if (ruta.startsWith("/px/"))
      return pexelsProxy(request, env, url);

    // --- CORS ---
    if (request.method === "OPTIONS")
      return new Response(null, { headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS" } });

    // --- Puente: requiere licencia ---
    const lic = await verificarLicencia(extraerLicencia(request, url));
    if (!lic.ok) {
      const msg = {
        formato: "Licencia inválida.", firma: "Licencia inválida (firma).",
        vencida: "Tu licencia está vencida — renuévala para seguir usando la IA incluida.",
        no_premium: "La IA incluida es del plan Premium. Tu plan actual no la incluye: " +
                    "usa tus propias claves (🔑) o mejora a Premium.",
      }[lic.razon] || "Licencia inválida.";
      return json({ error: msg }, lic.razon === "no_premium" ? 403 : 401);
    }

    if (ruta === "/v1/saldo") {
      const uso = await leerUso(env, lic.id);
      const saldo = {};
      for (const c of Object.keys(CUPO_MES))
        saldo[c] = { cupo: CUPO_MES[c], usado: uso.mes[c] || 0,
                     restante: Math.max(0, CUPO_MES[c] - (uso.mes[c] || 0)) };
      return json({ id: lic.id, plan: lic.plan, exp: lic.exp, mes: mesActual(), saldo });
    }

    // --- Gemini (Nano Banana) ---
    if (ruta.startsWith("/gg/")) {
      if (request.method === "POST" && ruta.includes(":generateContent")) {
        const cobro = await cobrar(env, lic.id, "imagen", 1);
        if (!cobro.ok) return json({ error: cobro.error }, 429);
      }
      const destino = new URL("https://generativelanguage.googleapis.com" + ruta.slice(3));
      destino.searchParams.set("key", env.GEMINI_API_KEY);
      return reenviar(request, destino.toString(), {});
    }

    // --- MiniMax (voz + video) ---
    if (ruta.startsWith("/mmx/")) {
      const camino = ruta.slice(4);
      const destino = new URL("https://api.minimax.io" + camino);
      if (env.MINIMAX_GROUP_ID) destino.searchParams.set("GroupId", env.MINIMAX_GROUP_ID);
      for (const [k, v] of url.searchParams) if (k !== "GroupId") destino.searchParams.set(k, v);
      let bodyTexto;
      if (request.method === "POST") {
        bodyTexto = await request.text();
        if (camino.startsWith("/v1/t2a_v2")) {
          let chars = 500;
          try { chars = (JSON.parse(bodyTexto).text || "").length || 500; } catch (e) {}
          const cobro = await cobrar(env, lic.id, "voz", chars);
          if (!cobro.ok) return json({ error: cobro.error }, 429);
        } else if (camino.startsWith("/v1/video_generation")) {
          const cobro = await cobrar(env, lic.id, "video", 1);
          if (!cobro.ok) return json({ error: cobro.error }, 429);
        }
      }
      return reenviar(request, destino.toString(),
                      { Authorization: `Bearer ${env.MINIMAX_API_KEY}` }, bodyTexto);
    }

    // --- ElevenLabs (música + voz premium) ---
    if (ruta.startsWith("/xi/")) {
      const camino = ruta.slice(3);
      let bodyTexto;
      if (request.method === "POST") {
        bodyTexto = await request.text();
        if (camino.startsWith("/v1/music")) {
          let seg = 60;
          try { seg = Math.ceil((JSON.parse(bodyTexto).music_length_ms || 60000) / 1000); } catch (e) {}
          const cobro = await cobrar(env, lic.id, "musica", seg);
          if (!cobro.ok) return json({ error: cobro.error }, 429);
        } else if (camino.startsWith("/v1/text-to-speech")) {
          let chars = 500;
          try { chars = (JSON.parse(bodyTexto).text || "").length || 500; } catch (e) {}
          const cobro = await cobrar(env, lic.id, "voz", Math.ceil(chars * 1.8));
          if (!cobro.ok) return json({ error: cobro.error }, 429);
        }
      }
      return reenviar(request, "https://api.elevenlabs.io" + camino + url.search,
                      { "xi-api-key": env.ELEVENLABS_API_KEY }, bodyTexto);
    }

    return json({ error: "Ruta desconocida." }, 404);
  },
};
