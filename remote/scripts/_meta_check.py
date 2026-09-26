#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查现有 PNG 里有没有生成信息（文本块 / EXIF）。"""
import glob
import os
import sys

from PIL import Image

paths = []
for pat in ("/root/qwen-image-2.1/outputs/*.png", "/root/autodl-tmp/*check*/*.png"):
    paths.extend(sorted(glob.glob(pat)))
paths = paths[:8]

print(f"检查 {len(paths)} 个 PNG\n")
for p in paths:
    try:
        im = Image.open(p)
        im.load()
    except Exception as e:                                             # noqa: BLE001
        print(f"  {os.path.basename(p)}: 打不开 {e}")
        continue
    info = dict(im.info)
    txt = {k: v for k, v in info.items() if isinstance(v, (str, bytes))}
    exif = None
    try:
        exif = im.getexif()
    except Exception:                                                  # noqa: BLE001
        pass
    print(f"  {os.path.basename(p)}")
    print(f"     info keys : {list(info.keys()) or '（空）'}")
    print(f"     exif tags : {len(exif) if exif else 0}")
    for k, v in txt.items():
        s = v if isinstance(v, str) else f"<{len(v)} bytes>"
        print(f"     {k} = {s[:120]}")
    print()

# 管线返回对象里有哪些可用字段
print("=== QwenImage21PipelineOutput 的字段 ===")
try:
    from diffusers.pipelines.qwenimage.pipeline_output import QwenImagePipelineOutput
    print("  QwenImagePipelineOutput:", [a for a in dir(QwenImagePipelineOutput) if not a.startswith("_")])
except Exception as e:                                                 # noqa: BLE001
    print("  导入失败:", e)
try:
    from diffusers.pipelines.qwenimage.pipeline_qwenimage21 import QwenImage21PipelineOutput
    print("  QwenImage21PipelineOutput:", [a for a in dir(QwenImage21PipelineOutput) if not a.startswith("_")])
except Exception as e:                                                 # noqa: BLE001
    print("  QwenImage21PipelineOutput 导入失败:", e)
