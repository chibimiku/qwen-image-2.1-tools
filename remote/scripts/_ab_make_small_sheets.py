#!/usr/bin/env python3
"""把盲评表压成能直接看的 JPEG —— 供人（或外层 agent）逐格评分。

为什么单独做：PNG 的盲评表 3.2MB/张，三张一起拉要十几 MB。
JPEG q=88 + 缩到 260px/格，每张降到 0.4MB 左右，肉眼判"多腿/融合"完全够用。

输出：
  sheets_small/blind_all.jpg        3 个任务拼成一张，4 列（列顺序固定 A→D，不标字母）
  sheets_small/blind_<task>.jpg     单任务
每格左上角标 seed，右下角标列号 —— 评分时按（任务, seed, 列号）记录。
"""
import io
import json
import os
from collections import defaultdict

from PIL import Image, ImageDraw

SRC = "/root/exp_out"
DST = f"{SRC}/sheets_small"
os.makedirs(DST, exist_ok=True)

manifest = [json.loads(l) for l in open(f"{SRC}/manifest.jsonl", encoding="utf-8") if l.strip()]
ORDER = ["A", "B", "C", "D"]
TASK_ORDER = ["t2i", "edit1", "edit2"]
TITLE = {"t2i": "文生图", "edit1": "单参考图大改姿势", "edit2": "双人肢体交叠"}


def build(rows_by_task, path, cell=260):
    seeds = sorted({r["seed"] for rows in rows_by_task.values() for r in rows})
    tasks = [t for t in TASK_ORDER if t in rows_by_task]
    pad, header, gap = 10, 30, 8
    H = header + sum(len(seeds) * (cell + gap) + header for _ in tasks) + pad
    W = pad * 2 + 4 * (cell + gap) + 150
    sheet = Image.new("RGB", (W, H), (18, 20, 26))
    d = ImageDraw.Draw(sheet)
    y = pad
    for task in tasks:
        d.text((pad, y + 6), f"任务 {task}（{TITLE[task]}）—— 每行同一 seed，列 ①②③④ 顺序固定不标变体",
               fill=(230, 236, 244))
        y += header
        for seed in seeds:
            d.text((pad, y + cell // 2), f"{task}\nseed\n{seed}", fill=(120, 200, 255))
            for ci, vk in enumerate(ORDER):
                hit = next((r for r in rows_by_task[task]
                            if r["seed"] == seed and r["variant"] == vk), None)
                x = pad + 150 + ci * (cell + gap)
                if hit:
                    try:
                        im = Image.open(hit["path"]).convert("RGB")
                        im.thumbnail((cell, cell))
                        sheet.paste(im, (x, y))
                    except Exception:                                # noqa: BLE001
                        d.rectangle([x, y, x + cell, y + cell], outline=(200, 60, 60))
                d.text((x + 4, y + cell - 16), f"col{ci + 1}", fill=(120, 200, 255))
            y += cell + gap
        y += 4
    sheet.save(path, quality=88, optimize=True)
    print("  %s  %dx%d  %.0f KB" % (path, sheet.width, sheet.height,
                                    os.path.getsize(path) / 1024))
    return path


by_task = defaultdict(list)
for r in manifest:
    by_task[r["task"]].append(r)

build(by_task, f"{DST}/blind_all.jpg")
for t in TASK_ORDER:
    if by_task.get(t):
        build({t: by_task[t]}, f"{DST}/blind_{t}.jpg")

# 顺手给一份"评分记录模板"：112 个空格子，填 0/1 就是完整打分
cells = [{"task": r["task"], "seed": r["seed"], "col": ORDER.index(r["variant"]) + 1,
          "blind_id": r["blind_id"], "score": None}
         for r in sorted(manifest, key=lambda r: (TASK_ORDER.index(r["task"]), r["seed"],
                                                  ORDER.index(r["variant"])))]
with open(f"{DST}/score_sheet.json", "w", encoding="utf-8") as fh:
    json.dump(cells, fh, ensure_ascii=False, indent=1)
print("  %s/score_sheet.json  %d 格" % (DST, len(cells)))
