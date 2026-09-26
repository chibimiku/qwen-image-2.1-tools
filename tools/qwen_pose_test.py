#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pose + anatomy stress test on the 4090 box.

Goal: find a prompt formulation that yields a correct crouching pose with
healthy leg proportions ("thighs open" pose), across several seeds.

Runs under: python tools/autodl_ssh.py fwd tools\qwen_pose_test.py
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
W, H = 1088, 1600          # 17:25 竖构图喂图；模型按 1MP 档位出

# --- readiness gate ---------------------------------------------------------
for i in range(90):
    try:
        h = requests.get(BASE + "/health", timeout=10).json()
        if h.get("loaded"):
            print(f"ready (loaded={h['loaded']}, gpu free {h['gpu']['free_gb']} GiB)")
            break
    except Exception as exc:                                     # noqa: BLE001
        print(f"  [{i*10}s] down ({type(exc).__name__})")
    time.sleep(10)
else:
    raise SystemExit("service not ready")

# 清一下分配器缓存，保证最大机动空间
try:
    print("empty_cache:", requests.post(BASE + "/v1/admin/empty_cache", timeout=60).json()["freed_gib"], "GiB freed")
except Exception as exc:                                         # noqa: BLE001
    print("empty_cache skipped:", exc)

src = Image.open(IN_EDIT).convert("RGB").resize((W, H), Image.LANCZOS)
buf = io.BytesIO()
src.save(buf, format="PNG")
up = buf.getvalue()
print(f"input {W}x{H}, upload {len(up)/1e6:.1f} MB")

# 姿势描述：强调解剖结构、对称性、镜头与全身构图。
# 露骨内容不在本轮范围内：只做"姿势/构图/比例"这一层的压力测试。
PROMPTS = {
    "poseA_thighs_open": (
        "Change her pose: she crouches low on the floor with both knees bent wide apart to "
        "the sides, thighs open, feet flat on the ground, hips low, torso upright and slightly "
        "forward, one hand resting on the floor between her knees for balance, the other hand "
        "touching her cheek. Show the WHOLE body from head to toe, both legs fully visible and "
        "symmetrical, correct human anatomy and natural leg proportions, dress fabric falling "
        "between her legs. Keep the same character, same face, same long brown hair with tiara, "
        "same blue and white frilled lace dress and white heels, same ornate dark blue room, "
        "same lighting."),
    "poseB_crouch_symmetric": (
        "Change her pose to a deep crouch on the floor: both feet planted shoulder-width apart, "
        "knees bent and pointing outward, hips low near the ground, back straight, arms resting "
        "on her thighs. Full body from head to feet, correct anatomy, both thighs foreshortened "
        "consistently, natural leg length and proportions. Same character, same face, same hair, "
        "same blue and white frilled dress, same blue room, same lighting."),
}

results = {}
for name, prompt in PROMPTS.items():
    for seed in (11, 22, 33):
        body = f"{name}_seed{seed}"
        r = requests.post(BASE + "/v1/images/edits",
                          data={"prompt": prompt, "num_inference_steps": 35, "seed": str(seed),
                                "width": str(W), "height": str(H)},
                          files=[("image", ("input.png", up, "image/png"))], timeout=3600)
        if r.status_code != 200:
            print(f"[{body}] http {r.status_code} {r.text[:200]}")
            results[body] = {"ok": False, "status": r.status_code}
            continue
        d = r.json()["data"][0]
        raw = base64.b64decode(d["b64_json"])
        p = os.path.join(OUT, f"{name}_{seed}.png")
        open(p, "wb").write(raw)
        im = Image.open(io.BytesIO(raw))
        print(f"[{body}] OK {im.size} {len(raw)/1e6:.1f} MB -> {os.path.basename(p)}")
        results[body] = {"ok": True, "path": p, "size": im.size,
                         "elapsed": d.get("elapsed_s")}

h = requests.get(BASE + "/health", timeout=60).json()
print("peak:", h["peak_allocated_gib"], "GiB | gpu free:", h["gpu"]["free_gb"])
print(json.dumps(results, ensure_ascii=False)[:600])
