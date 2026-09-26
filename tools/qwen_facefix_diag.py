#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose FaceFixer alignment: draw the source box and the located box."""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service"))
from face_fix import FaceFixer, detect_face_box   # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-data")
OUT = os.path.join(ROOT, "fix", "diag")
os.makedirs(OUT, exist_ok=True)
W, H = 1088, 1600

src = Image.open(os.path.join(ROOT, "input_edit.jpg")).convert("RGB").resize((W, H), Image.LANCZOS)
box, det = detect_face_box(src)
print("source box:", box, "detected:", det)

for rel in ("chain/chainA_pose_expr_hands_cam/4_camera.png",
            "anchor/A_single_ref_1pose.png",
            "nsfw_L1_open_pose.png",
            "edit_crouching_2k.png"):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    ed = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    dbox, ddet = detect_face_box(ed, fallback=None)
    fx = FaceFixer(src, box=box, manual_face=det)
    (bx, by, bw, bh), scale, method = fx.locate(ed)
    print(f"{rel:52s} haar={dbox} scale={scale:.2f} method={method} -> box=({bx},{by},{bw},{bh})")

    vis = ed.copy()
    d = ImageDraw.Draw(vis)
    if dbox:
        d.rectangle(dbox, outline=(0, 255, 0), width=4)          # 编辑版里检出的脸
    d.rectangle([bx, by, bx + bw, by + bh], outline=(255, 60, 60), width=4)   # 实际贴回位置
    d.rectangle(box, outline=(60, 160, 255), width=3)            # 源图里的脸
    name = rel.replace("/", "_").replace(".png", "")
    vis.resize((W // 2, H // 2)).save(os.path.join(OUT, f"diag_{name}.png"))
print("diag images ->", OUT)
