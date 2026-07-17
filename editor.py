#!/usr/bin/env python3
"""
AutoFaceless Video — editor automático de videos faceless para YouTube.

Flujo por historia:
  1. transcribir  → audio.mp3 con Whisper → transcripcion.json
  2. escenas      → divide en escenas de 5-10s → escenas.json + prompts_ia.md
  3. imagenes     → descarga de Pexels lo que pueda; el resto lo pones tú
  4. ensamblar    → Ken Burns + fundidos + audio → video.mp4 (1080p)

Final:
  unir → concatena las 3 historias con fundido → video de 30 min.

Uso:  ./editor <comando> [argumentos]   (ver README.md)
La app web (app.py) usa estas mismas funciones.
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

EMPAQUETADA = getattr(sys, "frozen", False)
ES_WIN = sys.platform.startswith("win")
ES_MAC = sys.platform == "darwin"
_EXE = ".exe" if ES_WIN else ""


def _carpeta_datos():
    """Carpeta de datos del usuario, según el sistema operativo (sobrevive a
    actualizaciones de la app)."""
    if ES_WIN:
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "AutoFacelessVideo"
    if ES_MAC:
        return Path.home() / "Library" / "Application Support" / "AutoFacelessVideo"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "AutoFacelessVideo"


if EMPAQUETADA:
    # App empaquetada: el código vive dentro del bundle (solo lectura); los datos
    # del usuario van en su carpeta de soporte del SO, para sobrevivir actualizaciones.
    BASE = Path(sys._MEIPASS)                      # recursos empaquetados (solo lectura)
    DATOS = _carpeta_datos()
    FFMPEG_BIN = BASE / "ffmpeg" / f"ffmpeg{_EXE}"
    FFPROBE_BIN = BASE / "ffmpeg" / f"ffprobe{_EXE}"
else:
    BASE = Path(__file__).resolve().parent          # modo desarrollo (como hasta ahora)
    DATOS = BASE
    # Preferir el ffmpeg estático empaquetado también en dev: es el mismo que
    # usan los usuarios y trae libass (subtítulos), que falta en el de Homebrew.
    _ff = BASE / "empaquetado" / "ffmpeg"
    FFMPEG_BIN = _ff / f"ffmpeg{_EXE}" if (_ff / f"ffmpeg{_EXE}").exists() else "ffmpeg"
    FFPROBE_BIN = _ff / f"ffprobe{_EXE}" if (_ff / f"ffprobe{_EXE}").exists() else "ffprobe"

DATOS.mkdir(parents=True, exist_ok=True)
PROYECTOS = DATOS / "proyectos"
PROYECTOS.mkdir(exist_ok=True)

FPS = 30
TIMESCALE = "15360"     # base de tiempo común en todos los clips (512*30)
ANCHO, ALTO = 1920, 1080   # 16:9 por defecto (lado corto = 1080)

# Formatos de lienzo/exportación soportados (lado corto = 1080 px)
FORMATOS = {
    "16:9": (1920, 1080),   # horizontal (YouTube)
    "9:16": (1080, 1920),   # vertical (Shorts/Reels/TikTok)
    "1:1":  (1080, 1080),   # cuadrado
}


def dims_formato(formato):
    return FORMATOS.get(formato or "16:9", (ANCHO, ALTO))

FUNDIDO = 0.6            # segundos de crossfade entre escenas
FUNDIDO_HISTORIAS = 1.0  # segundos de crossfade entre historias
ESCENA_MIN = 5.0         # las imágenes duran entre 5 y 10 segundos
ESCENA_MEDIA = 7.5
ESCENA_MAX = 10.0
TAM_LOTE_XFADE = 12      # escenas por lote al encadenar fundidos
EXT_IMAGEN = (".jpg", ".jpeg", ".png", ".webp")
EXT_VIDEO = (".mp4", ".mov", ".m4v", ".webm")
DUR_MINIMA_ESCENA = 1.5  # al ajustar límites a mano
MIN_DIVIDIR = 1.0        # cada mitad al dividir una escena

# efectos de imagen disponibles (por escena)
EFECTOS = ("auto", "zoom_in", "zoom_out", "pan_h", "pan_v", "estatico")

# transiciones disponibles → nombre del filtro xfade de ffmpeg
XFADE = {"fundido": "fade", "negro": "fadeblack", "disolver": "dissolve",
         "deslizar": "slideleft", "circulo": "circleopen",
         "zoom": "zoomin", "pixel": "pixelize"}
TRANSICIONES = ("corte",) + tuple(XFADE)

STOPWORDS = set("""
el la los las un una unos unas de del al a ante bajo con contra desde durante
en entre hacia hasta para por segun sin sobre tras y o u e ni que como cuando
donde quien cual cuyo se su sus le les lo mi mis tu tus nos os me te si no
mas pero aunque porque pues ya muy tan tanto toda todo todas todos esta este
estas estos esa ese esas esos aquel aquella aquellos aquellas fue era eran
ser es son estaba estaban estar ha han habia habian hay haber sido esto eso
aquello algo alguien nada nadie cada uno dos tres vez veces asi tambien
entonces luego despues antes ahora aqui alli alla habría sería podría
mientras incluso solo sólo hasta cerca lejos dentro fuera nunca siempre
jamas quizas quiza tal vez decir dijo dice dicen hacer hizo hacen tener
tenia tiene tienen poder podia puede pueden año años dia dias noche parte
misma mismo mismos mismas otro otra otros otras gran grandes segun sino
algun alguna algunos algunas varios varias mucho mucha muchos muchas poco
poca pocos pocas cierto cierta ciertos ciertas demasiado bastante
""".split())

# Palabras abstractas / no representables: al buscar imágenes solo estorban
# (dan resultados que "no concuerdan"). Se descartan como palabra clave.
ABSTRACTAS = set("""
version versiones inconsistencia inconsistencias detalle detalles manera maneras
modo modos forma formas hecho hechos caso casos asunto asuntos momento momentos
situacion situaciones realidad verdad verdades mentira mentiras historia historias
relato relatos idea ideas teoria teorias hipotesis prueba pruebas evidencia
evidencias informacion informe informes dato datos causa causas razon razones
motivo motivos consecuencia consecuencias resultado resultados proceso procesos
sistema sistemas metodo metodos aspecto aspectos punto puntos parte partes tipo
tipos clase clases nivel niveles estado estados condicion condiciones cantidad
cantidades numero numeros cifra cifras valor valores posibilidad capacidad
necesidad importancia interes sentido significado concepto conocimiento problema
problemas solucion soluciones pregunta preguntas respuesta respuestas decision
decisiones opinion opiniones palabra palabras nombre nombres tiempo tiempos
ocasion ocasiones presencia ausencia existencia principio comienzo intento
intentos suceso sucesos acontecimiento acontecimientos hora horas semana semanas
mes meses decada decadas siglo siglos epoca epocas persona personas gente
hombre mujer cosa cosas mundo vida muerte gobierno pais paises manera final
finales cuenta relatos testimonio testimonios version misterio enigma secreto
asegurar asegura aseguro aseguraron encontrar encontro encontraron coincidir
coincidia coincidian comenzar comenzo comenzaron guardar guardo guardaron
acercar acerco acercarse clasificar clasificado clasificados clasificada explicar
explico ocurrir ocurrio ocurria aparecer aparecio existir permitir permitio
lograr logro intentar intento tratar trato considerar senalar indicar mostrar
revelar revelo descubrir descubrio confirmar confirmo llegar llego llegaron
pasar paso pasaron quedar quedo suceder sucedio resultar resulto convertir
visto vista puesto dicho debido podido tenido sabido querido creido oido
mil ciento cientos doscientos trescientos cuatrocientos quinientos seiscientos
setecientos ochocientos novecientos millon millones cero cuatro cinco seis
siete ocho nueve diez once doce trece catorce quince dieciseis diecisiete
dieciocho diecinueve veinte treinta cuarenta cincuenta sesenta setenta ochenta
noventa cien primero primera segundo segunda tercero tercera cuarto quinto
pudo pude pudiste pudimos pudieron tuvo tuve tuvieron hizo hice hicieron puso
puse pusieron quiso quise supo supe vino vine trajo cupo anduvo estuvo estuve
""".split())


class ErrorPipeline(Exception):
    """Error esperado del flujo (mensaje apto para mostrar al usuario)."""


# ---------------------------------------------------------------- utilidades

def err(msg):
    raise ErrorPipeline(msg)


def run(cmd, **kw):
    """Ejecuta un comando y aborta con el error visible si falla. Si el
    primer elemento es 'ffmpeg'/'ffprobe', se resuelve al binario empaquetado
    (app de macOS) o al del PATH (modo desarrollo, vía Homebrew)."""
    cmd = list(cmd)
    if cmd and cmd[0] == "ffmpeg":
        cmd[0] = str(FFMPEG_BIN)
    elif cmd and cmd[0] == "ffprobe":
        cmd[0] = str(FFPROBE_BIN)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        cola = "\n".join(r.stderr.splitlines()[-15:])
        err(f"Falló: {' '.join(map(str, cmd[:6]))}…\n{cola}")
    return r


def ffprobe_duracion(archivo):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(archivo)])
    return float(r.stdout.strip())


def video_valido(ruta):
    """True si el mp4 se puede leer (no está truncado/corrupto). Sirve para no
    confiar en un maestro que quedó a medias, p. ej. por quedarse sin espacio."""
    ruta = Path(ruta)
    if not ruta.exists() or ruta.stat().st_size < 1024:
        return False
    try:
        return ffprobe_duracion(ruta) > 0
    except (ErrorPipeline, ValueError):
        return False


def dir_proyecto(nombre):
    p = PROYECTOS / nombre
    if not p.is_dir():
        err(f"No existe el proyecto '{nombre}'. Créalo con: ./editor nuevo {nombre}")
    return p


def buscar_audio(p):
    for ext in ("mp3", "wav", "m4a", "aac", "flac", "ogg"):
        candidatos = sorted(p.glob(f"*.{ext}"))
        if candidatos:
            return candidatos[0]
    err(f"No encontré ningún audio en {p}. Copia ahí el mp3 de MiniMax.")


def leer_env():
    env = {}
    archivo = DATOS / ".env"
    if archivo.exists():
        for linea in archivo.read_text().splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def guardar_env(cambios):
    """Escribe/actualiza claves en DATOS/.env preservando las líneas que no
    cambian (comentarios incluidos). `cambios` = {CLAVE: valor}; un valor
    vacío borra la clave."""
    archivo = DATOS / ".env"
    lineas = archivo.read_text().splitlines() if archivo.exists() else []
    pendientes = dict(cambios)
    nuevas = []
    for linea in lineas:
        cruda = linea.strip()
        if cruda and not cruda.startswith("#") and "=" in cruda:
            k = cruda.split("=", 1)[0].strip()
            if k in pendientes:
                v = pendientes.pop(k)
                if v:                       # valor nuevo → reemplaza la línea
                    nuevas.append(f"{k}={v}")
                continue                    # vacío → se elimina la línea
        nuevas.append(linea)
    for k, v in pendientes.items():         # claves que no existían
        if v:
            nuevas.append(f"{k}={v}")
    archivo.write_text("\n".join(nuevas).rstrip("\n") + "\n")


def sin_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def imagen_de_escena(p, n):
    """Devuelve la ruta de la imagen de la escena n, o None si no existe."""
    for ext in EXT_IMAGEN:
        cand = p / "imagenes" / f"{n:03d}{ext}"
        if cand.exists():
            return cand
    return None


def medio_de_escena(p, n):
    """Devuelve (ruta, tipo) del medio de la escena n; tipo es
    'imagen' o 'video'. (None, None) si no hay nada."""
    img = imagen_de_escena(p, n)
    if img:
        return img, "imagen"
    for ext in EXT_VIDEO:
        cand = p / "imagenes" / f"{n:03d}{ext}"
        if cand.exists():
            return cand, "video"
    return None, None


def borrar_medio(p, n):
    viejo, _ = medio_de_escena(p, n)
    if viejo:
        viejo.unlink()
    mini = p / "miniaturas" / f"{n:03d}.jpg"
    if mini.exists():
        mini.unlink()


def miniatura_de_escena(p, n):
    """Miniatura jpg del medio de la escena (para videos se genera y cachea)."""
    medio, tipo = medio_de_escena(p, n)
    if medio is None:
        return None
    if tipo == "imagen":
        return medio
    mini = p / "miniaturas" / f"{n:03d}.jpg"
    if not mini.exists() or mini.stat().st_mtime < medio.stat().st_mtime:
        (p / "miniaturas").mkdir(exist_ok=True)
        run(["ffmpeg", "-y", "-ss", "0.5", "-i", str(medio),
             "-frames:v", "1", "-vf", "scale=480:-2", str(mini)])
    return mini


# ----------------------------------------------------------- núcleo: whisper

def transcribir_audio(p, modelo="small", on_progreso=None):
    """Transcribe el audio del proyecto → transcripcion.json. Devuelve datos."""
    audio = buscar_audio(p)
    avisar = on_progreso or (lambda *_: None)
    avisar("Cargando modelo Whisper (la primera vez se descarga)…", 0)

    from faster_whisper import WhisperModel
    model = WhisperModel(modelo, device="cpu", compute_type="int8")
    duracion = round(ffprobe_duracion(audio), 2)
    segmentos_iter, _info = model.transcribe(str(audio), language="es",
                                             vad_filter=True,
                                             word_timestamps=True)
    segmentos = []
    for s in segmentos_iter:
        segmentos.append({"inicio": round(s.start, 2),
                          "fin": round(s.end, 2),
                          "texto": s.text.strip(),
                          "palabras": [{"inicio": round(w.start, 3),
                                        "fin": round(w.end, 3),
                                        "palabra": w.word}
                                       for w in (s.words or [])]})
        avisar(f"Transcribiendo… {s.end:.0f}s / {duracion:.0f}s",
               min(99, s.end / duracion * 100))

    datos = {"audio": audio.name, "duracion": duracion, "segmentos": segmentos}
    (p / "transcripcion.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2))
    return datos


# ----------------------------------------------------------- núcleo: escenas

def _entidades(texto):
    """Nombres propios / entidades: secuencias de palabras con mayúscula que
    NO abren frase (p. ej. "Nuevo México", "Área 51"). Son los términos más
    específicos y los que mejor funcionan al buscar imágenes concretas."""
    frases = []
    buf = []
    abre_frase = True
    for tok in texto.split():
        nucleo = tok.strip(".,;:!?…\"'()[]¡¿»«")
        es_nombre = bool(re.match(r"[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]{2,}$", nucleo))
        if es_nombre and not abre_frase:
            buf.append(nucleo)
        elif nucleo.isdigit() and buf:      # un número solo extiende ("Área 51")
            buf.append(nucleo)
        else:
            if buf:
                frases.append(" ".join(buf))
            buf = []
        abre_frase = tok.endswith((".", "!", "?", "…", ":"))
    if buf:
        frases.append(" ".join(buf))
    return list(dict.fromkeys(frases))


def _concretas(texto, n):
    """Sustantivos concretos/representables de la escena, filtrando lo abstracto
    y los verbos comunes; los nombres propios pesan más."""
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", texto)
    frec = {}
    orden = {}
    for i, w in enumerate(palabras):
        base = sin_acentos(w.lower())
        if len(base) <= 3 or base in STOPWORDS or base in ABSTRACTAS:
            continue
        if base.endswith("mente") and len(base) > 6:  # adverbios (-mente)
            continue
        if re.search(r"(ó|aron|ieron)$", w.lower()):   # verbos (llegó, vieron)
            continue
        peso = 1
        if w[0].isupper() and i > 0:        # nombre propio a mitad de frase
            peso += 3
        if base not in frec:
            orden[base] = w.lower()
        frec[base] = frec.get(base, 0) + peso
    mejores = sorted(frec, key=lambda b: -frec[b])[:n]
    return [orden[b] for b in mejores]


def _anclas_historia(textos, k=2):
    """Términos VISUALES dominantes de TODA la historia, para que cada escena
    mantenga coherencia con el video completo y no solo con su frase suelta.

    Prefiere sustantivos comunes representables (desierto, océano, avión) sobre
    nombres propios: un nombre propio ("Roswell") da contexto pero casi no tiene
    fotos en bancos como Pexels, así que sería un ancla que no encuentra nada."""
    # unidades y adjetivos frecuentes que NO representan una imagen concreta
    no_visual = {"metros", "metro", "kilometros", "kilometro", "centimetros",
                 "toneladas", "grados", "mundial", "mundiales", "nacional",
                 "internacional", "oficial", "oficiales", "general", "generales",
                 "total", "totales", "enorme", "inmenso", "extrano", "extrana",
                 "aterrador", "aterradora", "increible", "posible", "imposible"}
    completo = " ".join(textos)
    candidatos = [c for c in _concretas(completo, 10)
                  if sin_acentos(c) not in no_visual][:6]
    comunes, propios = [], []
    for c in candidatos:
        # nombre propio si aparece siempre capitalizado en el texto original
        es_propio = bool(re.search(rf"\b{re.escape(c[:1].upper() + c[1:])}\b", completo)) \
            and not re.search(rf"\b{re.escape(c)}\b", completo)
        (propios if es_propio else comunes).append(c)
    anclas = comunes[:k]
    if len(anclas) < k:                            # completa con propios si hace falta
        for pr in propios:
            if pr not in anclas:
                anclas.append(pr)
            if len(anclas) >= k:
                break
    return anclas[:k]


def _combinar_consulta(claves, anclas):
    """Une los términos de la escena con el ancla de la historia, sin duplicar,
    para que la imagen encaje a la vez con la frase y con el video completo."""
    generico = {"oscuridad", "misterio", "niebla"}
    escena = [c for c in claves if sin_acentos(c) not in generico]
    if not escena:                                 # escena sin nada concreto → manda la historia
        base = list(anclas) or list(claves)
    else:
        base = escena[:2] + list(anclas[:1])       # detalle de la escena + 1 ancla de contexto
    vistos, out = set(), []
    for t in base:
        k = sin_acentos(t.lower())
        if k and k not in vistos and not any(k in v or v in k for v in vistos):
            vistos.add(k)
            out.append(t)
    return out[:3] or ["oscuridad", "misterio", "niebla"]


SISTEMA_IMAGENES = """Eres director de arte de un video narrado. Recibes el \
guión completo dividido en escenas numeradas. Para CADA escena, escribe la mejor \
consulta de búsqueda de imágenes de archivo (stock) que:
- represente visualmente lo que se narra en ESA escena,
- y encaje con el tema y la atmósfera de TODA la historia (coherencia global).

Reglas de la consulta:
- En INGLÉS (los bancos de imágenes tienen mucha más cobertura en inglés).
- 2 a 4 palabras concretas y visuales (objetos, lugares, personas, acciones \
representables). Nada de conceptos abstractos ni nombres propios que no existan \
como foto (usa el objeto/lugar equivalente).
- Mantén un hilo visual entre escenas: si la historia trata de un naufragio en \
el Báltico, casi todas deben orbitar mar/barco/sonar/profundidad, adaptadas a \
cada frase.

Responde SOLO con una línea por escena, con este formato exacto y nada más:
N| consulta en inglés
(por ejemplo:  3| deep sea sonar anomaly)"""


def sugerir_consultas_ia(p, proveedor="gratis", modelo="", on_progreso=None):
    """Reescribe la `consulta` de cada escena con una IA que ve la historia
    COMPLETA, para máxima coherencia. Actualiza escenas.json y devuelve cuántas
    cambió. Requiere haber generado las escenas primero."""
    avisar = on_progreso or (lambda *_: None)
    escenas = leer_escenas(p)
    if not escenas:
        err("No hay escenas todavía.")
    avisar("Analizando la historia con IA…", 10)

    lineas = "\n".join(f"{e['n']}| {e['texto']}" for e in escenas)
    pedido = (f"Historia en {len(escenas)} escenas. Devuelve una consulta de "
              f"imagen (en inglés) para cada una, en el formato N| consulta.\n\n"
              f"{lineas}")
    crudo = chat_guion([{"rol": "usuario", "texto": pedido}],
                       proveedor=proveedor, modelo=modelo,
                       sistema=SISTEMA_IMAGENES)

    # Parseo tolerante: "N| consulta" o "N. consulta" o "N: consulta"
    consultas = {}
    for linea in crudo.splitlines():
        m = re.match(r"\s*(\d+)\s*[|.:)\-]\s*(.+)", linea)
        if m:
            q = re.sub(r'["*`]', "", m.group(2)).strip().strip(".")
            if q:
                consultas[int(m.group(1))] = q[:80]

    if not consultas:
        err("La IA no devolvió consultas en el formato esperado. Prueba con un "
            "proveedor más potente (Claude/Gemini/ChatGPT en 🔑 Claves API).")

    cambiadas = 0
    datos = json.loads((p / "escenas.json").read_text())
    for e in datos["escenas"]:
        q = consultas.get(e["n"])
        if q and q.lower() != (e.get("consulta") or "").lower():
            e["consulta"] = q
            e["consulta_ia"] = True
            cambiadas += 1
    (p / "escenas.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2))
    avisar("Consultas actualizadas", 100)
    return {"cambiadas": cambiadas, "total": len(escenas),
            "sin_respuesta": len(escenas) - len(consultas)}


def _palabras_clave(texto, n=2):
    """Devuelve hasta ~3 términos concretos para buscar la imagen de la escena.
    Combina la mejor entidad (nombre propio) con los sustantivos concretos, y
    descarta lo abstracto. Menos términos, pero más certeros."""
    terminos = []
    for ent in _entidades(texto)[:1]:       # la entidad más específica
        terminos.append(ent)
    for c in _concretas(texto, n + 1):
        base = sin_acentos(c)
        if all(base not in sin_acentos(t.lower()) for t in terminos):
            terminos.append(c)
        if len(terminos) >= (n + 1 if terminos and " " in terminos[0] else n):
            break
    terminos = terminos[:3]
    if not terminos:
        return ["oscuridad", "misterio", "niebla"]
    return terminos


def prompt_ia(texto):
    return (f"Fotografía cinematográfica oscura y misteriosa: {texto[:200]}. "
            f"Iluminación tenue, atmósfera inquietante, estilo documental, "
            f"muy detallada, 16:9.")


def alinear_con_guion(palabras, guion):
    """Corrige el texto de las palabras de Whisper con el guión original.

    Los tiempos vienen de Whisper (cuándo se dice cada palabra); el texto
    corregido viene del guión (qué se dice), alineado palabra a palabra.
    """
    import difflib

    def norm(t):
        return sin_acentos(re.sub(r"[^\wáéíóúüñ]", "", t.lower(), flags=re.U))

    tokens = guion.split()
    a = [norm(w["palabra"]) for w in palabras]
    b = [norm(t) for t in tokens]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.ratio() < 0.5:
        return palabras  # el guión no se parece al audio: mejor no tocar nada

    nuevos = [""] * len(palabras)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                nuevos[i1 + k] = tokens[j1 + k]
        elif op == "replace":
            trozo = tokens[j1:j2]
            ni = i2 - i1
            for k in range(ni):
                lo = round(k * len(trozo) / ni)
                hi = round((k + 1) * len(trozo) / ni)
                nuevos[i1 + k] = " ".join(trozo[lo:hi])
        elif op == "insert":
            # palabras del guión que Whisper no captó: van con la anterior
            extra = " ".join(tokens[j1:j2])
            destino = max(0, i1 - 1)
            nuevos[destino] = (nuevos[destino] + " " + extra).strip()
        # 'delete': Whisper oyó algo que no está en el guión → se descarta

    return [{"inicio": w["inicio"], "fin": w["fin"],
             "palabra": (" " + nuevos[i]) if nuevos[i] else ""}
            for i, w in enumerate(palabras)]


def generar_escenas(p):
    """transcripcion.json → escenas.json (5-10s por escena) + prompts_ia.md."""
    trans = p / "transcripcion.json"
    if not trans.exists():
        err("Falta transcripcion.json — corre antes la transcripción.")
    datos = json.loads(trans.read_text())
    segmentos = datos["segmentos"]
    duracion = datos["duracion"]
    if not segmentos:
        err("La transcripción no tiene segmentos (¿el audio tiene voz?).")

    # Trabajar a nivel de palabra para respetar 5-10s por escena; si la
    # transcripción es vieja y no trae palabras, cada segmento cuenta como una.
    palabras = []
    for seg in segmentos:
        if seg.get("palabras"):
            palabras += seg["palabras"]
        else:
            palabras.append({"inicio": seg["inicio"], "fin": seg["fin"],
                             "palabra": seg["texto"]})

    # Si el proyecto trae el guión original, se usa para corregir el texto
    guion_f = p / "guion.txt"
    if guion_f.exists() and palabras:
        palabras = alinear_con_guion(palabras, guion_f.read_text())

    # Agrupar palabras en escenas de 5-10s: se corta de preferencia al final
    # de una frase; si la frase es larga, también sirve una coma; y a los 10s
    # se corta sí o sí para que la edición se mantenga dinámica.
    escenas = []
    actual = []
    inicio_escena = 0.0

    def cerrar():
        nonlocal actual, inicio_escena
        texto = re.sub(r"\s+", " ", "".join(p["palabra"] for p in actual)).strip()
        escenas.append({"texto": texto, "fin_seg": actual[-1]["fin"]})
        inicio_escena = actual[-1]["fin"]
        actual = []

    for i, w in enumerate(palabras):
        # si esta palabra haría pasar de 10s, la escena se cierra antes
        if actual and w["fin"] - inicio_escena > ESCENA_MAX:
            cerrar()
        actual.append(w)
        dur = w["fin"] - inicio_escena
        texto_w = w["palabra"].rstrip()
        fin_frase = texto_w.endswith((".", "!", "?", "…"))
        pausa = texto_w.endswith((",", ";", ":"))
        if i == len(palabras) - 1 \
                or (fin_frase and dur >= ESCENA_MIN) \
                or (pausa and dur >= ESCENA_MEDIA):
            cerrar()

    # Si la última escena quedó muy corta, se fusiona con la anterior.
    if len(escenas) > 1 and \
            escenas[-1]["fin_seg"] - escenas[-2]["fin_seg"] < 3.0:
        cola = escenas.pop()
        escenas[-1]["texto"] = (escenas[-1]["texto"] + " " + cola["texto"]).strip()
        escenas[-1]["fin_seg"] = cola["fin_seg"]

    # Ancla de la historia: temas visuales de TODO el video, para dar coherencia
    # a cada escena (que no busque solo por su frase, sino dentro de la historia).
    anclas = _anclas_historia([e["texto"] for e in escenas])

    # Fronteras contiguas alineadas a fotogramas para que nada se desincronice
    resultado = []
    t = 0.0
    for n, esc in enumerate(escenas, 1):
        fin = duracion if n == len(escenas) else esc["fin_seg"]
        fin = round(fin * FPS) / FPS
        claves = _combinar_consulta(_palabras_clave(esc["texto"]), anclas)
        resultado.append({
            "n": n,
            "inicio": round(t, 3),
            "fin": round(fin, 3),
            "texto": esc["texto"],
            "consulta": " ".join(claves),
            "prompt": prompt_ia(esc["texto"]),
            "imagen": f"{n:03d}.jpg",
        })
        t = fin

    (p / "escenas.json").write_text(
        json.dumps({"duracion": duracion, "escenas": resultado},
                   ensure_ascii=False, indent=2))

    lineas = [f"# Prompts de imágenes — {p.name}", "",
              "Para cada escena que quieras generar con IA, usa el prompt y guarda",
              "el resultado como `imagenes/NNN.jpg` (reemplaza la de Pexels).", ""]
    for e in resultado:
        lineas += [f"## Escena {e['n']:03d}  ({e['inicio']:.0f}s – {e['fin']:.0f}s)",
                   f"*Narración:* {e['texto']}", "",
                   f"**Prompt:** {e['prompt']}", ""]
    (p / "prompts_ia.md").write_text("\n".join(lineas))
    return resultado


def leer_escenas(p):
    f = p / "escenas.json"
    if not f.exists():
        err("Falta escenas.json — corre antes el paso de escenas.")
    return json.loads(f.read_text())["escenas"]


# ------------------------------------------------------------ núcleo: pexels

def clave_pexels():
    key = leer_env().get("PEXELS_API_KEY")
    if not key:
        err("Falta la clave de Pexels. Crea el archivo .env con:\n"
            "PEXELS_API_KEY=tu_clave  (gratis en https://www.pexels.com/api/)")
    return key


ORIENTACION = {"16:9": "landscape", "9:16": "portrait", "1:1": "square"}


def pexels_buscar(consulta, cantidad=8, orientacion="landscape"):
    """Busca fotos en Pexels. Devuelve [{id, miniatura, grande, autor}, …]."""
    import requests
    r = requests.get("https://api.pexels.com/v1/search",
                     headers={"Authorization": clave_pexels()},
                     params={"query": consulta, "orientation": orientacion,
                             "per_page": cantidad, "locale": "es-ES"},
                     timeout=30)
    if not r.ok:
        err(f"Pexels respondió {r.status_code}: {r.text[:200]}")
    return [{"id": f["id"],
             "miniatura": f["src"]["medium"],
             "grande": f["src"]["large2x"],
             "autor": f.get("photographer", ""),
             "texto": f.get("alt", "")}
            for f in r.json().get("photos", [])]


def pexels_buscar_videos(consulta, cantidad=8, orientacion="landscape"):
    """Busca videos en Pexels. Devuelve [{id, miniatura, url, duracion}, …]."""
    import requests
    r = requests.get("https://api.pexels.com/videos/search",
                     headers={"Authorization": clave_pexels()},
                     params={"query": consulta, "orientation": orientacion,
                             "per_page": cantidad, "locale": "es-ES"},
                     timeout=30)
    if not r.ok:
        err(f"Pexels respondió {r.status_code}: {r.text[:200]}")
    res = []
    for v in r.json().get("videos", []):
        archivos = [f for f in v.get("video_files", [])
                    if f.get("file_type") == "video/mp4" and f.get("width")]
        if not archivos:
            continue
        # el mp4 más cercano a 1920 de ancho
        mejor = min(archivos, key=lambda f: abs(f["width"] - ANCHO))
        res.append({"id": v["id"], "miniatura": v.get("image", ""),
                    "url": mejor["link"], "duracion": v.get("duration", 0),
                    "autor": (v.get("user") or {}).get("name", "")})
    return res


def web_buscar_imagenes(consulta, cantidad=9):
    """Busca imágenes en la web (DuckDuckGo — indexa lo mismo que verías
    en Google/Bing Imágenes). Gratis y sin clave."""
    from ddgs import DDGS
    try:
        res = DDGS().images(consulta, region="es-es", safesearch="moderate",
                            max_results=cantidad)
    except Exception as e:
        err(f"La búsqueda web falló (suele ser temporal): {e}")
    return [{"miniatura": r.get("thumbnail", ""),
             "grande": r.get("image", ""),
             "autor": r.get("source", "web"),
             "titulo": r.get("title", "")}
            for r in (res or []) if r.get("image")]


def descargar_web_a_escena(p, n, url):
    """Descarga una imagen de cualquier sitio web como medio de la escena n."""
    import requests
    cab = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0 Safari/537.36"),
           "Referer": url}
    try:
        r = requests.get(url, timeout=60, headers=cab)
    except requests.RequestException as e:
        err(f"No pude descargar de ese sitio: {e}")
    ct = r.headers.get("Content-Type", "").lower()
    if not r.ok or "image" not in ct:
        err("Ese sitio no dejó descargar la imagen — prueba con otro resultado.")
    ext = {"image/png": ".png", "image/webp": ".webp"}.get(ct.split(";")[0], ".jpg")
    (p / "imagenes").mkdir(exist_ok=True)
    borrar_medio(p, n)
    (p / "imagenes" / f"{n:03d}{ext}").write_bytes(r.content)


def buscar_musica(p):
    """Devuelve la ruta del archivo de música de fondo del proyecto, o None."""
    for ext in ("mp3", "wav", "m4a", "aac", "flac", "ogg"):
        candidatos = sorted(p.glob(f"musica.{ext}"))
        if candidatos:
            return candidatos[0]
    return None


def leer_ajustes(p):
    f = p / "ajustes.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    return {}


def guardar_ajustes(p, **kw):
    ajustes = leer_ajustes(p)
    ajustes.update(kw)
    (p / "ajustes.json").write_text(json.dumps(ajustes, indent=2))


def formato_proyecto(p):
    """Formato de lienzo del proyecto ('16:9' | '9:16' | '1:1')."""
    fmt = leer_ajustes(p).get("formato", "16:9")
    return fmt if fmt in FORMATOS else "16:9"


def dims_proyecto(p):
    """Dimensiones (ancho, alto) del lienzo del proyecto."""
    return dims_formato(formato_proyecto(p))
    return ajustes


# ------------------------------------------- IA: guión, voz y video

def generar_guion(tema, minutos=10, estilo="misterio", canal="", on_progreso=None):
    """Genera el guión de una historia. Usa Claude (premium, si hay clave
    ANTHROPIC_API_KEY en .env) o Pollinations (gratis) como respaldo."""
    avisar = on_progreso or (lambda *_: None)
    palabras = max(200, int(minutos * 145))   # ~145 palabras/min narradas
    estilos = {
        "misterio": "misterio e intriga, con tensión creciente",
        "terror": "terror atmosférico, inquietante pero sin gore",
        "documental": "documental serio, con datos y fechas concretas",
    }
    canal = (canal or "").strip() or "un canal"
    prompt = (
        f"Escribe el guión de narración para un video de YouTube de "
        f"\"{canal}\" (canal en español de {estilos.get(estilo, estilos['misterio'])}).\n\n"
        f"Tema: {tema}\n\n"
        f"Requisitos:\n"
        f"- Aproximadamente {palabras} palabras (para ~{minutos} minutos narrados).\n"
        f"- SOLO el texto que dirá el narrador: sin encabezados, sin acotaciones, "
        f"sin \"[música]\", sin numerar secciones. Texto corrido en párrafos.\n"
        f"- Gancho fuerte en las primeras 2 frases para retener al espectador.\n"
        f"- Estructura: gancho → contexto → desarrollo con giros → final abierto "
        f"que deje una pregunta inquietante.\n"
        f"- Frases claras y cortas, aptas para voz en off. Puntuación normal "
        f"(el sistema corta las escenas en los puntos).\n"
        f"- Español neutro latinoamericano."
    )
    if leer_env().get("ANTHROPIC_API_KEY"):
        avisar("Escribiendo guión con Claude…", 20)
        return _limpiar_guion(_guion_claude(prompt)), "claude"
    avisar("Escribiendo guión (servicio gratuito)…", 20)
    return _limpiar_guion(_guion_pollinations(prompt)), "gratis"


def _limpiar_guion(texto):
    """Quita restos de formato que el TTS no debe leer (markdown, acotaciones)."""
    texto = re.sub(r"\*\*?|__", "", texto)
    texto = re.sub(r"^\s*#+ .*$", "", texto, flags=re.M)          # títulos md
    texto = re.sub(r"\[[^\]\n]{0,60}\]|\([Pp]ausa[^)]*\)", "", texto)
    texto = re.sub(r"^\s*(Narrador|NARRADOR|Voz en off)[^:\n]{0,30}:\s*",
                   "", texto, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _guion_claude(prompt):
    import anthropic
    cliente = anthropic.Anthropic(api_key=leer_env()["ANTHROPIC_API_KEY"])
    try:
        with cliente.messages.stream(
            model="claude-opus-4-8",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            respuesta = stream.get_final_message()
    except anthropic.AuthenticationError:
        err("La clave ANTHROPIC_API_KEY del .env no es válida.")
    except anthropic.RateLimitError:
        err("Claude está saturado en tu cuenta (límite de uso) — espera un momento.")
    except anthropic.APIStatusError as e:
        err(f"Error de la API de Claude ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        err("No pude conectar con la API de Claude — revisa tu internet.")
    if respuesta.stop_reason == "refusal":
        err("Claude declinó escribir este guión — prueba otro enfoque del tema.")
    texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
    if not texto:
        err("Claude no devolvió texto — intenta de nuevo.")
    return texto


def _extraer_texto_llm(crudo):
    """El servicio gratuito a veces responde texto plano y a veces un JSON
    (según a qué modelo enrute). Extrae el texto útil en ambos casos."""
    texto = crudo.strip()
    if texto.startswith("{"):
        try:
            d = json.loads(texto)
            texto = (d.get("content")
                     or ((d.get("choices") or [{}])[0]
                         .get("message", {}).get("content"))
                     or "").strip()
        except (ValueError, AttributeError, IndexError):
            texto = ""
    return texto


def _guion_pollinations(prompt):
    import requests
    from urllib.parse import quote
    intentos = [("OPENAI", "openai"), ("POST", "openai"), ("GET", "openai")]
    ultimo_error = "sin respuesta"
    for metodo, modelo in intentos:
        try:
            if metodo == "OPENAI":   # endpoint estable con formato garantizado
                r = requests.post(
                    "https://text.pollinations.ai/openai",
                    json={"model": modelo,
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=180)
            elif metodo == "POST":
                r = requests.post(
                    "https://text.pollinations.ai/",
                    json={"messages": [{"role": "user", "content": prompt}],
                          "model": modelo},
                    timeout=180)
            else:
                r = requests.get(
                    "https://text.pollinations.ai/" + quote(prompt[:1800])
                    + f"?model={modelo}", timeout=180)
            if not r.ok:
                ultimo_error = f"HTTP {r.status_code}"
                continue
            texto = _extraer_texto_llm(r.text)
            if len(texto) >= 200:
                return texto
            ultimo_error = "respuesta vacía o demasiado corta"
        except requests.RequestException as e:
            ultimo_error = str(e)
    err(f"El generador gratuito de guiones falló ({ultimo_error}). "
        f"Reintenta en un momento, o agrega una clave ANTHROPIC_API_KEY al "
        f".env para usar Claude (mejor calidad y más confiable).")


# ------------------------------------------------- estudio de guión (chat LLM)

GUIONES = DATOS / "guiones"

SISTEMA_GUIONISTA = """Eres un guionista experto en videos "faceless" de YouTube \
(misterio, documental, historias narradas). Trabajas dentro de AutoFaceless Video, \
una app que convierte guiones en videos con voz e imágenes automáticas.

Tu trabajo es AYUDAR Y GUIAR al usuario a crear un gran guión, no solo escribirlo:
- Si el usuario llega sin idea clara, hazle 2-3 preguntas cortas (tema, duración \
en minutos, tono, canal) antes de escribir.
- Propón ganchos de apertura (primeros 15 segundos) y estructura (gancho → \
desarrollo con giros → clímax → cierre con pregunta al espectador).
- Cuando escribas guión, escribe SOLO el texto que se narrará en voz alta: sin \
encabezados, sin acotaciones, sin "ESCENA 1", sin emojis. Párrafos cortos y \
lenguaje hablado natural (se convertirá a voz).
- Una duración de N minutos ≈ N x 150 palabras habladas.
- Si el usuario pide cambios, reescribe solo lo necesario y entrega el guión \
completo actualizado.
- Responde siempre en el idioma del usuario.

Cuando entregues una versión completa del guión (nueva o revisada), enciérrala \
EXACTAMENTE entre las marcas <guion> y </guion> (una sola vez por respuesta), \
con tus comentarios fuera de las marcas. Si solo estás conversando o haciendo \
preguntas, no uses las marcas."""


def _mensajes_openai(mensajes, sistema):
    ms = [{"role": "system", "content": sistema}]
    for m in mensajes:
        ms.append({"role": "user" if m.get("rol") == "usuario" else "assistant",
                   "content": m.get("texto", "")})
    return ms


def chat_guion(mensajes, proveedor="gratis", modelo="", sistema=None):
    """Un turno de un asistente LLM. mensajes = [{rol, texto}, ...] con el
    historial completo (el último es del usuario). `sistema` = prompt de sistema
    (por defecto el guionista). Despacha al proveedor elegido. Devuelve el texto."""
    import requests
    env = leer_env()
    sistema = sistema or SISTEMA_GUIONISTA

    if proveedor == "claude":
        import anthropic
        key = env.get("ANTHROPIC_API_KEY")
        if not key:
            err("Falta la clave de Claude (ANTHROPIC_API_KEY) — pégala en 🔑 Claves API.")
        cliente = anthropic.Anthropic(api_key=key)
        mod = modelo or env.get("ANTHROPIC_CHAT_MODEL", "claude-sonnet-5")
        try:
            with cliente.messages.stream(
                    model=mod, max_tokens=16000, system=sistema,
                    messages=[{"role": "user" if m.get("rol") == "usuario" else "assistant",
                               "content": m.get("texto", "")} for m in mensajes],
            ) as stream:
                r = stream.get_final_message()
        except anthropic.AuthenticationError:
            err("La clave ANTHROPIC_API_KEY no es válida — revísala en 🔑 Claves API.")
        except anthropic.APIStatusError as e:
            err(f"Claude respondió un error ({e.status_code}). Intenta de nuevo.")
        return "".join(b.text for b in r.content if b.type == "text").strip()

    if proveedor == "gemini":
        key = env.get("GEMINI_API_KEY")
        if not key:
            err("Falta la clave de Gemini (GEMINI_API_KEY) — pégala en 🔑 Claves API.")
        mod = modelo or env.get("GEMINI_MODEL", "gemini-2.5-flash")
        contents = [{"role": "user" if m.get("rol") == "usuario" else "model",
                     "parts": [{"text": m.get("texto", "")}]} for m in mensajes]
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent",
            params={"key": key},
            json={"contents": contents,
                  "systemInstruction": {"parts": [{"text": sistema}]}},
            timeout=180)
        if r.status_code in (401, 403):
            err("La clave GEMINI_API_KEY no es válida — revísala en 🔑 Claves API.")
        if not r.ok:
            err(f"Gemini respondió un error (HTTP {r.status_code}). Intenta de nuevo.")
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError):
            err("Gemini no devolvió texto (posible filtro de contenido). Reformula el mensaje.")

    if proveedor == "openai":
        key = env.get("OPENAI_API_KEY")
        if not key:
            err("Falta la clave de OpenAI (OPENAI_API_KEY) — pégala en 🔑 Claves API.")
        mod = modelo or env.get("OPENAI_MODEL", "gpt-4o-mini")
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": mod, "messages": _mensajes_openai(mensajes, sistema)},
            timeout=180)
        if r.status_code == 401:
            err("La clave OPENAI_API_KEY no es válida — revísala en 🔑 Claves API.")
        if not r.ok:
            err(f"ChatGPT respondió un error (HTTP {r.status_code}). Intenta de nuevo.")
        return r.json()["choices"][0]["message"]["content"].strip()

    if proveedor == "local":
        mod = modelo
        if not mod:
            err("Elige un modelo local de la lista (necesitas Ollama corriendo).")
        try:
            r = requests.post("http://127.0.0.1:11434/api/chat",
                              json={"model": mod, "stream": False,
                                    "messages": _mensajes_openai(mensajes, sistema)},
                              timeout=600)
        except requests.RequestException:
            err("No encuentro Ollama corriendo en tu Mac. Ábrelo (o instálalo "
                "gratis en ollama.com) y vuelve a intentar.")
        if not r.ok:
            err(f"El modelo local respondió un error (HTTP {r.status_code}). "
                f"¿Está descargado? Prueba: ollama pull {mod}")
        return r.json().get("message", {}).get("content", "").strip()

    # gratis (Pollinations) — sin clave
    intentos = 0
    while intentos < 3:
        intentos += 1
        try:
            r = requests.post("https://text.pollinations.ai/openai",
                              json={"model": "openai",
                                    "messages": _mensajes_openai(mensajes, sistema)},
                              timeout=180)
            if r.ok:
                texto = _extraer_texto_llm(r.text)
                if texto:
                    return texto
        except requests.RequestException:
            pass
    err("El asistente gratuito no respondió — reintenta en un momento, o usa "
        "un proveedor con clave (🔑 Claves API) para mayor confiabilidad.")


def modelos_ollama():
    """Modelos instalados en Ollama local, con su tamaño en GB. [] si no corre."""
    import requests
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if not r.ok:
            return None
        return [{"nombre": m.get("name", ""),
                 "gb": round(m.get("size", 0) / 1e9, 1)}
                for m in r.json().get("models", [])]
    except requests.RequestException:
        return None


# --------------------------------------------------- guiones guardados (CRUD)

def _ruta_guion(nombre):
    limpio = re.sub(r"[^\w\-. ]", "", (nombre or "").strip())[:80]
    if not limpio:
        err("Ponle un nombre al guión.")
    return GUIONES / f"{limpio}.json"


def listar_guiones():
    GUIONES.mkdir(exist_ok=True)
    res = []
    for f in sorted(GUIONES.glob("*.json"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        res.append({"nombre": f.stem,
                    "palabras": len((d.get("texto") or "").split()),
                    "actualizado": f.stat().st_mtime})
    return res


def leer_guion(nombre):
    f = _ruta_guion(nombre)
    if not f.exists():
        err(f"No existe el guión {nombre}.")
    return {"nombre": f.stem, **json.loads(f.read_text())}


def guardar_guion(nombre, texto, chat):
    GUIONES.mkdir(exist_ok=True)
    f = _ruta_guion(nombre)
    f.write_text(json.dumps({"texto": texto or "", "chat": chat or []},
                            ensure_ascii=False, indent=2))
    return f.stem


def borrar_guion(nombre):
    f = _ruta_guion(nombre)
    if f.exists():
        f.unlink()


# ------------------------------------------------- grupos de historias

def leer_grupos():
    """{'grupos': [{id, nombre}, ...], 'asignacion': {proyecto: grupo_id}}.
    El orden del array 'grupos' es el orden de visualización."""
    f = DATOS / "grupos.json"
    if f.exists():
        try:
            d = json.loads(f.read_text())
            d.setdefault("grupos", [])
            d.setdefault("asignacion", {})
            return d
        except ValueError:
            pass
    return {"grupos": [], "asignacion": {}}


def _guardar_grupos(d):
    (DATOS / "grupos.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))


def crear_grupo(nombre):
    import secrets
    nombre = (nombre or "").strip()[:60] or "Grupo"
    d = leer_grupos()
    gid = "grp_" + secrets.token_hex(4)
    d["grupos"].append({"id": gid, "nombre": nombre})
    _guardar_grupos(d)
    return gid


def renombrar_grupo(gid, nombre):
    d = leer_grupos()
    for g in d["grupos"]:
        if g["id"] == gid:
            g["nombre"] = (nombre or "").strip()[:60] or g["nombre"]
    _guardar_grupos(d)


def borrar_grupo(gid):
    """Borra el grupo; sus historias vuelven a 'sin grupo' (no se borran)."""
    d = leer_grupos()
    d["grupos"] = [g for g in d["grupos"] if g["id"] != gid]
    d["asignacion"] = {p: g for p, g in d["asignacion"].items() if g != gid}
    _guardar_grupos(d)


def ordenar_grupos(ids):
    """Reordena los grupos según la lista de ids dada."""
    d = leer_grupos()
    por_id = {g["id"]: g for g in d["grupos"]}
    d["grupos"] = [por_id[i] for i in ids if i in por_id] + \
                  [g for g in d["grupos"] if g["id"] not in ids]
    _guardar_grupos(d)


def mover_historia(proyecto, gid):
    """Asigna la historia a un grupo (gid vacío/None = sin grupo)."""
    d = leer_grupos()
    ids = {g["id"] for g in d["grupos"]}
    if gid and gid in ids:
        d["asignacion"][proyecto] = gid
    else:
        d["asignacion"].pop(proyecto, None)
    _guardar_grupos(d)


def borrar_proyecto(nombre):
    """Elimina por completo la carpeta de la historia y su asignación."""
    p = PROYECTOS / nombre
    if not p.is_dir():
        err(f"No existe la historia '{nombre}'.")
    shutil.rmtree(p, ignore_errors=True)
    d = leer_grupos()
    if nombre in d["asignacion"]:
        d["asignacion"].pop(nombre, None)
        _guardar_grupos(d)


def _minimax_conf():
    env = leer_env()
    key = env.get("MINIMAX_API_KEY")
    if not key:
        err("Falta MINIMAX_API_KEY en el .env. En tu cuenta de MiniMax "
            "(minimax.io) ve a API Keys, copia la clave y agrega:\n"
            "MINIMAX_API_KEY=tu_clave\nMINIMAX_GROUP_ID=tu_group_id")
    return (key, env.get("MINIMAX_GROUP_ID", ""),
            env.get("MINIMAX_BASE_URL", "https://api.minimax.io"))


def _trocear_texto(texto, maximo=1500):
    """Parte el guión en trozos de ~1500 caracteres cortando en fin de frase."""
    trozos, actual = [], ""
    for frase in re.split(r"(?<=[.!?…])\s+", texto.strip()):
        if len(actual) + len(frase) + 1 > maximo and actual:
            trozos.append(actual.strip())
            actual = ""
        actual += frase + " "
    if actual.strip():
        trozos.append(actual.strip())
    return trozos


def minimax_voz(texto, voz, velocidad=1.0, on_progreso=None):
    """Genera la voz del guión con MiniMax (T2A). Devuelve bytes de mp3."""
    import requests
    key, group_id, base = _minimax_conf()
    avisar = on_progreso or (lambda *_: None)
    modelo = leer_env().get("MINIMAX_TTS_MODEL", "speech-02-hd")
    url = f"{base}/v1/t2a_v2"
    if group_id:
        url += f"?GroupId={group_id}"

    trozos = _trocear_texto(texto)
    partes = []
    for i, trozo in enumerate(trozos):
        avisar(f"Generando voz… parte {i + 1}/{len(trozos)}",
               (i + 1) / len(trozos) * 90)
        try:
            r = requests.post(url, timeout=300,
                              headers={"Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json"},
                              json={
                                  "model": modelo,
                                  "text": trozo,
                                  "stream": False,
                                  "language_boost": "Spanish",
                                  "voice_setting": {"voice_id": voz,
                                                    "speed": float(velocidad)},
                                  "audio_setting": {"sample_rate": 32000,
                                                    "bitrate": 128000,
                                                    "format": "mp3"},
                              })
        except requests.RequestException as e:
            err(f"No pude conectar con MiniMax: {e}")
        datos = r.json() if r.ok else {}
        base_resp = datos.get("base_resp", {})
        if not r.ok or base_resp.get("status_code", -1) != 0:
            detalle = base_resp.get("status_msg") or r.text[:300]
            err(f"MiniMax rechazó la petición de voz: {detalle}\n"
                f"Revisa MINIMAX_API_KEY / MINIMAX_GROUP_ID y que la voz "
                f"'{voz}' exista en tu cuenta.")
        audio_hex = (datos.get("data") or {}).get("audio", "")
        if not audio_hex:
            err("MiniMax no devolvió audio — intenta de nuevo.")
        partes.append(bytes.fromhex(audio_hex))

    if len(partes) == 1:
        return partes[0]
    # unir los mp3 con ffmpeg para que los tiempos queden limpios
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        lista = tmp / "lista.txt"
        lineas = []
        for i, parte in enumerate(partes):
            f = tmp / f"p{i:03d}.mp3"
            f.write_bytes(parte)
            lineas.append(f"file '{f}'\n")
        lista.write_text("".join(lineas))
        salida = tmp / "voz.mp3"
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
             "-c:a", "libmp3lame", "-q:a", "2", str(salida)])
        return salida.read_bytes()


# ==================== voz multi-proveedor ====================
# Proveedores de narración: dos gratuitos (edge-tts neuronal y las voces del
# sistema macOS) y dos con clave propia (MiniMax y ElevenLabs). Todos devuelven
# bytes de mp3, así el resto del pipeline (guardar audio.mp3 + transcribir) no cambia.

VOCES_EDGE = [
    {"id": "es-MX-JorgeNeural",   "nombre": "Jorge",   "desc": "Grave y serio · México"},
    {"id": "es-MX-DaliaNeural",   "nombre": "Dalia",   "desc": "Cálida y clara · México"},
    {"id": "es-ES-AlvaroNeural",  "nombre": "Álvaro",  "desc": "Serio · España"},
    {"id": "es-ES-ElviraNeural",  "nombre": "Elvira",  "desc": "Clara · España"},
    {"id": "es-AR-TomasNeural",   "nombre": "Tomás",   "desc": "Neutro · Argentina"},
    {"id": "es-CO-GonzaloNeural", "nombre": "Gonzalo", "desc": "Cálido · Colombia"},
    {"id": "en-US-GuyNeural",     "nombre": "Guy",     "desc": "Deep · English (US)"},
    {"id": "en-US-JennyNeural",   "nombre": "Jenny",   "desc": "Clear · English (US)"},
]

# Voces "premade" de ElevenLabs disponibles en cualquier cuenta (modelo multilingüe).
VOCES_ELEVEN = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "nombre": "Rachel",  "desc": "Serena · multilingüe"},
    {"id": "AZnzlk1XvdvUeBnXmlld", "nombre": "Domi",    "desc": "Firme · multilingüe"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "nombre": "Bella",   "desc": "Suave · multilingüe"},
    {"id": "ErXwobaYiN019PkySvjV", "nombre": "Antoni",  "desc": "Cálido · multilingüe"},
    {"id": "pNInz6obpgDQGcFmaJgB", "nombre": "Adam",    "desc": "Grave · multilingüe"},
    {"id": "TxGEqnHWrfWFTfGW9XjX", "nombre": "Josh",    "desc": "Joven · multilingüe"},
]


def _concat_mp3(partes):
    """Une varios mp3 en uno solo con ffmpeg (tiempos limpios)."""
    if len(partes) == 1:
        return partes[0]
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        lista = tmp / "lista.txt"
        lineas = []
        for i, parte in enumerate(partes):
            f = tmp / f"p{i:03d}.mp3"
            f.write_bytes(parte)
            lineas.append(f"file '{f}'\n")
        lista.write_text("".join(lineas))
        salida = tmp / "voz.mp3"
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
             "-c:a", "libmp3lame", "-q:a", "2", str(salida)])
        return salida.read_bytes()


def _atempo_mp3(data, velocidad):
    """Ajusta la velocidad de un mp3 sin cambiar el tono (filtro atempo)."""
    velocidad = float(velocidad)
    if abs(velocidad - 1.0) < 0.01:
        return data
    velocidad = max(0.5, min(2.0, velocidad))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ent, sal = tmp / "i.mp3", tmp / "o.mp3"
        ent.write_bytes(data)
        run(["ffmpeg", "-y", "-i", str(ent), "-filter:a", f"atempo={velocidad}",
             "-c:a", "libmp3lame", "-q:a", "2", str(sal)])
        return sal.read_bytes()


def edge_voz(texto, voz, velocidad=1.0, on_progreso=None):
    """Voz gratuita de alta calidad con edge-tts (voces neuronales de Microsoft).
    Necesita internet, no necesita clave. Devuelve bytes de mp3."""
    import asyncio
    import tempfile
    try:
        import edge_tts
    except ImportError:
        err("Las voces neuronales gratuitas no están disponibles en esta "
            "instalación (falta edge-tts). Usa las voces del sistema o MiniMax.")
    voz = voz or "es-MX-JorgeNeural"
    avisar = on_progreso or (lambda *_: None)
    avisar("Generando la voz (gratis)…", 25)
    pct = round((float(velocidad) - 1) * 100)
    rate = f"{'+' if pct >= 0 else ''}{pct}%"

    async def _gen(destino):
        com = edge_tts.Communicate(texto, voz, rate=rate)
        await com.save(destino)

    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / "voz.mp3"
        try:
            asyncio.run(_gen(str(mp3)))
        except Exception as e:
            err(f"No pude generar la voz gratuita (¿sin conexión a internet?). "
                f"Detalle: {e}")
        avisar("Voz lista", 90)
        data = mp3.read_bytes() if mp3.exists() else b""
    if not data:
        err("La voz gratuita no devolvió audio — intenta de nuevo.")
    return data


_PS_LISTAR_VOCES = (
    "Add-Type -AssemblyName System.Speech; "
    "(New-Object System.Speech.Synthesis.SpeechSynthesizer)."
    "GetInstalledVoices() | ForEach-Object { $_.VoiceInfo } | "
    "ForEach-Object { \"$($_.Name)|$($_.Culture)\" }")


def _voces_windows():
    """Voces SAPI instaladas en Windows (es/en), vía PowerShell."""
    import subprocess
    try:
        salida = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _PS_LISTAR_VOCES],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return []
    voces, vistos = [], set()
    for linea in salida.splitlines():
        if "|" not in linea:
            continue
        nombre, loc = [x.strip() for x in linea.split("|", 1)]
        loc = loc.replace("_", "-")
        if not nombre or not (loc.lower().startswith("es") or loc.lower().startswith("en")):
            continue
        if nombre in vistos:
            continue
        vistos.add(nombre)
        voces.append({"id": nombre, "nombre": nombre, "desc": loc})
    voces.sort(key=lambda v: (0 if v["desc"].lower().startswith("es") else 1, v["nombre"]))
    return voces


def voces_sistema():
    """Voces del sistema operativo instaladas (español e inglés)."""
    if ES_WIN:
        return _voces_windows()
    if not ES_MAC:
        return []
    import subprocess
    try:
        salida = subprocess.run(["say", "-v", "?"], capture_output=True,
                                 text=True, timeout=10).stdout
    except Exception:
        return []
    voces, vistos = [], set()
    for linea in salida.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", linea)
        if not m:
            continue
        nombre, loc = m.group(1).strip(), m.group(2)
        if not (loc.startswith("es") or loc.startswith("en")):
            continue
        if nombre in vistos:
            continue
        vistos.add(nombre)
        voces.append({"id": nombre, "nombre": nombre, "desc": loc.replace("_", "-")})
    voces.sort(key=lambda v: (0 if v["desc"].startswith("es") else 1, v["nombre"]))
    return voces


def _say_windows(texto, voz, tmp):
    """Sintetiza con SAPI (Windows) a un WAV. Devuelve la ruta del wav."""
    import subprocess
    wav = tmp / "voz.wav"
    # el texto va por stdin en base64 para evitar problemas de comillas/acentos
    import base64
    b64 = base64.b64encode(texto.encode("utf-8")).decode("ascii")
    sel = f"$s.SelectVoice('{voz}'); " if voz else ""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        + sel +
        f"$t = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{b64}')); "
        f"$s.SetOutputToWaveFile('{wav}'); $s.Speak($t); $s.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not wav.exists():
        err(f"No pude usar la voz del sistema '{voz}' en Windows. "
            f"Detalle: {(r.stderr or '')[:200]}")
    return wav


def say_voz(texto, voz, velocidad=1.0, on_progreso=None):
    """Voz gratuita del sistema operativo (macOS `say` o Windows SAPI). Offline,
    sin clave. Devuelve bytes de mp3."""
    import subprocess
    import tempfile
    avisar = on_progreso or (lambda *_: None)
    avisar("Generando la voz del sistema…", 30)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mp3 = tmp / "voz.mp3"
        if ES_WIN:
            fuente = _say_windows(texto, voz, tmp)
        elif ES_MAC:
            fuente = tmp / "voz.aiff"
            try:
                subprocess.run(["say", "-v", voz or "Paulina", "-o", str(fuente), texto],
                               check=True, capture_output=True, text=True)
            except FileNotFoundError:
                err("Las voces del sistema no están disponibles en este equipo.")
            except subprocess.CalledProcessError as e:
                err(f"No pude usar la voz del sistema '{voz}' (¿no está instalada?). "
                    f"Instala más voces en Ajustes → Accesibilidad → Contenido "
                    f"hablado. Detalle: {(e.stderr or '')[:200]}")
        else:
            err("Las voces del sistema solo están disponibles en macOS y Windows.")
        run(["ffmpeg", "-y", "-i", str(fuente), "-c:a", "libmp3lame",
             "-q:a", "2", str(mp3)])
        data = mp3.read_bytes()
    avisar("Voz lista", 90)
    return _atempo_mp3(data, velocidad)


def _elevenlabs_key():
    k = leer_env().get("ELEVENLABS_API_KEY")
    if not k:
        err("Falta ELEVENLABS_API_KEY en el .env. En tu cuenta de ElevenLabs "
            "(elevenlabs.io) ve a tu perfil → API Keys, copia la clave y pégala "
            "en el botón 🔑 Claves API.")
    return k


def elevenlabs_voz(texto, voz, velocidad=1.0, on_progreso=None):
    """Voz con ElevenLabs (clave propia). Devuelve bytes de mp3."""
    import requests
    key = _elevenlabs_key()
    voz = voz or "21m00Tcm4TlvDq8ikWAM"
    modelo = leer_env().get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    avisar = on_progreso or (lambda *_: None)
    trozos = _trocear_texto(texto, 2200)
    partes = []
    for i, trozo in enumerate(trozos):
        avisar(f"Generando voz (ElevenLabs)… parte {i + 1}/{len(trozos)}",
               (i + 1) / len(trozos) * 90)
        try:
            r = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voz}", timeout=300,
                headers={"xi-api-key": key, "Content-Type": "application/json",
                         "Accept": "audio/mpeg"},
                json={"text": trozo, "model_id": modelo,
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}})
        except requests.RequestException as e:
            err(f"No pude conectar con ElevenLabs: {e}")
        if not r.ok:
            detalle = ""
            try:
                j = r.json()
                detalle = (j.get("detail", {}) or {})
                detalle = detalle.get("message") if isinstance(detalle, dict) else str(detalle)
            except Exception:
                detalle = r.text[:300]
            err(f"ElevenLabs rechazó la petición ({r.status_code}): {detalle}\n"
                f"Revisa ELEVENLABS_API_KEY y que la voz '{voz}' exista en tu cuenta.")
        partes.append(r.content)
    return _atempo_mp3(_concat_mp3(partes), velocidad)


def sintetizar_voz(texto, proveedor="edge", voz="", velocidad=1.0, on_progreso=None):
    """Enruta la generación de narración al proveedor elegido. mp3 bytes."""
    proveedor = (proveedor or "edge").lower()
    if proveedor == "minimax":
        return minimax_voz(texto, voz, velocidad, on_progreso)
    if proveedor == "elevenlabs":
        return elevenlabs_voz(texto, voz, velocidad, on_progreso)
    if proveedor == "sistema":
        return say_voz(texto, voz, velocidad, on_progreso)
    return edge_voz(texto, voz, velocidad, on_progreso)   # gratis por defecto


def proveedores_voz():
    """Lista de proveedores de voz para la interfaz, con disponibilidad y voces."""
    import sys as _sys
    env = leer_env()
    try:
        import edge_tts  # noqa: F401
        edge_ok = True
    except ImportError:
        edge_ok = False
    provs = []
    if edge_ok:
        provs.append({"id": "edge", "gratis": True, "disponible": True,
                      "custom": False, "voces": VOCES_EDGE})
    if ES_MAC or ES_WIN:
        provs.append({"id": "sistema", "gratis": True, "disponible": True,
                      "custom": False, "voces": voces_sistema()})
    provs.append({"id": "minimax", "gratis": False,
                  "disponible": bool(env.get("MINIMAX_API_KEY")),
                  "custom": True, "voces": []})
    provs.append({"id": "elevenlabs", "gratis": False,
                  "disponible": bool(env.get("ELEVENLABS_API_KEY")),
                  "custom": True, "voces": VOCES_ELEVEN})
    return provs


def minimax_video(p, n, prompt, on_progreso=None):
    """Genera un clip de video con IA (MiniMax Hailuo) y lo pone en la
    escena n. Tarda varios minutos y consume créditos de MiniMax."""
    import time
    import requests
    key, group_id, base = _minimax_conf()
    avisar = on_progreso or (lambda *_: None)
    modelo = leer_env().get("MINIMAX_VIDEO_MODEL", "MiniMax-Hailuo-02")
    cab = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    avisar("Enviando el encargo de video a MiniMax…", 5)
    r = requests.post(f"{base}/v1/video_generation", headers=cab, timeout=60,
                      json={"model": modelo, "prompt": prompt[:1500],
                            "duration": 6, "resolution": "1080P"})
    datos = r.json() if r.ok else {}
    base_resp = datos.get("base_resp", {})
    if not r.ok or base_resp.get("status_code", -1) != 0:
        err(f"MiniMax rechazó el encargo de video: "
            f"{base_resp.get('status_msg') or r.text[:300]}")
    task_id = datos.get("task_id")
    if not task_id:
        err("MiniMax no devolvió el identificador de la tarea de video.")

    file_id = None
    for intento in range(120):                # hasta ~10 minutos
        time.sleep(5)
        avisar(f"MiniMax está generando el video… ({intento * 5}s)",
               10 + min(80, intento * 1.5))
        q = requests.get(f"{base}/v1/query/video_generation",
                         headers=cab, params={"task_id": task_id}, timeout=60)
        qd = q.json() if q.ok else {}
        estado = qd.get("status", "")
        if estado == "Success":
            file_id = qd.get("file_id")
            break
        if estado == "Fail":
            err("MiniMax no pudo generar el video (tarea fallida) — "
                "prueba con otro prompt.")
    if not file_id:
        err("El video de MiniMax tardó demasiado — revisa tu cuenta, puede "
            "que se haya generado y puedas descargarlo desde su web.")

    avisar("Descargando el video…", 92)
    f = requests.get(f"{base}/v1/files/retrieve", headers=cab, timeout=60,
                     params={"GroupId": group_id, "file_id": file_id})
    fd = f.json() if f.ok else {}
    descarga = ((fd.get("file") or {}).get("download_url"))
    if not descarga:
        err("MiniMax no devolvió el enlace de descarga del video.")
    video = requests.get(descarga, timeout=300)
    if not video.ok:
        err("No pude descargar el video generado.")
    (p / "imagenes").mkdir(exist_ok=True)
    borrar_medio(p, n)
    (p / "imagenes" / f"{n:03d}.mp4").write_bytes(video.content)
    avisar("Video listo", 100)


def generar_imagen_ia(p, n, prompt, modelo="flux"):
    """Genera una imagen con IA (Pollinations, gratis y sin clave) para la
    escena n. Cada llamada usa una semilla distinta: regenerar da otra imagen."""
    import random
    import requests
    from urllib.parse import quote

    ancho, alto = dims_proyecto(p)      # genera en el formato del proyecto
    url = ("https://image.pollinations.ai/prompt/" + quote(prompt[:800]) +
           f"?width={ancho}&height={alto}&model={modelo}"
           f"&nologo=true&seed={random.randint(0, 10**9)}")
    try:
        r = requests.get(url, timeout=180)
    except requests.RequestException as e:
        err(f"No pude conectar con el generador de imágenes: {e}")
    if not r.ok:
        err(f"El generador de imágenes respondió {r.status_code}. "
            f"Suele ser temporal: intenta de nuevo en unos segundos.")
    if not r.headers.get("Content-Type", "").startswith("image"):
        err("El generador no devolvió una imagen. Intenta de nuevo.")
    (p / "imagenes").mkdir(exist_ok=True)
    borrar_medio(p, n)
    (p / "imagenes" / f"{n:03d}.jpg").write_bytes(r.content)


def gemini_imagen(p, n, prompt):
    """Genera una imagen con Google Gemini "Nano Banana" (gemini-2.5-flash-image)
    para la escena n. Usa la GEMINI_API_KEY del usuario. Mucho mejor calidad y
    seguimiento del prompt que el generador gratuito."""
    import base64
    import requests
    key = leer_env().get("GEMINI_API_KEY")
    if not key:
        err("Falta GEMINI_API_KEY — pégala en 🔑 Claves API (gratis en "
            "aistudio.google.com/apikey).")
    mod = leer_env().get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    aspecto = formato_proyecto(p)                      # 16:9 | 9:16 | 1:1
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent",
            params={"key": key}, timeout=180,
            json={"contents": [{"parts": [{"text": prompt[:1500]}]}],
                  "generationConfig": {"responseModalities": ["IMAGE"],
                                       "imageConfig": {"aspectRatio": aspecto}}})
    except requests.RequestException as e:
        err(f"No pude conectar con Google: {e}")
    datos = r.json() if r.ok else {}
    if not r.ok:
        detalle = (datos.get("error", {}) or {}).get("message", r.text[:300])
        err(f"Google rechazó la petición ({r.status_code}): {detalle}")
    imagen = None
    for cand in datos.get("candidates", []):
        for parte in (cand.get("content", {}) or {}).get("parts", []):
            blob = parte.get("inlineData") or parte.get("inline_data")
            if blob and blob.get("data"):
                imagen = base64.b64decode(blob["data"])
                break
        if imagen:
            break
    if not imagen:
        err("Google no devolvió una imagen (¿el prompt activó un filtro de "
            "seguridad?). Prueba reformulando el prompt.")
    (p / "imagenes").mkdir(exist_ok=True)
    borrar_medio(p, n)
    (p / "imagenes" / f"{n:03d}.png").write_bytes(imagen)


def descargar_a_escena(p, n, url, tipo="imagen", auto=False):
    """Descarga una imagen o video (url) como el medio de la escena n. Si auto
    es False (elección manual), marca la escena para que no la pise el
    reemplazo automático de coherencia."""
    import requests
    (p / "imagenes").mkdir(exist_ok=True)
    r = requests.get(url, timeout=300)
    if not r.ok:
        err(f"No pude descargar el archivo ({r.status_code}).")
    borrar_medio(p, n)
    ext = ".mp4" if tipo == "video" else ".jpg"
    (p / "imagenes" / f"{n:03d}{ext}").write_bytes(r.content)
    if not auto:                       # el usuario la eligió: protégela
        f = p / "escenas.json"
        if f.exists():
            datos = json.loads(f.read_text())
            e = next((e for e in datos["escenas"] if e["n"] == n), None)
            if e is not None:
                e["medio_auto"] = False
                f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))


def ajustar_limite(p, n, nuevo_fin):
    """Mueve el límite entre la escena n y la n+1 (el total no cambia)."""
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    escenas = datos["escenas"]
    idx = next((i for i, e in enumerate(escenas) if e["n"] == n), None)
    if idx is None or idx >= len(escenas) - 1:
        err("Esa escena no tiene una escena siguiente que ceda tiempo.")
    a, b = escenas[idx], escenas[idx + 1]
    minimo = a["inicio"] + DUR_MINIMA_ESCENA
    maximo = b["fin"] - DUR_MINIMA_ESCENA
    if maximo <= minimo:
        err("No hay espacio para ajustar entre estas dos escenas.")
    v = round(max(minimo, min(maximo, float(nuevo_fin))) * FPS) / FPS
    a["fin"] = round(v, 3)
    b["inicio"] = round(v, 3)
    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))
    return a, b


def _renombrar_medio(p, desde, hasta):
    """Renombra el medio y la miniatura de la escena `desde` → `hasta`."""
    m, _ = medio_de_escena(p, desde)
    if m:
        m.rename(m.with_name(f"{hasta:03d}{m.suffix}"))
    mini = p / "miniaturas" / f"{desde:03d}.jpg"
    if mini.exists():
        mini.rename(mini.with_name(f"{hasta:03d}.jpg"))


def dividir_escena(p, n, punto=None):
    """Divide la escena n en dos (inserta una escena intermedia). La imagen
    original se queda en la primera mitad; la segunda queda vacía para que le
    pongas otra. El total sigue calzando con el audio (no se toca la voz)."""
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    escenas = datos["escenas"]
    idx = next((i for i, e in enumerate(escenas) if e["n"] == n), None)
    if idx is None:
        err("No existe esa escena.")
    e = escenas[idx]
    dur = e["fin"] - e["inicio"]
    if dur < 2 * MIN_DIVIDIR:
        err(f"La escena dura {dur:.1f}s: es muy corta para dividirla en dos.")

    if punto is None:
        punto = e["inicio"] + dur / 2
    lo, hi = e["inicio"] + MIN_DIVIDIR, e["fin"] - MIN_DIVIDIR
    punto = round(max(lo, min(hi, float(punto))) * FPS) / FPS

    # el texto se reparte por palabras según la fracción de tiempo (la voz es
    # continua; el texto solo da contexto para prompts y búsquedas)
    palabras = e["texto"].split()
    frac = (punto - e["inicio"]) / dur
    corte = max(1, min(len(palabras) - 1, round(frac * len(palabras)))) \
        if len(palabras) > 1 else 0
    texto1 = " ".join(palabras[:corte]) or e["texto"]
    texto2 = " ".join(palabras[corte:]) or e["texto"]

    total = len(escenas)
    # correr los archivos de las escenas siguientes (de la última hacia n+1)
    for m in range(total, e["n"], -1):
        _renombrar_medio(p, m, m + 1)
    for esc in escenas:
        if esc["n"] > e["n"]:
            esc["n"] += 1

    nueva = {
        "n": e["n"] + 1,
        "inicio": round(punto, 3),
        "fin": round(e["fin"], 3),
        "texto": texto2,
        "consulta": " ".join(_palabras_clave(texto2)),
        "prompt": prompt_ia(texto2),
        "imagen": f"{e['n'] + 1:03d}.jpg",
        "efecto": "auto",
        "transicion": e.get("transicion", "fundido"),
        "video_inicio": 0,
    }
    e["fin"] = round(punto, 3)
    e["texto"] = texto1
    e["consulta"] = " ".join(_palabras_clave(texto1))
    e["prompt"] = prompt_ia(texto1)
    e["transicion"] = "fundido"   # transición de la 1ª mitad a la 2ª
    escenas.insert(idx + 1, nueva)

    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))
    return nueva


def eliminar_escena(p, n):
    """Elimina la escena n. Su tiempo lo absorbe la escena anterior (o la
    siguiente si es la primera), así el total sigue calzando con el audio."""
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    escenas = datos["escenas"]
    if len(escenas) <= 1:
        err("No puedes borrar la única escena que queda.")
    idx = next((i for i, e in enumerate(escenas) if e["n"] == n), None)
    if idx is None:
        err("No existe esa escena.")
    e = escenas[idx]
    if idx > 0:
        escenas[idx - 1]["fin"] = e["fin"]
    else:
        escenas[idx + 1]["inicio"] = e["inicio"]

    borrar_medio(p, n)
    # correr los archivos de las escenas siguientes un lugar hacia abajo
    for m in range(n + 1, len(escenas) + 1):
        _renombrar_medio(p, m, m - 1)
    escenas.pop(idx)
    for esc in escenas:
        if esc["n"] > n:
            esc["n"] -= 1
            esc["imagen"] = f"{esc['n']:03d}.jpg"
    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))


# ----------------------------------------------------- historial (deshacer)

MAX_HISTORIAL = 25


def _instantanea(p, destino):
    """Foto del estado editable del proyecto. Los medios se guardan como
    hardlinks (no ocupan espacio extra y sobreviven aunque el original se
    borre o renombre)."""
    (destino / "imagenes").mkdir(parents=True, exist_ok=True)
    if (p / "escenas.json").exists():
        shutil.copy2(p / "escenas.json", destino / "escenas.json")
    if (p / "imagenes").is_dir():
        import os
        for f in (p / "imagenes").iterdir():
            if f.is_file():
                os.link(f, destino / "imagenes" / f.name)


def _restaurar(p, instantanea):
    import os
    if (instantanea / "escenas.json").exists():
        shutil.copy2(instantanea / "escenas.json", p / "escenas.json")
    (p / "imagenes").mkdir(exist_ok=True)
    for f in (p / "imagenes").iterdir():
        if f.is_file():
            f.unlink()
    for f in (instantanea / "imagenes").iterdir():
        os.link(f, p / "imagenes" / f.name)
    if (p / "miniaturas").is_dir():
        shutil.rmtree(p / "miniaturas")


def guardar_historial(p):
    """Llamar ANTES de cada cambio: guarda el estado para poder deshacer."""
    if not (p / "escenas.json").exists():
        return
    import time
    hist = p / ".historial"
    hist.mkdir(exist_ok=True)
    _instantanea(p, hist / f"{time.time_ns()}")
    entradas = sorted(hist.iterdir())
    for vieja in entradas[:-MAX_HISTORIAL]:
        shutil.rmtree(vieja)
    if (p / ".rehacer").exists():        # un cambio nuevo invalida el rehacer
        shutil.rmtree(p / ".rehacer")


def _mover_estado(p, desde_dir, hacia_dir, que):
    import time
    entradas = sorted(desde_dir.iterdir()) if desde_dir.is_dir() else []
    if not entradas:
        err(f"No hay nada que {que}.")
    hacia_dir.mkdir(exist_ok=True)
    _instantanea(p, hacia_dir / f"{time.time_ns()}")
    _restaurar(p, entradas[-1])
    shutil.rmtree(entradas[-1])


def deshacer(p):
    _mover_estado(p, p / ".historial", p / ".rehacer", "deshacer")


def rehacer(p):
    _mover_estado(p, p / ".rehacer", p / ".historial", "rehacer")


# ------------------------------------------------------------ forma de onda

def forma_de_onda(archivo, muestras=1200):
    """Picos 0..1 del audio para dibujar la forma de onda en la timeline."""
    import array
    r = subprocess.run(
        [str(FFMPEG_BIN), "-v", "error", "-i", str(archivo),
         "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
        capture_output=True)
    crudo = r.stdout[: len(r.stdout) // 2 * 2]
    datos = array.array("h")
    datos.frombytes(crudo)
    if not datos:
        return []
    paso = max(1, len(datos) // muestras)
    picos = []
    for i in range(0, len(datos), paso):
        seg = datos[i:i + paso]
        picos.append(max(abs(min(seg)), abs(max(seg))) / 32768)
    tope = max(picos) or 1
    return [round(x / tope, 3) for x in picos[:muestras]]


# ------------------------------------------------- capa de textos y logos

TAM_TEXTO = {"s": 42, "m": 62, "g": 90}
TAM_LOGO = {"s": 90, "m": 150, "g": 240}
TAM_ANIM = {"s": 74, "m": 116, "g": 168}   # tamaño del número del contador
TAM_CITA = {"s": 40, "m": 54, "g": 70}
TAM_LISTA = {"s": 34, "m": 46, "g": 58}
MARGEN_OVERLAY = 48
PLANTILLAS = ("contador", "cuenta", "barras", "banner", "cita", "lista")


def _posicion(codigo, tipo):
    """Expresiones x,y de ffmpeg para las 9 posiciones (si/sc/sd/ci/cc/cd/
    ii/ic/id = superior/centro/inferior + izquierda/centro/derecha)."""
    M = MARGEN_OVERLAY
    if tipo == "texto":   # drawtext usa w/h para el lienzo y tw/th del texto
        X = {"i": str(M), "c": "(w-tw)/2", "d": f"w-tw-{M}"}
        Y = {"s": str(M), "c": "(h-th)/2", "i": f"h-th-{M}"}
    else:                 # overlay usa W/H del lienzo y w/h del logo
        X = {"i": str(M), "c": "(W-w)/2", "d": f"W-w-{M}"}
        Y = {"s": str(M), "c": "(H-h)/2", "i": f"H-h-{M}"}
    fila, col = codigo[0], codigo[1]
    return X[col], Y[fila]


def leer_overlays(p):
    f = p / "escenas.json"
    if not f.exists():
        return []
    return json.loads(f.read_text()).get("overlays", [])


def guardar_overlay(p, ov):
    """Crea o actualiza un overlay (texto o logo) por id."""
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    overlays = datos.setdefault("overlays", [])
    ov["inicio"] = max(0.0, round(float(ov.get("inicio", 0)), 2))
    ov["fin"] = max(ov["inicio"] + 0.5, round(float(ov.get("fin", 5)), 2))
    if ov.get("posicion") not in ("si", "sc", "sd", "ci", "cc", "cd",
                                  "ii", "ic", "id"):
        ov["posicion"] = "ic"
    if ov.get("tamano") not in ("s", "m", "g"):
        ov["tamano"] = "m"
    existente = next((o for o in overlays if o["id"] == ov["id"]), None)
    if existente:
        existente.update(ov)
    else:
        overlays.append(ov)
    overlays.sort(key=lambda o: o["inicio"])
    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))
    return ov


def borrar_overlay(p, oid):
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    overlays = datos.get("overlays", [])
    datos["overlays"] = [o for o in overlays if o["id"] != oid]
    for viejo in (p / "overlays").glob(f"{oid}.*") if (p / "overlays").is_dir() else []:
        viejo.unlink()
    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))


def logo_de_overlay(p, oid):
    if (p / "overlays").is_dir():
        for f in (p / "overlays").glob(f"{oid}.*"):
            return f
    return None


def _ruta_fuente():
    """Ruta a una fuente TTF válida según el sistema operativo (para Pillow)."""
    if ES_WIN:
        win = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidatos = [win / "arialbd.ttf", win / "segoeui.ttf", win / "arial.ttf"]
    elif ES_MAC:
        candidatos = [Path("/System/Library/Fonts/Helvetica.ttc"),
                      Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")]
    else:
        candidatos = [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                      Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for c in candidatos:
        if c.exists():
            return str(c)
    return None   # último recurso: la fuente por defecto de Pillow


def _texto_a_png(texto, tamano, color, salida):
    """Renderiza el texto a un PNG transparente con borde negro (no dependemos
    del filtro drawtext, que falta en algunos ffmpeg de Homebrew)."""
    from PIL import Image, ImageDraw, ImageFont
    fs = TAM_TEXTO[tamano]
    borde = max(2, fs // 14)
    ruta = _ruta_fuente()
    fuente = ImageFont.truetype(ruta, fs) if ruta else ImageFont.load_default()
    sonda = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    caja = sonda.textbbox((0, 0), texto, font=fuente, stroke_width=borde)
    mgn = borde + 6
    img = Image.new("RGBA", (caja[2] - caja[0] + 2 * mgn,
                             caja[3] - caja[1] + 2 * mgn), (0, 0, 0, 0))
    dib = ImageDraw.Draw(img)
    dib.text((mgn - caja[0], mgn - caja[1]), texto, font=fuente,
             fill=color, stroke_width=borde, stroke_fill=(0, 0, 0, 210))
    img.save(salida)


# ------------------------------------------- plantillas de animación

def _fuente(px):
    from PIL import ImageFont
    ruta = _ruta_fuente()
    return ImageFont.truetype(ruta, int(px)) if ruta else ImageFont.load_default()


def _ease_out(x):
    return 1 - (1 - x) ** 3


def _fmt_numero(v, formato):
    v = int(round(v))
    if formato == "anio":
        return str(v)
    return f"{v:,}".replace(",", ".")     # separador de miles estilo LatAm


def _render_frames_contador(ov, dur, dirdest):
    """Número que sube hasta el objetivo (fechas, estadísticas). Devuelve el
    número de frames escritos como f00000.png…"""
    from PIL import Image, ImageDraw
    fs = TAM_ANIM.get(ov.get("tamano", "m"), TAM_ANIM["m"])
    color = ov.get("color", "#ffffff")
    pre, suf = ov.get("prefijo", ""), ov.get("sufijo", "")
    objetivo = float(ov.get("objetivo", 0))
    formato = ov.get("formato", "numero")
    borde = max(2, fs // 14)
    fuente = _fuente(fs)
    sonda = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

    texto_final = pre + _fmt_numero(objetivo, formato) + suf
    caja = sonda.textbbox((0, 0), texto_final, font=fuente, stroke_width=borde)
    mgn = borde + 12
    W = caja[2] - caja[0] + 2 * mgn
    H = caja[3] - caja[1] + 2 * mgn

    frames = max(2, round(dur * FPS))
    p_cuenta = 0.6                         # llega al objetivo al 60% del tiempo
    for k in range(frames):
        tf = k / (frames - 1) if frames > 1 else 1.0
        val = objetivo * _ease_out(min(1.0, tf / p_cuenta))
        txt = pre + _fmt_numero(val, formato) + suf
        alpha = min(1.0, tf / 0.12)        # aparición suave
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = d.textbbox((0, 0), txt, font=fuente, stroke_width=borde)
        tx = (W - (c[2] - c[0])) / 2 - c[0]
        ty = (H - (c[3] - c[1])) / 2 - c[1]
        d.text((tx, ty), txt, font=fuente, fill=color,
               stroke_width=borde, stroke_fill=(0, 0, 0, 210))
        if alpha < 1:
            img.putalpha(img.getchannel("A").point(lambda a: int(a * alpha)))
        img.save(dirdest / f"f{k:05d}.png")
    return frames


def _render_frames_barras(ov, dur, dirdest):
    """Gráfica de barras que crecen a su valor. Devuelve el número de frames."""
    from PIL import Image, ImageDraw
    esc = {"s": 0.75, "m": 1.0, "g": 1.3}.get(ov.get("tamano", "m"), 1.0)
    color = ov.get("color", "#8b5cf6")
    barras = [b for b in ov.get("barras", []) if str(b.get("etiqueta", "")).strip()][:5]
    if not barras:
        barras = [{"etiqueta": "A", "valor": 60}, {"etiqueta": "B", "valor": 100}]
    valores = [max(0.0, float(b.get("valor", 0))) for b in barras]
    vmax = max(valores) or 1.0

    fs_et = int(26 * esc)
    fs_val = int(24 * esc)
    fuente_et = _fuente(fs_et)
    fuente_val = _fuente(fs_val)
    ancho_barra = int(90 * esc)
    hueco = int(46 * esc)
    alto_zona = int(300 * esc)
    pad = int(22 * esc)
    n = len(barras)
    W = pad * 2 + n * ancho_barra + (n - 1) * hueco
    H = pad + fs_val + int(10 * esc) + alto_zona + int(10 * esc) + fs_et + pad

    y_base = H - pad - fs_et - int(10 * esc)     # línea donde apoyan las barras
    frames = max(2, round(dur * FPS))
    for k in range(frames):
        tf = k / (frames - 1) if frames > 1 else 1.0
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for i, b in enumerate(barras):
            x0 = pad + i * (ancho_barra + hueco)
            crecer = _ease_out(min(1.0, tf / 0.75))
            alto = alto_zona * (valores[i] / vmax) * crecer
            y0 = y_base - alto
            d.rounded_rectangle([x0, y0, x0 + ancho_barra, y_base],
                                radius=int(8 * esc), fill=color)
            # valor encima
            val_txt = _fmt_numero(valores[i] * crecer, "numero")
            cv = d.textbbox((0, 0), val_txt, font=fuente_val)
            d.text((x0 + (ancho_barra - (cv[2] - cv[0])) / 2, y0 - fs_val - int(6 * esc)),
                   val_txt, font=fuente_val, fill="#ffffff",
                   stroke_width=2, stroke_fill=(0, 0, 0, 200))
            # etiqueta debajo
            et = str(b.get("etiqueta", ""))
            ce = d.textbbox((0, 0), et, font=fuente_et)
            d.text((x0 + (ancho_barra - (ce[2] - ce[0])) / 2, y_base + int(10 * esc)),
                   et, font=fuente_et, fill="#d0d0e0",
                   stroke_width=2, stroke_fill=(0, 0, 0, 200))
        img.save(dirdest / f"f{k:05d}.png")
    return frames


def _render_png_banner(ov, salida):
    """Banda (lower-third) con título y subtítulo. Un solo PNG; el deslizamiento
    se hace al componer con ffmpeg."""
    from PIL import Image, ImageDraw
    esc = {"s": 0.8, "m": 1.0, "g": 1.25}.get(ov.get("tamano", "m"), 1.0)
    color = ov.get("color", "#8b5cf6")
    titulo = ov.get("titulo", "") or ""
    subt = ov.get("subtitulo", "") or ""
    fs_t, fs_s = int(46 * esc), int(28 * esc)
    ft, fsub = _fuente(fs_t), _fuente(fs_s)
    pad = int(26 * esc)
    barra_w = int(8 * esc)
    sep = int(18 * esc)
    sonda = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    wt = sonda.textbbox((0, 0), titulo, font=ft)[2]
    ws = sonda.textbbox((0, 0), subt, font=fsub)[2] if subt else 0
    ancho_txt = max(wt, ws, int(120 * esc))
    alto_txt = fs_t + (int(8 * esc) + fs_s if subt else 0)
    W = pad * 2 + barra_w + sep + ancho_txt
    H = pad * 2 + alto_txt

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=int(14 * esc), fill=(15, 15, 25, 225))
    d.rounded_rectangle([pad, pad, pad + barra_w, H - pad], radius=barra_w // 2, fill=color)
    tx = pad + barra_w + sep
    d.text((tx, pad), titulo, font=ft, fill="#ffffff")
    if subt:
        d.text((tx, pad + fs_t + int(8 * esc)), subt, font=fsub, fill="#b8b8c8")
    img.save(salida)


def _envolver(texto, fuente, max_w, dib):
    """Parte el texto en líneas que caben en max_w píxeles."""
    lineas, actual = [], ""
    for w in texto.split():
        prueba = (actual + " " + w).strip()
        if not actual or dib.textlength(prueba, font=fuente) <= max_w:
            actual = prueba
        else:
            lineas.append(actual)
            actual = w
    if actual:
        lineas.append(actual)
    return lineas or [""]


def _render_frames_cuenta(ov, dur, dirdest):
    """Cuenta regresiva: un número que baja hasta 0 (tensión). Frames escritos."""
    from PIL import Image, ImageDraw
    fs = TAM_ANIM.get(ov.get("tamano", "m"), TAM_ANIM["m"])
    color = ov.get("color", "#ffffff")
    desde = float(ov.get("desde", 10))
    suf = ov.get("sufijo", "")
    borde = max(2, fs // 14)
    fuente = _fuente(fs)
    sonda = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tmax = _fmt_numero(desde, "numero") + suf
    caja = sonda.textbbox((0, 0), tmax, font=fuente, stroke_width=borde)
    mgn = borde + 12
    W = caja[2] - caja[0] + 2 * mgn
    H = caja[3] - caja[1] + 2 * mgn
    frames = max(2, round(dur * FPS))
    for k in range(frames):
        p = k / (frames - 1) if frames > 1 else 1.0
        val = desde * (1 - p)              # baja de 'desde' a 0, lineal
        txt = _fmt_numero(val, "numero") + suf
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = d.textbbox((0, 0), txt, font=fuente, stroke_width=borde)
        tx = (W - (c[2] - c[0])) / 2 - c[0]
        ty = (H - (c[3] - c[1])) / 2 - c[1]
        d.text((tx, ty), txt, font=fuente, fill=color,
               stroke_width=borde, stroke_fill=(0, 0, 0, 210))
        img.save(dirdest / f"f{k:05d}.png")
    return frames


def _render_frames_cita(ov, dur, dirdest):
    """Cita con comillas grandes y autor, con aparición y salida suaves."""
    from PIL import Image, ImageDraw
    fs = TAM_CITA.get(ov.get("tamano", "m"), TAM_CITA["m"])
    color = ov.get("color", "#8b5cf6")
    texto = (ov.get("texto") or "").strip()
    autor = (ov.get("autor") or "").strip()
    fuente = _fuente(fs)
    fuente_a = _fuente(int(fs * 0.6))
    fuente_q = _fuente(int(fs * 2.4))
    borde = max(2, fs // 14)
    sonda = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lineas = _envolver(texto, fuente, 1200, sonda)
    interlinea = int(fs * 1.3)
    q_h = int(fs * 1.1)
    ancho = max([int(sonda.textlength(ln, font=fuente)) for ln in lineas] +
                ([int(sonda.textlength("— " + autor, font=fuente_a))] if autor else [0]))
    mgn = borde + 16
    W = ancho + 2 * mgn
    H = q_h + len(lineas) * interlinea + (int(fs * 1.1) if autor else 0) + 2 * mgn
    frames = max(2, round(dur * FPS))
    for k in range(frames):
        t = k / FPS
        a = 1.0
        if t < 0.4:
            a = t / 0.4
        elif t > dur - 0.4:
            a = max(0.0, (dur - t) / 0.4)
        a = max(0.0, min(1.0, a))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((mgn, mgn - int(fs * 0.35)), "“", font=fuente_q, fill=color)
        y = mgn + q_h
        for ln in lineas:
            d.text((mgn, y), ln, font=fuente, fill="#ffffff",
                   stroke_width=borde, stroke_fill=(0, 0, 0, 200))
            y += interlinea
        if autor:
            d.text((mgn, y + int(fs * 0.15)), "— " + autor, font=fuente_a,
                   fill="#c8c8d8", stroke_width=2, stroke_fill=(0, 0, 0, 180))
        if a < 1:
            img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
        img.save(dirdest / f"f{k:05d}.png")
    return frames


def _render_frames_lista(ov, dur, dirdest):
    """Lista con viñetas que aparecen una por una (ideal para datos)."""
    from PIL import Image, ImageDraw
    fs = TAM_LISTA.get(ov.get("tamano", "m"), TAM_LISTA["m"])
    color = ov.get("color", "#8b5cf6")
    items = [str(i).strip() for i in (ov.get("items") or []) if str(i).strip()][:6]
    if not items:
        items = ["Punto 1", "Punto 2"]
    fuente = _fuente(fs)
    borde = max(2, fs // 14)
    sonda = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    bullet_w = int(fs * 0.95)
    interlinea = int(fs * 1.55)
    ancho = max(int(sonda.textlength(it, font=fuente)) for it in items)
    mgn = borde + 14
    W = mgn * 2 + bullet_w + ancho
    H = mgn * 2 + len(items) * interlinea
    frames = max(2, round(dur * FPS))
    reveal = 0.7 * dur
    for k in range(frames):
        t = k / FPS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for i, it in enumerate(items):
            ti = (i / len(items)) * reveal
            ap = max(0.0, min(1.0, (t - ti) / 0.3))
            if ap <= 0:
                continue
            capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            dd = ImageDraw.Draw(capa)
            dx = int((1 - ap) * 40)
            y = mgn + i * interlinea
            x = mgn + dx
            r = max(4, int(fs * 0.16))
            cy = int(y + fs * 0.5)
            dd.ellipse([x, cy - r, x + 2 * r, cy + r], fill=color)
            dd.text((x + bullet_w, y), it, font=fuente, fill="#ffffff",
                    stroke_width=borde, stroke_fill=(0, 0, 0, 200))
            if ap < 1:
                capa.putalpha(capa.getchannel("A").point(lambda v: int(v * ap)))
            img = Image.alpha_composite(img, capa)
        img.save(dirdest / f"f{k:05d}.png")
    return frames


_RENDER_FRAMES = {
    "contador": _render_frames_contador,
    "barras": _render_frames_barras,
    "cuenta": _render_frames_cuenta,
    "cita": _render_frames_cita,
    "lista": _render_frames_lista,
}


def _orden_overlay(o):
    return {"logo": 0, "animacion": 1, "texto": 2}.get(o["tipo"], 1)


def _aplicar_overlays(p, video_entrada, video_salida, overlays, clips_dir):
    """Quema textos, logos y animaciones sobre el video ya montado.
    Capas: logos debajo, animaciones en medio, textos encima."""
    overlays = sorted(overlays, key=lambda o: (_orden_overlay(o), o["inicio"]))
    cmd = ["ffmpeg", "-y", "-i", str(video_entrada)]
    filtros = []
    corriente = "[0:v]"
    idx = 1
    for k, ov in enumerate(overlays):
        ini, fin = float(ov["inicio"]), float(ov["fin"])
        dur = max(0.3, fin - ini)
        activo = f"enable='between(t,{ini:.2f},{fin:.2f})'"

        if ov["tipo"] == "texto":
            if not ov.get("texto", "").strip():
                continue
            imagen = clips_dir / f"texto_{k}.png"
            _texto_a_png(ov["texto"], ov["tamano"], ov.get("color", "#ffffff"), imagen)
            x, y = _posicion(ov["posicion"], "logo")
            cmd += ["-i", str(imagen)]
            filtros.append(f"[{idx}:v]format=rgba[o{k}];"
                           f"{corriente}[o{k}]overlay=x={x}:y={y}:{activo}[vo{k}]")

        elif ov["tipo"] == "logo":
            imagen = logo_de_overlay(p, ov["id"])
            if imagen is None:
                continue
            x, y = _posicion(ov["posicion"], "logo")
            cmd += ["-i", str(imagen)]
            filtros.append(f"[{idx}:v]scale=-1:{TAM_LOGO[ov['tamano']]},format=rgba[o{k}];"
                           f"{corriente}[o{k}]overlay=x={x}:y={y}:{activo}[vo{k}]")

        elif ov["tipo"] == "animacion":
            plantilla = ov.get("plantilla", "contador")
            if plantilla == "banner":
                imagen = clips_dir / f"anim_{k}.png"
                _render_png_banner(ov, imagen)
                sl = min(0.4, dur / 2)
                _, y = _posicion(ov["posicion"], "logo")
                xexpr = (f"'if(lt(t,{ini}+{sl}),-w+(w+{MARGEN_OVERLAY})*((t-{ini})/{sl}),"
                         f"if(gt(t,{fin}-{sl}),{MARGEN_OVERLAY}-(w+{MARGEN_OVERLAY})*"
                         f"((t-({fin}-{sl}))/{sl}),{MARGEN_OVERLAY}))'")
                cmd += ["-loop", "1", "-framerate", str(FPS), "-t",
                        f"{fin + 0.2:.2f}", "-i", str(imagen)]
                filtros.append(f"[{idx}:v]format=rgba[o{k}];"
                               f"{corriente}[o{k}]overlay=x={xexpr}:y={y}:"
                               f"{activo}:eof_action=pass[vo{k}]")
            else:
                dirf = clips_dir / f"anim_{k}"
                if dirf.exists():
                    shutil.rmtree(dirf)
                dirf.mkdir(parents=True)
                _RENDER_FRAMES.get(plantilla, _render_frames_contador)(ov, dur, dirf)
                x, y = _posicion(ov["posicion"], "logo")
                cmd += ["-framerate", str(FPS), "-start_number", "0",
                        "-i", str(dirf / "f%05d.png")]
                filtros.append(
                    f"[{idx}:v]format=rgba,tpad=start_duration={ini:.3f}:"
                    f"start_mode=clone[o{k}];"
                    f"{corriente}[o{k}]overlay=x={x}:y={y}:{activo}:eof_action=pass[vo{k}]")
        else:
            continue

        idx += 1
        corriente = f"[vo{k}]"

    if not filtros:
        shutil.move(str(video_entrada), video_salida)
        return
    cmd += ["-filter_complex", ";".join(filtros), "-map", corriente,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-video_track_timescale", TIMESCALE,
            str(video_salida)]
    run(cmd)


def sugerir_consulta(p, n):
    """Recalcula (con el algoritmo mejorado) las palabras clave de la escena n,
    las guarda y las devuelve."""
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    e = next((e for e in datos["escenas"] if e["n"] == n), None)
    if e is None:
        err("No existe esa escena.")
    e["consulta"] = " ".join(_palabras_clave(e["texto"]))
    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))
    return e["consulta"]


def intercambiar_medios(p, na, nb):
    """Intercambia la imagen/video (y el efecto) entre dos escenas."""
    ma, _ = medio_de_escena(p, na)
    mb, _ = medio_de_escena(p, nb)
    tmp = p / "imagenes" / "___tmp"
    if ma:
        ma = ma.rename(tmp.with_suffix(ma.suffix))
    if mb:
        mb.rename(mb.with_name(f"{na:03d}{mb.suffix}"))
    if ma:
        ma.rename(ma.with_name(f"{nb:03d}{ma.suffix}"))
    for n in (na, nb):
        mini = p / "miniaturas" / f"{n:03d}.jpg"
        if mini.exists():
            mini.unlink()

    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    ea = next((e for e in datos["escenas"] if e["n"] == na), None)
    eb = next((e for e in datos["escenas"] if e["n"] == nb), None)
    if ea and eb:
        ea["efecto"], eb["efecto"] = eb.get("efecto", "auto"), ea.get("efecto", "auto")
        f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))


def opciones_escena(p, n, efecto=None, transicion=None, prompt=None,
                    video_inicio=None, ajustes=None):
    """Guarda el efecto, la transición, el prompt, el punto de inicio del
    video y/o los ajustes finos (escala, posición, opacidad, velocidad)."""
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    e = next((e for e in datos["escenas"] if e["n"] == n), None)
    if e is None:
        err("No existe esa escena.")
    if efecto is not None:
        if efecto not in EFECTOS:
            err(f"Efecto desconocido: {efecto}")
        e["efecto"] = efecto
    if transicion is not None:
        if transicion not in TRANSICIONES:
            err(f"Transición desconocida: {transicion}")
        e["transicion"] = transicion
    if prompt is not None:
        e["prompt"] = prompt.strip()
    if video_inicio is not None:
        e["video_inicio"] = max(0.0, float(video_inicio))
    if ajustes:
        rangos = {"escala": (0.3, 3.0), "pos_x": (-80, 80), "pos_y": (-80, 80),
                  "opacidad": (0.0, 1.0), "velocidad": (0.25, 4.0)}
        for k, (lo, hi) in rangos.items():
            if k in ajustes and ajustes[k] is not None:
                e[k] = round(max(lo, min(hi, float(ajustes[k]))), 3)
    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))


def _marcar_auto(p, ns):
    """Marca en escenas.json qué escenas tienen imagen puesta AUTOMÁTICAMENTE,
    para poder reemplazarlas luego sin pisar las que el usuario eligió a mano."""
    if not ns:
        return
    f = p / "escenas.json"
    datos = json.loads(f.read_text())
    for e in datos["escenas"]:
        if e["n"] in ns:
            e["medio_auto"] = True
    f.write_text(json.dumps(datos, ensure_ascii=False, indent=2))


def descargar_imagenes(p, on_progreso=None, reemplazar_auto=False):
    """Descarga de Pexels una imagen por escena. Por defecto no pisa las que ya
    tienen medio; con reemplazar_auto=True sí reemplaza las puestas
    automáticamente (medio_auto), respetando las elegidas a mano."""
    escenas = leer_escenas(p)
    (p / "imagenes").mkdir(exist_ok=True)
    avisar = on_progreso or (lambda *_: None)
    clave_pexels()  # valida antes de empezar
    orient = ORIENTACION.get(formato_proyecto(p), "landscape")

    usadas = set()
    pendientes, descargadas, saltadas, nuevas_auto = [], 0, 0, []
    for i, e in enumerate(escenas):
        n = e["n"]
        tiene = medio_de_escena(p, n)[0] is not None
        es_auto = e.get("medio_auto", False)
        if tiene and not (reemplazar_auto and es_auto):
            saltadas += 1
        else:
            fotos = pexels_buscar(e["consulta"], 5, orientacion=orient)
            foto = next((f for f in fotos if f["id"] not in usadas), None)
            if foto is None:
                pendientes.append(n)
            else:
                usadas.add(foto["id"])
                descargar_a_escena(p, n, foto["grande"], auto=True)
                nuevas_auto.append(n)
                descargadas += 1
        avisar(f"Imágenes… escena {n}/{len(escenas)}",
               (i + 1) / len(escenas) * 100)
    _marcar_auto(p, nuevas_auto)
    return {"descargadas": descargadas, "saltadas": saltadas,
            "pendientes": pendientes}


# ------------------------------------------- relleno inteligente multi-fuente
# Un "director de arte" que, por escena, busca en varias fuentes (Pexels fotos,
# Pexels videos y la web tipo Google Imágenes), puntúa por relevancia, mezcla
# foto y video para que el video sea dinámico, y usa la web para lo muy
# específico (que los bancos de stock no tienen). Opcionalmente una IA planea
# la fuente y la consulta de cada escena a partir de la guía que pone el usuario.

FUENTES_ORDEN = ["FOTO", "VIDEO", "WEB"]

SISTEMA_PLAN_IMAGENES = """Eres director de arte de un video narrado. Recibes el \
guión completo dividido en escenas numeradas. Para CADA escena decide la MEJOR \
fuente y una consulta de búsqueda de material visual de archivo.

FUENTE (elige una):
- FOTO: foto de archivo genérica (personas, lugares, objetos, atmósferas).
- VIDEO: clip genérico con movimiento (olas del mar, tráfico, fuego, multitud, \
nubes, radar) — para dar dinamismo.
- WEB: buscador web (como Google Imágenes), SOLO para cosas MUY específicas que \
los bancos de stock no tienen: un avión o barco concreto, una persona/lugar/\
evento/objeto histórico con nombre propio, una marca o modelo específico.

CONSULTA: en INGLÉS, 2 a 5 palabras concretas y visuales. Para WEB puedes incluir \
el nombre propio específico. Nada de conceptos abstractos.

Mezcla para que el video sea dinámico: alterna FOTO y VIDEO (aprox. 1 de cada 3 \
en VIDEO cuando encaje). Mantén un hilo visual coherente con TODA la historia.
{guia}
Responde SOLO una línea por escena, con este formato exacto y nada más:
N| FUENTE| consulta en inglés
(por ejemplo:  3| VIDEO| deep ocean waves sonar)"""


def plan_imagenes_ia(p, proveedor="gratis", modelo="", guia="", on_progreso=None):
    """Una IA ve la historia completa y decide, por escena, la fuente (FOTO/
    VIDEO/WEB) y la consulta, incorporando la guía/inputs del usuario. Escribe
    consulta + fuente_ia en escenas.json. Devuelve cuántas planeó."""
    avisar = on_progreso or (lambda *_: None)
    escenas = leer_escenas(p)
    if not escenas:
        err("No hay escenas todavía.")
    avisar("Planeando las imágenes con IA…", 10)

    guia_txt = ""
    if (guia or "").strip():
        guia_txt = ("\nEl usuario pide especialmente: " + guia.strip() +
                    "\nIncorpora estas indicaciones en las consultas de las escenas "
                    "donde encajen.")
    sistema = SISTEMA_PLAN_IMAGENES.replace("{guia}", guia_txt)
    lineas = "\n".join(f"{e['n']}| {e['texto']}" for e in escenas)
    pedido = (f"Historia en {len(escenas)} escenas. Devuelve una línea por escena "
              f"con FUENTE y consulta.\n\n{lineas}")
    crudo = chat_guion([{"rol": "usuario", "texto": pedido}],
                       proveedor=proveedor, modelo=modelo, sistema=sistema)

    plan = {}
    for linea in crudo.splitlines():
        m = re.match(r"\s*(\d+)\s*[|.:)\-]\s*(FOTO|VIDEO|WEB)\s*[|.:)\-]\s*(.+)",
                     linea, re.I)
        if m:
            q = re.sub(r'["*`]', "", m.group(3)).strip().strip(".")
            if q:
                plan[int(m.group(1))] = {"fuente": m.group(2).upper(), "consulta": q[:80]}
            continue
        m2 = re.match(r"\s*(\d+)\s*[|.:)\-]\s*(.+)", linea)     # sin fuente explícita
        if m2:
            q = re.sub(r'["*`]', "", m2.group(2)).strip().strip(".")
            if q:
                plan[int(m2.group(1))] = {"fuente": "FOTO", "consulta": q[:80]}

    if not plan:
        err("La IA no devolvió un plan en el formato esperado. Prueba con un "
            "proveedor más potente (Claude/Gemini/ChatGPT en 🔑 Claves API).")

    datos = json.loads((p / "escenas.json").read_text())
    cambiadas = 0
    for e in datos["escenas"]:
        pl = plan.get(e["n"])
        if pl:
            e["consulta"] = pl["consulta"]
            e["consulta_ia"] = True
            e["fuente_ia"] = pl["fuente"]
            cambiadas += 1
    (p / "escenas.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2))
    avisar("Plan listo", 100)
    return {"cambiadas": cambiadas, "total": len(escenas),
            "sin_respuesta": len(escenas) - len(plan)}


def _buscar_fuente(fuente, consulta, orient, cantidad=8):
    """Busca en una fuente y normaliza a [{tipo, url, id, texto}, …].
    Tolerante: si la fuente falla (sin clave, red), devuelve []."""
    fuente = (fuente or "FOTO").upper()
    try:
        if fuente == "VIDEO":
            return [{"tipo": "video", "url": v["url"], "id": f"pv{v['id']}",
                     "texto": ""}
                    for v in pexels_buscar_videos(consulta, cantidad, orientacion=orient)]
        if fuente == "WEB":
            return [{"tipo": "web", "url": w["grande"], "id": w["grande"],
                     "texto": w.get("titulo", "")}
                    for w in web_buscar_imagenes(consulta, cantidad) if w.get("grande")]
        return [{"tipo": "imagen", "url": f["grande"], "id": f"pf{f['id']}",
                 "texto": f.get("texto", "")}
                for f in pexels_buscar(consulta, cantidad, orientacion=orient)]
    except (ErrorPipeline, Exception):
        return []


def _puntuar_candidato(texto_escena, texto_cand):
    """Cuántos términos concretos de la escena aparecen en la descripción del
    candidato (relevancia). Los videos de Pexels no traen descripción → 0 neutro."""
    if not texto_cand:
        return 0
    base = {sin_acentos(w.lower()) for w in _concretas(texto_escena, 8)}
    cand = sin_acentos(texto_cand.lower())
    return sum(1 for w in base if w and len(w) > 2 and w in cand)


def _orden_fuentes(pref, permitidas, mezclar, ult_tipos):
    """Orden de fuentes a intentar para una escena: primero la que sugirió la IA,
    luego el resto; con `mezclar`, evita 3+ del mismo tipo seguidas."""
    orden = [pref] if pref in permitidas else []
    for f in permitidas:
        if f not in orden:
            orden.append(f)
    if mezclar and len(ult_tipos) >= 2 and ult_tipos[-1] == ult_tipos[-2]:
        mono = ult_tipos[-1]
        if mono == "imagen" and "VIDEO" in orden:
            orden.remove("VIDEO"); orden.insert(0, "VIDEO")
        elif mono == "video":
            for foto in ("FOTO", "WEB"):
                if foto in orden:
                    orden.remove(foto); orden.insert(0, foto); break
    return orden


def _bajar_candidato(p, n, cand):
    """Descarga un candidato como medio de la escena. True si lo logró."""
    try:
        if cand["tipo"] == "web":
            descargar_web_a_escena(p, n, cand["url"])
        elif cand["tipo"] == "video":
            descargar_a_escena(p, n, cand["url"], tipo="video", auto=True)
        else:
            descargar_a_escena(p, n, cand["url"], tipo="imagen", auto=True)
        return True
    except Exception:
        return False


def rellenar_inteligente(p, guia="", fuentes=None, mezclar=True,
                         reemplazar_auto=True, on_progreso=None):
    """Rellena cada escena buscando en varias fuentes y eligiendo el mejor medio,
    mezclando foto y video. Respeta las escenas elegidas a mano."""
    escenas = leer_escenas(p)
    (p / "imagenes").mkdir(exist_ok=True)
    avisar = on_progreso or (lambda *_: None)
    orient = ORIENTACION.get(formato_proyecto(p), "landscape")
    permitidas = [f for f in FUENTES_ORDEN if (not fuentes or f in fuentes)]
    if not permitidas:
        permitidas = ["FOTO"]
    guia_kw = [w.strip() for w in re.split(r"[,\n]+", guia or "") if w.strip()][:3]

    usadas, ult_tipos = set(), []
    descargadas = saltadas = pendientes = 0
    nuevas_auto = []
    for i, e in enumerate(escenas):
        n = e["n"]
        medio, tipo_actual = medio_de_escena(p, n)
        es_auto = e.get("medio_auto", False)
        if medio is not None and not (reemplazar_auto and es_auto):
            saltadas += 1
            ult_tipos.append("video" if tipo_actual == "video" else "imagen")
        else:
            consulta = (e.get("consulta") or "").strip()
            # si no hubo plan IA, enriquece la consulta con la guía del usuario
            if guia_kw and not e.get("consulta_ia"):
                consulta = (consulta + " " + " ".join(guia_kw)).strip()
            if not consulta:
                consulta = " ".join(guia_kw) or "dark mystery atmosphere"
            pref = (e.get("fuente_ia") or "FOTO").upper()
            elegido = None
            for fuente in _orden_fuentes(pref, permitidas, mezclar, ult_tipos):
                cands = [c for c in _buscar_fuente(fuente, consulta, orient)
                         if c["id"] not in usadas]
                if not cands:
                    continue
                cands.sort(key=lambda c: _puntuar_candidato(e["texto"], c["texto"]),
                           reverse=True)
                for c in cands[:5]:
                    if _bajar_candidato(p, n, c):
                        elegido = c
                        break
                if elegido:
                    break
            if elegido:
                usadas.add(elegido["id"])
                nuevas_auto.append(n)
                descargadas += 1
                ult_tipos.append("video" if elegido["tipo"] == "video" else "imagen")
            else:
                pendientes += 1
        avisar(f"Buscando el mejor medio… escena {n}/{len(escenas)}",
               (i + 1) / len(escenas) * 100)
    _marcar_auto(p, nuevas_auto)
    return {"descargadas": descargadas, "saltadas": saltadas,
            "pendientes": pendientes}


# ---------------------------------------------------------- núcleo: ensamble

def _clip_imagen(imagen, salida, dur, efecto, alterno, dims=(ANCHO, ALTO)):
    """Renderiza una escena a partir de una imagen, con el efecto elegido."""
    ancho, alto = dims
    frames = max(2, round(dur * FPS))
    d = frames - 1
    zoom_max = 1.13
    paso = (zoom_max - 1.0)
    if efecto == "auto":
        efecto = ("zoom_in", "zoom_out", "pan_h", "pan_v")[alterno % 4]

    if efecto == "estatico":
        run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
             "-i", str(imagen), "-vf",
             f"scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
             f"crop={ancho}:{alto},format=yuv420p",
             "-frames:v", str(frames), "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "18",
             "-video_track_timescale", TIMESCALE, str(salida)])
        return

    if efecto == "zoom_out":
        z = f"{zoom_max}-{paso}*on/{d}"
        x, y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    elif efecto == "pan_h":
        z = f"1+{paso}*on/{d}"
        x, y = f"(iw-iw/zoom)*on/{d}", "(ih-ih/zoom)/2"
    elif efecto == "pan_v":
        z = f"1+{paso}*on/{d}"
        x, y = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*on/{d}"
    else:  # zoom_in
        z = f"1+{paso}*on/{d}"
        x, y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"

    # se supersamplea al doble del lienzo para que el zoompan no pixele
    grande_w, grande_h = ancho * 2, alto * 2
    filtro = (
        f"scale={grande_w}:{grande_h}:force_original_aspect_ratio=increase,"
        f"crop={grande_w}:{grande_h},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={ancho}x{alto}:fps={FPS},"
        f"format=yuv420p"
    )
    run(["ffmpeg", "-y", "-i", str(imagen), "-vf", filtro,
         "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-video_track_timescale", TIMESCALE, str(salida)])


def _clip_video(video, salida, dur, inicio=0.0, velocidad=1.0, dims=(ANCHO, ALTO)):
    """Renderiza una escena a partir de un video: usa el tramo que empieza
    en `inicio`, a la `velocidad` indicada (0.5=lento, 2=rápido). Si el video
    no alcanza, se repite. Siempre sin su audio."""
    ancho, alto = dims
    frames = max(2, round(dur * FPS))
    velocidad = max(0.25, min(4.0, float(velocidad or 1)))
    necesita = dur * velocidad          # segundos de fuente que consume
    dur_video = ffprobe_duracion(video)
    cmd = ["ffmpeg", "-y"]
    if dur_video >= inicio + necesita + 0.05:
        inicio = max(0.0, min(float(inicio or 0), dur_video - necesita - 0.02))
        if inicio > 0:
            cmd += ["-ss", f"{inicio:.3f}"]
    else:
        cmd += ["-stream_loop", "-1"]
    vf = (f"scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
          f"crop={ancho}:{alto},")
    if abs(velocidad - 1) > 0.001:
        vf += f"setpts=PTS/{velocidad:.4f},"
    vf += f"fps={FPS},format=yuv420p"
    cmd += ["-i", str(video), "-vf", vf,
            "-frames:v", str(frames), "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-video_track_timescale", TIMESCALE, str(salida)]
    run(cmd)


def _ajuste_fino(clip, escala=1.0, pos_x=0.0, pos_y=0.0, opacidad=1.0,
                 dims=(ANCHO, ALTO)):
    """Aplica escala / posición / opacidad a un clip ya renderizado.
    Solo se llama si algún parámetro se salió del valor por defecto."""
    if abs(escala - 1) < 1e-3 and abs(pos_x) < 1e-3 and abs(pos_y) < 1e-3 \
            and abs(opacidad - 1) < 1e-3:
        return
    ancho, alto = dims
    tmp = clip.with_name(clip.stem + "_aj.mp4")
    px = pos_x / 100 * ancho
    py = pos_y / 100 * alto
    filtro = (
        f"[0:v]scale=w=iw*{escala:.4f}:h=ih*{escala:.4f},"
        f"format=rgba,colorchannelmixer=aa={opacidad:.3f}[s];"
        f"color=black:s={ancho}x{alto}[bg];"
        f"[bg][s]overlay=x=(W-w)/2+({px:.1f}):y=(H-h)/2+({py:.1f}):shortest=1,"
        f"format=yuv420p[v]")
    run(["ffmpeg", "-y", "-i", str(clip), "-filter_complex", filtro,
         "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-video_track_timescale", TIMESCALE, str(tmp)])
    tmp.replace(clip)


def _encadenar_fundidos(archivos, duraciones, salida, transiciones=None):
    """Une clips con xfade. offsets: o_k = sum(L_j, j<k) - k*F.
    `transiciones[k]` es el nombre xfade entre el clip k y el k+1."""
    if len(archivos) == 1:
        shutil.copy(archivos[0], salida)
        return
    if transiciones is None:
        transiciones = ["fade"] * (len(archivos) - 1)
    cmd = ["ffmpeg", "-y"]
    for f in archivos:
        cmd += ["-i", str(f)]
    # xfade exige que ambos clips tengan la MISMA base de tiempo; los videos
    # (Pexels o subidos) suelen traer otra escala que los clips de imagen, así
    # que se normaliza cada entrada (fps, timebase, sar y formato) antes de unir.
    filtros = [f"[{k}:v]fps={FPS},settb=AVTB,setsar=1,format=yuv420p[n{k}]"
               for k in range(len(archivos))]
    previo = "[n0]"
    offset = 0.0
    for k in range(1, len(archivos)):
        offset += duraciones[k - 1] - FUNDIDO
        etiqueta = f"[vx{k}]"
        filtros.append(f"{previo}[n{k}]xfade=transition={transiciones[k-1]}:"
                       f"duration={FUNDIDO}:offset={offset:.3f}{etiqueta}")
        previo = etiqueta
    cmd += ["-filter_complex", ";".join(filtros), "-map", previo,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-video_track_timescale", TIMESCALE,
            str(salida)]
    run(cmd)


def _concatenar_cortes(archivos, salida, tmpdir):
    """Une clips con corte seco (concat sin re-codificar)."""
    if len(archivos) == 1:
        shutil.move(str(archivos[0]), salida)
        return
    lista = tmpdir / "concat.txt"
    lista.write_text("".join(f"file '{f.resolve()}'\n" for f in archivos))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
         "-c", "copy", str(salida)])


def _placeholder(salida, n, dims=(ANCHO, ALTO)):
    """Imagen oscura de relleno para escenas sin imagen."""
    ancho, alto = dims
    tono = 20 + (n * 7) % 30
    run(["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"gradients=s={ancho}x{alto}:c0=#0a0a{tono:02x}:c1=#000000:n=2:d=1",
         "-frames:v", "1", str(salida)])


# ----------------------------------------------------------- subtítulos

TAM_SUBS = {"s": 40, "m": 52, "g": 66}   # tamaño de fuente sobre 1080p


def leer_subtitulos(p):
    f = p / "subtitulos.json"
    if f.exists():
        return json.loads(f.read_text())
    return {"activo": False,
            "estilo": {"tamano": "m", "color": "#ffffff", "posicion": "abajo"},
            "frases": []}


def guardar_subtitulos(p, datos):
    (p / "subtitulos.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2))


def generar_subtitulos(p, max_chars=42, max_dur=4.5):
    """Agrupa las palabras de la transcripción (tiempos por palabra) en frases
    cortas de subtítulo. Corta por longitud, duración, pausas y puntuación."""
    f = p / "transcripcion.json"
    if not f.exists():
        err("Primero procesa el audio: no hay transcripción todavía.")
    trans = json.loads(f.read_text())

    frases, act = [], None

    def cerrar():
        nonlocal act
        if act and act["texto"].strip():
            frases.append(act)
        act = None

    for seg in trans.get("segmentos", []):
        palabras = seg.get("palabras") or []
        if not palabras:
            # segmento sin tiempos por palabra: úsalo entero como una frase
            cerrar()
            frases.append({"inicio": seg["inicio"], "fin": seg["fin"],
                           "texto": seg["texto"].strip()})
            continue
        for w in palabras:
            pal = w["palabra"].strip()
            if not pal:
                continue
            if act is None:
                act = {"inicio": w["inicio"], "fin": w["fin"], "texto": pal}
                continue
            hueco = w["inicio"] - act["fin"]
            termina_frase = act["texto"][-1:] in ".!?…"
            larga = len(act["texto"]) + 1 + len(pal) > max_chars
            excede = (w["fin"] - act["inicio"]) > max_dur
            if larga or excede or hueco > 0.8 or termina_frase:
                cerrar()
                act = {"inicio": w["inicio"], "fin": w["fin"], "texto": pal}
            else:
                act["texto"] += " " + pal
                act["fin"] = w["fin"]
    cerrar()

    for fr in frases:
        fr["inicio"] = round(max(0.0, fr["inicio"]), 2)
        fr["fin"] = round(max(fr["fin"], fr["inicio"] + 0.6), 2)
        fr["texto"] = fr["texto"].strip()

    datos = leer_subtitulos(p)
    datos["frases"] = frases
    datos["activo"] = True
    guardar_subtitulos(p, datos)
    return datos


def _color_ass(hexcolor):
    """#RRGGBB → &H00BBGGRR (formato de color de ASS)."""
    h = (hexcolor or "#ffffff").lstrip("#")
    if len(h) != 6:
        h = "ffffff"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _tiempo_ass(s):
    h = int(s // 3600)
    m = int(s % 3600 // 60)
    return f"{h:d}:{m:02d}:{s % 60:05.2f}"


def escribir_ass(p, datos, ruta, dims=(ANCHO, ALTO)):
    """Genera el archivo .ass con el estilo elegido, para quemarlo con libass."""
    ancho, alto = dims
    est = datos.get("estilo", {})
    # la fuente se escala con la altura para que el subtítulo se vea del mismo
    # tamaño físico en vertical (9:16) que en horizontal
    tam = round(TAM_SUBS.get(est.get("tamano", "m"), TAM_SUBS["m"]) * alto / 1080)
    margen_v = round((0 if est.get("posicion") == "centro" else 64) * alto / 1080)
    color = _color_ass(est.get("color", "#ffffff"))
    alineacion = 5 if est.get("posicion") == "centro" else 2  # 5=centro, 2=abajo
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {ancho}
PlayResY: {alto}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subs,Helvetica,{tam},{color},{color},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,{alineacion},80,80,{margen_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = [cab]
    for fr in datos.get("frases", []):
        texto = (fr.get("texto") or "").replace("{", "(").replace("}", ")")
        texto = texto.replace("\n", "\\N")
        if not texto.strip():
            continue
        lineas.append(f"Dialogue: 0,{_tiempo_ass(fr['inicio'])},"
                      f"{_tiempo_ass(fr['fin'])},Subs,,0,0,0,,{texto}\n")
    Path(ruta).write_text("".join(lineas), encoding="utf-8")


def _quemar_subtitulos(p, entrada, salida, clips_dir, dims=(ANCHO, ALTO)):
    datos = leer_subtitulos(p)
    ass = clips_dir / "subtitulos.ass"
    escribir_ass(p, datos, ass, dims=dims)
    # dentro de comillas simples del filtro solo hay que escapar \ y '
    ruta = str(ass).replace("\\", "\\\\").replace("'", "\\'")
    run(["ffmpeg", "-y", "-i", str(entrada),
         "-vf", f"ass='{ruta}'",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-an", str(salida)])


def ensamblar_video(p, on_progreso=None):
    """Imágenes + audio → video.mp4. Devuelve (ruta, escenas_sin_imagen)."""
    if leer_ajustes(p).get("tipo") == "relax":
        return ensamblar_relax(p, on_progreso)       # ruta eficiente para videos largos
    escenas = leer_escenas(p)
    audio = buscar_audio(p)
    avisar = on_progreso or (lambda *_: None)
    dims = dims_proyecto(p)              # (ancho, alto) según el formato elegido

    clips_dir = p / "clips"
    clips_dir.mkdir(exist_ok=True)

    # 1) Un clip por escena (imagen con efecto, o video recortado).
    #    Si la transición de salida es un fundido, el clip dura FUNDIDO extra
    #    para compensar el solapamiento y que el total calce con el audio.
    clips, largos, faltantes = [], [], []
    trans_salida = []  # transición entre la escena i y la i+1 ("corte" o xfade)
    for i, e in enumerate(escenas):
        medio, tipo = medio_de_escena(p, e["n"])
        if medio is None:
            medio, tipo = clips_dir / f"ph_{e['n']:03d}.png", "imagen"
            _placeholder(medio, e["n"], dims=dims)
            faltantes.append(e["n"])
        trans = e.get("transicion", "fundido")
        if trans not in TRANSICIONES:
            trans = "fundido"
        ultimo = i == len(escenas) - 1
        extra = FUNDIDO if (not ultimo and trans != "corte") else 0.0
        if not ultimo:
            trans_salida.append(trans)
        dur = e["fin"] - e["inicio"]
        L = round((dur + extra) * FPS) / FPS
        clip = clips_dir / f"{e['n']:03d}.mp4"
        if tipo == "video":
            _clip_video(medio, clip, L, e.get("video_inicio", 0.0),
                        e.get("velocidad", 1.0), dims=dims)
        else:
            _clip_imagen(medio, clip, L, e.get("efecto", "auto"), i, dims=dims)
        _ajuste_fino(clip, e.get("escala", 1.0), e.get("pos_x", 0.0),
                     e.get("pos_y", 0.0), e.get("opacidad", 1.0), dims=dims)
        clips.append(clip)
        largos.append(L)
        avisar(f"Renderizando escena {e['n']}/{len(escenas)}",
               (i + 1) / len(escenas) * 75)

    # 2) Tramos: escenas consecutivas unidas por fundidos; los cortes secos
    #    separan tramos (y luego se concatenan sin re-codificar).
    tramos = []          # cada tramo: (lista_clips, lista_L, lista_trans)
    ini = 0
    for k, t in enumerate(trans_salida):
        if t == "corte":
            tramos.append((clips[ini:k + 1], largos[ini:k + 1],
                           trans_salida[ini:k]))
            ini = k + 1
    tramos.append((clips[ini:], largos[ini:], trans_salida[ini:]))

    salidas_tramos = []
    for ti, (t_clips, t_L, t_trans) in enumerate(tramos):
        avisar(f"Transiciones… tramo {ti + 1}/{len(tramos)}",
               75 + ti / len(tramos) * 18)
        destino = clips_dir / f"tramo_{ti:02d}.mp4"
        # por lotes para no armar filtros gigantes de ffmpeg
        if len(t_clips) <= TAM_LOTE_XFADE:
            nombres = [XFADE[t] for t in t_trans]
            _encadenar_fundidos(t_clips, t_L, destino, nombres)
        else:
            lotes, lotes_L, lotes_trans = [], [], []
            for j in range(0, len(t_clips), TAM_LOTE_XFADE):
                grupo = t_clips[j:j + TAM_LOTE_XFADE]
                grupo_L = t_L[j:j + TAM_LOTE_XFADE]
                interno = [XFADE[t] for t in t_trans[j:j + len(grupo) - 1]]
                salida_lote = clips_dir / f"tramo_{ti:02d}_lote_{j:03d}.mp4"
                _encadenar_fundidos(grupo, grupo_L, salida_lote, interno)
                lotes.append(salida_lote)
                lotes_L.append(sum(grupo_L) - (len(grupo) - 1) * FUNDIDO)
                if j + TAM_LOTE_XFADE < len(t_clips):
                    lotes_trans.append(XFADE[t_trans[j + len(grupo) - 1]])
            _encadenar_fundidos(lotes, lotes_L, destino, lotes_trans)
        salidas_tramos.append(destino)

    video_mudo = clips_dir / "video_mudo.mp4"
    avisar("Uniendo tramos…", 94)
    _concatenar_cortes(salidas_tramos, video_mudo, clips_dir)

    # 2b) Textos y logos encima del video, si los hay.
    overlays = leer_overlays(p)
    if overlays:
        avisar("Aplicando textos y logos…", 96)
        con_overlays = clips_dir / "video_overlays.mp4"
        _aplicar_overlays(p, video_mudo, con_overlays, overlays, clips_dir)
        video_mudo = con_overlays

    # 2c) Subtítulos quemados, si están activados.
    subs = leer_subtitulos(p)
    if subs.get("activo") and subs.get("frases"):
        avisar("Quemando subtítulos…", 96)
        con_subs = clips_dir / "video_subs.mp4"
        _quemar_subtitulos(p, video_mudo, con_subs, clips_dir, dims=dims)
        video_mudo = con_subs

    # 3) Añadir la narración (y la música de fondo si hay).
    #    Se escribe a un temporal y solo al terminar bien se renombra a
    #    video.mp4, para que un corte (p. ej. sin espacio en disco) nunca deje
    #    el maestro corrupto/a medias.
    salida = p / "video.mp4"
    tmp = p / "video.tmp.mp4"
    avisar("Mezclando audio…", 97)
    musica = buscar_musica(p)
    if musica:
        vol = float(leer_ajustes(p).get("musica_volumen", 0.12))
        dur_total = escenas[-1]["fin"]
        fade_ini = max(0.0, dur_total - 3.0)
        run(["ffmpeg", "-y", "-i", str(video_mudo), "-i", str(audio),
             "-stream_loop", "-1", "-i", str(musica),
             "-filter_complex",
             # la música se normaliza primero para que el % de volumen se
             # comporte igual con cualquier archivo
             f"[1:a]aresample=48000[voz];"
             f"[2:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
             f"volume={vol:.3f},afade=t=out:st={fade_ini:.2f}:d=3[mus];"
             f"[voz][mus]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             "-t", f"{dur_total:.3f}", str(tmp)])
    else:
        run(["ffmpeg", "-y", "-i", str(video_mudo), "-i", str(audio),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             str(tmp)])
    if not video_valido(tmp):
        tmp.unlink(missing_ok=True)
        err("La exportación quedó incompleta (¿te quedaste sin espacio en el "
            "disco?). Libera espacio y vuelve a exportar.")
    os.replace(tmp, salida)               # renombrado atómico: maestro íntegro
    avisar("Listo", 100)
    return salida, faltantes


# calidades de exportación → (lado corto en px, CRF, etiqueta). El "corto" es
# el lado menor del video (alto en 16:9, ancho en 9:16), así funciona en
# cualquier formato: 1080 = 1080p, 720 = 720p.
CALIDADES = {
    "maxima":   {"corto": 1080, "crf": 16, "etiqueta": "Máxima (1080p, archivo grande)"},
    "alta":     {"corto": 1080, "crf": 19, "etiqueta": "Alta — recomendada (1080p)"},
    "estandar": {"corto": 1080, "crf": 23, "etiqueta": "Estándar (1080p, más ligero)"},
    "ligera":   {"corto": 720,  "crf": 24, "etiqueta": "Ligera (720p, rápida)"},
}


def carpetas_comunes():
    """Carpetas destino sugeridas que existen en el equipo."""
    home = Path.home()
    cand = [(home / "Desktop", "Escritorio"), (home / "Downloads", "Descargas"),
            (home / "Movies", "Películas"), (home, "Carpeta personal")]
    return [{"ruta": str(r), "etiqueta": e} for r, e in cand if r.is_dir()]


def nombre_archivo_seguro(nombre, por_defecto):
    nombre = re.sub(r"[/\\:*?\"<>|]", "", nombre or "").strip()
    nombre = nombre[:-4] if nombre.lower().endswith(".mp4") else nombre
    return (nombre or por_defecto) + ".mp4"


def _marca_agua_png(dims, salida):
    """Genera el PNG de la marca de agua (isotipo + 'AutoFaceless Studio' en una
    pastilla semitransparente), dimensionado según el alto del video de salida."""
    from PIL import Image, ImageDraw, ImageFont
    _ancho, alto = dims
    fs = max(18, round(alto * 0.030))
    txt = "AutoFaceless Studio"
    ruta = _ruta_fuente()
    fuente = ImageFont.truetype(ruta, fs) if ruta else ImageFont.load_default()
    sonda = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    caja = sonda.textbbox((0, 0), txt, font=fuente)
    tw, th = caja[2] - caja[0], caja[3] - caja[1]
    padx, pady = round(fs * 0.7), round(fs * 0.45)
    logo, gap = round(fs * 1.05), round(fs * 0.5)
    W = padx + logo + gap + tw + padx
    H = pady + max(th, logo) + pady
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2, fill=(15, 15, 20, 150))
    lx, ly = padx, (H - logo) // 2
    d.rounded_rectangle([lx, ly, lx + logo, ly + logo], radius=round(logo * 0.26),
                        fill=(196, 35, 27, 235))
    cab = round(logo * 0.34)
    d.ellipse([lx + logo / 2 - cab / 2, ly + logo * 0.16,
               lx + logo / 2 + cab / 2, ly + logo * 0.16 + cab], fill=(255, 255, 255, 235))
    hw, hh = round(logo * 0.62), round(logo * 0.42)
    d.rounded_rectangle([lx + logo / 2 - hw / 2, ly + logo - hh,
                         lx + logo / 2 + hw / 2, ly + logo], radius=round(hw * 0.5),
                        fill=(255, 255, 255, 235))
    d.text((lx + logo + gap, (H - th) // 2 - caja[1]), txt, font=fuente,
           fill=(255, 255, 255, 225))
    img.save(salida)


def exportar_final(p, carpeta, nombre_archivo, calidad="alta",
                   on_progreso=None, master_ok=False, marca_agua=False):
    """Construye el master (video.mp4) si hace falta y lo transcodifica a la
    calidad/carpeta/nombre elegidos. Devuelve la ruta final."""
    avisar = on_progreso or (lambda *_: None)
    # Reconstruir si no hay maestro, si cambió, o si el que hay está corrupto
    # (p. ej. quedó a medias por falta de espacio en una exportación anterior).
    if not master_ok or not video_valido(p / "video.mp4"):
        libre = shutil.disk_usage(p).free
        if libre < 1_500_000_000:              # armar el video necesita espacio temporal
            err(f"Poco espacio en el disco ({libre/1e9:.1f} GB libres). Libera al "
                f"menos 2 GB y vuelve a exportar (armar el video usa espacio temporal).")
        (p / "video.mp4").unlink(missing_ok=True)
        ensamblar_video(p, on_progreso=lambda t, pc: avisar(t, pc * 0.82))

    cfg = CALIDADES.get(calidad, CALIDADES["alta"])
    destino_dir = Path(carpeta).expanduser() if carpeta else (Path.home() / "Desktop")
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        err(f"No pude usar esa carpeta: {e}")
    if not destino_dir.is_dir():
        err(f"La carpeta destino no existe: {destino_dir}")
    destino = destino_dir / nombre_archivo_seguro(nombre_archivo, p.name)

    # Se escribe a un temporal en la misma carpeta y solo al terminar bien se
    # renombra al nombre final (así un corte no deja un archivo a medias).
    tmp = destino.with_name("." + destino.stem + ".tmp.mp4")
    # El master ya está a lado-corto 1080 en el formato del proyecto. Si la
    # calidad NO baja la resolución, no hace falta re-codificar: basta copiar
    # (casi instantáneo). Si baja (720p), se escala manteniendo el formato.
    ancho_m, alto_m = dims_proyecto(p)
    corto_m = min(ancho_m, alto_m)
    baja = cfg["corto"] < corto_m
    if baja:
        factor = cfg["corto"] / corto_m
        out_w = round(ancho_m * factor / 2) * 2      # dimensiones pares
        out_h = round(alto_m * factor / 2) * 2
    else:
        out_w, out_h = ancho_m, alto_m

    if marca_agua:
        avisar("Añadiendo la marca de agua y guardando…", 88)
        wm = tmp.with_name("_marca.png")
        _marca_agua_png((out_w, out_h), wm)
        mgn = max(10, round(out_h * 0.028))
        fc = (f"[0:v]scale={out_w}:{out_h}[v];[v][1:v]overlay=W-w-{mgn}:H-h-{mgn}"
              if baja else f"[0:v][1:v]overlay=W-w-{mgn}:H-h-{mgn}")
        run(["ffmpeg", "-y", "-i", str(p / "video.mp4"), "-i", str(wm),
             "-filter_complex", fc,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg["crf"]),
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             "-video_track_timescale", TIMESCALE, str(tmp)])
        wm.unlink(missing_ok=True)
    elif not baja:
        # el master ya está a la resolución final: basta copiar (casi instantáneo)
        avisar("Guardando el archivo…", 92)
        run(["ffmpeg", "-y", "-i", str(p / "video.mp4"),
             "-c", "copy", "-movflags", "+faststart", str(tmp)])
    else:
        avisar("Ajustando calidad y guardando el archivo…", 88)
        run(["ffmpeg", "-y", "-i", str(p / "video.mp4"),
             "-vf", f"scale={out_w}:{out_h}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg["crf"]),
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             "-video_track_timescale", TIMESCALE, str(tmp)])
    if not video_valido(tmp):
        tmp.unlink(missing_ok=True)
        err("El archivo final quedó incompleto (¿te quedaste sin espacio en el "
            "disco?). Libera espacio y vuelve a exportar.")
    os.replace(tmp, destino)
    avisar("Listo", 100)
    return destino


def revelar_en_finder(ruta):
    """Abre el explorador de archivos del SO mostrando (seleccionado) el archivo."""
    ruta = Path(ruta)
    if not ruta.exists():
        err("El archivo ya no existe.")
    if ES_WIN:
        subprocess.run(["explorer", "/select,", str(ruta)])
    elif ES_MAC:
        subprocess.run(["open", "-R", str(ruta)])
    else:
        subprocess.run(["xdg-open", str(ruta.parent)])


def _dims_video(ruta):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(ruta)])
    w, h = r.stdout.strip().split(",")
    return int(w), int(h)


def exportar_union(nombres, carpeta, nombre_archivo, calidad="alta",
                   on_progreso=None, marca_agua=False):
    """Exporta VARIAS historias unidas en un solo archivo, con fundido entre
    ellas. Arma el maestro que falte, normaliza todas al tamaño de la primera y
    guarda en la carpeta/calidad elegidas. Devuelve la ruta final."""
    avisar = on_progreso or (lambda *_: None)
    if len(nombres) < 2:
        err("Elige al menos 2 historias para unir.")

    # 1) asegurar el maestro (video.mp4) de cada historia
    masters = []
    for i, n in enumerate(nombres):
        p = dir_proyecto(n)
        if not video_valido(p / "video.mp4"):
            avisar(f"Armando «{n}»…", i / len(nombres) * 55)
            ensamblar_video(p)
        masters.append(p / "video.mp4")

    # 2) tamaño destino: el de la primera historia, escalado a la calidad
    w0, h0 = _dims_video(masters[0])
    cfg = CALIDADES.get(calidad, CALIDADES["alta"])
    corto0 = min(w0, h0)
    factor = min(1.0, cfg["corto"] / corto0)
    Wt = round(w0 * factor / 2) * 2
    Ht = round(h0 * factor / 2) * 2

    duraciones = [ffprobe_duracion(v) for v in masters]
    F = FUNDIDO_HISTORIAS
    cmd = ["ffmpeg", "-y"]
    for v in masters:
        cmd += ["-i", str(v)]
    wm_tmp = None
    if marca_agua:
        import tempfile
        wm_tmp = Path(tempfile.mktemp(suffix=".png"))
        _marca_agua_png((Wt, Ht), wm_tmp)
        cmd += ["-i", str(wm_tmp)]
        wm_idx = len(masters)
    # normaliza cada entrada al mismo tamaño/tiempo (xfade lo exige)
    fv = [f"[{k}:v]scale={Wt}:{Ht}:force_original_aspect_ratio=increase,"
          f"crop={Wt}:{Ht},fps={FPS},settb=AVTB,setsar=1,format=yuv420p[n{k}]"
          for k in range(len(masters))]
    fa = []
    pv, pa = "[n0]", "[0:a]"
    offset = 0.0
    for k in range(1, len(masters)):
        offset += duraciones[k - 1] - F
        fv.append(f"{pv}[n{k}]xfade=transition=fade:duration={F}:"
                  f"offset={offset:.3f}[vx{k}]")
        fa.append(f"{pa}[{k}:a]acrossfade=d={F}[ax{k}]")
        pv, pa = f"[vx{k}]", f"[ax{k}]"

    destino_dir = Path(carpeta).expanduser() if carpeta else (Path.home() / "Desktop")
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        err(f"No pude usar esa carpeta: {e}")
    destino = destino_dir / nombre_archivo_seguro(nombre_archivo, "video_final")
    tmp = destino.with_name("." + destino.stem + ".tmp.mp4")
    avisar("Uniendo y exportando…", 60)
    filtros = fv + fa
    map_v = pv
    if marca_agua:
        mgn = max(10, round(Ht * 0.028))
        filtros.append(f"{pv}[{wm_idx}:v]overlay=W-w-{mgn}:H-h-{mgn}[vout]")
        map_v = "[vout]"
    cmd += ["-filter_complex", ";".join(filtros), "-map", map_v, "-map", pa,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg["crf"]),
            "-pix_fmt", "yuv420p", "-video_track_timescale", TIMESCALE,
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp)]
    run(cmd)
    if wm_tmp:
        wm_tmp.unlink(missing_ok=True)
    if not video_valido(tmp):
        tmp.unlink(missing_ok=True)
        err("La unión quedó incompleta (¿te quedaste sin espacio?). "
            "Libera espacio y reintenta.")
    os.replace(tmp, destino)
    avisar("Listo", 100)
    return destino


def unir_videos(nombres, salida_nombre, on_progreso=None):
    """Une los video.mp4 de varios proyectos con fundido. Devuelve la ruta."""
    avisar = on_progreso or (lambda *_: None)
    videos = []
    for n in nombres:
        v = dir_proyecto(n) / "video.mp4"
        if not v.exists():
            err(f"El proyecto '{n}' no tiene video.mp4 — expórtalo primero.")
        videos.append(v)

    duraciones = [ffprobe_duracion(v) for v in videos]
    F = FUNDIDO_HISTORIAS
    cmd = ["ffmpeg", "-y"]
    for v in videos:
        cmd += ["-i", str(v)]
    # normaliza la base de tiempo de cada historia antes del xfade
    fv = [f"[{k}:v]fps={FPS},settb=AVTB,setsar=1,format=yuv420p[n{k}]"
          for k in range(len(videos))]
    fa = []
    pv, pa = "[n0]", "[0:a]"
    offset = 0.0
    for k in range(1, len(videos)):
        offset += duraciones[k - 1] - F
        fv.append(f"{pv}[n{k}]xfade=transition=fade:duration={F}:"
                  f"offset={offset:.3f}[vx{k}]")
        fa.append(f"{pa}[{k}:a]acrossfade=d={F}[ax{k}]")
        pv, pa = f"[vx{k}]", f"[ax{k}]"
    salida = PROYECTOS / f"{salida_nombre}.mp4"
    avisar(f"Uniendo {len(videos)} historias…", 10)
    cmd += ["-filter_complex", ";".join(fv + fa), "-map", pv, "-map", pa,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-video_track_timescale", TIMESCALE,
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(salida)]
    run(cmd)
    avisar("Listo", 100)
    return salida


# ============================================================ NICHO: RELAX
# Videos de música/sonidos relajantes (sin narración). El audio se GENERA:
# los paisajes sonoros (lluvia, mar, fuego…) se sintetizan gratis con ffmpeg
# (ruido filtrado + modulación lenta) a cualquier duración, y opcionalmente se
# mezcla una capa de música melódica hecha con IA (ElevenLabs). Las imágenes
# salen de los temas visuales que elige el usuario (lluvia, bosque, estrellas…).

# Cada paisaje = una o más capas de ruido con su cadena de filtros. La modulación
# de volumen con expresiones (eval=frame) da el vaivén natural (olas, viento…).
AMBIENTES = {
    "lluvia":   [("pink",  "highpass=f=600,lowpass=f=10000,volume=1.5")],
    "tormenta": [("pink",  "highpass=f=600,lowpass=f=9000,volume=1.4"),
                 ("brown", "lowpass=f=120,volume='0.55+0.4*sin(2*PI*0.045*t)':eval=frame,volume=1.4")],
    "mar":      [("brown", "lowpass=f=1200,volume='0.35+0.55*(0.5+0.5*sin(2*PI*0.09*t))':eval=frame,volume=1.7")],
    "rio":      [("pink",  "highpass=f=800,lowpass=f=6500,volume='0.85+0.15*sin(2*PI*1.4*t)':eval=frame,volume=1.3")],
    "bosque":   [("brown", "bandpass=f=900:width_type=h:w=1400,volume='0.45+0.4*sin(2*PI*0.05*t)':eval=frame,volume=1.4"),
                 ("pink",  "highpass=f=5000,lowpass=f=9000,volume=0.10")],
    "fuego":    [("brown", "lowpass=f=1500,volume='0.6+0.25*sin(2*PI*0.7*t)+0.15*sin(2*PI*3.3*t)':eval=frame,volume=1.4")],
    "viento":   [("brown", "bandpass=f=500:width_type=h:w=900,volume='0.3+0.6*(0.5+0.5*sin(2*PI*0.06*t))':eval=frame,volume=1.5")],
    "noche":    [("brown", "lowpass=f=400,volume=0.5"),
                 ("pink",  "highpass=f=4500,lowpass=f=7500,volume='0.16*(0.5+0.5*sin(2*PI*2.2*t))':eval=frame,volume=1.2")],
}
AMBIENTES_NOMBRE = {
    "lluvia": "Lluvia", "tormenta": "Tormenta", "mar": "Mar / Olas",
    "rio": "Río / Arroyo", "bosque": "Bosque", "fuego": "Fuego / Chimenea",
    "viento": "Viento", "noche": "Noche / Grillos",
}


def generar_ambiente(tipos, dur, salida, on_progreso=None):
    """Sintetiza un paisaje sonoro de `dur` segundos mezclando los `tipos`
    elegidos (lluvia, mar, fuego…) y lo escribe como mp3 en `salida`.
    Todo con ffmpeg, sin claves ni internet, a cualquier duración."""
    avisar = on_progreso or (lambda *_: None)
    tipos = [t for t in (tipos or []) if t in AMBIENTES]
    if not tipos:
        err("Elige al menos un sonido de ambiente (lluvia, mar, fuego…).")
    dur = max(3.0, float(dur))
    avisar("Generando el paisaje sonoro…", 5)

    entradas, filtros, etiquetas, idx = [], [], [], 0
    for t in tipos:
        for color, cadena in AMBIENTES[t]:
            entradas += ["-f", "lavfi", "-t", f"{dur:.2f}",
                         "-i", f"anoisesrc=c={color}:a=0.8:r=48000"]
            filtros.append(f"[{idx}:a]{cadena}[a{idx}]")
            etiquetas.append(f"[a{idx}]")
            idx += 1
    mezcla = (f"{''.join(etiquetas)}amix=inputs={idx}:normalize=0:"
              f"duration=longest[mx]")
    fin_fade = max(0.1, dur - 4.0)
    post = (f"[mx]aformat=channel_layouts=stereo,alimiter=limit=0.9,"
            f"afade=t=in:st=0:d=2,afade=t=out:st={fin_fade:.2f}:d=4[out]")
    cmd = (["ffmpeg", "-y"] + entradas +
           ["-filter_complex", ";".join(filtros + [mezcla, post]),
            "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", str(salida)])
    run(cmd)
    avisar("Paisaje sonoro listo", 100)
    return salida


# Música melódica opcional con IA (ElevenLabs Music). Es un extra: si falla o la
# cuenta no tiene acceso, el proyecto se queda solo con el ambiente (que basta).
MUSICA_PROMPT = {
    "piano":      "calm slow solo piano, peaceful and gentle, for sleep and relaxation, no drums, no vocals",
    "ambient":    "soft ambient pads, ethereal warm meditative drone, calming, no percussion, no vocals",
    "lofi":       "lo-fi chill beats, mellow and warm, relaxing study music, soft, no vocals",
    "meditacion": "meditation music, tibetan singing bowls and soft drones, deeply calming, no vocals",
}
MUSICA_NOMBRE = {"piano": "Piano suave", "ambient": "Ambient / Pads",
                 "lofi": "Lo-fi chill", "meditacion": "Meditación"}


def elevenlabs_musica(mood, salida, dur_s=180):
    """Genera una pista de música relajante con ElevenLabs Music y la guarda en
    `salida`. Best-effort: si la cuenta no tiene acceso, lanza y el llamador la
    omite (el ambiente sigue funcionando)."""
    import requests
    key = _elevenlabs_key()
    prompt = MUSICA_PROMPT.get(mood, MUSICA_PROMPT["ambient"])
    length_ms = int(max(10.0, min(float(dur_s), 300.0)) * 1000)  # Eleven limita el largo
    try:
        r = requests.post("https://api.elevenlabs.io/v1/music", timeout=300,
                          headers={"xi-api-key": key, "Accept": "audio/mpeg",
                                   "Content-Type": "application/json"},
                          json={"prompt": prompt, "music_length_ms": length_ms})
    except requests.RequestException as e:
        err(f"No pude conectar con ElevenLabs Music: {e}")
    if not r.ok:
        err(f"ElevenLabs Music rechazó la petición ({r.status_code}): {r.text[:200]}")
    Path(salida).write_bytes(r.content)
    return salida


# Temas visuales → consulta en Pexels (en inglés funciona mejor) + tipo preferido.
VISUALES = {
    "lluvia_ventana": ("rain on window", "video"),
    "bosque":         ("forest nature calm", "video"),
    "estrellas":      ("starry night sky stars", "video"),
    "chimenea":       ("fireplace fire cozy", "video"),
    "playa":          ("ocean waves beach calm", "video"),
    "nieve":          ("snow falling winter", "video"),
    "montanas":       ("mountains landscape mist", "video"),
    "nubes":          ("clouds sky timelapse", "video"),
    "aurora":         ("aurora borealis northern lights", "video"),
    "cafe":           ("cozy coffee shop rainy", "video"),
    "lago":           ("calm lake reflection nature", "video"),
    "espacio":        ("space stars nebula galaxy", "video"),
}
VISUALES_NOMBRE = {
    "lluvia_ventana": "Lluvia en la ventana", "bosque": "Bosque",
    "estrellas": "Cielo estrellado", "chimenea": "Chimenea", "playa": "Playa / Olas",
    "nieve": "Nieve cayendo", "montanas": "Montañas", "nubes": "Nubes",
    "aurora": "Aurora boreal", "cafe": "Cafetería acogedora", "lago": "Lago",
    "espacio": "Espacio",
}
RELAX_SEG = 24.0    # segundos por escena en el loop visual


def armar_escenas_relax(p, visuales, on_progreso=None):
    """Descarga un video/imagen de Pexels por cada tema visual elegido y escribe
    escenas.json (el loop visual corto que luego se repite hasta la duración)."""
    avisar = on_progreso or (lambda *_: None)
    aj = leer_ajustes(p)
    orient = ORIENTACION.get(aj.get("formato", "16:9"), "landscape")
    visuales = [v for v in (visuales or []) if v in VISUALES] or ["lluvia_ventana"]
    escenas, t = [], 0.0
    for i, v in enumerate(visuales, 1):
        consulta, pref = VISUALES[v]
        avisar(f"Buscando visual: {VISUALES_NOMBRE.get(v, v)}",
               10 + i / len(visuales) * 75)
        url, tipo = None, "imagen"
        try:
            if pref == "video":
                vids = pexels_buscar_videos(consulta, cantidad=12, orientacion=orient)
                vids = [x for x in vids if x.get("duracion", 0) >= 6]
                vids.sort(key=lambda x: abs(x.get("duracion", 0) - 20))
                if vids:
                    url, tipo = vids[0]["url"], "video"
            if url is None:
                fotos = pexels_buscar(consulta, cantidad=8, orientacion=orient)
                if fotos:
                    url, tipo = fotos[0]["grande"], "imagen"
        except Exception:
            pass
        if url:
            descargar_a_escena(p, i, url, tipo=tipo, auto=True)
        escenas.append({"n": i, "inicio": round(t, 3), "fin": round(t + RELAX_SEG, 3),
                        "texto": VISUALES_NOMBRE.get(v, v), "consulta": consulta,
                        "prompt": "", "imagen": f"{i:03d}.jpg",
                        "efecto": "zoom_in", "transicion": "fundido",
                        "medio_auto": True})
        t += RELAX_SEG
    (p / "escenas.json").write_text(
        json.dumps({"duracion": round(t, 3), "escenas": escenas},
                   ensure_ascii=False, indent=2))
    return escenas


# Música melódica GRATIS: pads/drones sintetizados con osciladores (ffmpeg). No es
# una melodía "real", pero los pads ambientales son un subgénero legítimo de música
# relajante y combinan perfecto con los sonidos de la naturaleza. Sin claves.
ACORDES = {
    "pad_calido":  [130.81, 164.81, 196.00, 261.63],   # Do mayor, cálido
    "pad_sonador": [130.81, 196.00, 293.66, 392.00],   # quintas abiertas + 9ª, etéreo
    "drone":       [110.00, 164.81, 220.00],           # La grave + quinta, meditación
    "campanas":    [261.63, 329.63, 392.00, 523.25],   # Do mayor agudo, brillante
}
MUSICA_GRATIS_NOMBRE = {"pad_calido": "Pad cálido", "pad_sonador": "Pad soñador",
                        "drone": "Drone / Meditación", "campanas": "Campanas"}
# equivalencia pad → prompt de ElevenLabs (si el usuario activa la versión IA)
_ELEVEN_DE_PAD = {"pad_calido": "piano", "pad_sonador": "ambient",
                  "drone": "meditacion", "campanas": "ambient"}


def generar_musica_ambiente(mood, dur, salida, loopable=False, on_progreso=None):
    """Sintetiza un pad/drone ambiental GRATIS con ffmpeg (acordes de sinusoides
    con vibrato/tremolo lentos + reverb). Se usa como cama de música relajante."""
    freqs = ACORDES.get(mood, ACORDES["pad_calido"])
    dur = max(3.0, float(dur))
    entradas, filtros, etiquetas = [], [], []
    for i, f in enumerate(freqs):
        entradas += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", f"sine=f={f}:r=48000"]
        rate = 0.12 + 0.03 * i           # tremolo lento (>=0.1Hz) distinto por voz → coro
        filtros.append(f"[{i}:a]vibrato=f=0.12:d=0.6,tremolo=f={rate:.3f}:d=0.5,"
                       f"volume=0.22[v{i}]")
        etiquetas.append(f"[v{i}]")
    mezcla = f"{''.join(etiquetas)}amix=inputs={len(freqs)}:normalize=0[mx]"
    # reverb suave + filtro cálido; si es loopable, sin fades (se repite sin cortes)
    cadena = "lowpass=f=2600,aecho=0.8:0.9:700|1300:0.35|0.25,alimiter=limit=0.9"
    if not loopable:
        fin = max(0.1, dur - 4.0)
        cadena += f",afade=t=in:st=0:d=3,afade=t=out:st={fin:.2f}:d=4"
    post = f"[mx]{cadena}[out]"
    run(["ffmpeg", "-y"] + entradas +
        ["-filter_complex", ";".join(filtros + [mezcla, post]),
         "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", str(salida)])
    return salida


def ensamblar_relax(p, on_progreso=None):
    """Ensamblado eficiente para videos largos: arma un loop visual corto con
    BITRATE ACOTADO y lo repite con `-stream_loop` copiando el video (sin
    recodificar la hora entera ni crear un intermedio gigante). Luego mezcla el
    audio ya generado."""
    avisar = on_progreso or (lambda *_: None)
    aj = leer_ajustes(p)
    escenas = leer_escenas(p)
    dims = dims_proyecto(p)
    clips_dir = p / "clips"
    clips_dir.mkdir(exist_ok=True)
    total = max(5.0, float(aj.get("relax_min", 10)) * 60)

    # 1) Un clip por escena → loop visual corto (silencioso).
    partes, faltantes = [], []
    for i, e in enumerate(escenas):
        medio, tipo = medio_de_escena(p, e["n"])
        if medio is None:
            medio, tipo = clips_dir / f"ph_{e['n']:03d}.png", "imagen"
            _placeholder(medio, e["n"], dims=dims)
            faltantes.append(e["n"])
        clip = clips_dir / f"loop_{e['n']:03d}.mp4"
        if tipo == "video":
            _clip_video(medio, clip, RELAX_SEG, 0.0,
                        float(aj.get("relax_vel", 0.85)), dims=dims)
        else:
            _clip_imagen(medio, clip, RELAX_SEG, "zoom_in", i, dims=dims)
        partes.append(clip)
        avisar(f"Preparando visual {i + 1}/{len(escenas)}",
               25 + (i + 1) / len(escenas) * 45)

    # loop.mp4 = las partes concatenadas y RECODIFICADAS con bitrate acotado.
    # Esto es lo que evita que un video de 1 h pese decenas de GB: el clip de
    # Pexels puede venir a ~18 Mbps; aquí lo bajamos a ~4 Mbps máx.
    loop = clips_dir / "loop.mp4"
    lista = clips_dir / "loop_lista.txt"
    lista.write_text("".join(f"file '{c.as_posix()}'\n" for c in partes))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
         "-maxrate", "4M", "-bufsize", "8M", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-an", str(loop)])
    loop_dur = RELAX_SEG * len(partes)

    # Aviso temprano si no hay espacio en disco para la duración pedida.
    bytes_seg = loop.stat().st_size / max(0.1, loop_dur)
    necesita = int(bytes_seg * total * 1.15) + 60 * 1024 * 1024
    if shutil.disk_usage(p).free < necesita:
        for f in clips_dir.glob("loop*.mp4"):
            f.unlink(missing_ok=True)
        err(f"No hay espacio en disco para un video de {int(total/60)} min "
            f"(hacen falta ~{necesita // (1024*1024)} MB libres). Libera espacio "
            f"o elige una duración menor.")

    # 2) Mux: repetir el loop con -stream_loop (video copiado) + audio, en una
    #    sola pasada. Sin archivo intermedio de longitud completa.
    avisar("Uniendo audio y video (esto puede tardar en videos largos)…", 82)
    audio = buscar_audio(p)
    musica = buscar_musica(p)
    salida = p / "video.mp4"
    tmp = p / "video.tmp.mp4"
    base = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(loop), "-i", str(audio)]
    if musica:
        vol = float(aj.get("musica_volumen", 0.5))
        fade_ini = max(0.0, total - 4.0)
        cmd = base + ["-stream_loop", "-1", "-i", str(musica), "-filter_complex",
                      f"[1:a]aresample=48000[amb];"
                      f"[2:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
                      f"volume={vol:.3f},afade=t=out:st={fade_ini:.2f}:d=4[mus];"
                      f"[amb][mus]amix=inputs=2:duration=first:normalize=0[a]",
                      "-map", "0:v", "-map", "[a]"]
    else:
        cmd = base + ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.2f}",
            "-movflags", "+faststart", str(tmp)]
    run(cmd)
    if not video_valido(tmp):
        tmp.unlink(missing_ok=True)
        err("El render quedó incompleto (¿espacio en disco?).")

    # Textos/logos encima, si los hay (raro en relax; recodifica, pero solo si hay).
    overlays = leer_overlays(p)
    if overlays:
        con_ov = clips_dir / "relax_ov.mp4"
        _aplicar_overlays(p, tmp, con_ov, overlays, clips_dir)
        os.replace(con_ov, tmp)

    os.replace(tmp, salida)
    for f in clips_dir.glob("loop*.mp4"):        # limpieza: liberar los temporales
        f.unlink(missing_ok=True)
    avisar("Listo", 100)
    return salida, faltantes


def crear_relax(p, sonidos, visuales, dur_min=10, formato="16:9", titulo="",
                musica_mood="", musica_ia=False, on_progreso=None):
    """Orquesta un proyecto Relax completo: audio (ambiente sintetizado + música
    opcional, gratis o con IA) → visuales por tema → ensamblado del video final."""
    avisar = on_progreso or (lambda *_: None)
    dur_min = max(1, min(180, int(dur_min)))
    guardar_ajustes(p, tipo="relax", formato=formato, relax_min=dur_min,
                    sonidos=sonidos, visuales=visuales, titulo=titulo,
                    musica=musica_mood, musica_ia=bool(musica_ia),
                    musica_volumen=0.5)

    # 1) Música opcional → musica.mp3 (la mezcla el ensamblado, en loop).
    if musica_mood:
        hecha = False
        if musica_ia:                       # versión IA (ElevenLabs), best-effort
            avisar("Generando la música con IA…", 3)
            try:
                elevenlabs_musica(_ELEVEN_DE_PAD.get(musica_mood, "ambient"),
                                  p / "musica.mp3", dur_s=180)
                hecha = True
            except Exception:
                (p / "musica.mp3").unlink(missing_ok=True)   # cae a la versión gratis
        if not hecha:                       # música GRATIS sintetizada (pads/drones)
            avisar("Generando la música…", 3)
            generar_musica_ambiente(musica_mood, 90, p / "musica.mp3", loopable=True)

    # 2) Paisaje sonoro a longitud completa → audio.mp3
    generar_ambiente(sonidos, dur_min * 60, p / "audio.mp3",
                     on_progreso=lambda t, pc: avisar(t, 6 + (pc or 0) * 0.14))

    # 3) Visuales por tema → escenas.json
    armar_escenas_relax(p, visuales,
                        on_progreso=lambda t, pc: avisar("Buscando visuales…", 22))

    # 4) Ensamblar el video final (delegado a ensamblar_relax por tipo=relax)
    _, faltantes = ensamblar_video(
        p, on_progreso=lambda t, pc: avisar(t, 25 + (pc or 0) * 0.72))
    return faltantes


# ------------------------------------------------------------------ CLI

def cmd_nuevo(nombre):
    p = PROYECTOS / nombre
    (p / "imagenes").mkdir(parents=True, exist_ok=True)
    print(f"✓ Proyecto creado: {p}")
    print(f"  1. Copia el audio de MiniMax a {p}/ (mp3, wav…)")
    print(f"  2. Corre: ./editor todo {nombre}")


def cmd_transcribir(nombre, modelo="small"):
    p = dir_proyecto(nombre)
    print(f"→ Transcribiendo con Whisper ({modelo})…")
    datos = transcribir_audio(p, modelo,
                              on_progreso=lambda t, pc: print(f"  {t}", end="\r"))
    print(f"\n✓ {len(datos['segmentos'])} segmentos → transcripcion.json "
          f"({datos['duracion']:.0f}s de audio)")


def cmd_escenas(nombre):
    p = dir_proyecto(nombre)
    escenas = generar_escenas(p)
    print(f"✓ {len(escenas)} escenas → escenas.json")
    print("✓ Prompts para IA → prompts_ia.md")


def cmd_imagenes(nombre):
    p = dir_proyecto(nombre)
    r = descargar_imagenes(p, on_progreso=lambda t, pc: print(f"  {t}", end="\r"))
    print(f"\n✓ {r['descargadas']} descargadas, {r['saltadas']} ya existían, "
          f"{len(r['pendientes'])} pendientes")
    if r["pendientes"]:
        print("  Genera las pendientes con los prompts de prompts_ia.md")


def cmd_ensamblar(nombre):
    p = dir_proyecto(nombre)
    salida, faltantes = ensamblar_video(
        p, on_progreso=lambda t, pc: print(f"  {t}          ", end="\r"))
    print()
    if faltantes:
        print(f"  ⚠ Sin imagen (usé relleno oscuro): "
              f"{', '.join(f'{n:03d}' for n in faltantes)}")
    print(f"✓ {salida}  ({ffprobe_duracion(salida)/60:.1f} min)")


def cmd_todo(nombre, modelo="small"):
    cmd_transcribir(nombre, modelo)
    cmd_escenas(nombre)
    if leer_env().get("PEXELS_API_KEY"):
        cmd_imagenes(nombre)
    else:
        print("⚠ Sin PEXELS_API_KEY en .env — salto la descarga de imágenes.")
    cmd_ensamblar(nombre)


def cmd_unir(salida_nombre, nombres):
    salida = unir_videos(nombres, salida_nombre,
                         on_progreso=lambda t, pc: print(f"→ {t}"))
    print(f"✓ {salida}  ({ffprobe_duracion(salida)/60:.1f} min) — listo para YouTube")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("nuevo", help="crea la carpeta de una historia")
    s.add_argument("nombre")

    s = sub.add_parser("transcribir", help="audio → transcripcion.json (Whisper)")
    s.add_argument("nombre")
    s.add_argument("--modelo", default="small",
                   help="tiny/base/small/medium (default: small)")

    s = sub.add_parser("escenas", help="transcripción → escenas.json + prompts_ia.md")
    s.add_argument("nombre")

    s = sub.add_parser("imagenes", help="descarga imágenes de Pexels por escena")
    s.add_argument("nombre")

    s = sub.add_parser("ensamblar", help="imágenes + audio → video.mp4")
    s.add_argument("nombre")

    s = sub.add_parser("todo", help="corre todo el flujo de una historia")
    s.add_argument("nombre")
    s.add_argument("--modelo", default="small")

    s = sub.add_parser("unir", help="une varias historias en el video final")
    s.add_argument("salida", help="nombre del video final (sin .mp4)")
    s.add_argument("historias", nargs="+", help="nombres de los proyectos, en orden")

    a = ap.parse_args()
    try:
        if a.cmd == "nuevo":
            cmd_nuevo(a.nombre)
        elif a.cmd == "transcribir":
            cmd_transcribir(a.nombre, a.modelo)
        elif a.cmd == "escenas":
            cmd_escenas(a.nombre)
        elif a.cmd == "imagenes":
            cmd_imagenes(a.nombre)
        elif a.cmd == "ensamblar":
            cmd_ensamblar(a.nombre)
        elif a.cmd == "todo":
            cmd_todo(a.nombre, a.modelo)
        elif a.cmd == "unir":
            cmd_unir(a.salida, a.historias)
    except ErrorPipeline as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
