"""Licencias offline firmadas (Ed25519).

Cada licencia es un código autocontenido que lleva {id, vencimiento, plan} +
una firma. La app trae SOLO la llave pública y verifica el código sin internet:
comprueba la firma y la fecha de vencimiento. Los códigos los emites tú con la
llave privada (scripts/generar_licencia.py) — la privada NUNCA va en la app.

Formato del código:  AFS1.<payload_b64url>.<firma_b64url>
donde payload es JSON canónico: {"id": "...", "exp": "YYYY-MM-DD", "plan": "..."}
"""

import base64
import datetime as _dt
import json

import licencia_ed25519 as _ed

# Llave PÚBLICA del producto (la privada se guarda aparte y se usa para emitir).
LLAVE_PUBLICA_HEX = "8df2510279dd9fcb7f348e11872242b96f341c14405d6367c302d63f99dcbda1"

PREFIJO = "AFS1"


def _b64u(b):
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64u_dec(s):
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _payload_bytes(datos):
    """JSON canónico (claves ordenadas, compacto) — lo mismo al firmar y verificar."""
    return json.dumps(datos, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def generar_codigo(id_cliente, vence, plan="beta", llave_privada_hex=""):
    """Emite un código de licencia. `vence` = 'YYYY-MM-DD'. Requiere la privada."""
    seed = bytes.fromhex(llave_privada_hex.strip())
    datos = {"id": str(id_cliente), "exp": str(vence), "plan": str(plan)}
    pb = _payload_bytes(datos)
    firma = _ed.sign(seed, pb)
    return f"{PREFIJO}.{_b64u(pb)}.{_b64u(firma)}"


def verificar_codigo(codigo):
    """Verifica un código offline. Devuelve un dict con:
    {valido, razon, vencida, id, plan, exp, dias_restantes}."""
    res = {"valido": False, "razon": "formato", "vencida": False,
           "id": "", "plan": "", "exp": "", "dias_restantes": None}
    try:
        codigo = (codigo or "").strip().replace("\n", "").replace(" ", "")
        partes = codigo.split(".")
        if len(partes) != 3 or partes[0] != PREFIJO:
            return res
        pb = _b64u_dec(partes[1])
        firma = _b64u_dec(partes[2])
        pub = bytes.fromhex(LLAVE_PUBLICA_HEX)
        if not _ed.verify(pub, pb, firma):
            res["razon"] = "firma"
            return res
        datos = json.loads(pb.decode("utf-8"))
        res.update({"id": datos.get("id", ""), "plan": datos.get("plan", ""),
                    "exp": datos.get("exp", "")})
        try:
            venc = _dt.date.fromisoformat(datos["exp"])
        except Exception:
            res["razon"] = "fecha"
            return res
        hoy = _dt.date.today()
        dias = (venc - hoy).days
        res["dias_restantes"] = dias
        if dias < 0:
            res.update({"valido": False, "razon": "vencida", "vencida": True})
            return res
        res.update({"valido": True, "razon": "ok"})
        return res
    except Exception:
        return res


# ---- almacenamiento en la carpeta de datos del usuario ----

def _ruta_licencia():
    import editor
    return editor.DATOS / "licencia.txt"


def guardar_licencia(codigo):
    r = verificar_codigo(codigo)
    if not r["valido"]:
        return r
    _ruta_licencia().write_text((codigo or "").strip() + "\n")
    return r


def leer_licencia_guardada():
    ruta = _ruta_licencia()
    if ruta.exists():
        try:
            return ruta.read_text().strip()
        except Exception:
            return ""
    return ""


def estado():
    """Estado de la licencia instalada (para la app)."""
    codigo = leer_licencia_guardada()
    if not codigo:
        return {"activa": False, "razon": "sin_licencia"}
    r = verificar_codigo(codigo)
    return {"activa": bool(r["valido"]), "razon": r["razon"], "id": r["id"],
            "plan": r["plan"], "exp": r["exp"],
            "dias_restantes": r["dias_restantes"]}
