#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Warm-up + benchmark for Qwen-Image-2.1 on the 48G card (单卡 4090-48G 魔改).

    python /root/qwen-image-2.1/scripts/bench.py            # 默认 1024/2048 两组
    python /root/qwen-image-2.1/scripts/bench.py --quick    # 只跑 1024/20步

Writes PNGs to /root/qwen-image-2.1/outputs and prints VRAM/timing per config.
"""
import argparse
import os
import time

import torch
from diffusers import QwenImage21Pipeline

MODEL_DIR = os.environ.get("QWEN_MODEL_DIR", "/root/autodl-tmp/Qwen-Image-2.1")
OUT = "/root/qwen-image-2.1/outputs"
DTYPE = torch.bfloat16 if os.environ.get("QWEN_TORCH_DTYPE", "bfloat16") == "bfloat16" else torch.float16
PROMPT = ("A neon shop sign that reads \"QWEN IMAGE 2.1\", rainy night, "
          "reflections on wet pavement, cinematic")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--offload", action="store_true", help="走 enable_model_cpu_offload")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    print(f"cuda={torch.cuda.is_available()} device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-'}")
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        print(f"vram total={total/1024**3:.1f}GiB free={free/1024**3:.1f}GiB capability={torch.cuda.get_device_capability(0)}")

    t0 = time.time()
    pipe = QwenImage21Pipeline.from_pretrained(MODEL_DIR, torch_dtype=DTYPE)
    if a.offload:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)
    print(f"load: {time.time()-t0:.1f}s  allocated={torch.cuda.memory_allocated()/1024**3:.2f}GiB")

    cases = [("1024", 1024, 1024, 20), ("2048", 2048, 2048, 40)]
    if a.quick:
        cases = cases[:1]

    for name, w, h, steps in cases:
        torch.cuda.reset_peak_memory_stats()
        t = time.time()
        img = pipe(prompt=PROMPT, width=w, height=h, num_inference_steps=steps,
                   generator=torch.Generator("cuda").manual_seed(42)).images[0]
        dt = time.time() - t
        path = os.path.join(OUT, f"bench_{name}_{steps}steps.png")
        img.save(path)
        print(f"{name} {steps}steps: {dt:.1f}s ({dt/steps:.2f}s/step)  "
              f"peak={torch.cuda.max_memory_allocated()/1024**3:.2f}GiB -> {path}")


if __name__ == "__main__":
    main()
