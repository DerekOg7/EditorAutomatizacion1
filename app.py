#!/usr/bin/env python3
"""
App web del editor — corre local y abre http://localhost:5178

  .venv/bin/python app.py
"""

import datetime
import re
import threading
import time
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

import editor
from editor import BASE, DATOS, PROYECTOS, ErrorPipeline
from version import VERSION

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024


@app.errorhandler(Exception)
def _registrar_error(e):
    """Beta: cualquier error no controlado se guarda en un log y se muestra
    completo en el navegador, para poder diagnosticarlo en la Mac del usuario."""
    if isinstance(e, HTTPException):
        return e  # 404, 405, etc. pasan tal cual
    tb = traceback.format_exc()
    try:
        with open(DATOS / "error.log", "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            f.write(f"{request.method} {request.path}\n{tb}\n")
    except Exception:
        pass
    cuerpo = ("AutoFaceless Video — error interno / internal error\n"
              "Manda esta pantalla (o el archivo error.log) para diagnosticarlo.\n\n"
              + tb)
    return cuerpo, 500, {"Content-Type": "text/plain; charset=utf-8"}

# Estado de trabajos en segundo plano: nombre → {fase, detalle, progreso, error}
ESTADOS = {}
LOCK = threading.Lock()
DURACIONES = {}  # caché de duraciones de video: (ruta, mtime) → segundos


def duracion_video(ruta):
    clave = (str(ruta), ruta.stat().st_mtime)
    if clave not in DURACIONES:
        try:
            DURACIONES[clave] = editor.ffprobe_duracion(ruta)
        except ErrorPipeline:
            DURACIONES[clave] = 0
    return DURACIONES[clave]


def video_desactualizado(p):
    """True si hay cambios posteriores a la última exportación."""
    v = p / "video.mp4"
    if not v.exists():
        return False
    vm = v.stat().st_mtime
    fuentes = [p / "escenas.json", p / "ajustes.json", p / "subtitulos.json"]
    fuentes += list((p / "imagenes").glob("*")) if (p / "imagenes").is_dir() else []
    m = editor.buscar_musica(p)
    if m:
        fuentes.append(m)
    return any(f.exists() and f.stat().st_mtime > vm for f in fuentes)


def set_estado(nombre, **kw):
    with LOCK:
        e = ESTADOS.setdefault(nombre, {})
        e.update(kw)
        e["actualizado"] = time.time()


def get_estado(nombre):
    with LOCK:
        return dict(ESTADOS.get(nombre, {"fase": "inactivo"}))


def ocupado(nombre):
    return get_estado(nombre).get("fase") in (
        "transcribiendo", "escenas", "imagenes", "exportando",
        "voz", "video_ia")


def nombre_valido(nombre):
    nombre = re.sub(r"[^a-zA-Z0-9_ áéíóúüñÁÉÍÓÚÜÑ-]", "", nombre).strip()
    return nombre.replace(" ", "_")[:60]


# ------------------------------------------------------- hilos de trabajo

def hilo_procesar(nombre, modelo):
    p = PROYECTOS / nombre
    try:
        set_estado(nombre, fase="transcribiendo", progreso=0, error=None,
                   detalle="Cargando Whisper…")
        editor.transcribir_audio(
            p, modelo,
            on_progreso=lambda t, pc: set_estado(nombre, detalle=t, progreso=pc))

        set_estado(nombre, fase="escenas", detalle="Dividiendo en escenas…",
                   progreso=0)
        editor.generar_escenas(p)

        if editor.leer_env().get("PEXELS_API_KEY"):
            set_estado(nombre, fase="imagenes", progreso=0,
                       detalle="Buscando imágenes en Pexels…")
            r = editor.descargar_imagenes(
                p, on_progreso=lambda t, pc: set_estado(nombre, detalle=t,
                                                        progreso=pc))
            pend = r["pendientes"]
            det = (f"{r['descargadas']} imágenes descargadas"
                   + (f", {len(pend)} sin resultados" if pend else ""))
        else:
            det = "Sin clave de Pexels (.env) — agrega las imágenes a mano."
        set_estado(nombre, fase="listo", detalle=det, progreso=100)
    except ErrorPipeline as e:
        set_estado(nombre, fase="error", error=str(e))
    except Exception as e:  # error inesperado: que se vea en la UI
        set_estado(nombre, fase="error", error=f"{type(e).__name__}: {e}")


def hilo_coherencia(nombre, proveedor, modelo):
    """Reescribe las consultas de imagen con IA (viendo toda la historia) y
    reemplaza las imágenes automáticas por otras más coherentes."""
    p = PROYECTOS / nombre
    try:
        set_estado(nombre, fase="imagenes", progreso=0, error=None,
                   detalle="Analizando la historia con IA…")
        r1 = editor.sugerir_consultas_ia(
            p, proveedor=proveedor, modelo=modelo,
            on_progreso=lambda t, pc: set_estado(nombre, detalle=t,
                                                 progreso=pc * 0.3))
        set_estado(nombre, detalle="Reemplazando imágenes coherentes…", progreso=30)
        r2 = editor.descargar_imagenes(
            p, reemplazar_auto=True,
            on_progreso=lambda t, pc: set_estado(nombre, detalle=t,
                                                 progreso=30 + pc * 0.7))
        det = (f"{r1['cambiadas']} consultas mejoradas · "
               f"{r2['descargadas']} imágenes actualizadas"
               + (f", {len(r2['pendientes'])} sin resultados" if r2['pendientes'] else ""))
        set_estado(nombre, fase="listo", detalle=det, progreso=100)
    except ErrorPipeline as e:
        set_estado(nombre, fase="error", error=str(e))
    except Exception as e:
        set_estado(nombre, fase="error", error=f"{type(e).__name__}: {e}")


def hilo_imagenes_inteligente(nombre, guia, fuentes, mezclar, usar_ia,
                              proveedor, modelo):
    """Planea (opcional, con IA) y rellena cada escena buscando en varias
    fuentes (Pexels fotos/videos + web) y eligiendo el mejor medio, mezclando
    foto y video para dar dinamismo."""
    p = PROYECTOS / nombre
    try:
        editor.guardar_ajustes(p, guia_imagenes=guia or "")
        base = 0
        if usar_ia:
            set_estado(nombre, fase="imagenes", progreso=0, error=None,
                       detalle="Planeando las imágenes con IA…")
            r1 = editor.plan_imagenes_ia(
                p, proveedor=proveedor, modelo=modelo, guia=guia,
                on_progreso=lambda t, pc: set_estado(nombre, detalle=t, progreso=pc * 0.3))
            base = 30
        else:
            set_estado(nombre, fase="imagenes", progreso=0, error=None,
                       detalle="Buscando el mejor medio para cada escena…")
        r2 = editor.rellenar_inteligente(
            p, guia=guia, fuentes=fuentes, mezclar=mezclar, reemplazar_auto=True,
            on_progreso=lambda t, pc: set_estado(nombre, detalle=t,
                                                 progreso=base + pc * (1 - base / 100)))
        det = (f"{r2['descargadas']} medios elegidos"
               + (f" · {r2['pendientes']} sin resultado" if r2['pendientes'] else ""))
        set_estado(nombre, fase="listo", detalle=det, progreso=100)
    except ErrorPipeline as e:
        set_estado(nombre, fase="error", error=str(e))
    except Exception as e:
        set_estado(nombre, fase="error", error=f"{type(e).__name__}: {e}")


def hilo_exportar(nombre):
    p = PROYECTOS / nombre
    try:
        set_estado(nombre, fase="exportando", progreso=0, error=None,
                   detalle="Preparando…")
        _, faltantes = editor.ensamblar_video(
            p, on_progreso=lambda t, pc: set_estado(nombre, detalle=t,
                                                    progreso=pc))
        det = "Video exportado"
        if faltantes:
            det += (" ⚠ escenas sin imagen: "
                    + ", ".join(str(n) for n in faltantes))
        set_estado(nombre, fase="listo", detalle=det, progreso=100)
    except ErrorPipeline as e:
        set_estado(nombre, fase="error", error=str(e))
    except Exception as e:
        set_estado(nombre, fase="error", error=f"{type(e).__name__}: {e}")


def hilo_exportar_final(nombre, carpeta, nombre_archivo, calidad):
    p = PROYECTOS / nombre
    try:
        set_estado(nombre, fase="exportando", progreso=0, error=None,
                   detalle="Preparando…", destino=None)
        master_ok = (p / "video.mp4").exists() and not video_desactualizado(p)
        destino = editor.exportar_final(
            p, carpeta, nombre_archivo, calidad, master_ok=master_ok,
            on_progreso=lambda t, pc: set_estado(nombre, detalle=t, progreso=pc))
        set_estado(nombre, fase="listo", progreso=100,
                   detalle=f"Guardado en {destino}", destino=str(destino))
    except ErrorPipeline as e:
        set_estado(nombre, fase="error", error=str(e))
    except Exception as e:
        set_estado(nombre, fase="error", error=f"{type(e).__name__}: {e}")


def hilo_exportar_union(nombres, carpeta, nombre_archivo, calidad):
    try:
        set_estado("__union__", fase="exportando", progreso=0, error=None,
                   detalle="Preparando…", destino=None)
        destino = editor.exportar_union(
            nombres, carpeta, nombre_archivo, calidad,
            on_progreso=lambda t, pc: set_estado("__union__", detalle=t, progreso=pc))
        set_estado("__union__", fase="listo", progreso=100,
                   detalle=f"Guardado en {destino}", destino=str(destino))
    except ErrorPipeline as e:
        set_estado("__union__", fase="error", error=str(e))
    except Exception as e:
        set_estado("__union__", fase="error", error=f"{type(e).__name__}: {e}")


def hilo_historia_ia(nombre, guion, voz, velocidad, modelo, formato="16:9",
                     proveedor="edge"):
    """Genera la voz con el proveedor elegido, crea el proyecto y corre el pipeline."""
    p = PROYECTOS / nombre
    nombres_prov = {"edge": "voces neuronales gratis", "sistema": "voz del sistema",
                    "minimax": "MiniMax", "elevenlabs": "ElevenLabs"}
    try:
        set_estado(nombre, fase="voz", progreso=0, error=None,
                   detalle=f"Generando la voz ({nombres_prov.get(proveedor, proveedor)})…")
        audio = editor.sintetizar_voz(
            guion, proveedor, voz, velocidad,
            on_progreso=lambda t, pc: set_estado(nombre, detalle=t, progreso=pc))
        (p / "imagenes").mkdir(parents=True, exist_ok=True)
        (p / "audio.mp3").write_bytes(audio)
        (p / "guion.txt").write_text(guion + "\n")
        if formato in editor.FORMATOS:
            editor.guardar_ajustes(p, formato=formato)
        hilo_procesar(nombre, modelo)
    except ErrorPipeline as e:
        set_estado(nombre, fase="error", error=str(e))
        if not (p / "audio.mp3").exists() and p.exists():
            import shutil as _sh
            _sh.rmtree(p, ignore_errors=True)   # no dejar proyectos vacíos
    except Exception as e:
        set_estado(nombre, fase="error", error=f"{type(e).__name__}: {e}")


def hilo_video_ia(nombre, n, prompt):
    p = PROYECTOS / nombre
    try:
        set_estado(nombre, fase="video_ia", progreso=0, error=None,
                   detalle=f"Generando video IA para la escena {n}…")
        editor.guardar_historial(p)
        editor.minimax_video(
            p, n, prompt,
            on_progreso=lambda t, pc: set_estado(nombre, detalle=t, progreso=pc))
        set_estado(nombre, fase="listo", progreso=100,
                   detalle=f"Video IA listo en la escena {n}")
    except ErrorPipeline as e:
        set_estado(nombre, fase="error", error=str(e))
    except Exception as e:
        set_estado(nombre, fase="error", error=f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------- rutas

@app.get("/")
def index():
    return send_file(BASE / "static" / "index.html")


@app.get("/api/salud")
def salud():
    """Identifica esta instancia: el lanzador la usa para detectar procesos
    viejos o rotos ocupando el puerto y reemplazarlos. `ok` confirma que la
    instancia aún puede servir la interfaz (sus archivos siguen existiendo)."""
    return jsonify({"app": "autofaceless", "version": VERSION,
                    "ok": (BASE / "static" / "index.html").exists()})


@app.get("/api/config")
def config():
    env = editor.leer_env()
    return jsonify({"pexels": bool(env.get("PEXELS_API_KEY")),
                    "anthropic": bool(env.get("ANTHROPIC_API_KEY")),
                    "minimax": bool(env.get("MINIMAX_API_KEY")),
                    "elevenlabs": bool(env.get("ELEVENLABS_API_KEY")),
                    "gemini": bool(env.get("GEMINI_API_KEY")),
                    "openai": bool(env.get("OPENAI_API_KEY"))})


@app.get("/api/voz/proveedores")
def voz_proveedores():
    """Proveedores de narración (2 gratis + MiniMax/ElevenLabs) con sus voces."""
    return jsonify(editor.proveedores_voz())


CLAVES_PERMITIDAS = ("PEXELS_API_KEY", "ANTHROPIC_API_KEY",
                     "MINIMAX_API_KEY", "MINIMAX_GROUP_ID",
                     "ELEVENLABS_API_KEY",
                     "GEMINI_API_KEY", "OPENAI_API_KEY")


@app.get("/api/claves")
def leer_claves():
    """Estado de cada clave, enmascarada (solo últimos 4 caracteres)."""
    env = editor.leer_env()
    res = {}
    for k in CLAVES_PERMITIDAS:
        v = env.get(k, "")
        res[k] = {"configurada": bool(v),
                  "pista": ("…" + v[-4:]) if len(v) >= 8 else ("✓" if v else "")}
    return jsonify(res)


@app.get("/api/proyectos/<nombre>/subtitulos")
def leer_subs(nombre):
    return jsonify(editor.leer_subtitulos(PROYECTOS / nombre))


@app.post("/api/proyectos/<nombre>/subtitulos/generar")
def generar_subs(nombre):
    try:
        return jsonify(editor.generar_subtitulos(PROYECTOS / nombre))
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/subtitulos")
def guardar_subs(nombre):
    d = request.get_json(force=True) or {}
    datos = editor.leer_subtitulos(PROYECTOS / nombre)
    if "activo" in d:
        datos["activo"] = bool(d["activo"])
    if isinstance(d.get("estilo"), dict):
        datos["estilo"].update({k: v for k, v in d["estilo"].items()
                                if k in ("tamano", "color", "posicion")})
    if isinstance(d.get("frases"), list):
        frases = []
        for fr in d["frases"]:
            try:
                ini, fin = float(fr["inicio"]), float(fr["fin"])
                texto = str(fr.get("texto", "")).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if texto and fin > ini >= 0:
                frases.append({"inicio": round(ini, 2), "fin": round(fin, 2),
                               "texto": texto})
        frases.sort(key=lambda x: x["inicio"])
        datos["frases"] = frases
    editor.guardar_subtitulos(PROYECTOS / nombre, datos)
    return jsonify(datos)



# ------------------------------------------------------- estudio de guión

@app.post("/api/proyectos/<nombre>/imagenes/coherencia")
def imagenes_coherencia(nombre):
    p = PROYECTOS / nombre
    if not p.is_dir():
        return jsonify({"error": "No existe"}), 404
    if not (p / "escenas.json").exists():
        return jsonify({"error": "Aún no hay escenas — procesa el audio primero."}), 400
    if not editor.leer_env().get("PEXELS_API_KEY"):
        return jsonify({"error": "Falta la clave de Pexels (🔑 Claves API) para descargar las imágenes."}), 400
    if ocupado(nombre):
        return jsonify({"error": "Ya hay un proceso en curso para esta historia."}), 400
    d = request.get_json(force=True) or {}
    threading.Thread(target=hilo_coherencia,
                     args=(nombre, d.get("proveedor", "gratis"), d.get("modelo", "")),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/proyectos/<nombre>/imagenes/inteligente")
def imagenes_inteligente(nombre):
    p = PROYECTOS / nombre
    if not p.is_dir():
        return jsonify({"error": "No existe"}), 404
    if not (p / "escenas.json").exists():
        return jsonify({"error": "Aún no hay escenas — procesa el audio primero."}), 400
    if ocupado(nombre):
        return jsonify({"error": "Ya hay un proceso en curso para esta historia."}), 400
    d = request.get_json(force=True) or {}
    fuentes = d.get("fuentes") or ["FOTO", "VIDEO", "WEB"]
    fuentes = [f.upper() for f in fuentes if f.upper() in ("FOTO", "VIDEO", "WEB")]
    if not fuentes:
        return jsonify({"error": "Elige al menos una fuente (fotos, videos o web)."}), 400
    usar_ia = bool(d.get("usar_ia", True))
    if ("FOTO" in fuentes or "VIDEO" in fuentes) and "WEB" not in fuentes \
            and not editor.leer_env().get("PEXELS_API_KEY"):
        return jsonify({"error": "Para fotos/videos de Pexels falta la clave (🔑 Claves API). "
                                 "También puedes activar solo «Web»."}), 400
    threading.Thread(
        target=hilo_imagenes_inteligente,
        args=(nombre, d.get("guia", ""), fuentes, bool(d.get("mezclar", True)),
              usar_ia, d.get("proveedor", "gratis"), d.get("modelo", "")),
        daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/guion/proveedores")
def guion_proveedores():
    env = editor.leer_env()
    return jsonify({
        "gratis": True,
        "claude": bool(env.get("ANTHROPIC_API_KEY")),
        "gemini": bool(env.get("GEMINI_API_KEY")),
        "openai": bool(env.get("OPENAI_API_KEY")),
        "local": editor.modelos_ollama(),   # None = Ollama no corre; [] = sin modelos
    })


@app.post("/api/guion/chat")
def guion_chat():
    d = request.get_json(force=True) or {}
    mensajes = d.get("mensajes") or []
    if not mensajes:
        return jsonify({"error": "mensaje vacío"}), 400
    try:
        texto = editor.chat_guion(mensajes,
                                  proveedor=d.get("proveedor", "gratis"),
                                  modelo=d.get("modelo", ""))
        return jsonify({"texto": texto})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/guiones")
def guiones_lista():
    return jsonify(editor.listar_guiones())


@app.get("/api/guiones/<nombre>")
def guion_leer(nombre):
    try:
        return jsonify(editor.leer_guion(nombre))
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 404


@app.post("/api/guiones/<nombre>")
def guion_guardar(nombre):
    d = request.get_json(force=True) or {}
    try:
        real = editor.guardar_guion(nombre, d.get("texto", ""), d.get("chat", []))
        return jsonify({"ok": True, "nombre": real})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.delete("/api/guiones/<nombre>")
def guion_borrar(nombre):
    try:
        editor.borrar_guion(nombre)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/claves")
def guardar_claves():
    """Guarda las claves pegadas en la interfaz en DATOS/.env (lo crea si no
    existe). Aplican al instante: leer_env() se consulta en cada uso."""
    d = request.get_json(force=True) or {}
    cambios = {}
    for k in CLAVES_PERMITIDAS:
        if k in d:
            v = str(d[k]).strip()
            if v == "\x00borrar":            # marcador explícito de borrado
                cambios[k] = ""
            elif v:
                cambios[k] = v               # pegada nueva → se guarda
            # vacío → no tocar la clave existente
    if cambios:
        editor.guardar_env(cambios)
    return config()


@app.get("/api/proyectos")
def listar_proyectos():
    PROYECTOS.mkdir(exist_ok=True)
    asign = editor.leer_grupos()["asignacion"]
    res = []
    for d in sorted(PROYECTOS.iterdir()):
        if not d.is_dir():
            continue
        escenas = []
        if (d / "escenas.json").exists():
            try:
                escenas = editor.leer_escenas(d)
            except Exception:
                pass
        res.append({
            "nombre": d.name,
            "escenas": len(escenas),
            "imagenes": sum(1 for e in escenas
                            if editor.medio_de_escena(d, e["n"])[0]),
            "video": (d / "video.mp4").exists(),
            "grupo": asign.get(d.name),
            "estado": get_estado(d.name),
        })
    return jsonify(res)


@app.get("/api/grupos")
def grupos_lista():
    return jsonify(editor.leer_grupos()["grupos"])


@app.post("/api/grupos")
def grupo_crear():
    nombre = (request.get_json(force=True) or {}).get("nombre", "")
    return jsonify({"id": editor.crear_grupo(nombre)})


@app.post("/api/grupos/orden")
def grupos_orden():
    ids = (request.get_json(force=True) or {}).get("ids", [])
    editor.ordenar_grupos(ids)
    return jsonify({"ok": True})


@app.post("/api/grupos/<gid>")
def grupo_renombrar(gid):
    nombre = (request.get_json(force=True) or {}).get("nombre", "")
    editor.renombrar_grupo(gid, nombre)
    return jsonify({"ok": True})


@app.delete("/api/grupos/<gid>")
def grupo_borrar(gid):
    editor.borrar_grupo(gid)
    return jsonify({"ok": True})


@app.post("/api/proyectos/<nombre>/grupo")
def proyecto_mover(nombre):
    if not (PROYECTOS / nombre).is_dir():
        return jsonify({"error": "No existe"}), 404
    gid = (request.get_json(force=True) or {}).get("grupo") or ""
    editor.mover_historia(nombre, gid)
    return jsonify({"ok": True})


@app.delete("/api/proyectos/<nombre>")
def proyecto_borrar(nombre):
    if not (PROYECTOS / nombre).is_dir():
        return jsonify({"error": "No existe"}), 404
    if ocupado(nombre):
        return jsonify({"error": "Hay un proceso en curso — espera a que termine."}), 400
    try:
        editor.borrar_proyecto(nombre)
        with LOCK:
            ESTADOS.pop(nombre, None)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos")
def crear_proyecto():
    nombre = nombre_valido(request.form.get("nombre", ""))
    if not nombre:
        return jsonify({"error": "Ponle un nombre a la historia."}), 400
    archivo = request.files.get("audio")
    if not archivo or not archivo.filename:
        return jsonify({"error": "Sube el audio de MiniMax."}), 400
    ext = Path(archivo.filename).suffix.lower()
    if ext not in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"):
        return jsonify({"error": f"Formato de audio no soportado: {ext}"}), 400

    p = PROYECTOS / nombre
    if p.exists():
        return jsonify({"error": f"Ya existe un proyecto llamado '{nombre}'."}), 400
    (p / "imagenes").mkdir(parents=True)
    archivo.save(p / f"audio{ext}")

    guion = (request.form.get("guion") or "").strip()
    if not guion:
        adjunto = request.files.get("guion_archivo")
        if adjunto and adjunto.filename:
            guion = adjunto.read().decode("utf-8", errors="replace").strip()
    if guion:
        (p / "guion.txt").write_text(guion + "\n")

    formato = request.form.get("formato", "16:9")
    if formato in editor.FORMATOS:
        editor.guardar_ajustes(p, formato=formato)

    modelo = request.form.get("modelo", "small")
    threading.Thread(target=hilo_procesar, args=(nombre, modelo),
                     daemon=True).start()
    return jsonify({"ok": True, "nombre": nombre})


@app.get("/api/proyectos/<nombre>")
def ver_proyecto(nombre):
    p = PROYECTOS / nombre
    if not p.is_dir():
        return jsonify({"error": "No existe"}), 404
    escenas = []
    duracion = 0
    if (p / "escenas.json").exists():
        import json
        datos = json.loads((p / "escenas.json").read_text())
        duracion = datos["duracion"]
        for e in datos["escenas"]:
            medio, tipo = editor.medio_de_escena(p, e["n"])
            e["tiene_imagen"] = medio is not None
            e["tipo_medio"] = tipo
            e["v"] = int(medio.stat().st_mtime) if medio else 0
            if tipo == "video":
                e["medio_duracion"] = round(duracion_video(medio), 2)
            e.setdefault("efecto", "auto")
            e.setdefault("transicion", "fundido")
            e.setdefault("video_inicio", 0)
            e.setdefault("escala", 1.0)
            e.setdefault("pos_x", 0.0)
            e.setdefault("pos_y", 0.0)
            e.setdefault("opacidad", 1.0)
            e.setdefault("velocidad", 1.0)
            escenas.append(e)
    audio = None
    try:
        audio = editor.buscar_audio(p).name
    except ErrorPipeline:
        pass
    musica = editor.buscar_musica(p)
    return jsonify({
        "nombre": nombre,
        "audio": audio,
        "duracion": duracion,
        "escenas": escenas,
        "video": (p / "video.mp4").exists(),
        "video_desactualizado": video_desactualizado(p),
        "formato": editor.formato_proyecto(p),
        "guia_imagenes": editor.leer_ajustes(p).get("guia_imagenes", ""),
        "overlays": editor.leer_overlays(p),
        "musica": ({"archivo": musica.name,
                    "volumen": editor.leer_ajustes(p).get("musica_volumen", 0.12)}
                   if musica else None),
        "estado": get_estado(nombre),
    })


@app.get("/api/proyectos/<nombre>/estado")
def estado_proyecto(nombre):
    return jsonify(get_estado(nombre))


@app.get("/api/proyectos/<nombre>/audio")
def audio_proyecto(nombre):
    try:
        return send_file(editor.buscar_audio(PROYECTOS / nombre),
                         conditional=True)
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 404


@app.get("/api/proyectos/<nombre>/imagen/<int:n>")
def imagen_escena(nombre, n):
    try:
        img = editor.miniatura_de_escena(PROYECTOS / nombre, n)
    except ErrorPipeline:
        img = None
    if img is None:
        return jsonify({"error": "sin imagen"}), 404
    resp = send_file(img)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/proyectos/<nombre>/medio/<int:n>")
def medio_escena(nombre, n):
    medio, _tipo = editor.medio_de_escena(PROYECTOS / nombre, n)
    if medio is None:
        return jsonify({"error": "sin medio"}), 404
    resp = send_file(medio, conditional=True)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/imagen")
def subir_imagen(nombre, n):
    p = PROYECTOS / nombre
    archivo = request.files.get("imagen")
    if not archivo or not archivo.filename:
        return jsonify({"error": "No llegó ningún archivo."}), 400
    ext = Path(archivo.filename).suffix.lower()
    if ext not in editor.EXT_IMAGEN + editor.EXT_VIDEO:
        return jsonify({"error": f"Formato no soportado: {ext}"}), 400
    editor.guardar_historial(p)
    editor.borrar_medio(p, n)
    (p / "imagenes").mkdir(exist_ok=True)
    archivo.save(p / "imagenes" / f"{n:03d}{ext}")
    return jsonify({"ok": True})


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/limite")
def limite_escena(nombre, n):
    fin = (request.json or {}).get("fin")
    if fin is None:
        return jsonify({"error": "Falta el nuevo fin."}), 400
    try:
        editor.guardar_historial(PROYECTOS / nombre)
        editor.ajustar_limite(PROYECTOS / nombre, n, fin)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/escenas/intercambiar")
def intercambiar_escenas(nombre):
    d = request.json or {}
    try:
        editor.guardar_historial(PROYECTOS / nombre)
        editor.intercambiar_medios(PROYECTOS / nombre, int(d["a"]), int(d["b"]))
        return jsonify({"ok": True})
    except (KeyError, ValueError):
        return jsonify({"error": "Faltan las escenas a intercambiar."}), 400
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/opciones")
def opciones_escena(nombre, n):
    d = request.json or {}
    try:
        editor.guardar_historial(PROYECTOS / nombre)
        editor.opciones_escena(PROYECTOS / nombre, n,
                               efecto=d.get("efecto"),
                               transicion=d.get("transicion"),
                               prompt=d.get("prompt"),
                               video_inicio=d.get("video_inicio"),
                               ajustes=d.get("ajustes"))
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/ia")
def generar_ia(nombre, n):
    prompt = ((request.json or {}).get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "El prompt está vacío."}), 400
    try:
        editor.guardar_historial(PROYECTOS / nombre)
        editor.generar_imagen_ia(PROYECTOS / nombre, n, prompt)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/pexels")
def buscar_pexels():
    consulta = request.args.get("q", "").strip()
    tipo = request.args.get("tipo", "fotos")
    proyecto = request.args.get("proyecto", "")
    if not consulta:
        return jsonify({"error": "Consulta vacía"}), 400
    orient = "landscape"
    if proyecto and (PROYECTOS / proyecto).is_dir():
        orient = editor.ORIENTACION.get(editor.formato_proyecto(PROYECTOS / proyecto), "landscape")
    try:
        if tipo == "videos":
            return jsonify(editor.pexels_buscar_videos(consulta, 8, orientacion=orient))
        return jsonify(editor.pexels_buscar(consulta, 9, orientacion=orient))
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/pexels")
def usar_pexels(nombre, n):
    d = request.json or {}
    url = d.get("url", "")
    tipo = "video" if d.get("tipo") == "video" else "imagen"
    if not (url.startswith("https://images.pexels.com/")
            or url.startswith("https://videos.pexels.com/")):
        return jsonify({"error": "URL inválida"}), 400
    try:
        editor.guardar_historial(PROYECTOS / nombre)
        editor.descargar_a_escena(PROYECTOS / nombre, n, url, tipo)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/eliminar")
def eliminar_escena(nombre, n):
    p = PROYECTOS / nombre
    try:
        editor.guardar_historial(p)
        editor.eliminar_escena(p, n)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/deshacer")
def deshacer_proyecto(nombre):
    try:
        editor.deshacer(PROYECTOS / nombre)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/rehacer")
def rehacer_proyecto(nombre):
    try:
        editor.rehacer(PROYECTOS / nombre)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/proyectos/<nombre>/waveform")
def waveform(nombre):
    p = PROYECTOS / nombre
    cual = request.args.get("cual", "narracion")
    if cual == "musica":
        archivo = editor.buscar_musica(p)
    else:
        try:
            archivo = editor.buscar_audio(p)
        except ErrorPipeline:
            archivo = None
    if archivo is None:
        return jsonify([])
    cache = p / f".onda_{cual}.json"
    if cache.exists() and cache.stat().st_mtime >= archivo.stat().st_mtime:
        return app.response_class(cache.read_text(), mimetype="application/json")
    import json as _json
    picos = editor.forma_de_onda(archivo)
    cache.write_text(_json.dumps(picos))
    return jsonify(picos)


@app.post("/api/proyectos/<nombre>/overlays")
def guardar_overlay(nombre):
    p = PROYECTOS / nombre
    editor.guardar_historial(p)
    import time as _t
    if request.files.get("logo"):           # logo nuevo: multipart
        archivo = request.files["logo"]
        ext = Path(archivo.filename).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            return jsonify({"error": f"Formato no soportado: {ext}"}), 400
        ov = {"id": request.form.get("id") or str(_t.time_ns()),
              "tipo": "logo",
              "inicio": request.form.get("inicio", 0),
              "fin": request.form.get("fin", 10),
              "posicion": request.form.get("posicion", "sd"),
              "tamano": request.form.get("tamano", "m")}
        (p / "overlays").mkdir(exist_ok=True)
        for viejo in (p / "overlays").glob(f"{ov['id']}.*"):
            viejo.unlink()
        archivo.save(p / "overlays" / f"{ov['id']}{ext}")
    else:                                    # texto o edición: JSON
        d = request.json or {}
        ov = {"id": d.get("id") or str(_t.time_ns()),
              "tipo": d.get("tipo", "texto"),
              "inicio": d.get("inicio", 0), "fin": d.get("fin", 5),
              "posicion": d.get("posicion", "ic"),
              "tamano": d.get("tamano", "m")}
        if ov["tipo"] == "texto":
            ov["texto"] = (d.get("texto") or "").strip()
            ov["color"] = d.get("color", "#ffffff")
            if not ov["texto"]:
                return jsonify({"error": "El texto está vacío."}), 400
        elif ov["tipo"] == "animacion":
            plantilla = d.get("plantilla", "contador")
            if plantilla not in editor.PLANTILLAS:
                return jsonify({"error": "Plantilla desconocida."}), 400
            ov["plantilla"] = plantilla
            ov["color"] = d.get("color", "#8b5cf6")
            if plantilla == "contador":
                try:
                    ov["objetivo"] = float(d.get("objetivo"))
                except (TypeError, ValueError):
                    return jsonify({"error": "Escribe el número objetivo."}), 400
                ov["prefijo"] = (d.get("prefijo") or "")[:20]
                ov["sufijo"] = (d.get("sufijo") or "")[:20]
                ov["formato"] = "anio" if d.get("formato") == "anio" else "numero"
            elif plantilla == "banner":
                ov["titulo"] = (d.get("titulo") or "").strip()[:80]
                ov["subtitulo"] = (d.get("subtitulo") or "").strip()[:80]
                if not ov["titulo"]:
                    return jsonify({"error": "El banner necesita un título."}), 400
            elif plantilla == "barras":
                barras = []
                for b in (d.get("barras") or [])[:5]:
                    et = (str(b.get("etiqueta", "")) or "").strip()[:20]
                    try:
                        val = float(b.get("valor", 0))
                    except (TypeError, ValueError):
                        val = 0
                    if et:
                        barras.append({"etiqueta": et, "valor": val})
                if len(barras) < 2:
                    return jsonify({"error": "La gráfica necesita al menos 2 barras con etiqueta."}), 400
                ov["barras"] = barras
            elif plantilla == "cuenta":
                try:
                    ov["desde"] = max(0, float(d.get("desde")))
                except (TypeError, ValueError):
                    return jsonify({"error": "Escribe el número de inicio de la cuenta."}), 400
                ov["sufijo"] = (d.get("sufijo") or "")[:20]
            elif plantilla == "cita":
                ov["texto"] = (d.get("texto") or "").strip()[:280]
                ov["autor"] = (d.get("autor") or "").strip()[:60]
                if not ov["texto"]:
                    return jsonify({"error": "La cita necesita un texto."}), 400
            elif plantilla == "lista":
                items = [str(i).strip()[:60] for i in (d.get("items") or [])
                         if str(i).strip()][:6]
                if len(items) < 2:
                    return jsonify({"error": "La lista necesita al menos 2 puntos."}), 400
                ov["items"] = items
    try:
        editor.guardar_overlay(p, ov)
        return jsonify({"ok": True, "id": ov["id"]})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.delete("/api/proyectos/<nombre>/overlays/<oid>")
def borrar_overlay(nombre, oid):
    p = PROYECTOS / nombre
    editor.guardar_historial(p)
    editor.borrar_overlay(p, oid)
    return jsonify({"ok": True})


@app.get("/api/proyectos/<nombre>/overlays/<oid>/imagen")
def logo_overlay(nombre, oid):
    f = editor.logo_de_overlay(PROYECTOS / nombre, oid)
    if f is None:
        return jsonify({"error": "sin logo"}), 404
    return send_file(f)


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/dividir")
def dividir_escena(nombre, n):
    if ocupado(nombre):
        return jsonify({"error": "Espera a que termine el proceso actual."}), 409
    punto = (request.json or {}).get("punto")
    try:
        editor.guardar_historial(PROYECTOS / nombre)
        nueva = editor.dividir_escena(PROYECTOS / nombre, n, punto)
        return jsonify({"ok": True, "nueva": nueva["n"]})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/sugerir")
def sugerir(nombre, n):
    try:
        consulta = editor.sugerir_consulta(PROYECTOS / nombre, n)
        return jsonify({"ok": True, "consulta": consulta})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/web")
def buscar_web():
    consulta = request.args.get("q", "").strip()
    if not consulta:
        return jsonify({"error": "Consulta vacía"}), 400
    try:
        return jsonify(editor.web_buscar_imagenes(consulta, 9))
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/web")
def usar_web(nombre, n):
    url = ((request.json or {}).get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL inválida"}), 400
    try:
        editor.guardar_historial(PROYECTOS / nombre)
        editor.descargar_web_a_escena(PROYECTOS / nombre, n, url)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/proyectos/<nombre>/musica")
def subir_musica(nombre):
    p = PROYECTOS / nombre
    archivo = request.files.get("musica")
    if not archivo or not archivo.filename:
        return jsonify({"error": "No llegó ningún archivo."}), 400
    ext = Path(archivo.filename).suffix.lower()
    if ext not in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"):
        return jsonify({"error": f"Formato no soportado: {ext}"}), 400
    vieja = editor.buscar_musica(p)
    if vieja:
        vieja.unlink()
    archivo.save(p / f"musica{ext}")
    return jsonify({"ok": True})


@app.post("/api/proyectos/<nombre>/formato")
def cambiar_formato(nombre):
    p = PROYECTOS / nombre
    if not p.is_dir():
        return jsonify({"error": "No existe"}), 404
    fmt = (request.get_json(force=True) or {}).get("formato", "")
    if fmt not in editor.FORMATOS:
        return jsonify({"error": "Formato no válido"}), 400
    editor.guardar_ajustes(p, formato=fmt)
    # el video hay que rearmarlo con el nuevo formato
    (p / "video.mp4").unlink(missing_ok=True)
    return jsonify({"ok": True, "formato": fmt})


@app.post("/api/proyectos/<nombre>/musica/volumen")
def volumen_musica(nombre):
    v = (request.json or {}).get("volumen")
    try:
        v = max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return jsonify({"error": "Volumen inválido"}), 400
    editor.guardar_ajustes(PROYECTOS / nombre, musica_volumen=v)
    return jsonify({"ok": True})


@app.delete("/api/proyectos/<nombre>/musica")
def quitar_musica(nombre):
    m = editor.buscar_musica(PROYECTOS / nombre)
    if m:
        m.unlink()
    return jsonify({"ok": True})


@app.get("/api/proyectos/<nombre>/musica/audio")
def audio_musica(nombre):
    m = editor.buscar_musica(PROYECTOS / nombre)
    if not m:
        return jsonify({"error": "Sin música"}), 404
    return send_file(m, conditional=True)


@app.post("/api/ia/guion")
def ia_guion():
    d = request.json or {}
    tema = (d.get("tema") or "").strip()
    if not tema:
        return jsonify({"error": "Escribe el tema de la historia."}), 400
    try:
        minutos = max(1, min(20, float(d.get("minutos", 10))))
        guion, proveedor = editor.generar_guion(tema, minutos,
                                                d.get("estilo", "misterio"),
                                                d.get("canal", ""))
        return jsonify({"guion": guion, "proveedor": proveedor,
                        "palabras": len(guion.split())})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/ia/voz_prueba")
def ia_voz_prueba():
    d = request.json or {}
    texto = (d.get("texto") or "").strip()[:220]
    if not texto:
        return jsonify({"error": "No hay texto para probar."}), 400
    try:
        audio = editor.sintetizar_voz(texto, d.get("proveedor", "edge"),
                                      d.get("voz", ""),
                                      float(d.get("velocidad", 1.0)))
        return app.response_class(audio, mimetype="audio/mpeg")
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/ia/historia")
def ia_historia():
    d = request.json or {}
    nombre = nombre_valido(d.get("nombre", ""))
    guion = (d.get("guion") or "").strip()
    if not nombre:
        return jsonify({"error": "Ponle un nombre a la historia."}), 400
    if len(guion) < 100:
        return jsonify({"error": "El guión está vacío o es demasiado corto."}), 400
    if (PROYECTOS / nombre).exists():
        return jsonify({"error": f"Ya existe un proyecto llamado '{nombre}'."}), 400
    threading.Thread(
        target=hilo_historia_ia,
        args=(nombre, guion, d.get("voz", ""), float(d.get("velocidad", 1.0)),
              d.get("modelo", "small"), d.get("formato", "16:9"),
              d.get("proveedor", "edge")),
        daemon=True).start()
    return jsonify({"ok": True, "nombre": nombre})


@app.post("/api/proyectos/<nombre>/escenas/<int:n>/video_ia")
def video_ia(nombre, n):
    if ocupado(nombre):
        return jsonify({"error": "Este proyecto ya está trabajando."}), 409
    prompt = ((request.json or {}).get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "El prompt está vacío."}), 400
    threading.Thread(target=hilo_video_ia, args=(nombre, n, prompt),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/proyectos/<nombre>/exportar")
def exportar(nombre):
    if ocupado(nombre):
        return jsonify({"error": "Este proyecto ya está trabajando."}), 409
    threading.Thread(target=hilo_exportar, args=(nombre,), daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/exportar/opciones")
def exportar_opciones():
    return jsonify({"carpetas": editor.carpetas_comunes(),
                    "calidades": [{"id": k, "etiqueta": v["etiqueta"]}
                                  for k, v in editor.CALIDADES.items()]})


@app.post("/api/proyectos/<nombre>/exportar_final")
def exportar_final(nombre):
    if ocupado(nombre):
        return jsonify({"error": "Este proyecto ya está trabajando."}), 409
    d = request.json or {}
    threading.Thread(
        target=hilo_exportar_final,
        args=(nombre, d.get("carpeta", ""), d.get("nombre_archivo", ""),
              d.get("calidad", "alta")),
        daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/revelar")
def revelar():
    ruta = (request.json or {}).get("ruta", "")
    try:
        editor.revelar_en_finder(ruta)
        return jsonify({"ok": True})
    except ErrorPipeline as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/proyectos/<nombre>/video")
def video_proyecto(nombre):
    v = PROYECTOS / nombre / "video.mp4"
    if not v.exists():
        return jsonify({"error": "Aún no hay video exportado."}), 404
    return send_file(v, conditional=True)


@app.post("/api/exportar_union")
def exportar_union():
    datos = request.json or {}
    nombres = datos.get("historias", [])
    if len(nombres) < 2:
        return jsonify({"error": "Elige al menos 2 historias."}), 400
    for n in nombres:
        if not (PROYECTOS / n).is_dir():
            return jsonify({"error": f"No existe la historia '{n}'."}), 404
    if ocupado("__union__"):
        return jsonify({"error": "Ya hay una exportación en curso."}), 409
    threading.Thread(
        target=hilo_exportar_union,
        args=(nombres, datos.get("carpeta", ""),
              datos.get("nombre_archivo", "video_final"),
              datos.get("calidad", "alta")),
        daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/exportar_union/estado")
def exportar_union_estado():
    return jsonify(get_estado("__union__"))


if __name__ == "__main__":
    PROYECTOS.mkdir(exist_ok=True)
    app.run(host="127.0.0.1", port=5178, threaded=True)
