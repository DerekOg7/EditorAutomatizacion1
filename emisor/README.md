# Emisor de licencias (cobros automáticos)

Cierra el círculo del negocio: cuando alguien **compra** una suscripción en
LemonSqueezy, este worker de Cloudflare **genera la licencia Ed25519 firmada y se
la envía por email** al instante (con Resend). Cero intervención manual.

Verificado end-to-end en Deno (6/6): firma HMAC del webhook, generación de
licencia Pro/Premium según la variante, y el código emitido pasa la validación
offline de la app.

## Cómo encaja

```
Cliente compra en LemonSqueezy
        │  (webhook subscription_created / subscription_payment_success)
        ▼
Worker "emisor"  ──> verifica firma HMAC
        │           genera licencia Ed25519 (Pro/Premium)
        │           vence = próxima renovación + 3 días
        ▼
Resend  ──> email con el código al cliente
        ▼
Cliente pega el código en la app (🔑) → activado
```

Cada **renovación** mensual dispara un email con un código fresco (por eso los
planes **anuales** son más cómodos: un solo código al año). Al **cancelar**, no
se emite nada y la licencia caduca sola.

## Puesta en marcha (una vez)

### 1. LemonSqueezy — productos
1. Crea cuenta en **lemonsqueezy.com** → crea tu **Store**.
2. Crea 2 productos de **suscripción**:
   - **AutoFaceless Pro** — variantes: $14.99/mes y $149/año.
   - **AutoFaceless Premium** — variantes: $24.99/mes y $249/año.
3. Anota el **ID de cada variante** (aparece en la URL o en la API). Los usarás
   como secretos `LS_VARIANT_PRO` y `LS_VARIANT_PREMIUM` (usa el de la mensual;
   si el nombre incluye "Premium"/"Pro" el worker igual acierta por respaldo).
4. Copia los **links de checkout** de cada variante (botón "Share / Buy link")
   → van en los botones de la landing.

### 2. Resend — email
1. Crea cuenta en **resend.com**.
2. **Domains → Add domain → autofaceless.studio** → te da unos registros DNS
   (SPF/DKIM). Agrégalos en **Netlify → Domains → autofaceless.studio → DNS**.
3. Cuando el dominio quede "Verified", crea una **API key**.

### 3. Desplegar el worker (panel de Cloudflare, como el puente)
1. Workers & Pages → **Create application** → Worker → nómbralo **`emisor-autofaceless`**.
2. **Edit code** → pega `emisor/worker.js` → **Deploy**.
3. **Settings → Variables and Secrets** → agrega (tipo Secret):
   - `LS_SIGNING_SECRET` — (lo obtienes en el paso 4)
   - `LICENSE_PRIVATE_KEY_HEX` — el contenido de `LLAVE_PRIVADA_NO_COMPARTIR.hex`
   - `RESEND_API_KEY` — la clave de Resend
   - `LS_VARIANT_PRO`, `LS_VARIANT_PREMIUM` — los IDs de variante
   - `EMAIL_FROM` — `AutoFaceless Studio <licencias@autofaceless.studio>`
4. **Deploy** de nuevo. URL: `https://emisor-autofaceless.derekog7.workers.dev`.

### 4. LemonSqueezy — webhook
1. LemonSqueezy → **Settings → Webhooks → Add endpoint**.
2. URL: `https://emisor-autofaceless.derekog7.workers.dev/webhook/lemonsqueezy`.
3. Marca los eventos: **subscription_created** y **subscription_payment_success**.
4. Copia el **Signing secret** que te da → es el `LS_SIGNING_SECRET` del paso 3.

### 5. Landing — botones de compra
En `landing/index.html`, en la sección de precios, reemplaza los `href` de los
botones "Suscribirme" (Pro y Premium) por tus links de checkout de LemonSqueezy.
Vuelve a publicar (arrastrar la carpeta a Netlify).

## Seguridad

⚠️ El worker guarda la **llave privada** (`LICENSE_PRIVATE_KEY_HEX`) como secreto
cifrado en Cloudflare. Es lo que permite firmar licencias sin intervención. Riesgo
aceptable para empezar (cifrada, solo la lee el worker), pero es la joya de la
corona: si algún día se compromete, rota la llave (nueva pareja Ed25519, actualiza
`LLAVE_PUBLICA_HEX` en la app + el puente + este worker, y re-empaqueta).

## Probar

```bash
curl https://emisor-autofaceless.derekog7.workers.dev/health   # {ok:true,...}
```
Y una compra real de prueba en modo test de LemonSqueezy debe llegarte al correo.

## Limitación conocida (mejora futura)

Los suscriptores **mensuales** reciben un código nuevo cada mes y deben re-pegarlo.
Para evitarlo: (a) empujar planes anuales, o (b) añadir a la app un "auto-refresh"
que, al estar online, pida un código fresco a un endpoint por su id de suscripción.
