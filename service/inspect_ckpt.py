#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Weights sanity check — runs WITHOUT a GPU (无卡模式) so problems surface
before paying for a card. Loads the checkpoint in bf16 on CPU (meta-free but
lazy: use low_cpu_mem_usage) and reports each component.

    python /root/qwen-image-2.1/scripts/inspect_ckpt.py
"""
import os
import time

import torch
from diffusers import QwenImage21Pipeline

MODEL_DIR = os.environ.get("QWEN_MODEL_DIR", "/root/autodl-tmp/Qwen-Image-2.1")


def count(mod):
    if mod is None:
        return 0
    return sum(p.numel() for p in mod.parameters())


def main():
    t0 = time.time()
    pipe = QwenImage21Pipeline.from_pretrained(
        MODEL_DIR, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True
    )
    print(f"loaded config in {time.time()-t0:.1f}s")
    for name, mod in [
        ("transformer", pipe.transformer),
        ("text_encoder", getattr(pipe, "text_encoder", None)),
        ("vae", pipe.vae),
    ]:
        n = count(mod)
        print(f"{name:14s} params={n/1e9:6.2f}B  dtype={getattr(mod,'dtype','?')}  class={type(mod).__name__}")

    print("scheduler:", type(pipe.scheduler).__name__)
    print("pipeline class:", type(pipe).__name__)

    # scheduler config sanity
    sc = pipe.scheduler.config
    print("scheduler config:",
          {k: getattr(sc, k, None) for k in ("num_train_timesteps", "shift", "use_dynamic_shifting")})

    # VAE: Qwen-Image-2.1 用的是 64 通道 RGBA 自编码器，config 是 FrozenDict，
    # 键名随 diffusers 版本变，所以按可用键汇报而不是硬取属性
    try:
        cfg = dict(pipe.vae.config)
        keys = ("in_channels", "out_channels", "latent_channels", "block_out_channels",
                "down_block_types", "scaling_factor", "shift_factor")
        print("vae config:", {k: cfg.get(k) for k in keys if k in cfg})
    except Exception as exc:                                   # noqa: BLE001
        print("vae config read failed:", exc)

    # text encoder tokenizer sanity
    if getattr(pipe, "tokenizer", None) is not None:
        ids = pipe.tokenizer("a quick prompt sanity check", return_tensors="pt").input_ids
        print("tokenizer ok, ids shape:", tuple(ids.shape))

    print(f"TOTAL pipeline load (CPU) {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
