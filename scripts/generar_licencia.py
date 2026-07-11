#!/usr/bin/env python3
"""Emite códigos de licencia para AutoFaceless Studio (para uso del dueño).

La llave privada se lee de LLAVE_PRIVADA_NO_COMPARTIR.hex (en la raíz del
proyecto) o de la variable de entorno AFS_LLAVE_PRIVADA. NUNCA la compartas ni
la subas a git.

Ejemplos:
  python scripts/generar_licencia.py --id cliente@correo.com --dias 30
  python scripts/generar_licencia.py --id beta-tester-01 --exp 2026-12-31 --plan beta
"""

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import licencia  # noqa: E402


def leer_privada():
    env = os.environ.get("AFS_LLAVE_PRIVADA", "").strip()
    if env:
        return env
    f = RAIZ / "LLAVE_PRIVADA_NO_COMPARTIR.hex"
    if f.exists():
        return f.read_text().strip()
    sys.exit("No encuentro la llave privada. Ponla en "
             "LLAVE_PRIVADA_NO_COMPARTIR.hex o en la variable AFS_LLAVE_PRIVADA.")


def main():
    ap = argparse.ArgumentParser(description="Emite un código de licencia.")
    ap.add_argument("--id", required=True, help="identificador del cliente (correo o nombre)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dias", type=int, help="días de validez desde hoy")
    g.add_argument("--exp", help="fecha de vencimiento AAAA-MM-DD")
    ap.add_argument("--plan", default="beta", help="plan (por defecto: beta)")
    args = ap.parse_args()

    if args.dias is not None:
        vence = (dt.date.today() + dt.timedelta(days=args.dias)).isoformat()
    else:
        vence = dt.date.fromisoformat(args.exp).isoformat()

    codigo = licencia.generar_codigo(args.id, vence, args.plan, leer_privada())
    print(f"\nCliente : {args.id}\nPlan    : {args.plan}\nVence   : {vence}\n")
    print("CÓDIGO DE LICENCIA (cópialo al cliente):\n")
    print(codigo)
    print()
    # comprobación de sanidad
    chk = licencia.verificar_codigo(codigo)
    assert chk["valido"], "el código recién emitido no verifica (revisa la llave)"


if __name__ == "__main__":
    main()
