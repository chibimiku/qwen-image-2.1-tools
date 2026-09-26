#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Task #1 follow-up: can we stop the identity drift inside a multi-step chain?

Three arms, same pose step, same seed:

  A  single reference   : [pose-src]                         (baseline)
  B  anchor             : [pose-src, original]               (2 ref images)
  C  anchor + res1280   : [pose-src, original], output_resolution=1280

Then a second step ("change expression, keep pose") on each arm's output, with and
without the anchor again, to see whether anchoring keeps helping as the chain grows.

Metrics: SSIM + face-region drift vs the original input (identity) and vs the
previous step (how much actually moved).

Runs under: python tools/autodl_ssh.py fwd tools\qwen_anchor_test.py
"""
import base64
import io
import json
import os
import time

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw

from config import TEST_DATA as _ROOT
OUT = os.path.join(_ROOT, "anchor")
os.makedirs(OUT, exist_ok=True)
IN_EDIT = os.path.join(_ROOT, "input_edit.jpg")
W, H = 1088, 1600
FACE_BOX = (int(W * 0.22), int(H * 0.03), int(W * 0.78), int(H * 0.30))
STEPS = 35
SEED = 22

for i in range(90):
    try:
        h = requests.get(BASE + "/health", timeout=10).json()
        if h.get("loaded"):
            print(f"ready, gpu free {h['gpu']['free_gb']} GiB")
            break
    except Exception:                                            # noqa: BLE001
        pass
    time.sleep(10)
else:
    raise SystemExit("service not ready")
requests.post(BASE + "/v1/admin/empty_cache", timeout=60)


def png_bytes(im):
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def gauss(x, k=11, s=1.5):
    return cv2.GaussianBlur(x, (k, k), s)


def ssim(a, b):
    a, b = a.astype(np.float64), b.astype(np.float64)
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    mu_a, mu_b = gauss(a), gauss(b)
    sa, sb = gauss(a * a) - mu_a ** 2, gauss(b * b) - mu_b ** 2
    sab = gauss(a * b) - mu_a * mu_b
    return float((((2 * mu_a * mu_b + C1) * (2 * sab + C2)) /
                  ((mu_a ** 2 + mu_b ** 2 + C1) * (sa + sb + C2))).mean())


def gray(im):
    return np.asarray(im.convert("L")).astype(np.float32) / 255.0


def face_mad(a, b):
    x0, y0, x1, y1 = FACE_BOX
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


src = Image.open(IN_EDIT).convert("RGB").resize((W, H), Image.LANCZOS)
SRC_BYTES = png_bytes(src)
SRC_GRAY = gray(src)

POSE = ("Change only the pose: she crouches low on the floor, both knees bent apart, feet flat "
        "on the ground, both hands resting on the floor behind her for support. Keep the same "
        "character, same face, same hair, same dress, same room, same lighting.")
EXPR = ("Keep the pose and camera exactly as they are and change only the facial expression to "
        "a soft shy smile with slightly blushing cheeks. Keep the same face and identity, same "
        "hair, same dress, same room, same lighting.")


def call(images, prompt, out_res=None, seed=SEED):
    files = [("image", (f"ref{i}.png", b, "image/png")) for i, b in enumerate(images)]
    data = {"prompt": prompt, "num_inference_steps": str(STEPS), "seed": str(seed)}
    if out_res:
        data["output_resolution"] = str(out_res)
    t0 = time.time()
    r = requests.post(BASE + "/v1/images/edits", data=data, files=files, timeout=3600)
    dt = time.time() - t0
    if r.status_code != 200:
        return None, dt, r.text[:200]
    raw = base64.b64decode(r.json()["data"][0]["b64_json"])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    return im, dt, raw


rows = []
arms = [
    ("A_single_ref", [SRC_BYTES], None),
    ("B_anchor_orig", [SRC_BYTES, SRC_BYTES], None),
    ("C_anchor_res1280", [SRC_BYTES, SRC_BYTES], 1280),
]

pose_images = {}
for name, refs, res in arms:
    im, dt, raw = call(refs, POSE, out_res=res)
    if im is None:
        print(f"[{name}] pose FAIL {raw}")
        rows.append({"arm": name, "stage": "pose", "ok": False, "err": raw})
        continue
    p = os.path.join(OUT, f"{name}_1pose.png")
    open(p, "wb").write(raw)
    cur = im.resize((W, H), Image.LANCZOS)
    g = gray(cur)
    m = {"arm": name, "stage": "pose", "ok": True, "size": im.size, "elapsed": round(dt, 1),
         "identity_ssim": round(ssim(SRC_GRAY, g), 4),
         "face_drift_vs_input": round(face_mad(SRC_GRAY, g), 4)}
    print(f"[{name}] pose {im.size} {dt:.1f}s identity_ssim={m['identity_ssim']} face_drift={m['face_drift_vs_input']}")
    rows.append(m)
    pose_images[name] = (raw, cur)

# 第二步：在每条链的输出上再加 anchor，看是否继续起作用
for name, (raw, cur) in pose_images.items():
    g_prev = gray(cur)
    for tag, refs in (("plain", [raw]), ("anchored", [raw, SRC_BYTES])):
        im, dt, raw2 = call(refs, EXPR)
        if im is None:
            print(f"[{name}/{tag}] expr FAIL {raw2}")
            continue
        p = os.path.join(OUT, f"{name}_2expr_{tag}.png")
        open(p, "wb").write(raw2)
        c2 = im.resize((W, H), Image.LANCZOS)
        g2 = gray(c2)
        m = {"arm": name, "stage": f"expr_{tag}", "ok": True, "size": im.size,
             "elapsed": round(dt, 1),
             "moved_ssim_vs_pose": round(ssim(g_prev, g2), 4),
             "identity_ssim_vs_input": round(ssim(SRC_GRAY, g2), 4),
             "face_drift_vs_input": round(face_mad(SRC_GRAY, g2), 4)}
        print(f"[{name}/{tag}] expr {im.size} {dt:.1f}s identity_ssim={m['identity_ssim_vs_input']} "
              f"face_drift_vs_input={m['face_drift_vs_input']}")
        rows.append(m)

json.dump(rows, open(os.path.join(OUT, "anchor_metrics.json"), "w"), indent=1)
print(json.dumps(rows, ensure_ascii=False, indent=1)[:1800])
