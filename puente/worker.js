/**
 * Puente de créditos Premium — AutoFaceless Studio
 *
 * Un proxy con cupos: la app manda su código de licencia como "clave", el
 * worker verifica la firma Ed25519 (misma llave pública que la app), descuenta
 * del cupo mensual y reenvía la petición a la API real con NUESTRAS claves.
 *
 * Rutas (espejo de cada proveedor, así la app no cambia su lógica):
 *   /gg/*   → generativelanguage.googleapis.com   (Nano Banana; licencia va en ?key=)
 *   /mmx/*  → api.minimax.io                      (voz + video; licencia en Bearer)
 *   /xi/*   → api.elevenlabs.io                   (música + voz; licencia en xi-api-key)
 *   /v1/saldo → cupo restante del mes (JSON)
 *
 * Secretos (wrangler secret put …): GEMINI_API_KEY, MINIMAX_API_KEY,
 * MINIMAX_GROUP_ID, ELEVENLABS_API_KEY.  KV binding: CUPOS.
 */

const LLAVE_PUBLICA_HEX =
  "8df2510279dd9fcb7f348e11872242b96f341c14405d6367c302d63f99dcbda1";

const PLANES_PREMIUM = new Set(["premium", "todo", "vip", "owner", "lifetime"]);

// Cupo mensual por licencia (decidido en docs/estrategia_precios.md)
const CUPO_MES = { voz: 90000, imagen: 80, musica: 480, video: 4 };
// Tope diario anti-abuso: un tercio del mes
const CUPO_DIA = { voz: 30000, imagen: 27, musica: 160, video: 2 };
const NOMBRE = { voz: "caracteres de voz", imagen: "imágenes",
                 musica: "segundos de música", video: "clips de video" };

// ---------------------------------------------------------------- utilidades

function b64uDec(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  s += "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function hexABytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++)
    out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function json(objeto, status = 200) {
  return new Response(JSON.stringify(objeto), {
    status, headers: { "Content-Type": "application/json" },
  });
}

// -------------------------------------------------------------- licencia

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

function mesActual() { return new Date().toISOString().slice(0, 7); }    // YYYY-MM
function diaActual() { return new Date().toISOString().slice(0, 10); }   // YYYY-MM-DD

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
    env.CUPOS.put(`m:${id}:${mesActual()}`, JSON.stringify(uso.mes),
                  { expirationTtl: 40 * 86400 }),
    env.CUPOS.put(`d:${id}:${diaActual()}`, JSON.stringify(uso.dia),
                  { expirationTtl: 2 * 86400 }),
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ruta = url.pathname;

    // CORS básico (la app es local, pero por si acaso)
    if (request.method === "OPTIONS")
      return new Response(null, { headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS" } });

    // 1) licencia
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

    // 2) saldo
    if (ruta === "/v1/saldo") {
      const uso = await leerUso(env, lic.id);
      const saldo = {};
      for (const c of Object.keys(CUPO_MES))
        saldo[c] = { cupo: CUPO_MES[c], usado: uso.mes[c] || 0,
                     restante: Math.max(0, CUPO_MES[c] - (uso.mes[c] || 0)) };
      return json({ id: lic.id, plan: lic.plan, exp: lic.exp, mes: mesActual(),
                    saldo });
    }

    // 3) rutas proxy con su cobro
    // --- Gemini (Nano Banana) ---
    if (ruta.startsWith("/gg/")) {
      if (request.method === "POST" && ruta.includes(":generateContent")) {
        const cobro = await cobrar(env, lic.id, "imagen", 1);
        if (!cobro.ok) return json({ error: cobro.error }, 429);
      }
      const destino = new URL("https://generativelanguage.googleapis.com" +
                              ruta.slice(3));
      destino.searchParams.set("key", env.GEMINI_API_KEY);
      return reenviar(request, destino.toString(), {});
    }

    // --- MiniMax (voz + video) ---
    if (ruta.startsWith("/mmx/")) {
      const camino = ruta.slice(4);
      const destino = new URL("https://api.minimax.io" + camino);
      // GroupId lo pone el worker (la app lo manda vacío en modo puente)
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
          try { seg = Math.ceil((JSON.parse(bodyTexto).music_length_ms || 60000) / 1000); }
          catch (e) {}
          const cobro = await cobrar(env, lic.id, "musica", seg);
          if (!cobro.ok) return json({ error: cobro.error }, 429);
        } else if (camino.startsWith("/v1/text-to-speech")) {
          let chars = 500;
          try { chars = (JSON.parse(bodyTexto).text || "").length || 500; } catch (e) {}
          // Eleven cuesta ~1.8× MiniMax → consume más cupo (documentado en la UI)
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
