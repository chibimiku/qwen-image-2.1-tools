# -*- coding: utf-8 -*-
"""验证 auto 模式：页面不含 key、未输入 key 时被拦、预置 localStorage 后能正常出图。

    python tools\webui_auto_check.py
"""
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
from keys import api_key                                              # noqa: E402

EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

PROBE = r"""
<script>
(function(){
  function send(s){ try{ fetch('/probe',{method:'POST',body:String(s)}); }catch(e){} }
  window.__pre = function(k){ try{ localStorage.setItem('qwen_ui_key', k); return 'stored'; }
                              catch(e){ return 'store-failed:'+e; } };
  window.__snap = function(tag){
    const b = document.getElementById('run');
    send(tag + ' | busy=' + (function(){try{return eval('busy')}catch(e){return 'ERR'}})() +
         ' disabled=' + (b?b.disabled:'-') +
         ' conn=' + document.getElementById('conn').textContent +
         ' keyInput=' + (document.getElementById('apikey').value || '(空)') +
         ' keyMode=' + (typeof KEY_MODE!=='undefined'?KEY_MODE:'?'));
  };
  // 覆盖 prompt，避免无头浏览器里弹窗卡死；记录它被调用过
  var _p = window.prompt, called = 0;
  window.prompt = function(msg, def){ called++; window.__promptCalled = called;
                                      window.__promptMsg = msg; return window.__preKey || null; };
  setTimeout(() => { window.__snap('boot'); }, 1500);
})();
</script>
"""

AUTO = r"""
<script>
(function(){
  function say(s){ try{ fetch('/probe',{method:'POST',body:String(s)}); }catch(e){} }
  setTimeout(async () => {
    document.getElementById('prompt').value = 'a tiny paper boat on a puddle';
    document.getElementById('width').value = '512';
    document.getElementById('height').value = '512';
    document.getElementById('steps').value = '8';
    document.getElementById('stepv').textContent = '8';

    // 阶段 A：没有 key（localStorage 空、输入框空）→ 应被拦住，不发请求
    try { localStorage.removeItem('qwen_ui_key'); } catch(e){}
    document.getElementById('apikey').value = '';
    window.prompt = function(){ window.__promptCalled = (window.__promptCalled||0)+1; return null; };
    say('A 开始（无 key）');
    await run();
    say('A 结束 disabled=' + document.getElementById('run').disabled +
        ' 提示框调用次数=' + (window.__promptCalled||0) +
        ' 最后日志=' + document.getElementById('log').innerText.split('\n').filter(Boolean).slice(-1)[0]);

    // 阶段 B：预置 localStorage 里的 key → 应能出图
    try { localStorage.setItem('qwen_ui_key', '__KEY__'); } catch(e){}
    document.getElementById('apikey').value = '';
    window.prompt = function(){ window.__promptCalled = (window.__promptCalled||0)+1; return null; };
    say('B 开始（localStorage 里有 key）');
    await run();
    say('B 结束 disabled=' + document.getElementById('run').disabled +
        ' 有图=' + !!document.querySelector('#stage img') +
        ' 耗时=' + document.getElementById('k-time').textContent +
        ' 提示框调用次数=' + (window.__promptCalled||0));
    say('PROBE_DONE');
  }, 1500);
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
        raise SystemExit("没有 key（tools/.qwenkey）")

    autodl_ssh.load_env()
    conn = autodl_ssh.connect()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16060), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = conn.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    api = "http://127.0.0.1:16060"
    print("[fwd]", api)

    html = urllib.request.urlopen(api + "/", timeout=30).read().decode("utf-8")
    print("[check] 页面含 key 明文:", k in html)                     # 期望 False
    m = re.search(r'const KEY_MODE = "([^"]*)"', html)
    print("[check] 注入的 KEY_MODE:", m.group(1) if m else "?")      # 期望 auto
    html = re.sub(r"const ROOT = location\.origin[^;]*;", f'const ROOT = "{api}";', html, count=1)
    html = html.replace("</body>", PROBE.replace("__KEY__", k) + "</body>")
    # 把两段脚本合并成一个（PROBE 定义函数，AUTO 驱动）
    html = html.replace("</body>", AUTO.replace("__KEY__", k) + "</body>")
    Handler.page = html.encode("utf-8")

    srv = HTTPServer(("127.0.0.1", 16160), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    edge = next((p for p in EDGE if os.path.exists(p)), None)
    if not edge:
        raise SystemExit("no Edge")
    subprocess.Popen([edge, "--headless=new", "--disable-gpu", "http://127.0.0.1:16160/"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    t0 = time.time()
    while time.time() - t0 < 240:
        if any("PROBE_DONE" in l for l in Handler.lines):
            break
        time.sleep(2)

    print("\n=== 浏览器报告 ===")
    for l in Handler.lines:
        if l.strip():
            print("  ", l.strip()[:200])

    srv.shutdown()
    fwd.shutdown()
    conn.close()


if __name__ == "__main__":
    main()
