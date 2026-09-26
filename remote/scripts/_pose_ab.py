#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""姿态复杂度对照：同 seed / 同参考图 / 同尺寸，只改提示词写法。

重点不是内容，而是**姿态复杂度**与**写法**哪个更容易让肢体崩掉。
参考图故意画成"紧身衣 + 四肢清晰"，这样腿一多一眼就能看出来；
prompt 只描述姿态，不涉及任何裸露内容。

对照的写法取自官方 PE-T2I/PE-I2I 的 system prompt（docs/upstream/prompt-rewriter-*.txt）：
  · Core Objective：整个场景从零构建 vs 只改点名的属性
  · Governing Principle（Attribute Disentanglement）：只改点名的、其余保持
  · 操作放句首（Write it as an instruction）
  · 锚定图上可见信息（Anchor on the image）
  · 不要重绘未被点名的内容（Say what stays, without repainting it）
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
SIZE = (1056, 1584)

# 姿态：一人被另一人托起、双腿绕腰 —— 就是多腿最常出现的形态
POSE = ("being lifted and held up by an adult man, her legs wrapped around his waist, "
        "dynamic action pose, both figures entirely inside the frame, full body, wide angle")

# A. 用户的写法：整场景从零描述 + 动作词堆叠
A_PROMPT = (
    "<image1> is a three-view reference of the female character. Strictly reconstruct her face, "
    "hair, body proportions and anime art style based on the three-view, keep high consistency. "
    f"Full body shot, show the entire female character from head to toe, wide camera angle, "
    f"no cropping. She is {POSE}. Aggressive movement, large motion, dramatic expression. "
    "Pure anime style, clean lines, high detail."
)

# B. 只加负向提示词（官方支持 CFG，用户从没用过）
NEG = ("extra limbs, extra legs, extra arms, extra hands, fused limbs, merged legs, "
       "malformed hands, missing limbs, distorted anatomy, deformed body, bad proportions, "
       "conjoined figures, watermark, text")

# C. 官方 PE 方法论改写：操作在句首 + 只声明该变的 + 明确"其余保持" + 降低动作幅度
C_PROMPT = (
    "Change only the pose in <image1>. "
    "The female character is being lifted and held by an adult man, her legs wrapped around "
    "his waist. Keep her face, hairstyle, anime art style and body proportions exactly as in <image1>. "
    "Both figures have simple, readable anatomy: each person has exactly two legs and two arms, "
    "and every limb is clearly attached to its own body. "
    "Full body, both figures entirely inside the frame, wide angle, no cropping. "
    "Pure anime style, clean lines, high detail."
)

# D. 降低姿态难度：改成静态、不交缠的构图（最容易成的写法）
D_PROMPT = (
    "Change only the pose in <image1>. "
    "The female character stands beside an adult man, both facing the camera, standing side by side. "
    "Keep her face, hairstyle, anime art style and body proportions exactly as in <image1>. "
    "Simple standing poses, arms relaxed at their sides, feet flat on the ground. "
    "Full body, both figures entirely inside the frame, wide angle, no cropping. "
    "Pure anime style, clean lines, high detail."
)

VARIANTS = [
    ("A 用户写法（基线）",     {"prompt": A_PROMPT}, None),
    ("B 用户写法+负向",        {"prompt": A_PROMPT, "negative_prompt": NEG}, 2.5),
    ("C PE式改写（强调肢体）",  {"prompt": C_PROMPT}, None),
    ("D PE式改写+简化姿态",    {"prompt": D_PROMPT}, None),
    ("E PE改写+负向+CFG",     {"prompt": C_PROMPT, "negative_prompt": NEG}, 2.5),
]


def make_ref(path):
    """紧身衣三视图：四肢清晰，腿一多一眼就能看出"""
    im = Image.new("RGB", (2528, 1696), (247, 245, 240))
    d = ImageDraw.Draw(im)
    for cx in (420, 1264, 2108):
        d.ellipse([cx - 160, 300, cx + 160, 620], fill=(247, 226, 212))
        d.polygon([(cx, 300), (cx - 150, 220), (cx + 150, 220)], fill=(238, 226, 170))
        d.rectangle([cx - 150, 640, cx + 150, 1040], fill=(70, 80, 110))     # 紧身上衣
        d.rectangle([cx - 140, 1040, cx - 40, 1420], fill=(70, 80, 110))     # 左腿（紧身）
        d.rectangle([cx + 40, 1040, cx + 140, 1420], fill=(70, 80, 110))     # 右腿
        d.ellipse([cx - 165, 1420, cx - 15, 1490], fill=(50, 55, 70))        # 左鞋
        d.ellipse([cx + 15, 1420, cx + 165, 1490], fill=(50, 55, 70))        # 右鞋
        d.line([(cx - 150, 700), (cx - 250, 980)], fill=(70, 80, 110), width=40)  # 左臂
        d.line([(cx + 150, 700), (cx + 250, 980)], fill=(70, 80, 110), width=40)  # 右臂
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


def generate(fields):
    f = {"num_inference_steps": str(STEPS), "seed": str(SEED), "output_format": "png",
         "width": str(SIZE[0]), "height": str(SIZE[1])}
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
    try:
        from anatomy_check import inspect_image
    except Exception as e:                                             # noqa: BLE001
        return {"passed": None, "reason": f"审图不可用: {e}"}
    return inspect_image(Image.open(io.BytesIO(png_bytes)).convert("RGB"), "")


ref = make_ref("/tmp/pose_ref.png")
print(f"参考图 {Image.open(ref).size}  输出 {SIZE[0]}x{SIZE[1]}  {STEPS} 步  seed={SEED}")
print(f"姿态：{POSE}\n")
print(f"{'变体':24} {'耗时':>7} {'md5':>13}  审图")
print("-" * 92)

out = "/tmp/pose_out"
os.makedirs(out, exist_ok=True)
res = []
for name, fields, cfg in VARIANTS:
    if cfg:
        fields = dict(fields, guidance_scale=cfg)
    it, err = generate(fields)
    if it is None:
        print(f"{name:24} {'':>7} {'':>13}  {err}")
        continue
    png = base64.b64decode(it["b64_json"])
    md5 = hashlib.md5(png).hexdigest()[:12]
    v = inspect(png)
    tag = "✅ PASS" if v.get("passed") else "❌ FAIL"
    print(f"{name:24} {it['elapsed_s']:>6.1f}s {md5:>13}  {tag} "
          f"{(v.get('reason') or v.get('label') or '')[:34]}")
    open(f"{out}/{name[0]}.png", "wb").write(png)
    res.append({"name": name, "md5": md5, "passed": v.get("passed"),
                "reason": v.get("reason"), "elapsed": it["elapsed_s"]})

json.dump(res, open(f"{out}/results.json", "w"), ensure_ascii=False, indent=2)
n = sum(1 for r in res if r["passed"])
print(f"\n通过 {n}/{len(res)}   图在 {out}/")
