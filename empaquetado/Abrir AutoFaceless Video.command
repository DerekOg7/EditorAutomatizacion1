#!/bin/bash
# Abre AutoFaceless Video quitando la marca de "cuarentena" que macOS pone a
# las apps descargadas de internet. Es necesario solo porque la beta todavía
# no está firmada con Apple. No modifica nada de tu Mac fuera de la app.
#
# Opens AutoFaceless Video removing the macOS "quarantine" flag that gets
# applied to apps downloaded from the internet. Only needed because this beta
# isn't signed with Apple yet. It changes nothing on your Mac beyond the app.

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/AutoFaceless Video.app"

echo ""
echo "  ── AutoFaceless Video ─────────────────────────────"
echo ""

if [ ! -d "$APP" ]; then
  echo "  ⚠  No encontré \"AutoFaceless Video.app\" junto a este archivo."
  echo "     Descomprime el .zip COMPLETO y deja este script en la misma"
  echo "     carpeta que la app, luego vuelve a abrirlo."
  echo ""
  echo "  ⚠  Couldn't find \"AutoFaceless Video.app\" next to this file."
  echo "     Unzip the WHOLE .zip and keep this script in the same folder"
  echo "     as the app, then open it again."
  echo ""
  read -n 1 -s -r -p "  Pulsa cualquier tecla para cerrar / Press any key to close."
  echo ""
  exit 1
fi

echo "  Preparando la app… / Preparing the app…"
xattr -cr "$APP"
open "$APP"

echo ""
echo "  ✓ Listo. Se está abriendo en tu navegador."
echo "    A partir de ahora ábrela con doble clic normal en la app."
echo ""
echo "  ✓ Done. It's opening in your browser."
echo "    From now on, open it with a normal double-click on the app."
echo ""
sleep 3
