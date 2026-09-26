#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Multi-step edit chain harness (task #1).

Runs an ordered chain of edits where each step changes ONE thing and claims to
keep everything else, feeding step N's output into step N+1. Two things get
measured per step:

  * how far the image moved            (SSIM, mean |diff|)
  * how far the FACE moved             (face-region mean |diff|)  <- identity drift
  * how much of the body region moved  (pose actually changed?)

A contact sheet of the whole chain is written for visual inspection.

Runs under: python tools/autodl_ssh.py fwd tools\qwen_chain.py
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
BASE_OUT = os.path.join(_ROOT, "chain")
os.makedirs(BASE_OUT, exist_ok=True)
IN_EDIT = os.path.join(_ROOT, "input_edit.jpg")
W, H = 1088, 1600
STEPS_PER_EDIT = 35
SEED = 22

# 脸部/身体区域（竖构图 2:3，脸在上部）
FACE_BOX = (int(W * 0.22), int(H * 0.03), int(W * 0.78), int(H * 0.30))
BODY_BOX = (int(W * 0.10), int(H * 0.35), int(W * 0.90), int(H * 0.97))


def gauss(x, k=11, s=1.5):
    return cv2.GaussianBlur(x, (k, k), s)


def ssim(a, b):
    """Minimal SSIM on grayscale float images in [0,1]."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    mu_a, mu_b = gauss(a), gauss(b)
    sa, sb = gauss(a * a) - mu_a ** 2, gauss(b * b) - mu_b ** 2
    sab = gauss(a * b) - mu_a * mu_b
    num = (2 * mu_a * mu_b + C1) * (2 * sab + C2)
    den = (mu_a ** 2 + mu_b ** 2 + C1) * (sa + sb + C2)
    return float((num / den).mean())


def to_gray(im):
    return np.asarray(im.convert("L")).astype(np.float32) / 255.0


def region_mad(a, b, box):
    x0, y0, x1, y1 = box
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


# ---------------------------------------------------------------- readiness
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

src = Image.open(IN_EDIT).convert("RGB").resize((W, H), Image.LANCZOS)
buf = io.BytesIO()
src.save(buf, format="PNG")
CHAIN_INPUT = buf.getvalue()

KEEP_ALL = ("Do not change anything else: keep exactly the same character, same face and facial "
            "features, same long brown hair with the silver tiara, same blue and white frilled "
            "lace dress and white high-heel boots, same ornate dark blue room, same background "
            "objects, same lighting and colour grading. Full body visible from head to toe.")

# 每条链：4 步，每步只动一个维度
CHAINS = {
    "chainA_pose_expr_hands_cam": [
        ("1_pose", "Change ONLY the pose: she crouches low on the floor, both knees bent apart, "
                   "feet flat on the ground, both hands resting on the floor behind her for "
                   "support, hips low, back straight. " + KEEP_ALL),
        ("2_expression", "Keep the pose exactly as it is. Change ONLY her facial expression to a "
                         "shy bashful smile, cheeks slightly blushing, eyes half closed looking at "
                         "the viewer. Keep the same face shape, same eye colour, same hairstyle. "
                         + KEEP_ALL.replace("Change ONLY", "change ONLY")),
        ("3_hands", "Keep the pose and the facial expression exactly as they are. Change ONLY her "
                    "hands so both hands are clearly visible, each with five correct fingers, "
                    "natural hand anatomy, no extra fingers, no fused fingers. " + KEEP_ALL),
        ("4_camera", "Keep the character, pose, expression and hands exactly as they are. Change "
                     "ONLY the camera: a slightly lower camera angle and a 3/4 view, camera a bit "
                     "closer, everything else identical. " + KEEP_ALL),
    ],
    "chainB_clean_keep_blocks": [
        ("1_pose", "Pose: deep crouch on the floor, knees apart, one hand on the floor.\n"
                   "KEEP: character identity, face, hair, tiara, dress, boots, room, lighting, "
                   "background objects, colour grading.\n"
                   "CHANGE: only the body pose."),
        ("2_head", "Pose: unchanged from the previous image.\n"
                   "CHANGE: only the head, tilted slightly to her left and looking up at the "
                   "viewer.\n"
                   "KEEP: identity, face, hair, tiara, dress, room, lighting, pose."),
        ("3_expression", "Pose and head: unchanged.\n"
                         "CHANGE: only the facial expression, a soft surprised expression with "
                         "slightly parted lips and raised eyebrows.\n"
                         "KEEP: identity, hairstyle, dress, room, lighting."),
        ("4_hands", "Pose, head, expression: unchanged.\n"
                    "CHANGE: only the hands, both clearly visible with five correct fingers each, "
                    "natural anatomy.\n"
                    "KEEP: identity, dress, room, lighting, camera."),
    ],
}


def run_chain(name, steps):
    outdir = os.path.join(BASE_OUT, name)
    os.makedirs(outdir, exist_ok=True)
    prev_img = src
    prev_gray = to_gray(prev_img)
    prev_img.save(os.path.join(outdir, "0_input.png"))
    rows = []
    payload = CHAIN_INPUT
    for tag, prompt in steps:
        t0 = time.time()
        r = requests.post(BASE + "/v1/images/edits",
                          data={"prompt": prompt, "num_inference_steps": str(STEPS_PER_EDIT),
                                "seed": str(SEED)},
                          files=[("image", ("step.png", payload, "image/png"))], timeout=3600)
        dt = time.time() - t0
        if r.status_code != 200:
            print(f"[{name}/{tag}] FAIL {r.status_code} {r.text[:160]}")
            rows.append({"step": tag, "ok": False, "status": r.status_code})
            break
        raw = base64.b64decode(r.json()["data"][0]["b64_json"])
        open(os.path.join(outdir, f"{tag}.png"), "wb").write(raw)
        cur = Image.open(io.BytesIO(raw)).convert("RGB").resize((W, H), Image.LANCZOS)
        cur_gray = to_gray(cur)
        m = {"step": tag, "ok": True, "elapsed": round(dt, 1),
             "ssim_vs_prev": round(ssim(prev_gray, cur_gray), 4),
             "mad_all": round(float(np.abs(prev_gray - cur_gray).mean()), 4),
             "mad_face": round(region_mad(prev_gray, cur_gray, FACE_BOX), 4),
             "mad_body": round(region_mad(prev_gray, cur_gray, BODY_BOX), 4)}
        print(f"[{name}/{tag}] {dt:.1f}s  ssim={m['ssim_vs_prev']}  "
              f"face_drift={m['mad_face']}  body_change={m['mad_body']}")
        rows.append(m)
        payload = raw                      # 上一步输出喂下一步
        prev_img, prev_gray = cur, cur_gray

    # 整链 vs 原始输入的累计漂移
    if rows and rows[-1].get("ok"):
        last = Image.open(os.path.join(outdir, f"{rows[-1]['step']}.png")).convert("RGB").resize((W, H))
        rows.append({"step": "cumulative_vs_input",
                     "ssim": round(ssim(to_gray(src), to_gray(last)), 4),
                     "mad_face": round(region_mad(to_gray(src), to_gray(last), FACE_BOX), 4),
                     "mad_body": round(region_mad(to_gray(src), to_gray(last), BODY_BOX), 4)})
    return rows, outdir


def contact_sheet(images, labels, path, cols=4, cell=320):
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 22)), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    for i, (im, lab) in enumerate(zip(images, labels)):
        r, c = divmod(i, cols)
        thumb = im.resize((cell, cell))
        sheet.paste(thumb, (c * cell, r * (cell + 22)))
        d.text((c * cell + 4, r * (cell + 22) + cell + 4), lab, fill=(230, 230, 230))
    sheet.save(path)
    return path


summary = {}
for name, steps in CHAINS.items():
    print(f"\n=== {name} ===")
    rows, outdir = run_chain(name, steps)
    summary[name] = rows
    files = ["0_input.png"] + [r["step"] + ".png" for r in rows if r.get("ok") and r["step"] != "cumulative_vs_input"]
    ims = [Image.open(os.path.join(outdir, f)).convert("RGB") for f in files]
    contact_sheet(ims, [f.replace(".png", "") for f in files],
                  os.path.join(BASE_OUT, f"{name}_sheet.png"))
    json.dump(rows, open(os.path.join(outdir, "metrics.json"), "w"), indent=1)

print("\n" + json.dumps(summary, ensure_ascii=False, indent=1))
