#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直接打印 /v1/progress/{rid} 的原始响应，确认阶段字段到底有没有上报。"""
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.request
import uuid

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


# 单张请求（不走 /v1/progress 列表，直接按 rid 查）
rid = "req_probe" + uuid.uuid4().hex[:6]
print("request_id =", rid)
body, ct = multipart(
    {"prompt": "把背景变成干净的白色，保留主体",
     "num_inference_steps": "12", "output_format": "png", "request_id": rid},
    [("image", "/tmp/follow_ref.png")])

rows = []
stop = threading.Event()


def poll():
    while not stop.is_set():
        try:
            req = auth(urllib.request.Request(API + "/v1/progress/" + rid))
            with urllib.request.urlopen(req, timeout=5) as r:
                rows.append(json.loads(r.read()))
        except urllib.error.HTTPError as e:
            rows.append({"__http_error": e.code})
        except Exception as e:                                     # noqa: BLE001
            rows.append({"__err": str(e)})
        time.sleep(0.12)


th = threading.Thread(target=poll, daemon=True)
th.start()
t0 = time.time()
resp = urllib.request.urlopen(auth(urllib.request.Request(
    API + "/v1/images/generations", data=body, headers={"Content-Type": ct})), timeout=600)
raw = resp.read()
print(f"总耗时 {time.time()-t0:.1f}s  响应 {len(raw)/1e6:.2f} MB")
stop.set()
time.sleep(0.3)

# 打印状态变化轨迹
prev = None
print("\n状态轨迹（只打变化点）:")
for r in rows:
    key = (r.get("status"), r.get("phase"), r.get("pct"), r.get("steps_done"))
    if key != prev:
        print("   ", json.dumps(r, ensure_ascii=False))
        prev = key

# 收尾：最终一次
try:
    req = auth(urllib.request.Request(API + "/v1/progress/" + rid))
    with urllib.request.urlopen(req, timeout=5) as r:
        print("\n最终:", json.dumps(json.loads(r.read()), ensure_ascii=False))
except Exception as e:                                             # noqa: BLE001
    print("\n最终查询失败:", e)

statuses = {r.get("status") for r in rows}
print("\n出现过的 status:", sorted(s for s in statuses if s))
d = json.loads(raw)
print("timing:", json.dumps(d["data"][0].get("timing", {}), ensure_ascii=False))
