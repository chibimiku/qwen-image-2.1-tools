#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test a skin-region heuristic for locating the face in edited anime frames
(Haar is useless here, template matching is unreliable when the pose changed a lot)."""
import os

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-data")
W, H = 1088, 1600
SRC_BOX = (364, 303, 574, 530)


def skin_mask(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # 宽范围肤色（含 anime 偏冷/偏亮的肤色）
    m1 = cv2.inRange(hsv, (0, 30, 120), (25, 190, 255))
    m2 = cv2.inRange(hsv, (160, 20, 120), (180, 190, 255))
    m = cv2.bitwise_or(m1, m2)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    return m


def find_face_like(rgb: np.ndarray, src_box):
    m = skin_mask(rgb)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    sw, sh = src_box[2] - src_box[0], src_box[3] - src_box[1]
    cands = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < (sw * sh) * 0.15:
            continue
        if y > H * 0.65:                     # 脸不会在下半身
            continue
        ar = w / max(1, h)
        if not (0.45 <= ar <= 2.2):
            continue
        cands.append((area, x, y, w, h, cent[i]))
    cands.sort(key=lambda c: -c[0])
    return cands[:3], m


for rel in ("input_edit.jpg",
            "edit_crouching_2k.png",
            "anchor/A_single_ref_1pose.png",
            "nsfw_L1_open_pose.png",
            "chain/chainA_pose_expr_hands_cam/4_camera.png"):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    im = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    rgb = np.asarray(im)
    cands, m = find_face_like(rgb, SRC_BOX)
    print(f"\n{rel}")
    for area, x, y, w, h, c in cands:
        print(f"   area={area:7d} box=({x:4d},{y:4d},{w:4d},{h:4d}) ar={w/h:.2f} cent=({c[0]:.0f},{c[1]:.0f})")
    out = rgb.copy()
    cv2.rectangle(out, (SRC_BOX[0], SRC_BOX[1]), (SRC_BOX[2], SRC_BOX[3]), (60, 160, 255), 4)
    for area, x, y, w, h, c in cands:
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 4)
    Image.fromarray(out).resize((W // 2, H // 2)).save(
        os.path.join(ROOT, "fix", "skin_" + rel.replace("/", "_")))
print("\nsaved -> fix\\skin_*.png")
