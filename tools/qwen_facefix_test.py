#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Face-paste compensation test: run every earlier edit output through FaceFixer
and measure how much of the identity comes back.

Outputs (D:\\workspace\\dsh-default\\tmp\\qwen_test\\fix\\):
  <name>_fixed_f014.png / _f025.png     补偿后
  <name>_strip.png                      原图 | 编辑版 | 补偿后 三段对比
  fix_metrics.json                      量化结果
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service"))
from face_fix import FaceFixer, detect_face_box   # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-data")
OUT = os.path.join(ROOT, "fix")
os.makedirs(OUT, exist_ok=True)
W, H = 1088, 1600
FACE_BOX = (int(W * 0.22), int(H * 0.03), int(W * 0.78), int(H * 0.30))

TARGETS = [
    ("chain/chainA_pose_expr_hands_cam/4_camera.png", "chainA_final"),
    ("chain/chainB_clean_keep_blocks/4_hands.png", "chainB_final"),
    ("anchor/A_single_ref_1pose.png", "anchorA_pose"),
    ("anchor/B_anchor_orig_1pose.png", "anchorB_pose"),
    ("anchor/C_anchor_res1280_1pose.png", "anchorC_res1280"),
    ("nsfw_L1_open_pose.png", "L1_open_pose"),
    ("poseB_crouch_symmetric_22.png", "poseB_seed22"),
    ("edit_crouching_2k.png", "edit_v2"),
]


def gray(im):
    return np.asarray(im.convert("L")).astype(np.float32) / 255.0


def gauss(x, k=11, s=1.5):
    return cv2.GaussianBlur(x, (k, k), s)


def ssim(a, b):
    a, b = a.astype(np.float64), b.astype(np.float64)
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    ma, mb = gauss(a), gauss(b)
    sa, sb = gauss(a * a) - ma ** 2, gauss(b * b) - mb ** 2
    sab = gauss(a * b) - ma * mb
    return float((((2 * ma * mb + C1) * (2 * sab + C2)) /
                  ((ma ** 2 + mb ** 2 + C1) * (sa + sb + C2))).mean())


def face_mad(a, b):
    x0, y0, x1, y1 = FACE_BOX
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


src = Image.open(os.path.join(ROOT, "input_edit.jpg")).convert("RGB").resize((W, H), Image.LANCZOS)
src_g = gray(src)
box, detected = detect_face_box(src)
print(f"face box {box}  haar_detected={detected}")

fx = FaceFixer(src, box=box, manual_face=detected)

rows = []
for rel, name in TARGETS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        print(f"skip (missing): {rel}")
        continue
    ed = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    ed_g = gray(ed)
    row = {"name": name, "source": rel,
           "before_face_mad": round(face_mad(src_g, ed_g), 4),
           "before_ssim": round(ssim(src_g, ed_g), 4)}
    thumbs = [src, ed]
    labels = ["0 原图", "1 编辑输出"]
    for tag, fe in (("f014", 0.14), ("f025", 0.25)):
        fixed, info = fx.paste(ed, feather=fe)
        fixed.save(os.path.join(OUT, f"{name}_fixed_{tag}.png"))
        fg = gray(fixed)
        row[f"after_face_mad_{tag}"] = round(face_mad(src_g, fg), 4)
        row[f"after_ssim_{tag}"] = round(ssim(src_g, fg), 4)
        row[f"match_{tag}"] = info.get("match_score")
        if tag == "f014":
            row["improve_face_mad"] = round(row["before_face_mad"] - row["after_face_mad_f014"], 4)
            thumbs.append(fixed)
            labels.append("2 补偿 feather=0.14")
        else:
            thumbs.append(fixed)
            labels.append("3 补偿 feather=0.25")
    # 三段/四段对比条
    cell = 360
    strip = Image.new("RGB", (cell * len(thumbs), cell + 20), (16, 16, 20))
    d = ImageDraw.Draw(strip)
    for i, (im, lab) in enumerate(zip(thumbs, labels)):
        strip.paste(im.resize((cell, cell), Image.LANCZOS), (i * cell, 0))
        d.text((i * cell + 5, cell + 4), lab, fill=(235, 235, 235))
    strip.save(os.path.join(OUT, f"{name}_strip.png"))
    print(f"[{name}] face_mad {row['before_face_mad']} -> {row['after_face_mad_f014']} "
          f"(feather .14) / {row['after_face_mad_f025']} (.25)   match={row['match_f014']}")
    rows.append(row)

json.dump(rows, open(os.path.join(OUT, "fix_metrics.json"), "w"), ensure_ascii=False, indent=1)
print("\nmean improvement (face MAD):",
      round(float(np.mean([r["improve_face_mad"] for r in rows])), 4))
