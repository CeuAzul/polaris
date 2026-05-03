"""
Servidor HTTP simples para monitor remoto.

Roda numa thread separada. Serve uma pagina HTML que se atualiza
sozinha com os valores atuais da bancada via /data (JSON).

Util para a equipe acompanhar o ensaio pelo celular sem ficar
proximo a helice ligada.

Implementacao usa apenas a stdlib (http.server) para nao adicionar
dependencias extras.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


HTML = """<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bancada - Monitor</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; background: #0f1115; color: #e7e9ec; }
  .header { padding: 16px; background: #1a1d24; border-bottom: 2px solid #2a2f3a; }
  .header h1 { margin: 0; font-size: 18px; color: #6db3ff; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 12px; }
  .card { background: #1a1d24; border-radius: 12px; padding: 18px; }
  .card .label { font-size: 12px; color: #8a93a4; text-transform: uppercase; letter-spacing: 1px; }
  .card .val { font-size: 32px; font-weight: 700; margin-top: 6px; color: #e7e9ec; }
  .card .unit { font-size: 16px; color: #8a93a4; margin-left: 4px; }
  .empuxo .val { color: #6db3ff; }
  .torque .val { color: #6dffaf; }
  .rpm .val    { color: #ffd66d; }
  .pmec .val   { color: #ff8a6d; }
  .badge { display:inline-block; padding:4px 10px; border-radius:8px; font-size:12px; font-weight:600; }
  .badge.estavel { background:#1f4d2a; color:#7be39a; }
  .badge.instavel { background:#5a3d1a; color:#ffb677; }
  .badge.off { background:#3a2a2a; color:#ff7f7f; }
  .footer { text-align:center; padding:10px; font-size:11px; color:#5a6478; }
</style></head>
<body>
<div class="header">
  <h1>Bancada de Empuxo - Monitor Remoto</h1>
  <div id="status" class="badge off" style="margin-top:8px">aguardando dados...</div>
</div>
<div class="grid">
  <div class="card empuxo"><div class="label">Empuxo</div>
    <div><span class="val" id="emp">--</span><span class="unit">g</span></div>
    <div style="color:#8a93a4;font-size:14px;margin-top:4px"><span id="empN">--</span> N</div>
  </div>
  <div class="card torque"><div class="label">Torque</div>
    <div><span class="val" id="tor">--</span><span class="unit">N&middot;m</span></div>
  </div>
  <div class="card rpm"><div class="label">RPM</div>
    <div><span class="val" id="rpm">--</span></div>
  </div>
  <div class="card pmec"><div class="label">P. mecanica</div>
    <div><span class="val" id="pm">--</span><span class="unit">W</span></div>
    <div style="color:#8a93a4;font-size:14px;margin-top:4px">T/P: <span id="tp">--</span> g/W</div>
  </div>
</div>
<div class="footer">atualiza a cada 500ms</div>
<script>
async function tick() {
  try {
    const r = await fetch('/data');
    const d = await r.json();
    document.getElementById('emp').textContent = d.empuxo_g.toFixed(1);
    document.getElementById('empN').textContent = d.empuxo_N.toFixed(2);
    document.getElementById('tor').textContent = d.torque_Nm.toFixed(4);
    document.getElementById('rpm').textContent = Math.round(d.rpm);
    document.getElementById('pm').textContent = d.p_mec_W.toFixed(0);
    document.getElementById('tp').textContent = d.T_por_P.toFixed(2);
    const s = document.getElementById('status');
    if (d.estavel) { s.className = 'badge estavel'; s.textContent = 'REGIME ESTAVEL  sigma=' + d.desvio_g.toFixed(1) + 'g'; }
    else { s.className = 'badge instavel'; s.textContent = 'instavel  sigma=' + d.desvio_g.toFixed(1) + 'g'; }
  } catch(e) {
    document.getElementById('status').textContent = 'sem conexao';
  }
}
setInterval(tick, 500);
tick();
</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "BancadaMonitor/1.0"
    sys_version = ""
    dados_compartilhados = {}

    def log_message(self, format, *args):
        return  # silencia logs HTTP

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/data":
            body = json.dumps(self.dados_compartilhados).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class RemoteServer:
    """Wrapper para o servidor HTTP, usado da GUI."""

    def __init__(self, port=8765):
        self.port = port
        self.thread = None
        self.httpd = None
        self.dados = {
            "empuxo_g": 0.0, "empuxo_N": 0.0, "torque_Nm": 0.0,
            "rpm": 0.0, "p_mec_W": 0.0, "T_por_P": 0.0,
            "estavel": False, "desvio_g": 0.0,
        }

    def start(self):
        if self.httpd:
            return
        # binda em 0.0.0.0 para celular conseguir acessar via IP local
        _Handler.dados_compartilhados = self.dados
        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            self.thread = None

    def atualizar(self, **kwargs):
        for k, v in kwargs.items():
            if k in self.dados:
                self.dados[k] = v
        # mantem a referencia compartilhada
        _Handler.dados_compartilhados = self.dados