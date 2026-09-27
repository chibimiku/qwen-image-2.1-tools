#!/usr/bin/env python3
"""把"可疑"的格子按 1:1 并排放大 —— 数腿这事的最终判据。

总览图能把可疑处挑出来，但"多一条腿"和"裙摆阴影"在 300px 下长得一样。
这里对指定的 (任务, seed) 把 4 个变体按原始分辨率并排铺出来，逐个确认。

    python _ab_crop_cells.py t2i 101 303 404 808
"""
import json
import os
import sys

from PIL import Image, ImageDraw

SRC = "/root/exp_out"
DST = f"{SRC}/sheets_zoom/cells"
os.makedirs(DST, exist_ok=True)
ORDER = ["A", "B", "C", "D"]

manifest = [json.loads(l) for l in open(f"{SRC}/manifest.jsonl", encoding="utf-8") if l.strip()]
idx = {(r["task"], r["seed"], r["variant"]): r for r in manifest}

TASK = sys.argv[1] if len(sys.argv) > 1 else "t2i"
SEEDS = [int(s) for s in sys.argv[2:]] or [101, 303, 404, 808]

# 只裁腰以下，但保持 1:1（512px 宽的原图区域）
X0, X1, Y0 = 0.22, 0.78, 0.42
LW, HEAD = 70, 26

for seed in SEEDS:
    cells = []
    for vk in ORDER:
        hit = idx.get((TASK, seed, vk))
        if not hit:
            continue
        im = Image.open(hit["path"]).convert("RGB")
        w, h = im.size
        cells.append((vk, im.crop((int(w * X0), int(h * Y0), int(w * X1), h))))
    if not cells:
        continue
    cw, ch = cells[0][1].size
    W = LW + len(cells) * (cw + 4) + 8
    H = HEAD + ch + 8
    sheet = Image.new("RGB", (W, H), (18, 20, 26))
    d = ImageDraw.Draw(sheet)
    d.text((8, 6), f"任务 {TASK} · seed {seed} · 列顺序 1→4（未标变体）· 1:1 原分辨率",
           fill=(230, 236, 244))
    for i, (vk, im) in enumerate(cells):
        x = LW + i * (cw + 4)
        sheet.paste(im, (x, HEAD))
        d.text((x + 4, HEAD + 4), f"col{i + 1}", fill=(160, 200, 255))
    p = f"{DST}/cell_{TASK}_{seed}.jpg"
    sheet.save(p, quality=95, optimize=True)
    print("  %s  %dx%d  %.0f KB" % (p, sheet.width, sheet.height,
                                    os.path.getsize(p) / 1024))
