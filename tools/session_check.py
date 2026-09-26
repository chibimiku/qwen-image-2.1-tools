# -*- coding: utf-8 -*-
"""验证 Cookie 会话登录流程（无头浏览器 + 隧道）。

检查项：
  1. 页面不含 key 明文、JS 里没有 localStorage
  2. 未登录时 /v1/session 报未认证，页面弹登录框
  3. 提交错误 key → 401，不产生会话
  4. 提交正确 key → 拿到 Set-Cookie（HttpOnly / Secure / SameSite）
  5. 会话建立后：不带任何 header 也能出图（全靠 Cookie）
  6. DELETE /v1/session 后会话失效
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodl_ssh                                                     # noqa: E402
from keys import api_key                                              # noqa: E402

EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

DRIVER = r"""
<script>
(function(){
  function send(s){ try{ fetch('/probe',{method:'POST',body:String(s)}); }catch(e){} }
  const KEY = "__KEY__";
  setTimeout(async () => {
    // 1) 未登录状态
    let st = await (await fetch('/v1/session')).json();
    send('1 未登录 session=' + JSON.stringify(st) +
         ' 登录框可见=' + (getComputedStyle(document.getElementById('login')).display !== 'none'));
    send('1 localStorage 里的键=' + JSON.stringify(Object.keys(localStorage)));

    // 2) 错误 key
    let r = await fetch('/v1/session', {method:'POST', headers:{'Content-Type':'application/json'},
                                        body: JSON.stringify({key:'definitely-wrong'})});
    send('2 错误 key -> HTTP ' + r.status);

    // 3) 正确 key
    r = await fetch('/v1/session', {method:'POST', headers:{'Content-Type':'application/json'},
                                    body: JSON.stringify({key: KEY})});
    let body = await r.json().catch(()=>({}));
    send('3 正确 key -> HTTP ' + r.status + ' ' + JSON.stringify(body));
    send('3 document.cookie 可见部分=' + JSON.stringify(document.cookie));

    // 4) 不带任何鉴权头，靠 Cookie 出图
    const t0 = performance.now();
    r = await fetch('/v1/images/generations', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({prompt:'a tiny paper boat', width:512, height:512,
                              num_inference_steps:6, seed:3})});
    send('4 靠 Cookie 出图 -> HTTP ' + r.status + ' 耗时 ' +
         ((performance.now()-t0)/1000).toFixed(1) + 's');
    if (r.ok){ const d = await r.json(); send('4 图片尺寸=' + d.size); }

    // 5) 退出登录
    r = await fetch('/v1/session', {method:'DELETE'});
    send('5 退出 -> HTTP ' + r.status);
    st = await (await fetch('/v1/session')).json();
    send('5 退出后 session=' + JSON.stringify(st));
    r = await fetch('/v1/models');
    send('5 退出后 /v1/models -> HTTP ' + r.status + '（期望 401）');
    send('PROBE_DONE');
  }, 1200);
})();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    page = b""
    lines = []

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
        Handler.lines.append(self.rfile.read(n).decode("utf-8", "replace"))
        self.send_response(204)
        self.end_headers()


def main():
    k = api_key()
    if not k:
        raise SystemExit("tools/.qwenkey 里没有 key")

    autodl_ssh.load_env()
    conn = autodl_ssh.connect()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16070), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = conn.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    api = "http://127.0.0.1:16070"
    print("[fwd]", api)

    # 等服务把 33G 权重灌进显存（重启后约 20 秒）
    for i in range(90):
        try:
            with urllib.request.urlopen(api + "/health", timeout=8) as r:
                if json.loads(r.read()).get("loaded"):
                    print(f"[wait] 服务就绪（等了 {i*3}s）")
                    break
        except Exception:                                             # noqa: BLE001
            pass
        time.sleep(3)
    else:
        raise SystemExit("服务一直没就绪，先跑 serve.sh start")

    # ---- 先用 urllib 验一遍协议层（能直接看到 Set-Cookie 属性）
    print("\n=== 协议层（urllib，不带浏览器）===")
    def call(method, path, body=None, cookie=None):
        req = urllib.request.Request(api + path, method=method)
        if body is not None:
            req.data = json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    st, hdr, _ = call("GET", "/v1/session")
    print(f"  GET  /v1/session 未登录 -> {st}  {_.decode()[:80]}")
    st, hdr, _ = call("POST", "/v1/session", {"key": "wrong"})
    print(f"  POST /v1/session 错 key -> {st}")
    st, hdr, bd = call("POST", "/v1/session", {"key": k})
    sc = hdr.get("Set-Cookie", "")
    print(f"  POST /v1/session 正确 key -> {st}")
    print(f"    Set-Cookie: {sc}")
    for flag in ("HttpOnly", "SameSite", "Secure", "Max-Age"):
        print(f"      {flag}: {'有' if flag.lower() in sc.lower() else '没有'}")
    cookie = sc.split(";")[0] if sc else ""
    st, _, _ = call("GET", "/v1/models", cookie=cookie)
    print(f"  带 Cookie GET /v1/models -> {st}  （期望 200）")
    st, _, _ = call("GET", "/v1/models")
    print(f"  不带 Cookie GET /v1/models -> {st}  （期望 401）")

    # ---- 再验浏览器侧
    html = urllib.request.urlopen(api + "/", timeout=30).read().decode("utf-8")
    print("\n=== 浏览器侧 ===")
    print("  页面含 key 明文:", k in html, "（期望 False）")
    print("  页面含 localStorage:", "localStorage" in html, "（期望 False）")
    html = re.sub(r"const ROOT = location\.origin[^;]*;", f'const ROOT = "{api}";', html, count=1)
    html = html.replace("</body>", DRIVER.replace("__KEY__", k) + "</body>")
    Handler.page = html.encode("utf-8")

    srv = HTTPServer(("127.0.0.1", 16170), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    edge = next((p for p in EDGE if os.path.exists(p)), None)
    if not edge:
        print("  !! 没找到 Edge，跳过浏览器段")
    else:
        subprocess.Popen([edge, "--headless=new", "--disable-gpu", "http://127.0.0.1:16170/"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < 240:
            if any("PROBE_DONE" in l for l in Handler.lines):
                break
            time.sleep(2)
        print("  浏览器报告：")
        for l in Handler.lines:
            if l.strip():
                print("    ", l.strip()[:190])
        if not any("PROBE_DONE" in l for l in Handler.lines):
            print("    （超时：浏览器没跑完，可能是 Edge 启动慢或页面脚本报错）")

    srv.shutdown()
    fwd.shutdown()
    conn.close()


if __name__ == "__main__":
    main()
