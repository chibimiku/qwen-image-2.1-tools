#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ladder test: same seed, progressively stronger pose/exposure wording.

Purpose: find where the model's output starts breaking (extra limbs, fused
thighs, broken fabric) so we can give a usable ceiling for this pipeline.

Runs under: python tools/autodl_ssh.py fwd tools\qwen_nsfw_test.py
"""
import base64
import io
import json
import os
import time

import requests
from PIL import Image

from config import TEST_DATA as _ROOT
OUT = _ROOT
IN_EDIT = os.path.join(OUT, "input_edit.jpg")
W, H = 1088, 1600
SEED = 22                       # poseB seed22 是上一轮里最稳的，作为基线继续加压

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
up = buf.getvalue()

KEEP = ("Keep the same character, same face, same long brown hair with tiara, same blue room, "
        "same lighting. Full body from head to toe, both legs fully visible, correct human "
        "anatomy, natural and symmetrical leg proportions, five fingers per hand.")

LADDER = {
    # L1: 姿态更开，但服装完整
    "L1_open_pose": (
        "She crouches on the floor with both knees bent far apart to the sides, thighs open wide, "
        "hips low, back straight, both hands resting on the floor behind her for support. "
        "Her lace dress and white thigh-high stockings stay as they are. " + KEEP),
    # L2: 裙摆散开、腿部露出更多
    "L2_skirt_spread": (
        "She crouches low on the floor with her knees bent wide apart, thighs open, leaning back "
        "on both hands, her long frilled skirt spread out around her hips so her thighs and "
        "stockings are clearly visible. Head tilted to one side, looking at the viewer. " + KEEP),
    # L3: 蹲伏前倾 + 更贴身的服装描写
    "L3_kneeling_lean": (
        "She kneels-crouches on the rug, knees wide apart, thighs open, torso leaning forward "
        "with both hands on the floor in front of her, looking up at the viewer over her "
        "shoulder, her dress clinging to her body. " + KEEP),
    # L4: 构图拉近，重点放在姿态与腿
    "L4_low_angle": (
        "Low camera angle, she crouches in the middle of the room with her knees bent wide apart "
        "and thighs open, feet flat on the floor, chin lifted, both hands on her knees, her "
        "frilled dress draped between her legs. Cinematic rim light. " + KEEP),
}

results = {}
for name, prompt in LADDER.items():
    t0 = time.time()
    r = requests.post(BASE + "/v1/images/edits",
                      data={"prompt": prompt, "num_inference_steps": 35, "seed": str(SEED),
                            "width": str(W), "height": str(H)},
                      files=[("image", ("input.png", up, "image/png"))], timeout=3600)
    if r.status_code != 200:
        print(f"[{name}] http {r.status_code} {r.text[:200]}")
        results[name] = {"ok": False, "status": r.status_code}
        continue
    d = r.json()["data"][0]
    raw = base64.b64decode(d["b64_json"])
    p = os.path.join(OUT, f"nsfw_{name}.png")
    open(p, "wb").write(raw)
    print(f"[{name}] OK {time.time()-t0:.1f}s -> {os.path.basename(p)}")
    results[name] = {"ok": True, "path": p, "elapsed": round(time.time() - t0, 1)}

print(json.dumps(results, ensure_ascii=False, indent=1))
