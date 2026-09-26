#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Measure which similarity metric can find the source face in an edited frame.

The source face patch contains background (books, blue wall) that changes between
poses, which drags the normalised cross-correlation down. Try a few metrics and a
masked variant over a wide search window.
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service"))
from face_fix import detect_face_box   # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-data")
W, H = 1088, 1600
src = Image.open(os.path.join(ROOT, "input_edit.jpg")).convert("RGB").resize((W, H), Image.LANCZOS)
BOX, det = detect_face_box(src)
x0, y0, x1, y1 = BOX
bw, bh = x1 - x0, y1 - y0
print("source box:", BOX)

# 只保留椭圆内的像素做模板（去掉背景），并给模板加边缘
patch = np.asarray(src.crop(BOX).convert("L"))
ell = np.zeros_like(patch)
cv2.ellipse(ell, (bw // 2, int(bh * 0.55)), (int(bw * 0.40), int(bh * 0.46)), 0, 0, 360, 255, -1)
cut = (patch * (ell > 0)).astype(np.uint8)
mask = ell


def search(img_gray):
    px, py = int(bw * 1.0), int(bh * 1.0)
    sx0, sy0 = max(0, x0 - px), max(0, y0 - py)
    sx1, sy1 = min(W, x1 + px), min(H, y1 + py)
    region = img_gray[sy0:sy1, sx0:sx1]
    out = []
    for scale in np.arange(0.55, 1.35, 0.05):
        tw, th = int(bw * scale), int(bh * scale)
        if tw < 16 or th < 16 or tw > region.shape[1] or th > region.shape[0]:
            continue
        t_cut = cv2.resize(cut, (tw, th), interpolation=cv2.INTER_AREA)
        t_mask = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_AREA)
        for name, method in (("ccoeff_normed", cv2.TM_CCOEFF_NORMED),
                             ("ccorr_normed", cv2.TM_CCORR_NORMED),
                             ("sqdiff_normed", cv2.TM_SQDIFF_NORMED)):
            res = cv2.matchTemplate(region, t_cut, method, mask=t_mask)
            res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
            _, mv, ml, _ = cv2.minMaxLoc(res)
            score = (1.0 - mv) if method == cv2.TM_SQDIFF_NORMED else mv
            out.append((score, name, float(scale), (sx0 + ml[0], sy0 + ml[1], tw, th)))
    out.sort(key=lambda r: -r[0])
    return out[:4]


for rel in ("edit_crouching_2k.png", "anchor/A_single_ref_1pose.png", "nsfw_L1_open_pose.png",
            "poseB_crouch_symmetric_22.png", "chain/chainA_pose_expr_hands_cam/4_camera.png",
            "chain/chainB_clean_keep_blocks/4_hands.png"):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    ed = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    g = np.asarray(ed.convert("L"))
    print(f"\n{rel}")
    for score, name, sc, box in search(g):
        print(f"   {score:.3f}  {name:16s} scale={sc:.2f}  box={box}")
