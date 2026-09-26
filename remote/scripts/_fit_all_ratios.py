#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证"选了 2:3 档位 + 参考图"不再被拒，而是同比例缩到能跑。

这是用户实际踩的路径：编辑模式 + 选官方 2:3（1696x2528 = 4.29MP）→ 以前 507。
修复后应该：200，输出为同比例的合理尺寸，并在 metadata.size_note 里说明缩过。
顺便把 7 个档位都过一遍，确认全部可用。
"""
import base64
import io
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
RATIOS = ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"]


def make_ref(path, w=2528, h=1696):
    im = Image.new("RGB", (w, h), (238, 240, 246))
    d = ImageDraw.Draw(im)
    d.ellipse([200, 200, 900, 900], fill=(200, 80, 100))
    d.rectangle([1200, 400, 2200, 1300], fill=(60, 90, 200))
    im.save(path, quality=70)
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


ref = make_ref("/tmp/fit_ref.jpg")
print(f"参考图 {Image.open(ref).size}\n")
print(f"{'档位':6} {'官方尺寸':>12} {'实际输出':>12} {'比例':>7}  {'耗时':>6}  说明")
print("-" * 96)

ok = 0
for r in RATIOS:
    body, ct = multipart(
        {"prompt": "把背景换成干净的浅灰色，保留主体", "num_inference_steps": "8",
         "aspect_ratio": r, "width": "1024", "height": "1024"},   # 故意带上默认宽高
        [("image", ref)])
    req = urllib.request.Request(API + "/v1/images/generations", data=body,
                                 headers={"Content-Type": ct, "Authorization": "Bearer " + KEY})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=600).read())
        it = d["data"][0]
        md = it.get("metadata") or {}
        reqd = md.get("size") or f"{it['width']}x{it['height']}"
        note = (md.get("size_note") or "（未缩，本身就够小或没超）")[:40]
        ra = it["width"] / it["height"]
        print(f"{r:6} {reqd:>12} {it['width']}x{it['height']:>7} {ra:>7.3f}  "
              f"{it['elapsed_s']:>5.1f}s  {note}")
        ok += 1
    except urllib.error.HTTPError as e:
        msg = e.read()[:200].decode("utf-8", "replace")
        print(f"{r:6} {'—':>12} HTTP {e.code}: {msg}")

print(f"\n{ok}/{len(RATIOS)} 个档位可用")
print("（以前 2:3 / 3:2 / 16:9 这些官方 2K 档位在编辑模式下全是 507）")
sys.exit(0 if ok == len(RATIOS) else 1)
