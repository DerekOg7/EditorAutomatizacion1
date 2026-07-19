# Puente de créditos Premium

El servicio que hace posible el plan **Premium ($24.99/mes)**: la app manda su
código de licencia, este worker verifica la firma Ed25519 (misma llave pública
que la app), descuenta del cupo mensual y reenvía la petición a la API real con
**nuestras** claves. El usuario nunca ve ni necesita claves propias.

## Cupos (por licencia, por mes)

| Categoría | Cupo mensual | Tope diario |
|---|---|---|
| Voz (caracteres) | 90,000 | 30,000 |
| Imágenes Nano Banana | 80 | 27 |
| Música (segundos) | 480 (8 min) | 160 |
| Clips de video Hailuo | 4 | 2 |

La voz con ElevenLabs consume 1.8× caracteres (su API cuesta casi el doble).
Los cupos viven en `worker.js` (CUPO_MES / CUPO_DIA) — cambiarlos y redeploy.

## Desplegar (una vez, ~10 minutos)

```bash
cd puente
# 1) cuenta de Cloudflare (gratis) + wrangler
npx wrangler login

# 2) el KV de cupos → pega el id que devuelva en wrangler.toml
npx wrangler kv namespace create CUPOS

# 3) NUESTRAS claves de las APIs (las que pagan las generaciones Premium)
npx wrangler secret put GEMINI_API_KEY
npx wrangler secret put MINIMAX_API_KEY
npx wrangler secret put MINIMAX_GROUP_ID
npx wrangler secret put ELEVENLABS_API_KEY

# 4) publicar
npx wrangler deploy
# → te da la URL, p.ej. https://puente-autofaceless.<tu-cuenta>.workers.dev
```

Luego pon esa URL en `editor.py` (constante `PUENTE_URL`) y re-empaqueta, o
exporta `AFS_PUENTE_URL` para probar sin reempaquetar.

## Emitir licencias Premium

Las licencias con plan `premium` (o `todo`/`vip`/`owner`/`lifetime`) pasan el
puente; cualquier otro plan recibe 403 con mensaje claro.

```bash
.venv/bin/python scripts/generar_licencia.py cliente@correo.com 2027-08-01 premium
```

## Verificado

El `worker.js` se probó ejecutándolo en Deno (mismo WebCrypto/fetch que
Cloudflare Workers) con licencias reales: 9/9 casos OK — verificación Ed25519,
rechazo de planes no-premium (403), reenvío a cada API con la clave correcta, y
corte por cupo (429). El deploy debería funcionar a la primera.

## Probar

```bash
# saldo (con un código premium válido)
curl -H "X-Licencia: AFS1...." https://TU-WORKER.workers.dev/v1/saldo
```

La app también expone `GET /api/premium/saldo` (lee el puente con la licencia
instalada) — útil para mostrar el cupo restante en la UI.

## Cómo se conecta la app (ya implementado)

Cuando la licencia instalada es Premium y el usuario NO tiene clave propia:
- Voz/video MiniMax → `PUENTE_URL/mmx/...` (licencia como Bearer)
- Imagen Nano Banana → `PUENTE_URL/gg/...` (licencia como ?key=)
- Música/voz ElevenLabs → `PUENTE_URL/xi/...` (licencia como xi-api-key)

Si el usuario SÍ tiene clave propia, se usa la suya (no gasta cupo). Si el cupo
se agota, el worker responde 429 con un mensaje que la app muestra tal cual.
