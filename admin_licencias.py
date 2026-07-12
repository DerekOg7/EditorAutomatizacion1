#!/usr/bin/env python3
"""Panel de licencias de AutoFaceless Studio (SOLO para el dueño).

Abre una página local para emitir y administrar licencias con un formulario —
sin terminal. Usa la LLAVE PRIVADA (LLAVE_PRIVADA_NO_COMPARTIR.hex o la variable
AFS_LLAVE_PRIVADA). NO lo distribuyas: quien tenga la privada puede emitir
licencias.

Uso:
    .venv/bin/python admin_licencias.py      (Mac, en la carpeta del proyecto)
    python admin_licencias.py                (Windows)
Se abre solo en http://127.0.0.1:5179
"""

import datetime as dt
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
import licencia  # noqa: E402

REGISTRO = RAIZ / "licencias_emitidas.json"
PUERTO = 5179
app = Flask(__name__)


def leer_privada():
    env = os.environ.get("AFS_LLAVE_PRIVADA", "").strip()
    if env:
        return env
    f = RAIZ / "LLAVE_PRIVADA_NO_COMPARTIR.hex"
    if f.exists():
        return f.read_text().strip()
    return ""


def leer_registro():
    if REGISTRO.exists():
        try:
            return json.loads(REGISTRO.read_text())
        except Exception:
            return []
    return []


def guardar_registro(lista):
    REGISTRO.write_text(json.dumps(lista, ensure_ascii=False, indent=2))


def _con_estado(entrada):
    r = licencia.verificar_codigo(entrada.get("codigo", ""))
    return {**entrada, "vencida": r["vencida"], "valida": r["valido"],
            "dias_restantes": r["dias_restantes"]}


@app.get("/")
def index():
    return PAGINA


@app.get("/api/licencias")
def listar():
    reg = leer_registro()
    tiene = bool(leer_privada())
    return jsonify({"tiene_llave": tiene,
                    "licencias": [_con_estado(e) for e in reversed(reg)]})


@app.post("/api/licencias")
def emitir():
    priv = leer_privada()
    if not priv:
        return jsonify({"error": "No encuentro la llave privada "
                        "(LLAVE_PRIVADA_NO_COMPARTIR.hex)."}), 400
    d = request.get_json(force=True) or {}
    cliente = (d.get("cliente") or "").strip()
    plan = (d.get("plan") or "beta").strip()
    if not cliente:
        return jsonify({"error": "Escribe el cliente (nombre o correo)."}), 400
    try:
        if d.get("exp"):
            vence = dt.date.fromisoformat(d["exp"]).isoformat()
        else:
            dias = int(d.get("dias", 30))
            vence = (dt.date.today() + dt.timedelta(days=dias)).isoformat()
    except Exception:
        return jsonify({"error": "Fecha o días inválidos."}), 400
    codigo = licencia.generar_codigo(cliente, vence, plan, priv)
    entrada = {"id": cliente, "plan": plan, "exp": vence,
               "creado": dt.date.today().isoformat(), "codigo": codigo}
    reg = leer_registro()
    reg.append(entrada)
    guardar_registro(reg)
    return jsonify(_con_estado(entrada))


@app.post("/api/verificar")
def verificar():
    codigo = (request.get_json(force=True) or {}).get("codigo", "")
    return jsonify(licencia.verificar_codigo(codigo))


PAGINA = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de licencias — AutoFaceless Studio</title>
<style>
 @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&display=swap');
 *{box-sizing:border-box;margin:0} body{font-family:'Roboto',system-ui,sans-serif;background:#f9f9f9;color:#0f0f0f;padding:28px}
 h1{font:900 26px 'Roboto';letter-spacing:-.5px} h1 span{color:#c4231b}
 .sub{color:#606060;font-size:14px;margin:4px 0 20px}
 .wrap{max-width:1080px;margin:0 auto;display:grid;grid-template-columns:340px 1fr;gap:20px;align-items:start}
 .card{background:#fff;border:1px solid #e5e5e5;border-radius:14px;padding:18px}
 .card h2{font:700 16px 'Roboto';margin-bottom:14px}
 label{display:block;font:500 11px 'Roboto';color:#606060;letter-spacing:.4px;margin:12px 0 4px}
 input,select{width:100%;font:inherit;border:1px solid #d9d9d9;border-radius:8px;padding:9px 10px;background:#fff}
 input:focus,select:focus{outline:none;border-color:#c4231b}
 button{font:500 14px 'Roboto';border:1px solid #d9d9d9;background:#fff;border-radius:20px;padding:9px 16px;cursor:pointer}
 button:hover{background:#f2f2f2}
 button.primario{background:#c4231b;color:#fff;border-color:#c4231b;box-shadow:0 4px 14px rgba(196,35,27,.3);width:100%;margin-top:16px;padding:12px}
 button.primario:hover{background:#a81d16}
 .codigo{margin-top:14px;background:#fdecea;border:1px solid #f3c9c4;border-radius:10px;padding:12px;font:12px ui-monospace,Menlo,monospace;word-break:break-all;display:none}
 .codigo.on{display:block}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th{text-align:left;color:#606060;font:600 11px 'Roboto';letter-spacing:.4px;padding:8px 10px;border-bottom:1px solid #e5e5e5}
 td{padding:9px 10px;border-bottom:1px solid #f0f0f0;vertical-align:middle}
 .badge{font:600 11px 'Roboto';border-radius:12px;padding:3px 9px}
 .ok{background:#e5f5ea;color:#1a8f3c} .no{background:#fdecea;color:#c4231b} .pronto{background:#fdf6e3;color:#b7791f}
 .mini{font:500 12px 'Roboto';border-radius:14px;padding:5px 10px}
 .aviso{background:#fdf6e3;border:1px solid #f0e0b0;color:#b7791f;border-radius:10px;padding:10px 12px;font-size:12.5px;margin-bottom:14px;display:none}
 .aviso.on{display:block}
 .vacio{color:#909090;font-size:13px;padding:14px 10px}
 .fila-dur{display:flex;gap:8px} .fila-dur>div{flex:1}
 code{background:#f2f2f2;border-radius:5px;padding:1px 5px}
</style></head><body>
<div style="max-width:1080px;margin:0 auto">
  <h1>Panel de <span>licencias</span></h1>
  <div class="sub">Emite y administra los códigos de AutoFaceless Studio. Herramienta local — no la compartas.</div>
</div>
<div class="wrap">
  <div class="card">
    <h2>Emitir una licencia</h2>
    <div class="aviso" id="aviso-llave">⚠ No encuentro la llave privada (<code>LLAVE_PRIVADA_NO_COMPARTIR.hex</code>). Sin ella no puedes emitir códigos.</div>
    <label>CLIENTE (nombre o correo)</label>
    <input id="cliente" placeholder="ej: juan@correo.com">
    <div class="fila-dur">
      <div>
        <label>VIGENCIA</label>
        <select id="dias" onchange="toggleFecha()">
          <option value="7">7 días</option>
          <option value="15">15 días</option>
          <option value="30" selected>30 días</option>
          <option value="60">60 días</option>
          <option value="90">90 días</option>
          <option value="180">180 días</option>
          <option value="365">1 año</option>
          <option value="__fecha__">Fecha exacta…</option>
        </select>
      </div>
      <div>
        <label>PLAN</label>
        <select id="plan"><option value="free">free (con marca de agua / 720p)</option><option>pro</option><option>beta</option><option>owner</option></select>
      </div>
    </div>
    <div id="zona-fecha" style="display:none"><label>VENCE EL</label><input type="date" id="exp"></div>
    <button class="primario" onclick="emitir()">Generar licencia</button>
    <div class="codigo" id="codigo-nuevo"></div>
    <div style="margin-top:20px;border-top:1px solid #eee;padding-top:14px">
      <h2 style="font-size:14px">Verificar un código</h2>
      <input id="ver-codigo" placeholder="pega un código para revisarlo" style="margin-top:8px">
      <button onclick="verificar()" style="margin-top:8px">Revisar</button>
      <div id="ver-res" style="font-size:13px;margin-top:8px"></div>
    </div>
  </div>

  <div class="card">
    <h2>Licencias emitidas (<span id="conteo">0</span>)</h2>
    <div id="tabla"></div>
  </div>
</div>
<script>
const $=id=>document.getElementById(id);
function toggleFecha(){ $('zona-fecha').style.display = $('dias').value==='__fecha__' ? '' : 'none'; }
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function copiar(t){ navigator.clipboard.writeText(t); }
function estadoBadge(l){
  if(!l.valida && !l.vencida) return '<span class="badge no">inválida</span>';
  if(l.vencida) return '<span class="badge no">vencida</span>';
  const d=l.dias_restantes;
  const cls = d<=14?'pronto':'ok';
  return `<span class="badge ${cls}">${d} días</span>`;
}
async function cargar(){
  const r = await (await fetch('/api/licencias')).json();
  $('aviso-llave').classList.toggle('on', !r.tiene_llave);
  const t=$('tabla'); $('conteo').textContent=r.licencias.length;
  if(!r.licencias.length){ t.innerHTML='<div class="vacio">Todavía no has emitido licencias.</div>'; return; }
  let h='<table><thead><tr><th>Cliente</th><th>Plan</th><th>Vence</th><th>Estado</th><th></th></tr></thead><tbody>';
  for(const l of r.licencias){
    h+=`<tr><td>${esc(l.id)}</td><td>${esc(l.plan)}</td><td>${l.exp}</td><td>${estadoBadge(l)}</td>
      <td><button class="mini" onclick='copiar(${JSON.stringify(l.codigo)})'>Copiar código</button></td></tr>`;
  }
  t.innerHTML=h+'</tbody></table>';
}
async function emitir(){
  const cliente=$('cliente').value.trim();
  if(!cliente){ alert('Escribe el cliente.'); return; }
  const body={cliente, plan:$('plan').value};
  if($('dias').value==='__fecha__'){ if(!$('exp').value){alert('Elige la fecha.');return;} body.exp=$('exp').value; }
  else body.dias=parseInt($('dias').value);
  const res=await fetch('/api/licencias',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await res.json();
  if(!res.ok){ alert(d.error||'Error'); return; }
  const box=$('codigo-nuevo');
  box.className='codigo on';
  box.innerHTML=`<b>Código para ${esc(d.id)}</b> (vence ${d.exp}):<br>${esc(d.codigo)}
    <br><button class="mini" style="margin-top:8px" onclick='copiar(${JSON.stringify(d.codigo)})'>Copiar</button>`;
  $('cliente').value='';
  cargar();
}
async function verificar(){
  const codigo=$('ver-codigo').value.trim();
  if(!codigo) return;
  const d=await (await fetch('/api/verificar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({codigo})})).json();
  const el=$('ver-res');
  if(d.valido) el.innerHTML=`<span class="badge ok">válida</span> ${esc(d.id)} · plan ${esc(d.plan)} · vence ${d.exp} (${d.dias_restantes} días)`;
  else if(d.vencida) el.innerHTML=`<span class="badge no">vencida</span> venció el ${d.exp}`;
  else el.innerHTML=`<span class="badge no">inválida</span> (${d.razon})`;
}
cargar();
</script></body></html>"""


def main():
    if not leer_privada():
        print("AVISO: no encontré LLAVE_PRIVADA_NO_COMPARTIR.hex — no podrás emitir.")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PUERTO}")).start()
    print(f"Panel de licencias en http://127.0.0.1:{PUERTO}  (Ctrl+C para salir)")
    app.run(host="127.0.0.1", port=PUERTO)


if __name__ == "__main__":
    main()
