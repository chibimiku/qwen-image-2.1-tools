#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 outputs 里所有图的 prompt / 参数捞出来，看看实际在用什么写法。"""
import json
import pathlib
import re
import sys

try:
    from PIL import Image
except ImportError:                                                    # noqa: BLE001
    print("需要 pillow")
    sys.exit(2)

roots = [pathlib.Path(p) for p in sys.argv[1:]] or [pathlib.Path("/root/qwen-image-2.1/outputs")]
files = []
for r in roots:
    files += [p for p in r.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
files.sort(key=lambda p: p.stat().st_mtime)

print(f"共 {len(files)} 个图片文件\n")
rows = []
for p in files:
    try:
        im = Image.open(p)
        im.load()
        raw = im.info.get("qwen_image_21")
    except Exception:                                                  # noqa: BLE001
        continue
    if not raw:
        continue
    m = json.loads(raw if isinstance(raw, str) else raw.decode())
    r = m.get("request") or {}
    rows.append({
        "file": p.name,
        "size": f"{r.get('width')}x{r.get('height')}",
        "steps": r.get("num_inference_steps"),
        "seed": r.get("seed"),
        "negative": r.get("negative_prompt"),
        "cfg": r.get("true_cfg_scale") or r.get("guidance_scale"),
        "outres": r.get("output_resolution"),
        "aspect": r.get("aspect_ratio"),
        "n_inputs": len(m.get("inputs") or []),
        "prompt": (r.get("prompt") or ""),
    })

print(f"其中 {len(rows)} 张带元数据\n")
print("=" * 100)
for x in rows:
    print(f"■ {x['file']}   {x['size']}  steps={x['steps']}  seed={x['seed']}")
    print(f"   negative={x['negative']!r}   cfg={x['cfg']!r}   outres={x['outres']!r} "
          f"aspect={x['aspect']!r}  输入图 {x['n_inputs']} 张")
    pr = x["prompt"]
    print(f"   prompt ({len(pr)} 字):")
    for ln in re.findall(r".{1,96}", pr) or [""]:
        print(f"     {ln}")
    print()

# 统计：有没有人用过 negative / CFG
neg_n = sum(1 for x in rows if x["negative"])
cfg_n = sum(1 for x in rows if x["cfg"] and float(x["cfg"]) > 1)
print("=" * 100)
print(f"用了 negative_prompt 的：{neg_n}/{len(rows)}")
print(f"把 CFG 调到 >1 的：{cfg_n}/{len(rows)}")
lens = [len(x["prompt"]) for x in rows]
if lens:
    print(f"prompt 长度：最短 {min(lens)}，最长 {max(lens)}，平均 {sum(lens) // len(lens)} 字")
