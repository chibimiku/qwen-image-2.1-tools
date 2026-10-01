# -*- coding: utf-8 -*-
"""查清两件事：响应格式（JSON+base64）与宽高被服务端改成什么。

  python tools/_svc_response_shape.py

1. 打印一次真实响应的键结构（含 data[0] 里的字段）
2. 逐个试不同宽高，看服务端最终给什么尺寸 —— 用来确认"能要到的最宽 16:9"是多少
"""
from __future__ import annotations

import json
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
KEY = [l.strip() for l in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines()
       if l.strip() and not l.startswith("#")][0]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
          password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16067), autodl_ssh.Handler)
fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
fwd.transport = c.get_transport()
threading.Thread(target=fwd.serve_forever, daemon=True).start()
time.sleep(0.4)
base = "http://127.0.0.1:16067"
hdr = {"Authorization": "Bearer " + KEY}

print("=== 1. 响应结构（带参考图走 multipart）===")
REF = TOOLS.parent / "exp" / "galgame-cg-20260928" / "refs"
# 注意：带图的请求必须走 multipart（files=）。
# 用 data= 发出去是 x-www-form-urlencoded，服务端在 _parse_gen_request 里会去
# request.json() 解析、直接 500 JSONDecodeError —— 这是本服务的一个协议约束。
r = requests.post(
    base + "/v1/images/generations", headers=hdr,
    data={"prompt": "a red teapot on a wooden table", "width": "1600", "height": "896",
          "num_inference_steps": "8", "seed": "42"},
    files=[("image", ("char.png", open(REF / "char.png", "rb"), "image/png"))],
    timeout=1800)
print("HTTP", r.status_code, "| content-type:", r.headers.get("content-type"))
if r.status_code != 200:
    print("body 前 400 字:", r.content[:400].decode("utf-8", "replace"))
    fwd.shutdown()
    c.close()
    raise SystemExit(1)
d = r.json()
print("顶层键:", sorted(d))
meta = {k: v for k, v in d.items() if k not in ("data", "images")}
print("非图像字段:", json.dumps(meta, ensure_ascii=False)[:500])
for k in ("data", "images"):
    if k not in d:
        continue
    item = d[k][0]
    print(f"\n{k}[0] 的键: {sorted(item)}")
    for kk, vv in item.items():
        if isinstance(vv, str) and len(vv) > 60:
            print(f"   {kk}: <{len(vv)} 字符，前缀 {vv[:32]!r}>")
        else:
            print(f"   {kk}: {vv}")

print("\n=== 2. 宽度上限（纯文本 JSON，4 步只看尺寸）===")
for w, h in ((1536, 864), (1600, 896), (1792, 1008), (1920, 1104), (2048, 1152),
             (2560, 1440), (2752, 1536), (1920, 1280), (2048, 1248)):
    try:
        rr = requests.post(base + "/v1/images/generations", headers=hdr,
                           json={"prompt": "a teapot", "width": w, "height": h,
                                 "num_inference_steps": 4, "seed": 1}, timeout=1800)
        dd = rr.json()
        got = dd.get("size")
        mark = "同请求" if got == f"{w}x{h}" else "已改"
        print(f"   请求 {w:>5}x{h:<5} -> HTTP {rr.status_code}  实际 {got:<12} {mark}")
    except Exception as exc:                                            # noqa: BLE001
        print(f"   请求 {w:>5}x{h:<5} -> 异常 {type(exc).__name__}")

fwd.shutdown()
c.close()
