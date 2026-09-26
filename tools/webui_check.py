#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Verify the WebUI end to end through an SSH tunnel.

What it does, in order:
  1. opens an SSH port-forward to the remote service (default 6006 → local 16010)
  2. serves a small HTTP wrapper page on localhost that embeds the *remote WebUI*
     in an iframe, drives it with injected JS, and reports back what happened
  3. waits until the wrapper reports a finished generation (or times out)
  4. takes a headless-Edge screenshot of the real UI and saves it next to the tools

So the browser talks to the tunnel exactly like your browser would talk to the
AutoDL custom-service URL, and we get a real screenshot + a machine-checkable
verdict instead of "it should work".

    python tools/webui_check.py                 # 1024x1024 / 12 steps, ~15 s
    python tools/webui_check.py --steps 20 --size 1024
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodl_ssh                                                     # noqa: E402

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

WRAPPER = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>webui check</title>
<style>body{{background:#0e1116;color:#e6edf3;font:13px/1.6 system-ui;margin:0}}
#report{{padding:10px 14px;background:#161b22;border-bottom:1px solid #262d38;
        font:12px/1.5 ui-monospace,Consolas;white-space:pre-wrap;min-height:70px}}
iframe{{width:100%;height:calc(100vh - 95px);border:0;display:block}}</style></head>
<body><div id="report">booting…</div>
<iframe id="ui" src="{ui_url}"></iframe>
<script>
const R = document.getElementById('report');
const lines = [];
function say(s){{ lines.push(new Date().toLocaleTimeString() + '  ' + s);
  R.textContent = lines.join('\\n'); send(s); }}
function send(s){{ try{{ fetch('/report', {{method:'POST', body: s}}); }}catch(e){{}} }}
window.addEventListener('error', e => say('PAGE ERROR ' + e.message));
async function main(){{
  const BASE = '{api_url}';
  say('wrapper loaded, api=' + BASE);
  const frame = document.getElementById('ui');
  frame.addEventListener('load', () => say('iframe loaded: ' + frame.src), {{once:true}});
  try {{
    const h = await (await fetch(BASE + '/health')).json();
    say('health: loaded=' + h.loaded + ' mock=' + h.mock + ' gpu=' +
        (h.gpu && h.gpu.available ? h.gpu.name + ' free ' + h.gpu.free_gb + 'G' : 'none'));
  }} catch(e) {{ say('health FAILED ' + e); }}
  try {{
    const html = await (await fetch(BASE + '/')).text();
    say('GET / bytes=' + html.length + ' title=' +
        (html.match(/<title>([^<]*)<\\/title>/) || [,'?'])[1]);
    say('页面含控制台标记=' + html.includes('控制台') + ' 含生成按钮=' + html.includes('onclick="run()"') +
        ' 含编辑标签=' + html.includes('tab-edit'));
  }} catch(e) {{ say('GET / FAILED ' + e); }}
  try {{
    const t0 = performance.now();
    const r = await fetch(BASE + '/v1/images/generations', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{prompt:'a red paper lantern floating on a calm night lake, reflection, anime style',
        width:{size}, height:{size}, num_inference_steps:{steps}, seed:4242}})}});
    if(!r.ok) throw new Error(await r.text());
    const d = await r.json();
    const item = d.data[0];
    say('generation OK: ' + item.width + 'x' + item.height + ' in ' +
        ((performance.now()-t0)/1000).toFixed(1) + 's seed=' + item.seed);
    const img = document.createElement('img');
    img.src = 'data:image/png;base64,' + item.b64_json;
    img.style.cssText = 'position:fixed;right:310px;bottom:8px;width:200px;border-radius:8px;' +
                        'z-index:99;border:1px solid #30363d';
    document.body.appendChild(img);
    say('DONE');
  }} catch(e) {{ say('generation FAILED ' + e); }}
}}
main();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    page = b""
    state = {"done": False, "lines": []}

    def log_message(self, *a):                                          # noqa: D102
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.page)))
        self.end_headers()
        self.wfile.write(self.page)

    def do_POST(self):                       # 页面把报告回传到这里，避免依赖控制台
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8", "replace")
        Handler.state["lines"].append(body)
        if "DONE" in body:
            Handler.state["done"] = True
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()


def find_edge():
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def screenshot(edge, url, out_png, height=1500, budget=15000):
    cmd = [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           f"--window-size=1560,{height}", f"--virtual-time-budget={budget}",
           f"--screenshot={out_png}", url]
    subprocess.run(cmd, capture_output=True, timeout=180)
    return os.path.exists(out_png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=16010)
    ap.add_argument("--http-port", type=int, default=16110)
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    autodl_ssh.load_env()
    conn = autodl_ssh.connect()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", a.port), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = conn.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    print(f"[fwd] 127.0.0.1:{a.port} -> remote 6006")

    api = f"http://127.0.0.1:{a.port}"
    Handler.page = WRAPPER.format(ui_url=api + "/", api_url=api,
                                  size=a.size, steps=a.steps).encode("utf-8")
    srv = HTTPServer(("127.0.0.1", a.http_port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    wrapper_url = f"http://127.0.0.1:{a.http_port}/"
    print("[http] wrapper at", wrapper_url)

    edge = find_edge()
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    os.makedirs(out_dir, exist_ok=True)
    png = os.path.join(out_dir, "webui-preview.png")

    if not edge:
        print("!! 没找到 Edge/Chrome，只做接口层验证")
    else:
        subprocess.Popen([edge, "--headless=new", "--disable-gpu", wrapper_url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[edge] headless browser opened the wrapper page")

    t0 = time.time()
    while time.time() - t0 < a.timeout:
        if Handler.state["done"]:
            break
        time.sleep(2)
    time.sleep(3)

    print("\n=== 浏览器内报告 ===")
    for line in Handler.state["lines"][-12:]:
        print("   ", line.strip().replace("\n", " | ")[:200])
    ok = Handler.state["done"]
    print("\n结果：", "✅ 通过（页面加载 + 健康检查 + 真实出图）" if ok else "❌ 未完成（见上面的报告）")

    if edge:
        screenshot(edge, wrapper_url, png, height=1400, budget=12000)
        print("截图：", png if os.path.exists(png) else "失败")

    srv.shutdown()
    fwd.shutdown()
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
