# AutoFaceless Video — contexto completo del proyecto

> Este archivo es el traspaso maestro. Léelo COMPLETO antes de tocar código.
> Claude Code lo carga automáticamente al abrir esta carpeta.

## Qué es

**AutoFaceless Video** es una app de escritorio para macOS (beta) que convierte
un guión en un video de YouTube listo para subir: transcribe el audio con
Whisper, lo divide en escenas, busca imágenes/videos (Pexels/IA), permite editar
en una timeline visual y exporta en 1080p con ffmpeg. El dueño es Derek
(derekog7@gmail.com); su canal de YouTube "Secretos Inexplicables" (misterio, en
español) es el caso de uso original, pero el producto es genérico.

**Modelo de negocio**: app LOCAL con BYOK (bring-your-own-key) — el usuario pone
sus propias claves de API (Pexels, Claude, MiniMax, etc.), así el negocio no
absorbe costos de cómputo. Beta gratuita ahora; después suscripción (~$12-15/mes
licencia, ~$35-45/mes todo incluido). macOS primero, Windows después. Hay una
landing (`landing/index.html`, bilingüe, Formspree pendiente de configurar).

## Arquitectura (3 archivos hacen todo)

- **`editor.py`** — motor. Whisper (faster-whisper), escenas, Pexels, ffmpeg
  (Ken Burns, transiciones xfade, overlays con Pillow, subtítulos .ass/libass),
  MiniMax (voz TTS + video Hailuo), chat de guiones multi-proveedor
  (`chat_guion`), guiones guardados (CRUD en `DATOS/guiones/`), `.env`
  (`leer_env`/`guardar_env`). También es CLI (`./editor`).
- **`app.py`** — servidor Flask (puerto 5178), API REST. Manejador global de
  errores que escribe traceback a `DATOS/error.log` Y lo muestra en el navegador
  (clave para diagnosticar en Macs de testers).
- **`static/index.html`** — TODA la interfaz (una sola página, ~3000 líneas:
  CSS + HTML + JS vanilla, sin frameworks). Timeline multipista, previsualización
  WYSIWYG, modales, Estudio de guión, i18n ES/EN.

Soporte: `version.py` (VERSION única — la leen app.py, lanzador y spec),
`scripts/lanzador.py` (entrada del .app: auto-reparación de puerto/instancias),
`empaquetar.spec` (PyInstaller), `empaquetado/ffmpeg/` (ffmpeg/ffprobe ESTÁTICOS
de evermeet.cx — ver gotchas), `empaquetado/Abrir AutoFaceless Video.command`
(quita cuarentena con xattr y abre la app; va dentro del zip).

**Rutas de datos**: en dev, `DATOS = carpeta del proyecto`; empaquetada,
`DATOS = ~/Library/Application Support/AutoFacelessVideo/` (proyectos/, guiones/,
.env, error.log). Detección: `getattr(sys, "frozen", False)`.

## Cómo trabajar

```bash
# dev (SIEMPRE cd primero; el venv es local)
cd ~/Documents/CLAUDE/EditorAutomatizacion
.venv/bin/python app.py          # → http://localhost:5178
# (hay entrada "editor-web" en ../.claude/launch.json para preview)

# empaquetar una versión nueva
# 1) sube VERSION en version.py   2) reconstruye   3) arma el zip
rm -rf build dist && .venv/bin/pyinstaller empaquetar.spec --noconfirm --clean
# 4) staging: carpeta "AutoFaceless Video vX.XX" con .app + .command + LÉEME,
#    xattr -cr, y ditto -c -k --sequesterRsrc --keepParent → zip en ~/Documents/CLAUDE/
#    (mira los commits recientes: el bloque de empaquetado está en el historial)
```

**Git**: el repo tiene el tag **`v0.05-safe`** (estado estable conocido).
`git reset --hard v0.05-safe` restaura. Commitea cada versión con su número.
**Verifica SIEMPRE en el navegador** (preview + screenshots) antes de empaquetar,
y prueba el binario (`dist/.../Contents/MacOS/lanzador` y `curl /api/salud`).

## Gotchas CRÍTICOS (cada uno costó un bug real)

1. **ffmpeg**: usar SIEMPRE el estático de `empaquetado/ffmpeg/` (el de Homebrew
   no tiene drawtext NI libass y depende de dylibs frágiles). El dev mode ya lo
   prefiere automáticamente (FFMPEG_BIN en editor.py). Texto sobre video se hace
   con Pillow→PNG→overlay; subtítulos con .ass + filtro `ass` (libass).
2. **Piso de macOS**: la app debe correr en macOS 11+. numpy/onnxruntime/av
   están FIJADOS a versiones con wheels `macosx_11_0` (`numpy==1.26.4`,
   `onnxruntime==1.19.2`, `av==14.0.0`). NO los actualices sin verificar:
   tras cada build, ningún mach-o en Contents/Frameworks debe tener `minos>=13`
   (`otool -l X | grep -A3 LC_BUILD_VERSION`). Se rompió en la Mac Monterey 12
   de una tester por esto.
3. **Proceso fantasma**: el servidor Flask NO muere al cerrar el navegador. El
   lanzador se auto-repara: `/api/salud` devuelve `{app, version, ok}`; si el
   puerto 5178 lo ocupa una instancia vieja/rota nuestra, la mata (lsof+ps por
   "lanzador"/"AutoFaceless"); si es un proceso ajeno, usa 5179+. NO romper esto.
4. **Gatekeeper**: app sin firmar (no hay cuenta Apple Developer). El usuario
   abre con clic derecho → Abrir sobre el `.command` del zip (hace `xattr -cr`).
   El "clic derecho → Abrir" sobre la .app NO basta (las dylibs internas fallan
   con ImportError al transcribir).
5. **i18n**: el español es el markup original; el diccionario `EN` en el JS solo
   trae inglés. Estáticos: `data-i18n` / `data-i18n-ph` / `data-i18n-title` /
   `data-i18n-html` (snapshot/restore en `aplicarIdioma()`). Dinámicos: helper
   `L('es','en')`. OJO: el objeto EN tiene claves multi-por-línea; si defines una
   clave dos veces, la ÚLTIMA gana (object literal JS).
6. **El preview Flask NO recarga editor.py** (app.run sin reloader): reinicia el
   servidor tras editar Python o verás código viejo (p.ej. "Plantilla desconocida").
7. **xfade timebase**: al mezclar clips de imagen y video hay que normalizar la
   base de tiempo (TIMESCALE=15360) o ffmpeg falla.
8. **Pantalla de bienvenida**: se muestra solo la 1ª vez (localStorage
   `afv_bienvenida_vista`); el idioma en `afv_idioma`. Si "no aparece" en pruebas
   es porque el navegador ya la vio — probar en ventana privada o limpiar
   localStorage.

## Coherencia de imágenes (v0.07)

Problema: las imágenes automáticas por escena no eran coherentes con la historia
(cada escena buscaba en aislamiento; escenas sin sustantivo caían en genéricos).
Dos capas de solución en editor.py:
- **Ancla de historia (gratis, siempre activa)**: `_anclas_historia(textos)` saca
  los 1-2 temas visuales dominantes de TODO el video (prefiere sustantivos
  comunes representables sobre nombres propios, que Pexels casi no tiene; filtra
  unidades/adjetivos no visuales). `_combinar_consulta()` mezcla el término de
  la escena + el ancla. Se aplica en `generar_escenas` → cada video NUEVO ya sale
  más coherente sin claves.
- **Coherencia por IA (con proveedor, botón "✨ Coherencia IA" en el header)**:
  `sugerir_consultas_ia(p, proveedor, modelo)` manda la historia COMPLETA (todas
  las escenas numeradas) al LLM (mismo dispatch multi-proveedor de `chat_guion`,
  ahora con param `sistema`; SISTEMA_IMAGENES) y recibe una consulta visual EN
  INGLÉS por escena (formato `N| query`, parseo tolerante). Endpoint
  `/api/proyectos/<n>/imagenes/coherencia` → `hilo_coherencia`: reescribe
  consultas y **reemplaza solo las imágenes automáticas** (respeta las manuales).
  Tracking auto/manual: flag `medio_auto` en escenas.json (descargar_imagenes lo
  pone; descargar_a_escena con auto=False lo limpia); `descargar_imagenes(...,
  reemplazar_auto=True)` re-baja solo las auto. Modal con selector de proveedor
  (reusa afv_guion_prov). Verificado: parseo, respeto de manuales, i18n.

TECHO conocido: el ancla local a veces elige un término poco visual si la
historia no tiene un sustantivo recurrente fuerte — por eso la capa IA. Mejora
futura: correr la capa IA automáticamente en el pipeline si hay clave (con aviso
de costo), y generar también un prompt de imagen IA rico por escena.

## Velocidad de exportación (v0.08)

Export lento. Causa doble: (1) el ffmpeg empaquetado es **x86_64 bajo Rosetta**
en Apple Silicon (toda codificación emulada) y (2) el 1080p se re-codificaba
entero VARIAS veces (overlays → subtítulos → transcodificado final con preset
`medium`). Arreglado:
- **exportar_final ya NO re-codifica cuando no baja resolución**: el master ya es
  1080p H.264, así que para calidades 1080p hace `ffmpeg -c copy` (re-empaquetar,
  ~0.1s) en vez de re-encode `medium`. Medido: pase final de 31s → 0.2s (195×) en
  un video de 44s; una re-exportación con master al día es casi instantánea. Solo
  "ligera" (720p) re-codifica (scale + veryfast). Efecto lateral aceptado: las 3
  calidades 1080p ahora dan el mismo archivo (el master crf18); simplificar el
  dropdown a 1080p/720p a futuro.
- Presets bajados a `veryfast` en subtítulos (era `fast`). Todos los pases que sí
  codifican usan veryfast (mismo tamaño a igual CRF, ~2× más rápido que medium).

PRÓXIMO GRAN SALTO (pendiente): **empaquetar un ffmpeg ARM64 nativo** (con libass
+ codecs, minos ≤ 11) para salir de Rosetta — aceleraría TODO el encode (clips por
escena, transiciones, overlays, subtítulos) 2-4×. Es lo que más falta. Verificar
que el build arm64 tenga los filtros `ass`/`drawtext` y arquitectura correcta.

## Estado actual: v0.06 (todo verificado y funcionando)

- Editor completo: timeline multipista, efectos/transiciones por escena, texto/
  logos/6 plantillas de animación, música, deshacer/rehacer, previsualización
  WYSIWYG, exportación por calidad, unir historias.
- **Subtítulos** automáticos desde la transcripción (tiempos por palabra) con
  editor de frases, estilo y quemado con libass. Botón 💬 en el header.
- **Bilingüe ES/EN** + pantalla de bienvenida.
- **🔑 Claves API en la app** (escribe el .env sola, sin reiniciar): Pexels,
  Anthropic, MiniMax (key+group), Gemini, OpenAI.
- **📝 Estudio de guión** (sidebar → HERRAMIENTAS): interfaz propia con chat
  asistente-guionista a la izquierda y documento editable a la derecha. El
  asistente entrega guiones entre marcas `<guion>...</guion>` que el front
  extrae al panel. Proveedores en `chat_guion()`: gratis (Pollinations, default),
  claude (claude-sonnet-5), gemini (gemini-2.5-flash), openai (gpt-4o-mini),
  local (Ollama en 127.0.0.1:11434, lista modelos con GB; si no está instalado,
  la opción sale deshabilitada). Guiones guardados con autosave.
- **🎙 Estudio de voz** (ex "Crear con IA", ya sin generación de guión): carga
  guiones guardados y genera la narración con MiniMax → crea el proyecto.
- Zip actual: `~/Documents/CLAUDE/AutoFaceless-Video-v0.06-beta-macOS.zip`.

## BACKLOG priorizado (lo que Derek quiere ahora)

1. **Calidad del asistente de guiones**: con Pollinations/gemma pequeños la IA
   responde mal (no sigue el formato `<guion>`, texto pobre). Ideas: mejorar el
   fallback gratuito (probar modelos mejores de Pollinations, p.ej.
   `openai-large`/otros del endpoint /models), reforzar el prompt para modelos
   débiles, reintentar si no vino la marca `<guion>` cuando se pidió guión, y
   empujar en la UI a configurar una clave (Gemini es gratis con límites).
   Verificar con clave real que Claude/Gemini/GPT lo hacen excelente.
2. **Estudio de voz v2 → "Estudio de audio"**: interfaz dedicada a crear la
   narración. Agregar **ElevenLabs** (BYOK, endpoint text-to-speech; listar
   voces de la cuenta con GET /v1/voices) además de MiniMax; y una opción de voz
   **gratuita** (investigar: edge-tts funciona sin clave y suena bien; Piper es
   local). Con MiniMax y ElevenLabs listar MÚLTIPLES voces para elegir/probar
   (dropdown de voces + botón ▶ probar, quizá multi-voz por párrafo a futuro).
   Mantener el flujo: guión → audio → proyecto.
3. **Verificar bienvenida** en navegador limpio (ver gotcha 8) y quizá añadir
   un botón para reabrirla/cambiar idioma desde ajustes.
4. Pendientes menores: atribución de Pexels (requisito legal de su API),
   traducir mensajes de progreso del backend (est.detalle llega en español),
   configurar Formspree en la landing, cuenta Apple Developer ($99/año) para
   firmar/notarizar y eliminar el paso xattr.

## Reglas de trabajo con Derek

- Habla en español. Explica los errores con causa raíz, sin tecnicismos de más.
- Los testers son personas no técnicas con MacBook Air M1 (Monterey 12): toda
  fricción de instalación importa.
- Verificación end-to-end SIEMPRE antes de entregar zip (navegador con
  screenshots, binario empaquetado con curl, y para bugs: reproducir primero).
- Versionado: sube `version.py`, empaqueta, zip con versión en el nombre en
  `~/Documents/CLAUDE/`, borra el zip anterior, commit en git.
