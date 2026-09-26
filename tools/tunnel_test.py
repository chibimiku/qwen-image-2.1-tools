# -*- coding: utf-8 -*-
"""验证本机 SSH 隧道能否访问远端服务（等价于你在自己电脑上执行 ssh -L）。

  1. 建立 127.0.0.1:16020 -> 远端 127.0.0.1:6006 的 SSH 本地转发
  2. 直接 HTTP 探测 /health、/、以及带 key 的 /v1/models
  3. 用无头浏览器打开隧道地址，确认 WebUI 渲染正常
"""
import os
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodl_ssh                                                     # noqa: E402
from keys import api_key as _api_key                                     # noqa: E402

PORT = 16020
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def get(url, hdrs=None, timeout=15):
    req = urllib.request.Request(url, headers=hdrs or {})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.getcode(), len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception as e:                                            # noqa: BLE001
        return type(e).__name__, 0


autodl_ssh.load_env()
print(f"实例：{autodl_ssh.CFG['host']}:{autodl_ssh.CFG['port']}")
conn = autodl_ssh.connect()
fwd = autodl_ssh.ForwardServer(("127.0.0.1", PORT), autodl_ssh.Handler)
fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
fwd.transport = conn.get_transport()
threading.Thread(target=fwd.serve_forever, daemon=True).start()
print(f"[fwd] 本机 127.0.0.1:{PORT} -> 远端 6006")
time.sleep(0.5)

base = f"http://127.0.0.1:{PORT}"
print("\n=== 隧道内的接口探测 ===")
_MASK = (_api_key()[:6] + "***") if _api_key() else "(未设置)"
for path, hdrs, label in [
    ("/health", None, "health（免鉴权）"),
    ("/", None, "WebUI 页面（免鉴权）"),
    ("/v1/models", None, "models 不带 key"),
    ("/v1/models", {"Authorization": "Bearer " + _api_key()}, "models 带 key"),
    ("/docs", None, "Swagger（用 header 带 key）"),
]:
    h = dict(hdrs or {})
    if label.startswith("Swagger"):
        h["Authorization"] = "Bearer " + _api_key()
    code, n = get(base + path, h)
    shown = path if "key=" not in path else path.split("key=")[0] + "key=" + _MASK
    print(f"  {label:24s} {shown:22s} -> HTTP {code}  {n} bytes")

# 真出一张图（512/8 步，几秒）
import json
try:
    req = urllib.request.Request(base + "/v1/images/generations", method="POST",
                                 data=json.dumps({"prompt": "a tiny paper boat in a puddle",
                                                  "width": 512, "height": 512,
                                                  "num_inference_steps": 8, "seed": 7}).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + _api_key()})
    t0 = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    print(f"\n  生成测试 -> OK {d['size']}  {time.time()-t0:.1f}s  "
          f"b64 {len(d['data'][0]['b64_json'])} 字节")
except Exception as exc:                                              # noqa: BLE001
    print("\n  生成测试失败：", exc)

print("\n=== 隧道地址上的 WebUI 渲染 ===")
png = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "reports", "webui-tunnel.png")
if os.path.exists(EDGE):
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=1700,1150", "--virtual-time-budget=12000",
                    f"--screenshot={png}", base + "/"], capture_output=True, timeout=120)
    print("  截图:", png if os.path.exists(png) else "失败")
else:
    print("  没找到 Edge，跳过截图")

fwd.shutdown()
conn.close()
print("\n[fwd] closed")
