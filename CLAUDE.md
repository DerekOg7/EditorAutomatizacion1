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

## Versión gratis ABIERTA sin código (v0.20)

Decisión de Derek: la versión gratis se usa **sin código de activación**. Se quitó
la "puerta" de licencia (`_puerta_licencia` before_request ELIMINADA; ya no hay 402
por falta de licencia). El código de licencia solo sirve para **desbloquear Pro**.
- `es_pro()`: sin licencia → gratis en la app empaquetada (`return not
  editor.EMPAQUETADA`); en dev sin licencia = Pro (para probar). AFS_FORZAR_GRATIS=1
  fuerza gratis. Con licencia activa → su plan.
- `/api/licencia` devuelve `exigir: False` siempre → el frontend nunca muestra el
  gate al arrancar (va directo a home; el badge "🆓 Gratis" aparece si no es Pro).
- Se eliminaron `EXIGIR_LICENCIA` / `_LIBRES` / `AFS_FORZAR_LICENCIA` (ya no hay
  beta cerrada; si se quisiera, se reañade una puerta). La pantalla `#licencia`
  ahora solo se abre a voluntad (badge / upsell) para pegar un código Pro.
- Verificado: sin código → `/api/proyectos` da 200 (no bloquea), `pro:false`,
  export solo 720p; la app arranca en home sin pantalla de licencia. Con código
  Pro → 1080p sin marca.

## Candado Pexels + coherencia IA automática + Nano Banana + fix voz→editor (v0.21)

Cuatro mejoras pedidas por Derek:
1. **Candado de Pexels en la Principal**: `empezarNicho()` exige `configApp.pexels`;
   sin clave abre el modal 🔑 con mensaje y NO avanza (evita que el usuario se
   frustre a mitad del flujo sin imágenes automáticas). Con clave avanza normal.
2. **Coherencia IA AUTOMÁTICA al crear historias**: `hilo_procesar` (app.py) ya no
   usa `descargar_imagenes` plano — tras `generar_escenas` corre
   `plan_imagenes_ia` (proveedor auto: claude > gemini > openai > gratis, con la
   `guia_imagenes` del proyecto) y luego `rellenar_inteligente` (todas las fuentes
   si hay Pexels; solo WEB si no). El plan IA es tolerante (try/except: si falla,
   quedan las consultas locales). El botón "✨ Imágenes IA" sigue para re-runs.
   Verificado e2e REAL: historia nueva desde audio → 5 escenas planeadas
   (fuente_ia FOTO/VIDEO 3-2) → medios descargados en esa mezcla exacta.
3. **Nano Banana (Google)**: `editor.gemini_imagen(p, n, prompt)` llama
   `gemini-2.5-flash-image` (`GEMINI_IMAGE_MODEL` para override) con
   `responseModalities:["IMAGE"]` + `imageConfig.aspectRatio` = formato del
   proyecto; parsea `inlineData` (b64) → guarda `NNN.png`. Endpoint
   `/escenas/<n>/ia` acepta `motor:"nano"`. Botón `#btn-nano` 🍌 junto al de IA
   gratis, visible si `configApp.gemini` (`generarIA('nano')`). OJO: el tier
   gratis de Gemini casi no da cuota de imagen → 429 con mensaje claro (la
   integración quedó verificada con la respuesta real de Google).
4. **Fix voz→editor**: (a) `crearHistoriaIA` ya no salta a un editor vacío a los
   600ms — `esperarHistoriaYAbrir()` sondea `/estado` cada 2s mostrando el
   detalle real en el spinner (voz X%, transcribiendo…) y abre el editor SOLO
   cuando `GET /api/proyectos/<n>` responde ok. (b) Overlay `#pv-cargando` sobre
   el preview (spinner + fase + detalle) cuando fase ∈ voz/transcribiendo/escenas
   o imagenes-sin-ninguna-lista (se pinta en `renderEstado`). (c) **Pestaña
   duplicada**: era multiprocessing re-ejecutando el lanzador congelado
   (PyInstaller) durante el trabajo pesado → el "hijo" corría main(), veía la
   instancia sana y abría otra pestaña. Fix: `multiprocessing.freeze_support()`
   en el `__main__` de scripts/lanzador.py ANTES de main(). NO quitar.

## Tutorial interactivo tipo videojuego (v0.22)

Onboarding de coach-marks (spotlight) que lleva al usuario por TODO el flujo para
hacer su primer video demo. Todo en `static/index.html` (motor + contenido).

- **Motor** (`iniciarTutorial`/`mostrarPasoTut`/`tutColocar`/`tutSiguiente`/
  `tutAnterior`/`cerrarTutorial`): un overlay `#tut-hueco` con
  `box-shadow: 0 0 0 9999px` recorta un "hueco" sobre el elemento resaltado
  (todo lo demás atenuado), `#tut-cazador` bloquea clics de la app durante el tour
  (Next-driven), y `#tut-globo` es el globo (número, título, texto, barra de
  puntos, Saltar/Atrás/Siguiente). Posicionamiento: rect del target + scrollIntoView;
  si el target está oculto o es null → tarjeta centrada (hueco de 0px = atenúa todo).
- **Contenido** (`construirPasosTutorial`): 12 pasos si hay historias
  (intro → nicho → guión → voz → editor×5 → cierre), o versión reducida si no las
  hay (los pasos del editor se vuelven tarjetas explicativas). Cada paso: `{page,
  sel, antes, titulo, texto}`. `mostrarPasoTut` hace `irA(page)`, corre `antes`
  (p.ej. `abrirGuionPagina`, `abrirVozPagina`, o abrir `proyectos[0]` con
  `abrirHistoriaEnEditor` para poblar el editor) y coloca el spotlight. **El texto
  del globo se pinta ANTES de esperar la red** (feedback inmediato) con guarda
  anti-carrera (`idxEste === tutIdx`) al reposicionar. Bilingüe con `L()`.
- **Disparo**: automático la 1ª vez tras la bienvenida (`entrarApp` + fallback en
  init si `afv_bienvenida_vista` pero no `afv_tutorial_visto`); relanzable desde
  "▶ Ver tutorial guiado" en la Principal (`home_tutorial`) y en el modal de Ayuda
  (`help_tour`). Teclas: →/Enter avanza, ← retrocede, Esc cierra.
- Verificado e2e en navegador: 12 pasos, navegación entre páginas, spotlight sobre
  los 9 controles reales (todos existen), abre proyecto real en el editor, cierre
  por botón/Esc, ambos botones de lanzamiento, i18n ES/EN, sin errores en consola.

## Segundo nicho: Música & Sonidos Relajantes (v0.23)

Canales de música/sonidos relajantes (lluvia, naturaleza, estrellas, chimenea…):
NO hay narración — el audio se GENERA y las imágenes salen de temas que elige el
usuario. Reusa la estructura de proyecto (audio.mp3 = pista relajante en vez de
narración; escenas = loop visual corto; `ajustes.tipo="relax"`).

Backend en `editor.py` (sección "NICHO: RELAX", antes del CLI):
- **`generar_ambiente(tipos, dur, salida)`**: sintetiza el paisaje sonoro GRATIS
  con ffmpeg (ruido `anoisesrc` filtrado + modulación de volumen por expresión
  `eval=frame` para el vaivén natural). `AMBIENTES` = recetas por sonido (lluvia
  agudo ~4.4kHz, mar grave ~620Hz, fuego ~730Hz, etc. — verificado por centro
  espectral). Mezcla varias capas con `amix`+`alimiter`, fade in/out. Rápido a
  cualquier duración (ruido es baratísimo), así los videos largos son viables.
- **Música relajante (opcional)**: por defecto GRATIS con
  `generar_musica_ambiente(mood, dur, salida, loopable)` — pads/drones de
  sinusoides con vibrato+tremolo lentos (>=0.1Hz, ojo: `tremolo` mínimo 0.1) +
  reverb `aecho` (moods `ACORDES`: pad_calido/pad_sonador/drone/campanas). Y
  opcionalmente `elevenlabs_musica()` (ElevenLabs `/v1/music`) si el usuario marca
  la casilla IA (best-effort: si falla, cae a la música gratis). La música se
  guarda como `musica.mp3` y el ensamblado la mezcla en loop bajo el ambiente.
- **`VISUALES`**: 12 temas → consulta Pexels (video preferido, imagen fallback).
  `armar_escenas_relax` baja un medio por tema y escribe escenas.json (loop de
  `RELAX_SEG`=24s por escena).
- **`ensamblar_relax`** (clave para videos largos): arma el loop visual corto y lo
  recodifica con **bitrate ACOTADO** (`libx264 -crf 25 -maxrate 4M`; SIN esto el
  clip de Pexels a ~18 Mbps hacía que 1 h pesara ~8 GB → ahora ~1.85 GB). Luego lo
  repite con `-stream_loop -1 -i loop -c:v copy -t total` en el MISMO mux del audio
  (sin archivo intermedio de longitud completa, para no duplicar el pico de disco)
  y limpia los `loop*.mp4`. Guarda de espacio en disco antes de mux (`shutil.
  disk_usage`) con mensaje claro. `ensamblar_video` delega aquí si `tipo=="relax"`.
  Verificado: 5 min reales en la app a 4.3 Mbps (154 MB).
- **`crear_relax(...)`** orquesta todo. Endpoint `POST /api/relax` +
  `hilo_relax` en app.py (estado fase="relax"→"listo").

Frontend: tarjeta de nicho activa en el home (`empezarRelax`, portada azul
estrellada), página `#pg-relax` con chips (sonidos multi, visuales multi, música
mood única) + duración (5/10/30/60) + formato + nombre. `crearRelax` hace POST y
sondea `/estado` con barra de progreso; al terminar muestra el video en un panel
con Exportar/Ajustar/Crear otro. i18n ES/EN (claves `rx_*`). El candado de Pexels
también aplica. Música gratis por defecto; ElevenLabs es una casilla opcional.

**Mezcla, preview y edición (mejoras posteriores):**
- **Mixer** (`#rx-mezcla`, `rxRenderMezcla`): una fila por pista seleccionada
  (cada sonido + la música) con slider 0–150 % → `rxVols`{tipo:ganancia} y
  `rxMusVol`. `generar_ambiente` aplica un `volume=` por sonido; la música va a su
  `musica_volumen`. Se re-pinta al togglear sonidos/música/mood.
- **Preview** (`POST /api/relax/preview` → `generar_preview_relax`): genera una
  muestra de ~8 s de la mezcla actual (sonidos a sus volúmenes + música) y la
  devuelve como mp3; el front la reproduce (blob). Botón ▶ por sonido (solo) y
  "▶ Escuchar mezcla". Deja escuchar ANTES de generar el video largo.
- **Editar/regenerar** (`rxEditarProyecto`): `POST /api/relax` con `editar:true`
  sobreescribe un proyecto relax existente (borra medios/render viejos, conserva
  el nombre). `ver_proyecto` devuelve `tipo` + `relax` (config) para pre-rellenar
  el formulario. Abrir un proyecto relax desde "Mis historias" enruta al formulario
  pre-rellenado (no al editor de escenas). `empezarRelax` resetea a defaults limpios.

**Relax PRO (más control — mejora grande):**
- **Catálogo dinámico**: `editor.catalogo_relax()` + `GET /api/relax/catalogo`; el
  frontend arma los chips desde ahí (ya no hardcodeados). 25 sonidos en 4
  categorías (`AMBIENTES_META`/`SONIDOS_CATEGORIAS`: naturaleza/agua/ambientes/
  ruido) con tabs; incluye ruido blanco/rosa/marrón, avión, tren, ventilador,
  cascada, variantes de lluvia/mar, etc.
- **Música ampliada**: 7 pads + 6 tonos de meditación (`MUSICA_META`):
  binaurales alpha/theta/delta (`_musica_binaural`, estéreo real L/R), solfeggio
  432/528, cuenco (parciales inarmónicos). `generar_musica_ambiente` despacha por
  tipo de mood.
- **Control fino**: `generar_ambiente(..., calidez, reverb)` — `_cadena_tono_reverb`
  añade lowpass (calidez 0-100 → 18k…700 Hz) y aecho (reverb). En el mixer:
  volumen + **mute** por pista + sliders maestros calidez/reverb. Se pasan por
  preview y crear_relax; se guardan en ajustes.
- **Presets**: de fábrica (`PRESETS_FABRICA`: Noche de tormenta, Bosque al amanecer,
  Cabaña, Sueño profundo, Concentración, Meditación zen, Playa) + del usuario
  (`relax_presets.json`; `GET/POST/DELETE /api/relax/presets`). Un clic carga la
  mezcla completa; "Guardar mezcla" persiste la actual.
- Frontend catalog-driven: estado en Sets (`rxSonSel`/`rxVisSel`) + `rxVols`/
  `rxMuted`/`rxMusMood`/`rxCalidez`/`rxReverb`; render por `rxRenderSonTabs/
  SonChips/Musica/Visuales/Presets/Mezcla`. Verificado e2e: tabs, presets,
  mute, calidez/reverb, preview, guardar/borrar preset, y render real con
  sonidos+tono+calidez+reverb (60s, 3.45 Mbps).

**UX premium + estéreo real (mejora posterior):**
- **Escucha al clic**: seleccionar un sonido, pad/tono o preset lo REPRODUCE al
  instante (reproductor central `rxTocar` con caché de blobs `rxPrevCache`, máx 40
  — repetir un sonido ya oído es instantáneo). Soltar el slider de volumen de una
  pista re-reproduce esa pista. Deseleccionar el chip que suena detiene el audio.
  El preview de música sola (sin sonidos) lo soporta `generar_preview_relax`
  (endpoint acepta `sonidos=[]` si hay `musica`).
- **Selección visible**: acento propio del nicho `--rxa` (#2e86c1, azul calmado)
  — chips/tabs/botones seleccionados en azul SÓLIDO con texto blanco y sombra
  (antes rgba al 12% casi invisible). El preset cargado queda marcado
  (`rxPresetActivo`). Hover con elevación; pulso `rxLatido` mientras carga; la
  pista sonando muestra un ecualizador animado (`.rx-eq`, 3 barras CSS).
- **Estéreo REAL**: `generar_ambiente` genera DOS ruidos por capa (semillas
  distintas) unidos con `join=stereo` → canales decorrelacionados (sensación de
  amplitud; antes era mono duplicado). Verificado con RMS de L−R en el video final.

**Banco de sonidos REALES (mejora posterior):**
- `SONIDOS_REALES` en editor.py: 9 grabaciones de campo dominio público/CC0 de
  archive.org (lluvia, tormenta, pájaros, ranas, viento en árboles, olas, arroyo,
  fogata, café europeo) con URL directa y crédito. Se descargan la 1ª vez que se
  usan (`_ruta_sonido_real`) a `DATOS/sonidos/<key>.mp3` normalizadas: recorte a
  90s, loudnorm I=-20, 48k estéreo, fades relativos a ambos bordes (el de salida
  vía `areverse` — OJO: `-t 90` debe ir como opción de ENTRADA o areverse
  bufferiza grabaciones de 30+ min y ffmpeg se cuelga, bug real).
- `generar_ambiente` acepta claves reales: entrada `-stream_loop -1 -t dur` +
  `aresample,aformat=stereo` — se mezclan con los sintetizados, mismos volúmenes/
  calidez/reverb/mute. El catálogo las marca `real:true` + `credito`; la UI pinta
  badge "🎙️ REAL" y tooltip con el crédito. `sonidos/` está gitignorado (datos).
- Verificado: 9/9 descargan y normalizan (~7-10s c/u), mezcla real+sintético,
  descarga automática al primer preview (9.4s → luego instantáneo con caché), y
  render de video completo con sonidos reales.

**Música REAL + previsualizador de visuales + poda (v2 del nicho, estilo lofi-girl):**
- **Música REAL CC0** (`MUSICA_REAL` + `_ruta_musica_real`): 6 pistas de verdad de
  archive.org (2 lofi hip hop completas de man9ww/OE Beats + 4 ambient/chill de
  los álbumes CC0 "Calm Pills"/"Chill Pills" de Alaeddin Hallak, cuyos tracks de
  1 h/145 MB se bajan PARCIALES con HTTP Range ~14 MB ≈ 6 min). Descarga al 1er
  uso → `DATOS/musica/<key>.mp3`, loudnorm + fades en bordes (areverse; `-t 360`
  como opción de ENTRADA). En el catálogo van primero (cat "real", badge 🎙️).
  Las "canciones" procedurales anteriores se ELIMINARON (sintetizar melodías con
  senos de ffmpeg suena a órgano raro — Derek las rechazó con razón; no reintentar).
- **Previsualizador de visuales** (`visual_preview` + `GET /api/relax/visual/<key>`
  ?formato&regen=1): al elegir una visual aparece su imagen bajo los chips
  (tarjetas `#rx-vis-prev`). Arte IA: genera con Pollinations y CACHEA en
  `DATOS/visuales/<key>_<fmt>.jpg`; botón 🔄 regenera hasta que guste, y
  `armar_escenas_relax` COPIA esa caché al proyecto → el video lleva EXACTAMENTE
  la imagen vista (verificado por md5). Pexels: miniatura del primer resultado
  (el mismo que usará el video).
- **Loop ping-pong**: en `ensamblar_relax` las escenas de imagen renderizan DOS
  clips (zoom_in + zoom_out) → el movimiento nunca "salta" al reiniciar el loop.
- UX: Duración+Formato fusionados en un bloque, numeración 1-5, ayuda de visuales
  explica el preview. `visuales/` y `musica/` gitignorados (cachés de usuario).

## Precios y estrategia de negocio

`docs/estrategia_precios.md` tiene los costos por generación investigados
(jul-2026: Nano Banana $0.039/img, Hailuo $0.19-0.56/clip, Eleven Music
~$0.16/min, MiniMax voz $0.10/1k chars), el costo por video ($1.4-4.5 premium)
y la propuesta de paquetes: Gratis $0 / Pro BYOK $12.99 / Premium $19.99 con
cupos (≤$6 de costo por usuario → margen ≥70%; video Hailuo como add-on).
Premium requiere un puente de créditos en la nube (pendiente). OJO: migrar
Nano Banana a Gemini 3.1 Flash Image antes del 2-oct-2026.

## Estado actual: v0.23 (nicho Relax v2: música real, preview de visuales, WYSIWYG; código commiteado — pendiente empaquetar zip)

> Las secciones de arriba (v0.07–v0.16) documentan lo añadido después de v0.06.
> Esta lista es la base v0.06. Zip vigente:
> `AutoFaceless-Video-v0.22-beta-macOS.zip`. Deps nuevas: `edge-tts` (v0.14).
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
