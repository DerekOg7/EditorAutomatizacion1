# -*- mode: python ; coding: utf-8 -*-
# Empaqueta el editor.  Uso:  pyinstaller empaquetar.spec
#
# macOS  → dist/AutoFaceless Video.app  (BUNDLE; sin firmar: clic derecho → Abrir).
# Windows → dist/AutoFaceless Video/AutoFaceless Video.exe  (carpeta onedir;
#           SmartScreen: Más información → Ejecutar de todos modos).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

exec(Path("version.py").read_text())  # define VERSION

ES_WIN = sys.platform.startswith("win")
ES_MAC = sys.platform == "darwin"

block_cipher = None
nombre_app = "AutoFaceless Video"

# faster-whisper / ctranslate2 traen binarios y datos que PyInstaller no
# detecta solo — se recolectan explícitamente.
datas, binarios, ocultos = [], [], []
# edge_tts/aiohttp: la voz gratuita se importa de forma perezosa dentro de una
# función, así que PyInstaller no la detecta solo — se recolecta explícitamente.
for paquete in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers",
                "edge_tts", "aiohttp"):
    d, b, h = collect_all(paquete)
    datas += d
    binarios += b
    ocultos += h

# ffmpeg estático según el SO (en Windows, ffmpeg.exe/ffprobe.exe en ffmpeg-win).
_ff_win = Path("empaquetado/ffmpeg-win")
_ff_dir = "empaquetado/ffmpeg-win" if (ES_WIN and _ff_win.is_dir()) else "empaquetado/ffmpeg"

datas += [
    ("static", "static"),
    (_ff_dir, "ffmpeg"),
]

# Icono de la app (marca AF): .ico en Windows, .icns en macOS.
_icono = ("empaquetado/icono/AutoFaceless.ico" if ES_WIN
          else "empaquetado/icono/AutoFaceless.icns")

a = Analysis(
    ["scripts/lanzador.py"],
    pathex=["."],
    binaries=binarios,
    datas=datas,
    hiddenimports=ocultos + ["editor", "app", "version",
                             "licencia", "licencia_ed25519"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# En Windows el ejecutable lleva el nombre de la app (AutoFaceless Video.exe);
# en macOS se llama "lanzador" y el .app envolvente lleva el nombre bonito.
_exe_name = nombre_app if ES_WIN else "lanzador"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=_exe_name,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=_icono,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=nombre_app,
)

# El BUNDLE (.app) solo existe en macOS; en Windows el resultado es la carpeta
# onedir dist/AutoFaceless Video/ con el .exe adentro.
if ES_MAC:
    app = BUNDLE(
        coll,
        name=f"{nombre_app}.app",
        icon=_icono,
        bundle_identifier="com.autofacelessvideo.editor",
        info_plist={
            "CFBundleName": nombre_app,
            "CFBundleDisplayName": nombre_app,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSUIElement": False,
        },
    )
