#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证本轮修复：进度阶段上报 + 跟随参考图尺寸。

在实例上跑（服务在 127.0.0.1:6006）。不依赖外部库，只用标准库。
"""
import base64
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.request
import uuid

sys.path.insert(0, "/root/qwen-image-2.1/service")
KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"


def auth(req):
    if KEY:
        req.add_header("Authorization", "Bearer " + KEY)
    return req


def multipart(fields, files):
    b = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n').encode()
    for k, path in files:
        name = os.path.basename(path)
        ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                 f'Content-Type: {ct}\r\n\r\n').encode()
        body += open(path, "rb").read() + b"\r\n"
    body += f"--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def get_json(path):
    req = auth(urllib.request.Request(API + path))
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


OUT = "/root/autodl-tmp/follow_check"
os.makedirs(OUT, exist_ok=True)

# 造一张竖长参考图（比例 0.421，跟用户那张 539x1217 接近）
from PIL import Image, ImageDraw           # noqa: E402
im = Image.new("RGB", (512, 1216), (240, 242, 248))
d = ImageDraw.Draw(im)
d.ellipse([120, 300, 392, 572], fill=(200, 70, 90))
d.rectangle([100, 700, 412, 1000], fill=(60, 90, 200))
im.save("/tmp/follow_ref.png")
print("参考图 512x1216（比例 0.421）")

# ---------- 1. 跟随参考图：只观察进度阶段，不指定宽高 ----------
rid = "req_follow" + uuid.uuid4().hex[:6]
body, ct = multipart(
    {"prompt": "把背景变成干净的白色，保留主体",
     "num_inference_steps": "20", "output_format": "png", "request_id": rid},
    [("image", "/tmp/follow_ref.png")])

seen_status = []
stop = threading.Event()


def poll():
    while not stop.is_set():
        try:
            view = get_json("/v1/progress/" + rid)
            st = (view or {}).get("status")
            if st and (not seen_status or seen_status[-1] != st):
                seen_status.append(st)
                print(f"    [{time.strftime('%H:%M:%S')}] status={st} phase={view.get('phase')} "
                      f"pct={view.get('pct')}")
        except Exception:
            pass
        time.sleep(0.25)


th = threading.Thread(target=poll, daemon=True)
th.start()

req = auth(urllib.request.Request(
    API + "/v1/images/generations", data=body,
    headers={"Content-Type": ct}))
t0 = time.time()
raw = urllib.request.urlopen(req, timeout=900).read()
dt = time.time() - t0
stop.set()
time.sleep(0.4)

d = json.loads(raw)
it = d["data"][0]
tm = it.get("timing", {})
print(f"  输出 {it['width']}x{it['height']}  总 {dt:.1f}s")
print(f"  timing: decode_s={tm.get('decode_s')}  encode_s={tm.get('encode_s')}  "
      f"per_step_s={tm.get('per_step_s')}")
open(OUT + "/follow.png", "wb").write(base64.b64decode(it["b64_json"]))

ratio_in = 512 / 1216
ratio_out = it["width"] / it["height"]
print(f"  比例：参考图 {ratio_in:.3f} → 输出 {ratio_out:.3f}  "
      f"{'一致 ✅' if abs(ratio_in - ratio_out) < 0.01 else '不一致 ❌'}")
print(f"  进度阶段序列：{seen_status}")
ok_phase = ("decoding" in seen_status) or ("encoding" in seen_status)
print(f"  阶段上报：{'有 ✅' if ok_phase else '没有（服务端可能没更新）❌'}")

print("\n===== done =====")
