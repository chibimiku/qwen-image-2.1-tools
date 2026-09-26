#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""专项：把裙子上的花纹改成贝壳（局部纹理替换，属于模型最弱的一类指令）。

三条对照，同一张输入图、同 seed、同 35 步，逐条与输入图对比：
  S0  基线（要求原样返回）—— 标定"整图重绘"的幅度
  S1  只要把裙上图案换成贝壳，其余不变
  S2  同上但强调"不要动构图/颜色/其他元素"（重复约束能不能提高执行率）
然后裁裙子区域再跑一次（更近的镜头 = 更高的局部像素密度），看是不是分辨率问题。

    python tools/run_tunnel.py dress_shell_test.py
"""
import base64
import io
import json
import os
import sys
import time

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C                                                    # noqa: E402

BASE = globals().get("BASE", "http://127.0.0.1:6006")
OUT = os.path.join(C.TEST_DATA, "case_shell")
C.ensure(OUT, C.REPORT)

STEPS = 35
SEED = 22
W, H = C.W, C.H
# 裙子区域（画布归一化，按输入图量出来的）
DRESS = (0.10, 0.28, 0.82, 0.68)

KEEP = ("Keep the same character, the same face and hairstyle, the same pose, the same boat, "
        "the same sea and lighting, and the same camera angle.")

CASES = [
    ("S0_baseline", "baseline",
     "Return the image unchanged: keep every detail exactly as it is, including the flower "
     "pattern on her dress. " + KEEP),
    ("S1_shells", "shell",
     "Change only the pattern printed on her dress: replace the blue and purple flowers with "
     "scallop seashells. Keep the dress shape, the white fabric, the colours and everything "
     "else in the image identical. " + KEEP),
    ("S2_shells_strict", "shell",
     "Edit ONLY the fabric print of her dress: its floral print must become a seashell print "
     "(scallop shells in the same blue and purple palette). Do not change the dress silhouette, "
     "the ruffles, the character, the pose, the boat or the water. " + KEEP),
    ("S3_shell_print_only", "shell",
     "The dress fabric pattern: seashells instead of flowers, same size, same spacing, same "
     "colours, same layout. Nothing else changes. " + KEEP),
]


def png_bytes(im):
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def gray(im):
    return np.asarray(im.convert("L").resize((W, H))).astype(np.float32) / 255.0


def mad(a, b, box=None):
    if box:
        x0, y0, x1, y1 = box
        a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    return float(np.abs(a - b).mean())


def hf(g, box):
    x0, y0, x1, y1 = box
    sub = (g[y0:y1, x0:x1] * 255).astype(np.uint8)
    return float(cv2.Laplacian(sub, cv2.CV_32F).var())


def edit(payload, prompt):
    t0 = time.time()
    r = requests.post(BASE + "/v1/images/edits",
                      data={"prompt": prompt, "num_inference_steps": str(STEPS), "seed": str(SEED)},
                      files=[("image", ("ref.png", payload, "image/png"))], timeout=3600)
    dt = time.time() - t0
    if r.status_code != 200:
        return None, dt, r.text[:200]
    return base64.b64decode(r.json()["data"][0]["b64_json"]), dt, None


# ---------------------------------------------------------------- readiness
for _ in range(120):
    try:
        if requests.get(BASE + "/health", timeout=10).json().get("loaded"):
            break
    except Exception:                                                  # noqa: BLE001
        pass
    time.sleep(10)
else:
    raise SystemExit("service not ready")
requests.post(BASE + "/v1/admin/empty_cache", timeout=60)

# ---------------------------------------------------------------- 整图
src_full = Image.open(os.path.join(OUT, "dress_input.jpg")).convert("RGB").resize((W, H), Image.LANCZOS)
full_payload = png_bytes(src_full)
full_g = gray(src_full)
dbox = C.px(DRESS)
print(f"dress box = {dbox}")

rows = []
base_g = None
for cid, kind, prompt in CASES:
    raw, dt, err = edit(full_payload, prompt)
    if raw is None:
        print(f"[{cid}] FAIL {err}")
        rows.append({"id": cid, "kind": kind, "prompt": prompt, "ok": False, "err": err})
        continue
    p = os.path.join(OUT, f"full_{cid}.png")
    open(p, "wb").write(raw)
    im = Image.open(io.BytesIO(raw)).convert("RGB").resize((W, H), Image.LANCZOS)
    g = gray(im)
    row = {"id": cid, "kind": kind, "prompt": prompt, "ok": True, "file": p,
           "elapsed": round(dt, 1), "scope": "full",
           "mad_all": round(mad(full_g, g), 4),
           "mad_dress": round(mad(full_g, g, dbox), 4),
           "hf_dress": round(hf(g, dbox), 1),
           "hf_input_dress": round(hf(full_g, dbox), 1)}
    if cid.startswith("S0"):
        base_g = g
    rows.append(row)
    print(f"[{cid:18s}] {dt:5.1f}s  mad_all={row['mad_all']:.4f}  mad_dress={row['mad_dress']:.4f}  "
          f"hf_dress={row['hf_dress']} (input {row['hf_input_dress']})")

# ---------------------------------------------------------------- 裁裙子近景
crop_box = (int(DRESS[0] * W), int(DRESS[1] * H), int(DRESS[2] * W), int(DRESS[3] * H))
crop = src_full.crop(crop_box)
crop = crop.resize((1024, max(64, int(crop.height * 1024 / crop.width))), Image.LANCZOS)
print(f"\ncrop for close-up: {crop.size}")
crop_payload = png_bytes(crop)
crop_g = gray(crop)
for cid, kind, prompt in CASES[:3]:
    raw, dt, err = edit(crop_payload, prompt)
    if raw is None:
        print(f"[crop {cid}] FAIL {err}")
        continue
    p = os.path.join(OUT, f"crop_{cid}.png")
    open(p, "wb").write(raw)
    im = Image.open(io.BytesIO(raw)).convert("RGB").resize(crop.size, Image.LANCZOS)
    g = gray(im)
    rows.append({"id": cid, "kind": kind, "prompt": prompt, "ok": True, "file": p,
                 "elapsed": round(dt, 1), "scope": "dress-crop",
                 "mad_all": round(mad(crop_g, g), 4),
                 "mad_dress": round(mad(crop_g, g), 4),
                 "hf_dress": round(float(cv2.Laplacian((g * 255).astype(np.uint8), cv2.CV_32F).var()), 1),
                 "hf_input_dress": round(float(cv2.Laplacian((crop_g * 255).astype(np.uint8), cv2.CV_32F).var()), 1)})
    print(f"[crop {cid:14s}] {dt:5.1f}s  mad={rows[-1]['mad_all']:.4f}  hf={rows[-1]['hf_dress']}")

json.dump(rows, open(os.path.join(OUT, "shell_results.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ---------------------------------------------------------------- 对比图
ims, labs = [src_full], ["0 input"]
for r in rows:
    if r.get("ok") and r["scope"] == "full":
        ims.append(Image.open(r["file"]).convert("RGB"))
        labs.append(r["id"])
cell = 420
sheet = Image.new("RGB", (cell * len(ims), cell + 22), (16, 16, 20))
d = ImageDraw.Draw(sheet)
for i, (im, lab) in enumerate(zip(ims, labs)):
    sheet.paste(im.resize((cell, cell), Image.LANCZOS), (i * cell, 0))
    d.text((i * cell + 5, cell + 5), lab, fill=(235, 235, 235))
sheet.save(os.path.join(OUT, "shell_full_sheet.png"))

# 裙子特写对比（原图裁切 vs 各输出的对应区域）
zooms = [src_full.crop(crop_box).resize((520, 520), Image.LANCZOS)]
zlabs = ["input dress"]
for r in rows:
    if r.get("ok") and r["scope"] == "full":
        im = Image.open(r["file"]).convert("RGB")
        zooms.append(im.crop(crop_box).resize((520, 520), Image.LANCZOS))
        zlabs.append(r["id"])
zs = Image.new("RGB", (520 * len(zooms), 545), (16, 16, 20))
d = ImageDraw.Draw(zs)
for i, (im, lab) in enumerate(zip(zooms, zlabs)):
    zs.paste(im, (i * 520, 0))
    d.text((i * 520 + 5, 528), lab, fill=(235, 235, 235))
zs.save(os.path.join(OUT, "shell_dress_zoom.png"))

# 近景结果
crops = [crop]
clabs = ["input crop"]
for r in rows:
    if r.get("ok") and r["scope"] == "dress-crop":
        crops.append(Image.open(r["file"]).convert("RGB"))
        clabs.append(r["id"] + " (crop)")
if len(crops) > 1:
    cw = 340
    cs = Image.new("RGB", (cw * len(crops), cw + 22), (16, 16, 20))
    d = ImageDraw.Draw(cs)
    for i, (im, lab) in enumerate(zip(crops, clabs)):
        cs.paste(im.resize((cw, cw), Image.LANCZOS), (i * cw, 0))
        d.text((i * cw + 5, cw + 5), lab, fill=(235, 235, 235))
    cs.save(os.path.join(OUT, "shell_crop_sheet.png"))

print("\nsheets ->", OUT)
