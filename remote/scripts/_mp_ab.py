#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""只改分辨率，看人体崩坏率变不变。同 seed / 同参考图 / 同 prompt。

假设：模型是按 2K 原生训练的（README：natively supports 2K），
我们常跑 1.0~1.7MP，肢体细节的像素预算只有训练时的 1/4~1/2。
这个实验就是验证"分辨率是不是解剖崩坏的诱因之一"。
"""
import base64
import hashlib
import io
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/root/qwen-image-2.1")
sys.path.insert(0, "/root/qwen-image-2.1/service")
from PIL import Image, ImageDraw                                # noqa: E402

KEY = os.environ.get("KEY", "")
API = "http://127.0.0.1:6006"
SEED = 20260927
STEPS = 16

# 用最容易崩的写法：整场景重建 + 复杂姿态（对照实验里的 A 写法）
PROMPT = (
    "<image1> is a three-view reference of the female character. Strictly reconstruct her face, "
    "hair, body proportions and anime art style based on the three-view, keep high consistency. "
    "Full body shot, show the entire female character from head to toe, wide camera angle, "
    "no cropping. She is being lifted and held up by an adult man, her legs wrapped around his "
    "waist, dynamic action pose. Aggressive movement, large motion, dramatic expression. "
    "Pure anime style, clean lines, high detail."
)

# 全部保持 3:2（参考图比例），只变像素总数；32 对齐
SIZES = [
    ("~0.65MP", 992, 640),
    ("~1.0MP", 1248, 832),
    ("~1.4MP", 1376, 928),
    ("~1.9MP", 1664, 1120),     # 贴本机编辑上限
]


def make_ref(path):
    im = Image.new("RGB", (2528, 1696), (247, 245, 240))
    d = ImageDraw.Draw(im)
    for cx in (420, 1264, 2108):
        d.ellipse([cx - 160, 300, cx + 160, 620], fill=(247, 226, 212))
        d.polygon([(cx, 300), (cx - 150, 220), (cx + 150, 220)], fill=(238, 226, 170))
        d.rectangle([cx - 150, 640, cx + 150, 1040], fill=(70, 80, 110))
        d.rectangle([cx - 140, 1040, cx - 40, 1420], fill=(70, 80, 110))
        d.rectangle([cx + 40, 1040, cx + 140, 1420], fill=(70, 80, 110))
        d.ellipse([cx - 165, 1420, cx - 15, 1490], fill=(50, 55, 70))
        d.ellipse([cx + 15, 1420, cx + 165, 1490], fill=(50, 55, 70))
        d.line([(cx - 150, 700), (cx - 250, 980)], fill=(70, 80, 110), width=40)
        d.line([(cx + 150, 700), (cx + 250, 980)], fill=(70, 80, 110), width=40)
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


def gen(w, h):
    f = {"prompt": PROMPT, "num_inference_steps": str(STEPS), "seed": str(SEED),
         "output_format": "png", "width": str(w), "height": str(h)}
    body, ct = multipart(f, [("image", ref)])
    req = urllib.request.Request(API + "/v1/images/generations", data=body,
                                 headers={"Content-Type": ct, "Authorization": "Bearer " + KEY})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:130].decode('utf-8', 'replace')}"
    return d["data"][0], ""


def inspect(png):
    try:
        from anatomy_check import inspect_image
        return inspect_image(Image.open(io.BytesIO(png)).convert("RGB"), "")
    except Exception as e:                                             # noqa: BLE001
        return {"passed": None, "reason": str(e)[:60]}


ref = make_ref("/tmp/mp_ref.png")
print(f"参考图 {Image.open(ref).size}   同 seed={SEED} / {STEPS} 步 / 同 prompt")
print(f"{'像素档':>10} {'尺寸':>12} {'MP':>6} {'耗时':>7} {'md5':>13}  审图")
print("-" * 88)

out = "/tmp/mp_out"
os.makedirs(out, exist_ok=True)
res = []
for label, w, h in SIZES:
    it, err = gen(w, h)
    if it is None:
        print(f"{label:>10} {w}x{h:<7} {w*h/1e6:>6.2f} {'':>7} {'':>13}  {err}")
        continue
    png = base64.b64decode(it["b64_json"])
    md5 = hashlib.md5(png).hexdigest()[:12]
    v = inspect(png)
    tag = "✅" if v.get("passed") else "❌"
    print(f"{label:>10} {it['width']}x{it['height']:<7} {it['width']*it['height']/1e6:>6.2f} "
          f"{it['elapsed_s']:>6.1f}s {md5:>13}  {tag} {(v.get('reason') or '')[:30]}")
    open(f"{out}/{label}.png", "wb").write(png)
    res.append({"label": label, "size": f"{it['width']}x{it['height']}",
                "mp": round(it["width"] * it["height"] / 1e6, 2),
                "md5": md5, "passed": v.get("passed"), "reason": v.get("reason")})

json.dump(res, open(f"{out}/results.json", "w"), ensure_ascii=False, indent=2)
print(f"\n图在 {out}/")
