#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""同 seed / 同参考图 / 同尺寸，只改提示词写法，看人体崩坏率有没有变化。

背景：用户反馈"经常出现多条腿"。官方 PE 的 system prompt 给了一套改写方法论
（Attribute Disentanglement：只改点名的属性、其余保持；操作放句首；锚定图上可见信息）。
这里把它落成几个可对比的变体，用仓库已有的 anatomy_check 当自动判据。

用法（在实例上）：KEY=xxx python _prompt_ab.py
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
STEPS = 14
W, H = 1056, 1584          # 约 1.67MP，能装下两个人且不超编辑上限

# 原 prompt 的"核心指令"（按用户那条 578 字 prompt 的结构抽取，保留其写法特征）
BASE = (
    "<image1> is a three-view reference of the female character. Strictly reconstruct her face, "
    "hair, body proportions and anime art style based on the three-view, keep high consistency. "
    "Full body shot, show the entire female character from head to toe, wide camera angle, "
    "no cropping. She is being held up by an adult man, legs wrapped around his waist. "
    "Aggressive movement, large motion, climax expression. Pure anime style, clean lines, "
    "high detail, no photorealistic look."
)

# 官方 PE 方法论改写版：操作在句首 + 只声明该变的 + 其余明确"保持"
DISC = (
    "Edit <image1>: change only the pose and the scene. "
    "Pose: the female character is lifted and held by an adult man, her legs wrapped around his waist. "
    "Keep the female character's face, hairstyle, anime art style and body proportions exactly as in "
    "<image1>. Keep the man's anatomy simple and readable. "
    "Full body, both figures entirely inside the frame, wide angle, no cropping. "
    "Pure anime style, clean lines, high detail."
)

NEG = ("extra limbs, extra legs, extra arms, fused limbs, malformed hands, "
       "missing limbs, distorted anatomy, deformed body, bad proportions, "
       "watermark, text, photorealistic")

VARIANTS = [
    ("A 原写法（基线）",        {"prompt": BASE},                        None),
    ("B 原写法 + 负向提示词",    {"prompt": BASE, "negative_prompt": NEG}, 2.5),
    ("C 原写法 + 只加分辨率",    {"prompt": BASE},                        None, (1376, 2064)),
    ("D 官方 PE 式改写",        {"prompt": DISC},                        None),
    ("E 改写 + 负向提示词",      {"prompt": DISC, "negative_prompt": NEG}, 2.5),
]


def make_ref(path):
    """三视图参考图：三个不同姿态的同角色，信息量足"""
    im = Image.new("RGB", (2528, 1696), (248, 244, 238))
    d = ImageDraw.Draw(im)
    for k, (cx, label) in enumerate([(420, "FRONT"), (1264, "SIDE"), (2108, "BACK")]):
        d.ellipse([cx - 170, 300, cx + 170, 640], fill=(246, 224, 210))      # 头
        d.polygon([(cx, 300), (cx - 150, 200), (cx + 150, 200)], fill=(70, 60, 90))  # 头发
        d.rectangle([cx - 160, 660, cx + 160, 1080], fill=(210, 90, 110))     # 躯干
        d.rectangle([cx - 150, 1080, cx - 30, 1500], fill=(60, 70, 110))      # 左腿
        d.rectangle([cx + 30, 1080, cx + 150, 1500], fill=(60, 70, 110))      # 右腿
        d.line([(cx, 120), (cx, 190)], fill=(30, 30, 30), width=6)
        d.text((cx - 60, 1300), label, fill=(30, 30, 30))
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


def generate(fields, ref, size):
    f = {"num_inference_steps": str(STEPS), "seed": str(SEED), "output_format": "png",
         "width": str(size[0]), "height": str(size[1])}
    f.update({k: str(v) for k, v in fields.items()})
    body, ct = multipart(f, [("image", ref)])
    req = urllib.request.Request(API + "/v1/images/generations", data=body,
                                 headers={"Content-Type": ct, "Authorization": "Bearer " + KEY})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:150].decode('utf-8', 'replace')}"
    return d["data"][0], ""


def inspect(png_bytes):
    """用仓库的 anatomy_check 判一次（保守判据，只抓明显畸形）"""
    try:
        from anatomy_check import inspect_image
    except Exception as e:                                             # noqa: BLE001
        return {"passed": None, "reason": f"审图不可用: {e}"}
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return inspect_image(im, "")


ref = make_ref("/tmp/ab_ref.png")
print(f"参考图 {Image.open(ref).size}   输出 {W}x{H}   步数 {STEPS}   固定 seed {SEED}")
print(f"prompt 长度：基线 {len(BASE)} 字 / 改写 {len(DISC)} 字\n")
print(f"{'变体':22} {'尺寸':>11} {'耗时':>7} {'md5':>13}  审图")
print("-" * 96)

results = []
out = "/tmp/ab_out"
os.makedirs(out, exist_ok=True)
for name, fields, cfg, *rest in VARIANTS:
    size = rest[0] if rest else (W, H)
    if cfg:
        fields = dict(fields, guidance_scale=cfg)
    it, err = generate(fields, ref, size)
    if it is None:
        print(f"{name:22} {'':>11} {'':>7} {'':>13}  {err}")
        continue
    png = base64.b64decode(it["b64_json"])
    md5 = hashlib.md5(png).hexdigest()[:12]
    v = inspect(png)
    tag = ("✅ PASS" if v.get("passed") else "❌ FAIL")
    reason = (v.get("reason") or v.get("label") or "")[:40]
    print(f"{name:22} {it['width']}x{it['height']:<6} {it['elapsed_s']:>6.1f}s {md5:>13}  "
          f"{tag} {reason}")
    open(f"{out}/{name.split()[0]}.png", "wb").write(png)
    results.append({"name": name, "size": f"{it['width']}x{it['height']}",
                    "md5": md5, "passed": v.get("passed"), "reason": reason,
                    "elapsed": it["elapsed_s"]})

print()
n_pass = sum(1 for r in results if r["passed"])
print(f"通过 {n_pass}/{len(results)}")
json.dump(results, open(f"{out}/results.json", "w"), ensure_ascii=False, indent=2)
print(f"图与结果在 {out}/")
