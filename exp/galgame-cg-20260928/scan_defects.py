# -*- coding: utf-8 -*-
"""对 out/ 全部出图做客观扫描，找"能用数字判定"的缺陷。

  python exp/galgame-cg-20260928/scan_defects.py

测三类**可量化**的问题（不替代人眼，但能把范围缩小到几张）：

1. **过曝/死白**：接近纯白的像素占比。CG 里大面积 255,255,255 就是渲染失败或背景缺失。
2. **死黑**：接近纯黑的像素占比（可能是没画完的区域）。
3. **孤立色斑**：在人脸/皮肤区域出现的、与周围明显不同的高饱和小连通域。

输出按严重度排序，并把可疑图连区域坐标一起列出，方便直接 zoom 复核。
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image

EXP = pathlib.Path(__file__).resolve().parent
OUT = EXP / "out"


def analyse(path: pathlib.Path) -> dict:
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    h, w, _ = a.shape
    total = h * w

    # 1) 死白 / 2) 死黑
    white = (a >= 250).all(axis=2)
    black = (a <= 6).all(axis=2)

    # 最大死白矩形块（按行段粗估）：只看"整行/整列连续"的规模
    row_white = white.mean(axis=1)          # 每行的死白比例
    col_white = white.mean(axis=0)
    wide_rows = int((row_white > 0.5).sum())
    wide_cols = int((col_white > 0.5).sum())

    # 3) 高饱和孤立色斑：在绿色通道显著高于红蓝的像素上找
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenish = (g - np.maximum(r, b) > 25) & (g > 90)
    # 只关心"小"连通域：用简单的行列投影判断（不引入 scipy）
    gy, gx = np.where(greenish)
    spots = 0
    spot_boxes = []
    if len(gy) > 0:
        # 按 8x8 网格聚类，统计每格里有多少像素
        cell = 32
        grid = {}
        for y, x in zip(gy, gx):
            grid.setdefault((y // cell, x // cell), 0)
            grid[(y // cell, x // cell)] += 1
        for (cy, cx), n in grid.items():
            # 单格内 30~2000 像素、且集中在很小范围 -> 像色斑而不是大片绿色背景
            if 30 <= n <= 2000:
                spots += 1
                spot_boxes.append((cx * cell, cy * cell, n))

    area = h * w
    return {
        "file": path.name, "w": w, "h": h,
        "white_pct": round(white.sum() / area * 100, 2),
        "black_pct": round(black.sum() / area * 100, 2),
        "wide_white_rows": wide_rows, "wide_white_cols": wide_cols,
        "green_spots": spots,
        "spot_boxes": sorted(spot_boxes, key=lambda t: -t[2])[:6],
    }


def main() -> int:
    files = sorted(OUT.glob("*.png"))
    if not files:
        print("out/ 里没有 PNG")
        return 2

    rows = [analyse(p) for p in files]
    print(f"扫描 {len(rows)} 张（{rows[0]['w']}x{rows[0]['h']} 基准）\n")

    # 尺寸不等于主流的先列出来（尺寸被吸附是已知行为，不是缺陷，但要看清楚）
    from collections import Counter
    sizes = Counter((r["w"], r["h"]) for r in rows)
    print("尺寸分布:", dict(sizes), "\n")

    def show(title: str, key, fmt, thresh=None, limit=12):
        print(f"=== {title} ===")
        sel = [r for r in rows if (thresh is None or key(r) >= thresh)]
        sel.sort(key=key, reverse=True)
        if not sel:
            print("  （无）")
        for r in sel[:limit]:
            print(f"  {fmt(r)}")
        print()

    show("死白占比最高（>8% 值得看）", lambda r: r["white_pct"],
         lambda r: f"  {r['white_pct']:>6.2f}%  {r['file']}", thresh=8)
    show("整行/整列大面积死白（背景缺失的典型形态）",
         lambda r: max(r["wide_white_rows"], r["wide_white_cols"]),
         lambda r: f"  rows={r['wide_white_rows']:<4} cols={r['wide_white_cols']:<4} {r['file']}",
         thresh=1)
    show("死黑占比最高（>6% 值得看）", lambda r: r["black_pct"],
         lambda r: f"  {r['black_pct']:>6.2f}%  {r['file']}", thresh=6)
    show("可疑绿色色斑格数最多", lambda r: r["green_spots"],
         lambda r: "  {:>3} 格  {}   最密: {}".format(
             r["green_spots"], r["file"], r["spot_boxes"][:3]),
         thresh=1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
