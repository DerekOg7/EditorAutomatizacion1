# AutoFaceless Video — editor automático de videos faceless

Convierte el audio de una historia (MiniMax) en un video 1080p con imágenes
sincronizadas (escenas de 5-10s), efecto Ken Burns (zoom lento) y fundidos,
y une las 3 historias en el video final de ~30 min para YouTube.

## App empaquetada para macOS (beta)

Para compartir el editor como una app de doble clic (sin terminal, sin Python
instalado) — pensada para la beta gratuita:

```bash
cd ~/Documents/CLAUDE/EditorAutomatizacion
rm -rf build dist
.venv/bin/pyinstaller empaquetar.spec --noconfirm
```

Genera `dist/AutoFaceless Video.app` (~370 MB, incluye Python, ffmpeg
estático y las dependencias de Whisper). Para compartirlo, comprime esa
carpeta en un `.zip`.

**Notas importantes:**
- No está firmado (no hay cuenta de Apple Developer todavía) — quien lo abra
  por primera vez debe hacer clic derecho → Abrir para saltarse el aviso de
  Gatekeeper de "desarrollador no identificado".
- Los datos del usuario (proyectos, `.env`) se guardan en
  `~/Library/Application Support/SecretosInexplicables/` — separado del
  `.app`, así que sobrevive si se reemplaza por una versión nueva.
- El modelo de Whisper se descarga la primera vez que alguien transcribe (no
  viene incluido en el `.app` para no inflar la descarga).
- Solo se probó en Apple Silicon (arm64); el ffmpeg empaquetado es x86_64 y
  corre vía Rosetta 2 — funciona, pero un ffmpeg arm64 nativo sería más rápido
  si se vuelve a empaquetar más adelante.

La página de aterrizaje para la lista de espera de la beta está en
[`landing/`](landing/) — ver [`landing/README.md`](landing/README.md) para
publicarla.

## App visual (recomendado)

Doble clic en **"AutoFaceless Video.command"** (está en
`~/Documents/CLAUDE/`) — arranca la app y abre el navegador solo.
O a mano:

```bash
cd ~/Documents/CLAUDE/EditorAutomatizacion
.venv/bin/python app.py      # y abre http://localhost:5178
```

En el navegador:

- **＋ Nueva historia** → le pones nombre, subes el audio de MiniMax y
  **pega el guión** (opcional pero recomendado: el audio da los tiempos de
  cada palabra y el guión corrige el texto — nombres propios, palabras mal
  oídas — para que las búsquedas y los prompts salgan exactos).
- Se transcribe y se arma sola la **línea de tiempo**; las imágenes de Pexels
  van apareciendo en vivo (las escenas sin imagen se marcan en rojo).
- Clic en una escena → ves su **narración y el prompt (editable)**, puedes
  **generar la imagen con IA ahí mismo** (botón ✨, gratis vía Pollinations,
  sin clave), **buscar fotos o VIDEOS en Pexels** o **subir tu propia imagen
  o video**. Cada clic en ✨ genera una imagen distinta (semilla aleatoria):
  si no te gusta, edita el prompt y vuelve a generar.
- **Duración**: arrastra el borde derecho de una escena en la línea de tiempo
  (o usa −0.5s/+0.5s). El tiempo se toma de la escena siguiente, así el video
  siempre queda sincronizado con la voz.
- **Mover de lugar**: arrastra una miniatura sobre otra para intercambiar sus
  imágenes/videos (la narración se queda en su sitio, que es lo que manda).
- **Insertar una escena**: en el panel de una escena, botón "➕ Insertar
  escena (dividir esta en 2)". Parte la escena por la mitad; la imagen actual
  se queda en la primera mitad y la segunda queda vacía para ponerle otra.
  El total sigue calzando con la voz. Luego puedes arrastrar el borde para
  ajustar dónde cae el corte.
- **Palabras clave más certeras**: las búsquedas sugeridas ahora ignoran
  palabras abstractas, años, verbos y adverbios, y priorizan lo concreto y
  los nombres propios (p. ej. "El ejército llegó rápidamente y acordonó la
  zona" → **ejército zona**). Si una escena vieja trae malas palabras, usa
  el botón **"✨ sugerir palabras"** junto al buscador para recalcularlas.
- **Efecto por escena**: automático, acercar, alejar, paneo horizontal,
  paneo vertical o estático.
- **Transición de salida por escena**: fundido cruzado, corte seco, fundido a
  negro, deslizar, círculo, zoom o pixelar.
- Las escenas con **video** se recortan a la duración de la escena (y se
  repiten si el clip es más corto); su audio original se descarta, siempre
  manda la narración.
- **Timeline por pistas**: capa de texto/logos (+T/+🖼), video, narración con
  forma de onda (clic para saltar a ese punto) y música.
- **Textos y logos encima del video**: aparecen/desaparecen en el rango de
  segundos que elijas, 9 posiciones, 3 tamaños, color libre; se arrastran en
  su pista para moverlos de tiempo y clic para editarlos.
- **Eliminar escena** (su tiempo lo absorbe la anterior) y **deshacer/rehacer
  con ⌘Z / ⇧⌘Z** — cubre borrar, dividir, mover, reemplazar imágenes, todo.
- **Previsualización** (pestaña ▶): reproduce el video tal como va — imágenes
  con su efecto Ken Burns, videos, transiciones, textos y logos, con la
  narración y la música mezcladas — sin tener que exportar. Es una vista
  aproximada (el render final lo hace ffmpeg al Exportar); sirve para ir
  viendo resultados mientras editas.
- **Panel de efectos** (a la derecha del previsualizador): ajusta en vivo la
  escala, la posición X e Y, la opacidad y la velocidad (0.5×/1×/1.5×/2×, solo
  para videos) de la escena que estás viendo. Los cambios se ven al instante en
  el lienzo y se guardan solos; el botón ↺ reset vuelve a los valores por
  defecto. El mismo panel incluye la duración (−0.5s/+0.5s), el efecto de
  movimiento, la transición de salida y los botones Insertar/Eliminar escena,
  para editar todo sin salir de la previsualización.
- **Capas separadas de texto e imagen**: en la timeline, los textos y los
  logos/imágenes viven en dos pistas distintas (no se enciman ni entran en
  conflicto). Al exportar, las imágenes van debajo y los textos encima, para
  que los títulos siempre se lean.
- **Plantillas de animación** (pista "Animación +📊"): elementos animados que
  suben el nivel del video y lo alejan de lo genérico. Seis plantillas:
  - **Contador**: un número que sube hasta su objetivo (fechas — "1947" — o
    estadísticas — "+2.300 víctimas"). Formato año o número.
  - **Cuenta regresiva**: un número que baja hasta 0 (tensión).
  - **Gráfica de barras**: 2 a 5 barras etiquetadas que crecen a su valor.
  - **Banner (lower-third)**: banda con título y subtítulo que entra deslizándose.
  - **Cita**: frase con comillas grandes y autor, con aparición suave (testimonios).
  - **Lista**: 2 a 6 puntos que aparecen uno por uno (datos, "3 cosas que…").
  Cada una se posiciona en 9 lugares, con tamaño, color y rango de tiempo.
  Se ven aproximadas en la Previsualización y se renderizan de verdad al
  exportar (con Pillow + ffmpeg, sin depender de fuentes del sistema).

## Tutorial dentro de la app

Botón **❓ Cómo se usa** en la barra superior: abre una guía de 4 pasos
(crear historia → ajustar escenas → previsualizar → exportar) para que
cualquier persona nueva entienda el flujo sin explicación externa. Si el video dura más que la escena, aparece un
  **deslizador para elegir qué tramo usar** (con vista previa).
- El buscador tiene 3 fuentes: **Pexels Fotos**, **Pexels Videos** y
  **Web (Google/Bing)** — esta última encuentra imágenes reales de noticias,
  archivos históricos, etc. que no están en bancos de stock.
- **🎵 Música de fondo**: botón "Subir música" bajo el reproductor. Se
  normaliza el volumen (el % funciona igual con cualquier archivo), se
  repite en bucle si es corta y termina con fade out de 3s. 10–15% = fondo
  sutil; 25–40% = presente.
- Las **transiciones se ven en el video exportado**, no en la línea de
  tiempo: empiezan justo en el cambio de escena y duran 0.6s. Si editas algo
  después de exportar, la app avisa "⚠ hay cambios sin exportar".
- Pestaña **"Todas las escenas y prompts"** → vista previa de todo el video.
- **Exportar video** → genera `video.mp4` con barra de progreso; ▶ Ver video
  lo reproduce ahí mismo.
- Abajo a la izquierda: **Unir historias** para el video final de 30 min.

## Crear historia con IA (guión + voz)

Botón **✨ Crear historia con IA** en la barra lateral:

1. Escribes el **tema**, los minutos y el estilo → **Generar guión**. Usa
   Claude (premium, si pusiste `ANTHROPIC_API_KEY` en el `.env`) o un servicio
   gratuito. El guión es editable y se puede copiar.
2. Pegas tu **voice_id de MiniMax** (sirven voces clonadas), eliges velocidad
   y pruebas la voz con ▶. Necesita `MINIMAX_API_KEY` y `MINIMAX_GROUP_ID` en
   el `.env` (usa tus créditos de MiniMax).
3. **Crear historia** → genera la voz, crea el proyecto y corre el pipeline
   completo (transcripción, escenas, imágenes) automáticamente.

En el panel de cada escena también hay **🎬 Video IA (MiniMax)**: genera un
clip de video con Hailuo a partir del prompt de la escena (tarda minutos y
consume créditos; pide confirmación antes).

## Configuración inicial (una sola vez)

1. Crea tu clave gratis en <https://www.pexels.com/api/> (2 minutos).
2. Crea el archivo `.env` en esta carpeta (mira `.env.example`):

   ```
   PEXELS_API_KEY=tu_clave_aqui
   # opcionales premium:
   # ANTHROPIC_API_KEY=...   (guiones con Claude)
   # MINIMAX_API_KEY=...     (voz y video con IA)
   # MINIMAX_GROUP_ID=...
   ```

## Flujo por historia

```bash
./editor nuevo historia1          # crea proyectos/historia1/
# → copia ahí el mp3 de MiniMax
./editor todo historia1           # transcribe + escenas + imágenes + video
```

O paso por paso:

```bash
./editor transcribir historia1    # Whisper local (gratis) → transcripcion.json
./editor escenas historia1        # divide en escenas ~10s → escenas.json + prompts_ia.md
./editor imagenes historia1       # descarga de Pexels una imagen por escena
./editor ensamblar historia1      # → proyectos/historia1/video.mp4
```

### El paso híbrido (tu toque manual)

Después de `imagenes` y ANTES de `ensamblar`:

1. Abre `proyectos/historia1/imagenes/` y revisa las fotos descargadas.
2. Las que no te gusten (o las marcadas como "pendientes"), genéralas con tu
   IA de imágenes usando los prompts de `proyectos/historia1/prompts_ia.md`.
3. Guarda tu imagen con el **mismo nombre** (`001.jpg`, `002.jpg`…) para
   reemplazar la de Pexels. Sirven `.jpg`, `.png` y `.webp`.
4. Corre `./editor ensamblar historia1`.

Si vuelves a correr `imagenes`, NO toca las que ya existen — solo descarga
las que falten.

## Exportar una historia

Botón **Exportar video** → abre un diálogo donde eliges:

- **Nombre del archivo** (por defecto el de la historia).
- **Carpeta destino**: Escritorio, Descargas, Películas, tu carpeta personal, o
  "Otra carpeta…" para escribir una ruta cualquiera.
- **Calidad**: Máxima / Alta (recomendada) / Estándar (1080p más ligero) /
  Ligera (720p, rápida).

Cada historia se exporta por su cuenta (no hace falta unir nada). Al terminar,
un botón **Mostrar en Finder** te lleva al archivo. Si hubo cambios sin
renderizar, el video se reconstruye automáticamente antes de guardar.

## Video final de 30 min (opcional)

```bash
./editor unir video_final historia1 historia2 historia3
# → proyectos/video_final.mp4 con fundido entre historias
```

## Detalles

- **Whisper**: usa el modelo `small` (buen español). La primera vez descarga
  ~500 MB. Si tu Mac va lento: `./editor transcribir historia1 --modelo base`.
- **Sincronización**: las escenas se cortan en los tiempos exactos de la
  narración; el video final dura exactamente lo que dura el audio.
- **Salida**: 1920×1080, 30 fps, H.264 CRF 18 — listo para subir a YouTube.
- Los archivos intermedios quedan en `proyectos/<nombre>/clips/`; puedes
  borrar esa carpeta cuando el video esté listo.
- Si una escena no tiene imagen, se usa un fondo oscuro de relleno y se
  avisa en pantalla (así el render nunca se bloquea).

## Requisitos (ya instalados)

- Python 3.11 (entorno en `.venv/`), ffmpeg, faster-whisper.
