# Página de aterrizaje — lista de espera de la beta

Página estática de una sola pantalla (`index.html`), sin backend propio.
Recolecta correos de la lista de espera mediante un formulario ya hosteado
(Formspree) — no hay servidor que mantener.

## 1. Crear el formulario en Formspree (gratis)

1. Entra a <https://formspree.io> y crea una cuenta gratis.
2. Crea un formulario nuevo (New Form) — el plan gratis alcanza para una beta.
3. Copia el **ID del formulario** (la parte final de la URL que te dan, algo
   como `xzkabcde`).
4. Abre `index.html`, busca la línea:

   ```js
   const FORMSPREE_ID = "TU_ID_DE_FORMSPREE";
   ```

   y reemplázala por tu ID real.

Cada correo que alguien envíe en la página te llegará a tu email y quedará
guardado en el panel de Formspree.

## 2. Publicar la página (gratis)

Con Netlify (recomendado, no requiere terminal):

1. Crea una cuenta gratis en <https://app.netlify.com>.
2. En el panel, arrastra esta carpeta (`landing/`) al área de "Deploy manually".
3. Netlify te da una URL del tipo `https://algo-al-azar.netlify.app` — ya
   está en vivo. Puedes renombrar el subdominio en Site settings → Domain
   management → Options → Edit site name.
4. Cuando tengas un dominio propio, se conecta desde esa misma pantalla sin
   tener que volver a subir nada.

Alternativa igual de válida: Vercel (drag & drop en <https://vercel.com/new>)
o GitHub Pages si el sitio ya vive en un repositorio.

## 3. Actualizar el enlace de descarga

Cuando el `.app` esté listo para compartirse (ver `../empaquetar.spec` y las
instrucciones de empaquetado), sube el archivo comprimido a donde lo vayas a
alojar (Google Drive, un bucket, GitHub Releases) y cambia el botón
"Unirme a la beta gratuita" para que apunte directo a la descarga en vez de
al formulario, si prefieres saltarte la lista de espera.
