# Guía: hacer el primer .exe de Windows y probarlo

No necesitas saber programar. La idea: subir el proyecto a **GitHub** una vez, y
que **GitHub arme el `.exe` por ti** en la nube. Luego lo descargas y lo pruebas
en tu PC Windows. Tú **no** compilas nada a mano.

Tiempo estimado: ~30–40 min la primera vez (la mayoría es esperar a que compile).

---

## PARTE A — Subir el proyecto a GitHub (solo una vez)

La forma más fácil, sin terminal, es con **GitHub Desktop** (una app con botones).

1. Crea una cuenta gratis en https://github.com (si no tienes).
2. Descarga e instala **GitHub Desktop**: https://desktop.github.com
3. Abre GitHub Desktop e inicia sesión con tu cuenta.
4. Menú **File → Add Local Repository…**
5. Elige la carpeta del proyecto:
   `/Users/derekogfilms/Documents/CLAUDE/EditorAutomatizacion`
   (ya es un repositorio git, así que la reconoce sola).
6. Arriba verás un botón **Publish repository**. Haz clic.
   - Nombre: `autofaceless-studio` (o el que quieras).
   - **Marca "Keep this code private"** (privado). ✅
   - Publica.

> ⚠️ La **llave privada de licencias** NO se sube (está en la lista de exclusión
> `.gitignore`). Así debe ser: esa llave se queda solo en tu Mac.

Listo: tu código ya está en GitHub. Esto solo se hace una vez. Cada vez que
cambies algo, en GitHub Desktop haces **Commit** + **Push** y ya.

---

## PARTE B — Que GitHub arme el `.exe`

1. En el navegador entra a tu repo:
   `https://github.com/TU-USUARIO/autofaceless-studio`
2. Arriba, pestaña **Actions**.
   - Si te sale un aviso de "Workflows aren't being run", haz clic en el botón
     verde para **habilitarlos** (I understand… → Enable).
3. En la lista de la izquierda, elige el flujo **build**.
4. A la derecha, botón **Run workflow** → deja la rama `main` → **Run workflow**.
5. Aparece un renglón "build" en amarillo. Haz clic para ver el progreso.
   - Verás dos trabajos: **windows** y **macos**. Espera al **windows**
     (tarda ~10–20 min; el punto se pone verde ✅ cuando termina).

> Nota: GitHub da minutos gratis al mes para esto (los de Windows cuentan un poco
> más). Para una beta con builds ocasionales, alcanza de sobra.

---

## PARTE C — Descargar y probar en tu PC Windows

1. Cuando el trabajo **windows** termine (✅), en la misma página del run, baja
   hasta **Artifacts** y descarga **AutoFaceless-Studio-windows** (es un `.zip`).
2. Pásalo a tu PC Windows (o ábrelo directo si entraste a GitHub desde Windows).
3. En Windows: clic derecho al zip → **Extraer todo**.
4. Entra a la carpeta **AutoFaceless Video** y abre **`AutoFaceless Video.exe`**.
5. Windows mostrará **SmartScreen** ("Windows protegió tu PC"):
   → **Más información** → **Ejecutar de todos modos**.
   (Es normal: el `.exe` no está firmado todavía, igual que el aviso del Mac.)
6. Se abre el navegador con la app. **Pega tu código de licencia** para activarla.
7. Prueba el flujo: crea una historia, transcribe, exporta un video.

La primera vez que transcribas, descargará el modelo de voz (unos minutos, una
sola vez).

---

## Si algo falla

- **El trabajo "windows" se pone rojo (❌):** haz clic en él, abre el paso que
  falló y cópiame el texto del error. Casi siempre es una dependencia que hay que
  ajustar en `requirements.txt` — se corrige rápido.
- **El antivirus marca el `.exe`:** es un falso positivo típico de apps
  empaquetadas con PyInstaller sin firmar. Puedes permitir la excepción; se
  resuelve del todo más adelante con un certificado de firma.
- **SmartScreen no te deja:** asegúrate de usar "Más información → Ejecutar de
  todos modos". Si tu Windows es muy restrictivo, clic derecho al `.exe` →
  Propiedades → marca **Desbloquear** → Aceptar.

---

## Resumen de por qué es así

- El `.exe` **no se puede crear desde la Mac** (la herramienta de empaquetado no
  compila para otro sistema). Por eso lo arma GitHub en una máquina Windows real.
- Alternativa: también puedes compilar en tu propia PC Windows con
  `pip install -r requirements.txt` y `pyinstaller empaquetar.spec`, pero el CI
  es más cómodo y no ensucia tu PC.
