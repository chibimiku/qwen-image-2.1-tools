#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sanity check: after paste(), the face pixels must equal the source face pixels."""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service"))
from face_fix import FaceFixer, detect_face_box   # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-data")
W, H = 1088, 1600
src = Image.open(os.path.join(ROOT, "input_edit.jpg")).convert("RGB").resize((W, H), Image.LANCZOS)
box, det = detect_face_box(src)
fx = FaceFixer(src, box=box, manual_face=det)
print("source box:", box)

for rel in ("edit_crouching_2k.png", "anchor/A_single_ref_1pose.png", "nsfw_L1_open_pose.png"):
    p = os.path.join(ROOT, rel)
    ed = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    out, info = fx.paste(ed, feather=0.10)
    print(f"\n{rel}\n  info={info}")
    sa = np.asarray(src).astype(int)
    ea = np.asarray(ed).astype(int)
    oa = np.asarray(out).astype(int)
    (bx, by, bw, bh) = info["paste_box"]
    # 贴回框中心区域（避开羽化边）的差异
    cy0, cy1 = by + bh // 4, by + 3 * bh // 4
    cx0, cx1 = bx + bw // 4, bx + 3 * bw // 4
    print(f"  centre-region |src-out| mean = {np.abs(sa[cy0:cy1, cx0:cx1] - oa[cy0:cy1, cx0:cx1]).mean():.2f}  (0 == perfect paste)")
    print(f"  centre-region |src-ed | mean = {np.abs(sa[cy0:cy1, cx0:cx1] - ea[cy0:cy1, cx0:cx1]).mean():.2f}  (before)")
    out.save(os.path.join(ROOT, "fix", "sanity_" + rel.replace("/", "_")))
print("\nsaved -> fix\\sanity_*.png")
