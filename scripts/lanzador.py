#!/usr/bin/env python3
"""Punto de entrada del .app: arranca el servidor Flask en segundo plano y
abre el navegador del usuario en el editor. Equivalente empaquetado de
`python app.py`, pero pensado para correr con doble clic, sin terminal.

Si el puerto ya está ocupado, distingue tres casos:
  · una instancia SANA de esta misma versión → solo abre el navegador;
  · una instancia nuestra rota o de una versión vieja (proceso fantasma que
    quedó vivo tras borrar/actualizar la app) → la cierra y arranca de nuevo;
  · otro programa ajeno → usa un puerto libre cercano.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from version import VERSION

PUERTO_PREFERIDO = 5178


def puerto_libre(puerto):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", puerto)) != 0


def salud(puerto):
    """Respuesta de /api/salud de lo que sea que escuche en el puerto, o None."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/api/salud", timeout=3) as r:
            return json.load(r)
    except Exception:
        return None


ES_WIN = sys.platform.startswith("win")


def _pids_en_puerto(puerto):
    try:
        if ES_WIN:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                                 capture_output=True, text=True, timeout=8).stdout
            pids = set()
            for linea in out.splitlines():
                partes = linea.split()
                if len(partes) >= 5 and partes[3] == "LISTENING" \
                        and partes[1].endswith(f":{puerto}"):
                    try:
                        pids.add(int(partes[4]))
                    except ValueError:
                        pass
            return list(pids)
        out = subprocess.run(["lsof", "-ti", f"tcp:{puerto}"],
                             capture_output=True, text=True, timeout=5).stdout
        return [int(x) for x in out.split()]
    except Exception:
        return []


def _es_nuestro(pid):
    """True si el proceso es una instancia de esta app (vieja o actual)."""
    try:
        if ES_WIN:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=8).stdout.lower()
            return "lanzador" in out or "autofaceless" in out
        comm = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                              capture_output=True, text=True, timeout=5).stdout
        return "lanzador" in comm or "AutoFaceless" in comm
    except Exception:
        return False


def _esperar_libre(puerto, intentos):
    for _ in range(intentos):
        if puerto_libre(puerto):
            return True
        time.sleep(0.25)
    return False


def elegir_puerto():
    """Devuelve (puerto, ya_corriendo). ya_corriendo=True → solo abrir navegador."""
    if puerto_libre(PUERTO_PREFERIDO):
        return PUERTO_PREFERIDO, False

    info = salud(PUERTO_PREFERIDO)
    if (info and info.get("app") == "autofaceless"
            and info.get("version") == VERSION and info.get("ok")):
        return PUERTO_PREFERIDO, True   # instancia sana de esta misma versión

    # Instancia nuestra rota o de otra versión: cerrarla y quedarnos el puerto.
    pids = [p for p in _pids_en_puerto(PUERTO_PREFERIDO)
            if p != os.getpid() and _es_nuestro(p)]
    if pids:
        for pid in pids:
            try:
                os.kill(pid, 15)
            except Exception:
                pass
        if _esperar_libre(PUERTO_PREFERIDO, 20):
            return PUERTO_PREFERIDO, False
        for pid in pids:                       # no se cerró por las buenas
            try:
                os.kill(pid, 9)
            except Exception:
                pass
        if _esperar_libre(PUERTO_PREFERIDO, 12):
            return PUERTO_PREFERIDO, False

    # Otro programa usa el puerto: buscar uno libre cercano.
    for p in range(PUERTO_PREFERIDO + 1, PUERTO_PREFERIDO + 30):
        if puerto_libre(p):
            return p, False
    return PUERTO_PREFERIDO, True              # último recurso: abrir tal cual


def main():
    puerto, ya_corriendo = elegir_puerto()
    url = f"http://127.0.0.1:{puerto}"

    if ya_corriendo:
        webbrowser.open(url)
        return

    import app as servidor  # importa aquí: ya con sys.path listo

    def arrancar():
        servidor.app.run(host="127.0.0.1", port=puerto, threaded=True,
                         use_reloader=False)

    hilo = threading.Thread(target=arrancar, daemon=True)
    hilo.start()

    for _ in range(60):
        if not puerto_libre(puerto):
            break
        time.sleep(0.25)

    webbrowser.open(url)
    hilo.join()


if __name__ == "__main__":
    main()
