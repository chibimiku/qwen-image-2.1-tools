#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Instruction-response matrix for Qwen-Image-2.1 image editing.

Question: which edit instructions does this model actually execute, and which ones
does it silently reduce to "redraw the whole frame"?

Method
------
For every instruction we send the SAME reference image with the SAME seed and
steps, then compare the output against a baseline that asked for *no change*
("keep everything identical"). Three signals per case:

  change_ratio   = MAD(case, input) / MAD(baseline, input)
                   ~0 means the model ignored the instruction; ~1 means it did
                   exactly as much as the empty instruction (i.e. nothing)
  region_delta   = MAD(case, baseline) measured inside the region the instruction
                   targets (face / torso / background / figure)
  moved_pct      = share of pixels whose |diff| > 0.06 * 255 inside that region

Verdicts: ignore (no measurable difference from the no-op baseline), weak
(target region barely moved), rewrite (everything moved, target region did not
move more than the rest ⇒ the model just repainted), ok (target region moved
clearly more than the rest).

Runs under: python tools\\autodl_ssh.py fwd tools\\matrix_test.py
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
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C                                                    # noqa: E402

# 由 run_tunnel.py 注入（SSH 端口转发地址）；直接用本地 ip 时回落到默认端口
BASE = globals().get("BASE", "http://127.0.0.1:6006")

OUT = os.path.join(C.TEST_DATA, "matrix")
SHEETS = os.path.join(OUT, "sheets")
C.ensure(OUT, SHEETS, C.REPORT)

STEPS = 35
SEED = 22
NSFW_OFF = ""   # 占位：本矩阵只测通用编辑指令

# ----------------------------------------------------------------- 指令矩阵
KEEP = ("Keep the same character, the same face and hairstyle, the same blue and white "
        "frilled dress, the same room, the same lighting and the same camera angle.")

MATRIX = [
    # id, 分组, 目标区域, 指令, 专属检测说明
    ("B0_baseline", "baseline", "none",
     "Return the image unchanged: keep every detail exactly the same. " + KEEP,
     "空指令基线，用来标定“模型什么都不做”时的重绘幅度"),
    ("P1_pose_stand", "pose", "figure",
     "Change only the pose: she stands up and takes one step forward, seen from the same camera. " + KEEP,
     "姿势是否真的变化"),
    ("P2_pose_arms_up", "pose", "figure",
     "Change only the pose: she raises both arms above her head. " + KEEP,
     "姿势是否真的变化"),
    ("C1_cloth_red", "clothing", "torso",
     "Change only the colour of her dress to deep red. " + KEEP,
     "torso 色相是否从蓝变红"),
    ("C2_cloth_remove_sleeves", "clothing", "torso",
     "Change only the design of her dress: remove the long lace sleeves so her arms are bare. " + KEEP,
     "袖子是否消失（torso 结构变化）"),
    ("B1_bg_beach", "background", "border",
     "Change only the background: replace the dark blue room with a bright tropical beach at noon. "
     "Keep the character exactly as she is. " + KEEP,
     "边框区域是否变亮/背景替换"),
    ("B2_bg_wall_white", "background", "border",
     "Change only the background wall colour to plain white. " + KEEP,
     "边框区域亮度是否上升"),
    ("O1_add_cat", "object", "figure",
     "Add a small grey cat sitting on the floor next to her. Keep everything else identical. " + KEEP,
     "是否出现新物体（局部高对比区域）"),
    ("O2_remove_globe", "object", "border",
     "Remove the large globe on the left side of the room. Keep everything else identical. " + KEEP,
     "左侧物体是否消失"),
    ("E1_expression_smile", "face", "face",
     "Change only her facial expression to a happy open smile with her eyes bright. " + KEEP,
     "face 区域是否出现结构变化（嘴/眼）"),
    ("E2_expression_sad", "face", "face",
     "Change only her facial expression to a sad expression with downturned mouth and teary eyes. " + KEEP,
     "与 E1 对比：两个表情是否做出区别"),
    ("H1_head_side", "head", "face",
     "Change only her head orientation: turn her head to her right so she looks sideways, "
     "keep the body pose. " + KEEP,
     "face 区域是否水平位移"),
    ("H2_hair_color_pink", "head", "face",
     "Change only her hair colour to bright pink. " + KEEP,
     "face 区域色相是否偏移到粉"),
    ("A1_style_anime_flat", "style", "border",
     "Change only the art style: render everything as flat cel-shaded anime line art with "
     "minimal shading. Keep the composition, character and colours. " + KEEP,
     "全图高频成分是否下降（平涂化）"),
    ("A2_style_photoreal", "style", "border",
     "Change only the art style: render it as a photorealistic photograph with real skin "
     "texture and camera bokeh, keeping the same composition. " + KEEP,
     "全图高频成分是否上升"),
    ("M1_multi_two", "multi", "figure",
     "Change only the pose: she lies down on her side on the floor. Also change her dress colour "
     "to green. " + KEEP,
     "多指令叠加：姿势与服装是否同时响应"),
]


# ----------------------------------------------------------------- 指标
def load_gray(im):
    return np.asarray(im.convert("L")).astype(np.float32) / 255.0


def mad(a, b, box=None):
    if box:
        x0, y0, x1, y1 = box
        a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    return float(np.abs(a - b).mean())


def moved_pct(a, b, box=None, thr=0.06):
    if box:
        x0, y0, x1, y1 = box
        a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    return float((np.abs(a - b) > thr).mean())


def ssim(a, b, box=None):
    if box:
        x0, y0, x1, y1 = box
        a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    ga = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5)                  # noqa: E731
    ma, mb = ga(a), ga(b)
    sa, sb = ga(a * a) - ma ** 2, ga(b * b) - mb ** 2
    sab = ga(a * b) - ma * mb
    return float((((2 * ma * mb + C1) * (2 * sab + C2)) /
                  ((ma ** 2 + mb ** 2 + C1) * (sa + sb + C2))).mean())


def mean_hue(rgb, box):
    x0, y0, x1, y1 = box
    sub = rgb[y0:y1, x0:x1]
    hsv = cv2.cvtColor(sub, cv2.COLOR_RGB2HSV)
    h = hsv[..., 0].astype(np.float32)
    s = hsv[..., 1].astype(np.float32)
    m = s > 40
    if m.sum() < 50:
        return None, float(s.mean())
    ang = h[m] * (2 * np.pi / 180.0)
    return float((np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) * 180 / np.pi) % 360), float(s[m].mean())


def high_freq_energy(gray):
    lap = cv2.Laplacian((gray * 255).astype(np.uint8), cv2.CV_32F)
    return float(lap.var())


# ----------------------------------------------------------------- 准备
for _ in range(120):
    try:
        h = requests.get(BASE + "/health", timeout=10).json()
        if h.get("loaded"):
            print(f"service ready · gpu free {h['gpu']['free_gb']} GiB · {h['gpu']['name']}")
            break
    except Exception:                                                  # noqa: BLE001
        pass
    time.sleep(10)
else:
    raise SystemExit("service not ready")
requests.post(BASE + "/v1/admin/empty_cache", timeout=60)

src = Image.open(C.INPUT_EDIT).convert("RGB").resize((C.W, C.H), Image.LANCZOS)
buf = io.BytesIO()
src.save(buf, format="PNG")
PAYLOAD = buf.getvalue()
SRC_G = load_gray(src)
SRC_RGB = np.asarray(src)
BOXES = {k: C.px(v) for k, v in C.REGIONS.items()}

results = []
baseline_g = baseline_rgb = None
t_start = time.time()

for cid, group, region, prompt, note in MATRIX:
    t0 = time.time()
    r = requests.post(BASE + "/v1/images/edits",
                      data={"prompt": prompt, "num_inference_steps": str(STEPS), "seed": str(SEED)},
                      files=[("image", ("ref.png", PAYLOAD, "image/png"))], timeout=3600)
    dt = time.time() - t0
    if r.status_code != 200:
        print(f"[{cid}] FAIL {r.status_code} {r.text[:140]}")
        results.append({"id": cid, "group": group, "region": region, "note": note,
                        "prompt": prompt, "ok": False, "error": r.text[:200]})
        continue
    raw = base64.b64decode(r.json()["data"][0]["b64_json"])
    p = os.path.join(OUT, f"{cid}.png")
    open(p, "wb").write(raw)
    im = Image.open(io.BytesIO(raw)).convert("RGB").resize((C.W, C.H), Image.LANCZOS)
    g = load_gray(im)
    rgb = np.asarray(im)

    box = BOXES.get(region)
    row = {"id": cid, "group": group, "region": region, "note": note,
           "prompt": prompt, "file": p, "elapsed": round(dt, 1), "ok": True,
           "mad_all": round(mad(SRC_G, g), 4),
           "ssim_all": round(ssim(SRC_G, g), 4),
           "hue_face": round(mean_hue(rgb, BOXES["face"])[0] or -1, 1),
           "hue_torso": round(mean_hue(rgb, BOXES["torso"])[0] or -1, 1),
           "sat_torso": round(mean_hue(rgb, BOXES["torso"])[1], 1),
           "hf_energy": round(high_freq_energy(g), 1),
           "luma_border": round(float(g[:120, :].mean()), 4)}

    if cid.startswith("B0"):
        baseline_g, baseline_rgb = g, rgb
        row.update({"verdict": "baseline", "target_delta": 0.0, "rest_delta": 0.0,
                    "change_ratio": 1.0, "moved_pct_region": 0.0})
    else:
        # 与基线的对比：目标区域 vs 其余区域
        tgt = mad(baseline_g, g, box) if box else mad(baseline_g, g)
        mask = np.ones_like(baseline_g, dtype=bool)
        if box:
            x0, y0, x1, y1 = box
            mask[y0:y1, x0:x1] = False
        rest = float(np.abs(baseline_g - g)[mask].mean())
        ratio = row["mad_all"] / max(1e-6, mad(SRC_G, baseline_g))
        moved = moved_pct(baseline_g, g, box) if box else moved_pct(baseline_g, g)
        if row["mad_all"] < 0.004:
            verdict = "ignore"
        elif tgt < rest * 0.85:
            verdict = "weak"
        elif tgt < rest * 1.15:
            verdict = "rewrite"
        else:
            verdict = "ok"
        row.update({"target_delta": round(tgt, 4), "rest_delta": round(rest, 4),
                    "change_ratio": round(ratio, 3), "moved_pct_region": round(moved, 4),
                    "verdict": verdict})
    print(f"[{cid:22s}] {dt:5.1f}s mad={row['mad_all']:.4f} tgt={row.get('target_delta')} "
          f"rest={row.get('rest_delta')} ratio={row.get('change_ratio')} -> {row.get('verdict')}")
    results.append(row)

print(f"\nmatrix done in {(time.time()-t_start)/60:.1f} min; "
      f"{sum(1 for r in results if r.get('ok'))}/{len(MATRIX)} ok")

# 基线重绘幅度（用于解释所有 ratio）
if baseline_g is not None:
    base_redraw = mad(SRC_G, baseline_g)
    print(f"baseline redraw MAD = {base_redraw:.4f} (模型“什么都不做”时的重绘幅度)")

json.dump(results, open(os.path.join(OUT, "matrix_results.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# 接触表：每行 4 张
cells, labels = [src], ["0 input"]
for r in results:
    if r.get("ok"):
        cells.append(Image.open(r["file"]).convert("RGB"))
        labels.append(r["id"])
cell = 300
cols = 4
rows = (len(cells) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cell, rows * (cell + 20)), (16, 16, 20))
from PIL import ImageDraw                                                   # noqa: E402
d = ImageDraw.Draw(sheet)
for i, (im, lab) in enumerate(zip(cells, labels)):
    rr, cc = divmod(i, cols)
    sheet.paste(im.resize((cell, cell), Image.LANCZOS), (cc * cell, rr * (cell + 20)))
    d.text((cc * cell + 4, rr * (cell + 20) + cell + 4), lab, fill=(230, 230, 230))
sheet.save(os.path.join(SHEETS, "matrix_contact_sheet.png"))
print("contact sheet ->", os.path.join(SHEETS, "matrix_contact_sheet.png"))
