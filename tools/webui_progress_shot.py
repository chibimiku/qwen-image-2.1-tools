# -*- coding: utf-8 -*-
"""抓一张"生成中"的 WebUI 截图，确认进度面板显示真实步数。

做法：抓页面 → 注入自动点击（用较慢的配置，保证有足够时间截图）→
立即起无头浏览器截图（virtual-time-budget 控制"拍在第几秒"）。

    python tools/webui_progress_shot.py --steps 40 --size 2048 --at 14000
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodl_ssh                                                     # noqa: E402
from keys import auth_header as _auth_header                              # noqa: E402

EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

AUTO = r"""
<script id="auto">
setTimeout(async () => {
  try {
    document.getElementById('prompt').value =
      'a lighthouse in a storm, huge waves, dramatic clouds, cinematic';
    document.getElementById('width').value = '__SIZE__';
    document.getElementById('height').value = '__SIZE__';
    document.getElementById('steps').value = '__STEPS__';
    document.getElementById('stepv').textContent = '__STEPS__';
    run();
  } catch(e){}
}, 400);
</script>
"""


class Handler(BaseHTTPRequestHandler):
    page = b""

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
        self.rfile.read(n)
        self.send_response(204)
        self.end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=16050)
    ap.add_argument("--http-port", type=int, default=16150)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--at", type=int, default=14000, help="拍在第几毫秒")
    ap.add_argument("--out", default=os.path.join("reports", "webui-progress.png"))
    a = ap.parse_args()

    autodl_ssh.load_env()
    conn = autodl_ssh.connect()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", a.port), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = conn.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{a.port}"
    print(f"[fwd] {api}")

    # 等模型加载完（preload 33G 权重约 2 分钟）
    for i in range(90):
        try:
            r = urllib.request.Request(api + "/health")
            h = json.loads(urllib.request.urlopen(r, timeout=10).read())
            if h.get("loaded") or h.get("mock"):
                print(f"[wait] ready after {i*5}s (loaded={h['loaded']})")
                break
        except Exception:                                             # noqa: BLE001
            pass
        time.sleep(5)
    else:
        raise SystemExit("service never became ready")

    html = urllib.request.urlopen(api + "/", timeout=30).read().decode("utf-8")
    html = re.sub(r"const ROOT = location\.origin[^;]*;", f'const ROOT = "{api}";', html, count=1)
    html = html.replace("</body>", AUTO.replace("__SIZE__", str(a.size))
                        .replace("__STEPS__", str(a.steps)) + "</body>")
    Handler.page = html.encode("utf-8")

    srv = HTTPServer(("127.0.0.1", a.http_port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[http] {a.http_port}, steps={a.steps} size={a.size}, 拍在 {a.at}ms")

    edge = next((p for p in EDGE if os.path.exists(p)), None)
    if not edge:
        raise SystemExit("no Edge")
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=1700,1150", f"--virtual-time-budget={a.at}",
                    f"--screenshot={out}", f"http://127.0.0.1:{a.http_port}/"],
                   capture_output=True, timeout=300)
    print("saved:", out, os.path.getsize(out) if os.path.exists(out) else "MISSING")

    # 顺带把服务端此刻的进度打出来对照
    try:
        r = urllib.request.Request(api + "/v1/progress", headers=_auth_header())
        import json
        data = json.loads(urllib.request.urlopen(r, timeout=15).read())["data"]
        for p in data[:2]:
            print(f"[server] {p['status']} {p['steps_done']}/{p['total']} {p['pct']}% "
                  f"每步={p['per_step_s']} ETA={p['eta_s']}")
    except Exception as exc:                                          # noqa: BLE001
        print("[server] progress read failed:", exc)

    srv.shutdown()
    fwd.shutdown()
    conn.close()


if __name__ == "__main__":
    main()
