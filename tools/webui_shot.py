# -*- coding: utf-8 -*-
"""给 WebUI 拍一张展示用截图。

headless 里 --window-size 常常不能真正撑开视口，导致 1100px 的媒体查询一直是单列，
左栏被挤到视野外。这里把远端的页面抓下来，注入一段样式钉死桌面布局，
再从一个临时 HTTP 服务上截图（同源，避免 iframe / file:// 的各种坑）。

    python tools/webui_shot.py [--port 16013] [--out reports/webui-preview.png]
"""
import argparse
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodl_ssh                                                     # noqa: E402

EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"]

PIN = """
<style id="shot-pin">
  html{width:1760px!important;overflow:visible!important}
  body{width:1760px!important;overflow:visible!important}
  .wrap{display:grid!important;grid-template-columns:360px 1fr!important;
        max-width:none!important;width:1760px!important;padding:18px 22px!important}
  .wrap>div:first-child{display:block!important;width:360px!important}
  header{position:static!important}
  .stage{min-height:520px!important}
</style>
"""

DIAG = """
<script>
(function(){
  const w = document.querySelector('.wrap');
  const left = w && w.children[0];
  const right = w && w.children[1];
  const cs = getComputedStyle(w);
  const rep = {
    innerWidth: innerWidth,
    wrapCols: cs.gridTemplateColumns,
    wrapWidth: w ? w.getBoundingClientRect().width : null,
    leftRect: left ? JSON.stringify(left.getBoundingClientRect()) : 'none',
    leftDisplay: left ? getComputedStyle(left).display : 'none',
    rightX: right ? Math.round(right.getBoundingClientRect().x) : null,
    leftChildren: left ? left.children.length : -1,
  };
  fetch('/diag', {method:'POST', body: JSON.stringify(rep)});
})();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    page = b""
    diag = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.page)))
        self.end_headers()
        self.wfile.write(self.page)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8", "replace")
        if self.path == "/diag":
            Handler.diag.append(body)
        self.send_response(204)
        self.end_headers()


def find_edge():
    for p in EDGE:
        if os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=16013)
    ap.add_argument("--http-port", type=int, default=16113)
    ap.add_argument("--out", default=os.path.join("reports", "webui-preview.png"))
    a = ap.parse_args()

    autodl_ssh.load_env()
    conn = autodl_ssh.connect()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", a.port), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = conn.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    print(f"[fwd] 127.0.0.1:{a.port} -> remote 6006")

    html = urllib.request.urlopen(f"http://127.0.0.1:{a.port}/", timeout=30).read().decode("utf-8")
    if "</head>" not in html:
        raise SystemExit("抓到的页面不像 UI")
    html = html.replace("</head>", PIN + "</head>")
    html = html.replace("</body>", DIAG + "</body>")
    # 关掉自动轮询，截图时不打无谓的请求
    html = html.replace("setInterval(probe, 15000);", "")
    Handler.page = html.encode("utf-8")
    print(f"[http] served {len(Handler.page)} bytes with desktop layout pinned")

    srv = HTTPServer(("127.0.0.1", a.http_port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    edge = find_edge()
    if not edge:
        raise SystemExit("no Edge/Chrome")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out = os.path.abspath(a.out)
    subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=1760,1180", "--virtual-time-budget=8000",
                    f"--screenshot={out}", f"http://127.0.0.1:{a.http_port}/"],
                   capture_output=True, timeout=180)
    time.sleep(1)
    print("saved:", out, os.path.getsize(out) if os.path.exists(out) else "MISSING")
    for d in Handler.diag[-2:]:
        print("[diag]", d)
    srv.shutdown()
    fwd.shutdown()
    conn.close()


if __name__ == "__main__":
    main()
