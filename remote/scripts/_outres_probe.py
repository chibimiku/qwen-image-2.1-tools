#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测清 output_resolution 到底管什么：和 width/height、参考图尺寸各是什么关系。

四个组合，比输出的 md5 与尺寸：
  A 只给宽高（不给 output_resolution）
  B 只给 output_resolution（不给宽高）→ 看跟随模式怎么走
  C 宽高 + output_resolution=1024
  D 宽高 + output_resolution=1280
如果 C 和 D 的输出不同，说明 output_resolution 即使有显式宽高也在起作用
（官方文档：它还负责把参考图缩放到某边长）。
"""
import base64
import hashlib
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/root/qwen-image-2.1/tools")
from PIL import Image, ImageDraw                                   # noqa: E402

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"
SEED = 999001


def make_ref(path, w=2048, h=2048):
    """高分辨率、细节丰富的参考图：缩放差异会体现在输出上"""
    im = Image.new("RGB", (w, h), (245, 245, 248))
    d = ImageDraw.Draw(im)
    for i in range(0, w, 64):                    # 细网格
        d.line([(i, 0), (i, h)], fill=(180, 190, 210), width=2)
        d.line([(0, i), (w, i)], fill=(180, 190, 210), width=2)
    d.ellipse([300, 300, 1100, 1100], fill=(200, 70, 90))
    d.rectangle([1200, 500, 1900, 1200], fill=(60, 90, 200))
    d.text((80, 60), "REF 2048", fill=(20, 20, 20))
    im.save(path)
    return path


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


def run(label, fields, ref):
    body, ct = multipart(fields, [("image", ref)])
    req = urllib.request.Request(API + "/v1/images/edits", data=body,
                                 headers={"Content-Type": ct, "Authorization": "Bearer " + KEY})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        print(f"  {label:28} HTTP {e.code}: {e.read()[:120].decode('utf-8', 'replace')}")
        return None
    it = d["data"][0]
    png = base64.b64decode(it["b64_json"])
    md5 = hashlib.md5(png).hexdigest()[:12]
    md = it.get("metadata") or {}
    print(f"  {label:28} {it['width']}x{it['height']:<6} md5={md5}  "
          f"outres={(md.get('output_resolution') or '—')}")
    return {"md5": md5, "w": it["width"], "h": it["height"]}


ref = make_ref("/tmp/outres_ref.png")
print(f"参考图 {Image.open(ref).size}（2048² 网格图，缩放差异会显现在输出上）")
print(f"固定 seed={SEED}，prompt 固定\n")

base = {"prompt": "只把背景换成纯白色，主体形状与位置完全不动。",
        "num_inference_steps": "8", "seed": str(SEED), "output_format": "png"}

print("=== 输出对比 ===")
A = run("A 只给宽高 512x512", dict(base, width="512", height="512"), ref)
B = run("B 只给 outres=1024", dict(base, output_resolution="1024"), ref)
C = run("C 宽高512 + outres=1024", dict(base, width="512", height="512",
                                        output_resolution="1024"), ref)
D = run("D 宽高512 + outres=1280", dict(base, width="512", height="512",
                                        output_resolution="1280"), ref)
E = run("E 只给 outres=1280", dict(base, output_resolution="1280"), ref)

print("\n=== 结论 ===")
if A and C:
    print(f"  A vs C（加不加 outres=1024）: {'相同' if A['md5'] == C['md5'] else '不同'}")
if C and D:
    print(f"  C vs D（outres 1024→1280）  : {'相同' if C['md5'] == D['md5'] else '不同'}")
if B and A:
    print(f"  A(512²) vs B(只给outres)    : B 输出 {B['w']}x{B['h']}")
if E and B:
    print(f"  B(outres1024) vs E(1280)    : {B['w']}x{B['h']} vs {E['w']}x{E['h']}")
