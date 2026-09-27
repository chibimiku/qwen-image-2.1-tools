#!/usr/bin/env python3
"""放大盲评：只看"腰以下"，让人能真的数腿。

小尺寸总览图（260px/格）能把"多一条腿"糊成一片，而判据恰恰就是腿。
这里按（任务 × 列）切一张大图：纵向是该任务的 12 个 seed，
每格只显示下半身并按 460px 渲染 —— 数腿需要的就是这个尺度。

已知这组图的主体基本居中、全身构图，所以固定裁 x∈[0.2,0.8]、y∈[0.45,1.0] 就够；
不用检测主体，避免引入另一处可能出错的东西。

输出：/root/exp_out/sheets_zoom/lower_<task>_col<N>.jpg
"""
import json
import os
from collections import defaultdict

from PIL import Image, ImageDraw

SRC = "/root/exp_out"
DST = f"{SRC}/sheets_zoom"
os.makedirs(DST, exist_ok=True)

manifest = [json.loads(l) for l in open(f"{SRC}/manifest.jsonl", encoding="utf-8") if l.strip()]
ORDER = ["A", "B", "C", "D"]
TASKS = ["t2i", "edit1", "edit2"]
TITLE = {"t2i": "文生图", "edit1": "单参考图大改姿势", "edit2": "双人肢体交叠"}

# 纵向裁 45%~100%（腰以下），横向 20%~80%（主体居中）
X0, X1, Y0 = 0.20, 0.80, 0.45
CELL = 460
GAP = 6
PAD = 10
HEADER = 28

by_task = defaultdict(dict)
for r in manifest:
    by_task[r["task"]][(r["seed"], r["variant"])] = r

# 一列一种变体、一列 12 个 seed —— 必须整列同屏才能判"这一组是否更容易崩"。
# 第一版按"3 seed × 4 行"铺，结果只剩半个屏幕能看，数腿数不准。
for task in TASKS:
    tab = by_task.get(task)
    if not tab:
        continue
    seeds = sorted({k[0] for k in tab})
    W = PAD * 2 + (CELL + GAP) * 4 + 60
    H = PAD + HEADER + len(seeds) * (CELL + GAP)
    sheet = Image.new("RGB", (W, H), (18, 20, 26))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, PAD + 6),
           f"任务 {task}（{TITLE[task]}）· 每列一个变体（未标字母）· 每行一个 seed · 只看腰以下",
           fill=(230, 236, 244))
    for ri, seed in enumerate(seeds):
        y = PAD + HEADER + ri * (CELL + GAP)
        d.text((PAD, y + CELL // 2 - 8), f"seed\n{seed}", fill=(255, 230, 120))
        for ci, vk in enumerate(ORDER):
            hit = tab.get((seed, vk))
            x = PAD + 60 + ci * (CELL + GAP)
            if not hit:
                continue
            try:
                im = Image.open(hit["path"]).convert("RGB")
                w, h = im.size
                im = im.crop((int(w * X0), int(h * Y0), int(w * X1), h))
                im.thumbnail((CELL, CELL))
                sheet.paste(im, (x, y))
            except Exception as e:                                   # noqa: BLE001
                d.rectangle([x, y, x + CELL, y + CELL], outline=(200, 60, 60))
                d.text((x + 6, y + 6), str(e)[:40], fill=(255, 120, 120))
            d.text((x + 4, y + 4), f"col{ci + 1}", fill=(160, 200, 255))
    p = f"{DST}/legs_{task}.jpg"
    sheet.save(p, quality=92, optimize=True)
    print("  %s  %dx%d  %.0f KB" % (p, sheet.width, sheet.height,
                                    os.path.getsize(p) / 1024))
print("\n每列对应一个变体（顺序固定 A→D，表上不标字母）；行是 seed，标在左边")
