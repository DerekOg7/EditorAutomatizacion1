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

## Robustez ante falta de espacio (v0.09)

Bug real: un tester se quedó sin espacio a mitad de export → el maestro
`video.mp4` quedó truncado ("moov atom not found"), y como `master_ok` solo
miraba existencia+mtime, la app confiaba en él y toda exportación posterior
fallaba (con la optimización copy de v0.08, intentaba copiar el archivo
corrupto). Arreglado en editor.py:
- `video_valido(ruta)`: ffprobe la duración; False si no existe/está vacío/corrupto.
- `exportar_final` reconstruye el maestro si `not video_valido(video.mp4)` (no
  solo si falta), borrándolo antes. Y chequea espacio libre (< 1.5 GB → error
  amable) antes de armar.
- **Escritura atómica**: el maestro y el archivo final se escriben a un temporal
  (`video.tmp.mp4` / `.NOMBRE.tmp.mp4` en la misma carpeta) y solo si `video_valido`
  pasa se hace `os.replace` al nombre real. Un corte nunca deja un archivo a
  medias que parezca completo. (requirió `import os`)
- Remedio manual si alguien queda atascado en una build vieja: borrar
  `~/Library/Application Support/AutoFacelessVideo/proyectos/<proy>/video.mp4` y
  la carpeta `clips/`.

## Formatos de lienzo/exportación 16:9 / 9:16 / 1:1 (v0.10)

Antes todo estaba clavado a 1920×1080. Ahora el formato es por proyecto (lado
corto siempre 1080). En editor.py: `FORMATOS = {"16:9":(1920,1080),
"9:16":(1080,1920),"1:1":(1080,1080)}`, `dims_formato()`, `formato_proyecto(p)`
(lee ajustes.json), `dims_proyecto(p)`. Las dims se pasan como PARÁMETRO `dims`
a cada función de render (thread-safe, sin globales mutables): `_clip_imagen`
(supersamplea a 2× las dims, no 3840×2160 fijo), `_clip_video`, `_ajuste_fino`,
`_placeholder`, `escribir_ass`/`_quemar_subtitulos` (PlayRes + fuente escalada
por alto/1080 para que el subtítulo se vea igual en vertical). ensamblar_video
calcula `dims = dims_proyecto(p)` y las reparte. CLAVE: `_posicion` ya usaba las
variables simbólicas de ffmpeg (W/H/w/h) → overlays/logos/textos se posicionan
bien en cualquier formato sin cambios. CALIDADES ahora usa "corto" (lado menor)
en vez de "alto"; exportar_final escala manteniendo el formato (copy si no baja
resolución, si no scale=w:h proporcional). Pexels: `ORIENTACION` +
`pexels_buscar(..., orientacion=)` (landscape/portrait/square) según formato.
Pollinations genera en las dims del proyecto. app.py: crear_proyecto y
crear_historia_ia aceptan `formato`; POST `/api/proyectos/<n>/formato` (borra
video.mp4, hay que re-exportar); ver_proyecto devuelve `formato`; /api/pexels
acepta `proyecto` para la orientación. Front: `#pv-lienzo{aspect-ratio:var(--fmt)}`
+ clase `.alto` (vertical limitado por altura), `aplicarFormatoLienzo(fmt)` en
render(), selector en header (`fmt-actual` → `cambiarFormato()`) y en ambos
modales de creación (`nuevo-formato`/`ia-formato`); i18n. Verificado: render de
los 3 formatos con dims correctas, ensamblado 9:16 completo (transiciones+audio)
= 1080×1920 aac, endpoint persiste, lienzo adapta en navegador. (De paso: probar
el endpoint borró prueba/video.mp4 — regenerable.)

## Grupos de historias + "Mis historias" (v0.11)

Sidebar reorganizado: cabecera colapsable "📁 Mis historias" (▾/▸, estado en
localStorage `afv_hist_abierto`) con botón "＋ 📁" para crear grupo. Las
historias se agrupan; grupos colapsables (localStorage `afv_grupo_<id>`).
Backend en editor.py: `grupos.json` en DATOS = `{"grupos":[{id,nombre}...],
"asignacion":{proyecto:grupo_id}}` (orden del array = orden visual). Funciones:
`leer_grupos`, `crear_grupo`, `renombrar_grupo`, `borrar_grupo` (historias vuelven
a sin grupo, NO se borran), `ordenar_grupos(ids)`, `mover_historia(proy,gid)`,
`borrar_proyecto(nombre)` (rmtree + quita de asignación). app.py: listar_proyectos
añade `grupo` por proyecto; GET `/api/grupos`, POST `/api/grupos` (crear), POST
`/api/grupos/orden` {ids}, POST `/api/grupos/<gid>` (renombrar), DELETE
`/api/grupos/<gid>`, POST `/api/proyectos/<n>/grupo` {grupo}, DELETE
`/api/proyectos/<n>` (borra historia; guard `ocupado` → 400 si hay proceso;
limpia ESTADOS). Front: `cargarLista()` reescrita renderiza por grupos + sección
"Sin grupo" (si no hay grupos, lista plana); `tarjetaHistoria()` con botón "⋯"
(hover) → `menuHistoria()` = menú flotante #menu-flot con "Mover a grupo" +
"Eliminar historia"; grupos con ✏ renombrar / ↑↓ reordenar / 🗑 borrar y
drag-and-drop para reordenar; `borrarHistoria()` cierra el proyecto si estaba
abierto. i18n side_stories/side_newgroup. Verificado e2e: crear/mover/reordenar/
borrar grupos, borrar historia (con guard ocupado), menú, toggle, inglés.

## Multi-selección + exportar-unión (v0.12)

Reemplazó la vieja sección "Unir historias" del sidebar por un flujo de
selección múltiple. "Mis historias" ahora es un botón de herramienta normal
(width:100%, mismo estilo que Estudio de guión/voz/Claves) que pliega/despliega
la lista; el "＋ Nuevo grupo" pasó a ser el primer botón dentro de la lista
(`#btn-nuevo-grupo-lista`). Multi-selección: Cmd/Ctrl+clic en una historia la
añade/quita de `seleccionadas` (array global) y la resalta (`.proy.sel`, borde
acento + barra izquierda); clic normal limpia la selección y abre la historia.
Barra `#barra-seleccion` abajo (aparece con 2+) muestra "N historias
seleccionadas" + "Quitar selección" (`limpiarSeleccion()`). El botón de exportar
del header muestra "Exportar y unir (N)" cuando hay 2+ seleccionadas
(`actualizarSeleccion()`; render() la llama al final para no pisar el conteo).
Al exportar con 2+: `abrirExportar()` entra en modo unión (`expUnion=[...]`,
título "Exportar y unir N historias", nombre default "video_final");
`lanzarExportar()` hace POST `/api/exportar_union` y sondea
`/api/exportar_union/estado`. Backend: `editor.exportar_union(nombres, carpeta,
nombre_archivo, calidad)` arma el maestro que falte (video_valido→ensamblar),
normaliza todas al tamaño de la 1ª (scale+crop, así mezcla formatos distintos),
une con xfade+acrossfade, escala a la calidad y escribe atómico a la carpeta.
app.py: `hilo_exportar_union` + estado key "__union__"; se quitaron
/api/unir*, hilo_unir, unir_videos sigue en editor.py pero sin uso en la UI.
Verificado: unión de 2 maestros de formatos distintos → 1 archivo con audio y
fundido; UI multi-select, contador, modo unión del modal, limpiar, bilingüe.

## Rediseño visual/UX — flujo guiado (v0.13)

Rediseño completo de `static/index.html` según `~/Downloads/design_handoff_autofaceless_rediseno/`
(README.md + `AutoFaceless Studio.dc.html`). Objetivo: usuarios sin conocimiento
de edición. **Se conservó TODO el motor JS y los endpoints**; solo cambió tema,
tipografía y la estructura de navegación. Puntos clave para no romperlo:

- **Tema claro + Roboto**: `:root` remapeado (bg `#f9f9f9`, superficies `#fff`,
  acento rojo `#c4231b`/`#a81d16`/tinte `#fdecea`, bordes `#e5e5e5`/`#d9d9d9`,
  ok `#1a8f3c`). `@import` de Roboto. Botones = píldora blanca con borde;
  `.primario` = rojo con sombra. Se cambiaron literales morados (`139,92,246`) y
  placeholders oscuros (`#23233a`→`#e8e8e8`); la onda de narración se dibuja en
  rojo (`dibujarOnda('onda-narra', ... 'rgba(196,35,27,.55)')`).
- **Isotipo faceless** (NO triángulo play): `.iso .iso-34/.iso-96` con `.cabeza`
  + `.hombros` (divs). Reemplazó el emoji 🎬 en bienvenida y da el logo de la
  barra superior/portada. Marca renombrada a **AutoFaceless Studio**.
- **`body` ahora es `flex-direction:column`**: `#topbar` (barra superior sticky
  compartida: Atrás/logo/subtítulo de paso/segmento ES-EN/🔑/Ayuda) + `#paginas`
  (contenedor flex). Router: `let pagina`, `irA(page)` (togglea `.pagina.activa`,
  actualiza `#tb-sub` y visibilidad de `#tb-atras`), `irAtras()`. Páginas:
  `#pg-home`, `#pg-historias`, `#pg-guion`, `#pg-voz`, `#pg-editor` (esta última
  envuelve el `#lateral`+`#principal` de siempre). `.pagina{display:none}` /
  `.activa{display:flex}`. **Ojo**: había un `</div>` de más en `#lateral` (bug
  histórico inocuo) que aquí cerraba `#pg-editor` antes de tiempo — se eliminó.
- **Principal** (`#pg-home`): hero + mapa de proceso (4 chips) + card de nicho
  activo (Misterio, `empezarNicho()`→`abrirGuionPagina()`) + 2 nichos
  "PRÓXIMAMENTE" + botón "Mis historias (N)" (`#home-conteo`) + barra de ayuda.
- **Guión** (`#pg-guion`): antes era el overlay `#estudio` (ELIMINADO); su
  contenido se movió a una página de 2 columnas (chat `#est-mensajes`/`#est-texto`
  + guión `#est-guion`). Se conservan todos los IDs `est-*` y funciones `est*`.
  `abrirEstudio()`→`abrirGuionPagina()` (alias), `cerrarEstudio()`→`irA('home')`.
  `estDocCambio()` habilita `#gu-siguiente`. Barra inferior Atrás/Siguiente.
- **Voz** (`#pg-voz`): antes era el modal `#modal-ia` (ELIMINADO); ahora página
  con card de voz (voice_id real de MiniMax `#ia-voz` + Probar + velocidad) +
  datos del video (`#ia-nombre/#ia-formato/#ia-modelo`) + botón grande
  `crearHistoriaIA()` (con `#voz-generando`) + aside guión `#ia-guion`.
  `abrirModalIA()`→`abrirVozPagina()` (alias). Al crear historia →
  `abrirHistoriaEnEditor()` (abre proyecto + `irA('editor')`).
- **Editor** (`#pg-editor`): `#lateral` convertido en **barra retráctil**
  (250/58px, `.colapsado`, `toggleSidebar()`, persiste en `afv_sidebar_col`):
  ✎ Estudio de guión, 🎙 Estudio de voz, 📁 Mis historias (togglea
  `#lista-proyectos`), ＋ Nueva historia, lista de grupos, `#barra-seleccion`.
  Header con "Paso 4 · Edita y exporta" + nombre; se quitaron los botones
  redundantes 🌐 idioma y "❓ Cómo se usa" (ya están en la barra superior).
- **Mis historias** (`#pg-historias`): grid `renderHistorias()` (miniatura =
  `/api/proyectos/<n>/imagen/1`), 1 clic selecciona (`histSel`), doble clic o
  "Abrir en el editor" → `abrirHistoriaEnEditor()`. `cargarLista()` refresca
  `#home-conteo` y, si toca, el grid.
- **i18n**: strings nuevas añadidas al dict `EN`. El `aplicarIdioma()` de siempre;
  el segmento ES/EN llama `fijarIdioma()` (marca `#tb-es/#tb-en`, refresca subtítulo).
- Verificado en navegador: las 5 páginas, ES/EN, colapso de sidebar, apertura de
  historia, hand-off Guión→Voz. Sin errores de consola. Backup del dark theme en
  el scratchpad de la sesión (`index.dark.backup.html`).

## Voz en off multi-proveedor + voces gratis (v0.14)

La página de Voz pasó de "solo MiniMax" a **4 proveedores**, con dos gratis para
que cualquiera pueda narrar sin pagar ni configurar claves:

- **`edge` — Gratis · voces neuronales** (edge-tts, voces de Microsoft): online,
  sin clave, calidad alta. Es el proveedor **por defecto**. Catálogo `VOCES_EDGE`
  (es-MX/es-ES/es-AR/es-CO + en-US). La velocidad se aplica con el `rate` nativo
  de edge-tts (`+/-N%`).
- **`sistema` — Gratis · del sistema (sin internet)**: macOS `say` → aiff → mp3.
  Offline, sin clave. `voces_sistema()` enumera en runtime las voces es/en
  instaladas (`say -v ?`). Velocidad vía `atempo`.
- **`minimax`** (BYOK): la función `minimax_voz` de siempre; el usuario pega su
  `voice_id`.
- **`elevenlabs`** (BYOK, NUEVO): `elevenlabs_voz` (POST a
  `api.elevenlabs.io/v1/text-to-speech/{voice_id}`, header `xi-api-key`, modelo
  `eleven_multilingual_v2`, trocea a ~2200 y concatena). Voces premade en
  `VOCES_ELEVEN` (Rachel/Domi/Bella/Antoni/Adam/Josh) + campo para voice_id propio.

Arquitectura: `editor.sintetizar_voz(texto, proveedor, voz, velocidad, on_progreso)`
despacha a cada proveedor y **todos devuelven bytes de mp3**, así el pipeline
(guardar `audio.mp3` → transcribir) no cambió. Helpers nuevos: `_concat_mp3`,
`_atempo_mp3` (velocidad sin cambiar tono, filtro `atempo`, para say/eleven).
`editor.proveedores_voz()` lista proveedores con `disponible` (según claves) y sus
voces. app.py: `GET /api/voz/proveedores`; `ia_voz_prueba` e `ia_historia`/
`hilo_historia_ia` aceptan `proveedor`; `ELEVENLABS_API_KEY` en `CLAVES_PERMITIDAS`
y `config()`. Frontend: selector `#voz-prov` + `#voz-voces` (tarjetas `.voz-tarjeta`
para proveedores con presets, o input `#ia-voz` para custom); `vozEfectiva()` decide
la voz; `probarVoz`/`crearHistoriaIA` mandan `proveedor`+`voz`. Campo ElevenLabs en
el modal 🔑. Nota inline "requiere clave" para proveedores de pago sin clave.

**Empaquetado**: `edge_tts` y `aiohttp` se importan de forma perezosa, así que se
añadieron al `collect_all` del spec (si no, PyInstaller no los detecta). Sus wheels
nativos (aiohttp `_http_parser`/`_websocket`, frozenlist/multidict/propcache/yarl)
son todos **macosx_11_0** → el piso de macOS sigue en 11 (verificado: 0 binarios
con minos>=13 tras la build). Verificado e2e: las 4 voces en el navegador (edge y
sistema generan mp3 real), y el `.app` congelado sirve `/api/voz/proveedores` con
`edge` disponible y genera una muestra edge de 21 KB.

## Imágenes inteligentes multi-fuente (v0.15)

El botón del header "✨ Coherencia IA" se convirtió en "✨ Imágenes IA": un
"director de arte" que rellena cada escena buscando en **varias fuentes** y
eligiendo el mejor medio, **mezclando foto y video** para dinamismo. Resuelve el
pedido: meter tus propios inputs, buscar en Pexels fotos/videos + web (Google) y
decidir la mejor opción, sin usar siempre solo fotos o solo videos.

- **Guía del usuario** (brief): textarea en el modal (`#img-guia`), persistida en
  `ajustes.json` (`guia_imagenes`, expuesta en GET proyecto para prefill). Se
  inyecta en el prompt de la IA y, si no se usa IA, se anexa a cada consulta.
- **Plan con IA** (`editor.plan_imagenes_ia`): una sola llamada `chat_guion` con
  `SISTEMA_PLAN_IMAGENES` que, viendo toda la historia, decide por escena
  **FUENTE** (FOTO/VIDEO/WEB) + consulta en inglés, incorporando la guía y
  alternando ~1/3 VIDEO. WEB = cosas muy específicas (nombres propios, aviones/
  barcos concretos) que el stock no tiene. Escribe `consulta`/`consulta_ia`/
  `fuente_ia` en escenas.json. (El proveedor sale del mismo selector de siempre.)
- **Motor** (`editor.rellenar_inteligente`): por escena que necesita medio, arma
  el orden de fuentes (la sugerida por la IA primero, luego el resto permitido;
  con `mezclar` evita 3+ del mismo tipo seguidas via `_orden_fuentes`), busca en
  cada fuente (`_buscar_fuente` → Pexels fotos/videos o web DDG, normalizado a
  `{tipo,url,id,texto}`), **puntúa por relevancia** (`_puntuar_candidato`: solape
  de términos concretos de la escena con la descripción `alt`/título del
  candidato — por eso `pexels_buscar` ahora devuelve `texto=alt`), descarga el
  mejor no-duplicado tolerante a fallos (`_bajar_candidato`, si falla prueba el
  siguiente candidato/fuente → así lo específico cae a la web). Respeta las
  escenas puestas a mano (solo pisa `medio_auto` con `reemplazar_auto=True`).
- app.py: `hilo_imagenes_inteligente` (plan opcional + relleno) y
  `POST /api/proyectos/<n>/imagenes/inteligente` (body `guia, fuentes[FOTO/VIDEO/
  WEB], mezclar, usar_ia, proveedor, modelo`). Si solo se pide Pexels sin clave →
  400; con «Web» activo funciona sin clave (DDG es gratis). La ruta vieja
  `/imagenes/coherencia` y `descargar_imagenes` siguen para compatibilidad.
- Frontend: el modal `#modal-coherencia` ahora tiene guía + checkboxes de fuentes
  + toggle mezclar + toggle "usar IA". `ejecutarImagenesIA()` manda todo.
- Verificado e2e (Pexels+Gemini reales, con backup/restore de un proyecto):
  el motor rellena escenas vacías con MEZCLA (jpg+mp4); el plan de Gemini repartió
  7 FOTO / 3 VIDEO (~30% video) con consultas en inglés según la guía; el `.app`
  v0.15 congelado responde el endpoint y hace búsqueda web (ddgs empaquetado). Sin
  dependencias nuevas. Piso macOS sigue en 11.

## Multiplataforma (Windows-ready) + licencias offline (v0.16)

Dos cambios grandes para poder lanzar la beta: código listo para Windows y un
sistema de licencias con código + vencimiento.

**Multiplataforma** (todo en `editor.py`/`lanzador.py`/`empaquetar.spec`):
- `ES_WIN`/`ES_MAC`/`_EXE`. Carpeta de datos por SO (`_carpeta_datos()`: `%APPDATA%`
  en Windows, Application Support en Mac, XDG en Linux). ffmpeg por SO
  (`ffmpeg{_EXE}`; en Windows el spec toma `empaquetado/ffmpeg-win/` si existe).
- Fuente para Pillow por SO (`_ruta_fuente()`: Arial/Segoe en Win, Helvetica en Mac,
  DejaVu en Linux) — antes estaba fija a Helvetica.ttc (rompía en Windows).
- `revelar_en_finder()` usa `explorer /select,` en Win, `open -R` en Mac.
- **Voz del sistema en Windows**: `voces_sistema()`/`say_voz()` usan SAPI vía
  PowerShell (`_voces_windows`/`_say_windows`) además del `say` de macOS; el
  proveedor 'sistema' se ofrece en Mac y Win.
- Lanzador: `_pids_en_puerto`/`_es_nuestro` usan `netstat`/`tasklist` en Windows
  (Unix sigue con lsof/ps). El spec: `BUNDLE` solo en macOS; en Windows el
  resultado es `dist/AutoFaceless Video/AutoFaceless Video.exe` (onedir).
- **Build de Windows por CI**: `.github/workflows/build.yml` (job `windows`:
  setup Python 3.11 → pip install -r requirements.txt → descarga ffmpeg de
  gyan.dev a `empaquetado/ffmpeg-win/` → pyinstaller → sube zip como artifact;
  job `macos` análogo con ffmpeg de evermeet). `requirements.txt` nuevo. **No se
  puede compilar Windows desde la Mac** (PyInstaller no cruza): se usa el CI (o
  una PC Windows con `pip install -r requirements.txt && pyinstaller empaquetar.spec`).

**Licencias offline firmadas (Ed25519)**:
- `licencia_ed25519.py` = Ed25519 en Python PURO (RFC 8032, dominio público) →
  **sin dependencias nativas, no sube el piso de macOS**. Verificado: acepta una
  firma Ed25519 real y rechaza forjadas/alteradas.
- `licencia.py`: `generar_codigo(id, exp, plan, priv)` y `verificar_codigo()`
  (comprueba firma con la **llave pública embebida** `LLAVE_PUBLICA_HEX` + fecha).
  Código = `AFS1.<payload_b64url>.<firma_b64url>` (payload JSON canónico
  {id,exp,plan}). Almacén en `DATOS/licencia.txt`; `estado()` para la app.
- `scripts/generar_licencia.py`: CLI del dueño para emitir códigos
  (`--id --dias N | --exp AAAA-MM-DD --plan`). Lee la privada de
  `LLAVE_PRIVADA_NO_COMPARTIR.hex` (raíz, **gitignored**) o `AFS_LLAVE_PRIVADA`.
  **La privada NUNCA va en la app ni en git.**
- app.py: `GET/POST /api/licencia` + `@app.before_request` (`_puerta_licencia`):
  si `EXIGIR_LICENCIA` y no hay licencia válida → 402 en todo salvo `/`,
  `/api/salud`, `/api/licencia`, `/api/config`, `/static/*`. `EXIGIR_LICENCIA =
  EMPAQUETADA or AFS_FORZAR_LICENCIA==1` (en dev NO exige, salvo con esa env para
  probar). Frontend: overlay `#licencia` (pantalla de activación, pega el código),
  chip `#tb-lic` de vencimiento cuando quedan ≤14 días, `activarLicencia()`.
- Verificado e2e: el `.app` v0.16 congelado exige licencia (`/api/proyectos` da 402
  sin código, 200 tras activar); pantalla de activación probada en el navegador
  (código inválido → error, válido → activa; caducado → aviso). Piso macOS sigue en 11.
- **Código de dueño (1 año, plan owner) para desbloquear tu propia build**:
  `AFS1.eyJleHAiOiIyMDI3LTA3LTExIiwiaWQiOiJkZXJlay1vd25lciIsInBsYW4iOiJvd25lciJ9.cZ1f7EqKzKdKaNFLripJpwqbcSj7znD0Sw28dHIHtQ2wt0N-pi3rastxeqr9k8JtXKmhGg7pnzBER1M9OC9OAg`

## Editor reestructurado sin pestañas (v0.17)

El editor (`#proyecto`) pasó de pestañas (Escena/Previsualización/Todas) a un
layout fijo más simple para no técnicos, según pidió Derek:
- `#ed-cuerpo` = flex row: **`#ed-centro`** (columna izquierda) + **`#ed-derecha`**
  (panel de 366px).
- Centro: **previsualización SIEMPRE visible** (`#pv-lienzo` con alto tope
  `min(46vh,600px)`; `.alto` 9:16 usa `min(58vh,760px)`) + su barra de play, y
  **debajo la línea de tiempo** (`#tl-cab` con botones +Texto/+Imagen/+Animación/
  ♪Música, `#timeline-caja` con pistas, `#regla`, fila de música). El `<audio>`
  ahora es `display:none` (reloj maestro; controla la barra del preview).
- Derecha: **un solo panel** = `#detalle` (imagen, narración, prompt+Regenerar IA,
  "Reemplazar con medios de" Pexels/Google) **apilado con** `#pv-panel` (efectos:
  escala/pos/opacidad/velocidad + movimiento + transición + duración +/- +
  insertar/eliminar). Se quitaron los controles duplicados de duración/efecto/
  transición que estaban en `#detalle`.
- "▦ Todas" (header) abre el modal `#modal-cuadricula` con la cuadrícula de escenas.
- JS: se eliminó `verTab`; `abrirProyecto` llama `pvIniciar()` (preview siempre
  activo, ahora idempotente: cancela el RAF previo); `render()` llama
  `renderPanelEfectos(escenaSel)`; `seleccionar(n)` hace seek del audio y render;
  `pvBucle` ya NO auto-cambia el panel (queda en la escena seleccionada, coherente
  con detalle); `renderCuadricula` solo al abrir el modal; música re-vincula el
  preview con `pvIniciar()`. `renderDetalle` recortado (sin det-dur/efecto/etc.).
- Verificado en navegador: preview central reproduce, timeline debajo, panel
  derecho con todas las herramientas, selección sincroniza detalle+efectos+seek,
  modal Todas, sin errores de consola. Backup del layout previo:
  `index.v016.backup.html` (scratchpad).

## Optimizaciones del editor (v0.18)

Cuatro mejoras de usabilidad sobre el editor v0.17:
1. **Panel derecho retráctil** (`#ed-derecha`): botón `#der-colapsar` en `#der-cab`,
   `togglePanelDer()` (persiste `afv_panel_der`), `.colapsado` → 46px y oculta todo
   menos el toggle (`> *:not(#der-cab){display:none !important}` — el `!important`
   es necesario porque `#ed-derecha #detalle.visible` empata en especificidad).
   Al togglear, `renderTimeline()` tras la transición (el ancho cambió).
2. **Capas por DURACIÓN, no desde/hasta**: los modales de texto/logo/animación
   cambiaron "DESDE (s)/HASTA (s)" (`ov-ini/ov-fin`, `an-ini/an-fin`, ELIMINADOS)
   por un solo campo "¿Cuántos segundos quieres que dure?" (`ov-dur`/`an-dur`). La
   capa nueva se coloca en el punto de la aguja (`ovEditando.inicio` = playhead) y
   `fin = inicio + dur`. Al editar, `dur = fin - inicio`.
3. **Redimensionar capas arrastrando el borde**: `renderOverlays` ahora pinta cada
   `.ov-item` con `.ov-lbl` + `.ov-asa` (asa de resize como las escenas). `ovResize`
   + listeners globales mousemove/mouseup cambian el ancho → `fin = inicio + dur`
   y guardan. El arrastre del cuerpo (mover) sigue con `ovDrag`; el asa hace
   `stopPropagation`.
4. **Zoom de timeline + aguja arrastrable**: `tlZoom` (0.3–6), `zoomTL(f)`; en
   `renderTimeline` `anchoTL = max(160, base*tlZoom)`. Botones 🔍−/🔍+ en `#tl-cab`.
   `#aguja` pasó a `pointer-events:auto` + perilla (`::after`) + zona de agarre
   (`::before`); `agujaDrag` con mousemove global hace scrub (`audio.currentTime`).
   La aguja se reposiciona al final de `renderTimeline` (para zoom con pausa).
- Verificado en navegador: colapso oculta el contenido (46px), modal pide segundos
  y crea la capa en el playhead, resize del borde cambia la duración, zoom escala
  la timeline, y arrastrar la aguja hace scrub exacto. Sin errores de consola.

## Freemium: gratis (marca de agua + 720p + upsell) vs Pro (v0.19)

Monetización de la versión gratis atada al **plan** de la licencia (no anuncios de
terceros — no funcionan en localhost; se descartó AdSense).
- **licencia.py**: `PLANES_PRO = {pro, owner, beta, premium, lifetime, todo, vip}`;
  `es_plan_pro()`; `estado()` expone `pro`. Cualquier otro plan (p. ej. `free`) o
  sin licencia = versión gratis.
- **app.py**: `es_pro()` (con override de dev `AFS_FORZAR_GRATIS=1` para probar la
  versión gratis; en dev sin exigir licencia = Pro). `/api/licencia` devuelve
  `pro=es_pro()`. `/api/exportar/opciones` filtra calidades a ≤720p si gratis y
  devuelve `pro`. `_calidad_permitida()` baja a "ligera" (720p) si gratis. Los
  hilos de export reciben `marca_agua=not es_pro()`.
- **editor.py**: `_marca_agua_png(dims)` = pastilla semitransparente con isotipo
  faceless + "AutoFaceless Studio" (Pillow). `exportar_final`/`exportar_union`
  aceptan `marca_agua`; cuando True hacen overlay con ffmpeg (`overlay=W-w-mgn:
  H-h-mgn`, esquina inferior derecha) — fuerza re-encode (el copy rápido solo
  aplica a Pro sin bajar resolución). El master interno (video.mp4) queda LIMPIO;
  la marca solo se aplica en el pase final del export, así al pasar a Pro se
  re-exporta sin marca.
- **Frontend**: badge `#tb-plan` "🆓 Gratis · Mejora a Pro" (abre la pantalla de
  licencia con botón "Seguir en la versión gratis" = `abrirLicencia`/`cerrarLicencia`;
  `mostrarLicencia` oculta el cierre porque es el gate). Franja `#exp-upsell` en el
  modal de exportar (marca de agua + 720p). `esPro` global viene de `/api/licencia`.
- **admin_licencias.py**: el plan `free` está en el selector para emitir códigos gratis.
- Verificado: gratis → `/api/exportar/opciones` solo 720p y `pro:false`; export real
  gratis = 1280x720 con la marca de agua visible (frame comprobado); Pro → 1080p
  limpio. Badge + upsell + flujo de upgrade sin errores.
- NOTA de modelo: el gate (`EXIGIR_LICENCIA`) sigue pidiendo código al abrir. La
  "versión gratis" hoy = activar un código de plan `free`. Para un free totalmente
  abierto (sin código) habría que permitir en `_puerta_licencia` que "sin licencia"
  = gratis; es 1 cambio, pendiente de decisión de Derek.

## Estado actual: v0.19 (freemium gratis/Pro; zip v0.19 en ~/Documents/CLAUDE/)

> Las secciones de arriba (v0.07–v0.16) documentan lo añadido después de v0.06.
> Esta lista es la base v0.06. Zip vigente:
> `AutoFaceless-Video-v0.19-beta-macOS.zip`. Deps nuevas: `edge-tts` (v0.14).
> Windows: se compila por GitHub Actions o en una PC Windows (ver v0.16).

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
