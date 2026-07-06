# -*- mode: python ; coding: utf-8 -*-
# Empaqueta el editor como app de macOS.  Uso:  pyinstaller empaquetar.spec
#
# El .app resultante queda en dist/AutoFaceless Video.app — se puede
# copiar/comprimir para compartir. No está firmado: la primera vez hay que
# abrirlo con clic derecho → Abrir (Gatekeeper).

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

exec(Path("version.py").read_text())  # define VERSION

block_cipher = None
nombre_app = "AutoFaceless Video"

# faster-whisper / ctranslate2 traen binarios y datos que PyInstaller no
# detecta solo — se recolectan explícitamente.
datas, binarios, ocultos = [], [], []
for paquete in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers"):
    d, b, h = collect_all(paquete)
    datas += d
    binarios += b
    ocultos += h

datas += [
    ("static", "static"),
    ("empaquetado/ffmpeg", "ffmpeg"),
]

a = Analysis(
    ["scripts/lanzador.py"],
    pathex=["."],
    binaries=binarios,
    datas=datas,
    hiddenimports=ocultos + ["editor", "app", "version"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lanzador",
    debug=False,
    strip=False,
    upx=False,
    console=False,
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

app = BUNDLE(
    coll,
    name=f"{nombre_app}.app",
    icon=None,
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
