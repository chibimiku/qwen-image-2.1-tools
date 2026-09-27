# -*- coding: utf-8 -*-
"""体检：服务能不能正常出图。跑长度实验前后都用它当基线。

  python tools/_svc_sanity.py          # 一次短 prompt 出图 + 报告显存/健康
  python tools/_svc_sanity.py --restart # 先重启再体检
"""
from __future__ import annotations

import base64
import pathlib
import sys
import threading
import time

import paramiko
import requests

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import autodl_ssh  # noqa: E402

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
              password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)

    def sh(cmd, t=600):
        _, o, e = c.exec_command(cmd, timeout=t)
        return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()

    if "--restart" in sys.argv:
        print("[restart]", sh("bash /root/qwen-image-2.1/scripts/serve.sh restart 2>&1 | tail -2", 300))
        for _ in range(18):
            time.sleep(10)
            if sh('curl -s -m 5 -o /dev/null -w "%{http_code}" localhost:6006/health') == "200":
                break

    print("[gpu]", sh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader"))
    h = sh("curl -s -m 8 localhost:6006/health | head -c 200")
    print("[health]", h[:200])

    key = ""
    for line in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            key = line.strip()
            break

    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16058), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = c.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    ok = True
    try:
        t0 = time.time()
        r = requests.post("http://127.0.0.1:16058/v1/images/generations",
                          json={"prompt": "one red teapot on a wooden table",
                                "width": 512, "height": 512, "num_inference_steps": 8,
                                "output_format": "png", "seed": 7},
                          headers={"Authorization": "Bearer " + key}, timeout=(30, 600))
        dt = round(time.time() - t0, 2)
        if r.status_code == 200:
            img = base64.b64decode(r.json()["data"][0]["b64_json"])
            print(f"[gen] OK  512x512/8步  {dt}s  {len(img)} B")
        else:
            ok = False
            print(f"[gen] FAIL http={r.status_code} {dt}s  {r.text[:200]}")
            print("[log]", sh("tail -12 /root/qwen-image-2.1/logs/service.log")[-800:])
    finally:
        fwd.shutdown()
    # 注意顺序：先查显存再关 SSH 连接（关早了会 AttributeError: NoneType has no attribute open_session）
    print("[gpu after]", sh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader"))
    c.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
