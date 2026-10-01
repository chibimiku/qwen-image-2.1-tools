# -*- coding: utf-8 -*-
"""把「原图 vs 修复版」逐对拼成对照表 + 统计过曝变化。

  python exp/galgame-cg-20260928/sheets_fix.py

过曝/死黑的变化用数字给出来（不是感觉），因为 C1/C2 是这批里出现 4 次的缺陷，
有一个客观量能直接说明"有没有改善"。
"""
from __future__ import annotations

import pathlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

EXP = pathlib.Path(__file__).resolve().parent
OUT = EXP / "out"
FIXED = EXP / "fixed-2"
FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]


def font(size: int = 15):
    for p in FONTS:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:                                           # noqa: BLE001
                continue
    return ImageFont.load_default()


def stats(p: pathlib.Path) -> tuple[float, float]:
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
    white = float((a >= 250).all(axis=2).mean() * 100)
    black = float((a <= 6).all(axis=2).mean() * 100)
    return round(white, 2), round(black, 2)


def main() -> int:
    names = sorted(p.stem for p in FIXED.glob("*.png") if not p.stem.startswith("_"))
    if not names:
        print("fixed-2/ 里没有图")
        return 2
    f = font(15)
    tw = 780
    th = int(tw * 896 / 1600)
    pad, lab = 10, 46
    sheet = Image.new("RGB", (2 * tw + 3 * pad, len(names) * (th + lab) + (len(names) + 1) * pad),
                      (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    print(f"{'图':<24} {'原图 白%/黑%':<16} {'修复 白%/黑%':<16} 变化")
    for i, n in enumerate(names):
        o, fx = OUT / f"{n}.png", FIXED / f"{n}.png"
        y = pad + i * (th + lab + pad)
        for ci, (label, p) in enumerate((("原图", o), ("修复", fx))):
            if not p.exists():
                continue
            im = Image.open(p).convert("RGB")
            im = im.resize((tw, int(tw * im.height / im.width)), Image.LANCZOS)
            x = pad + ci * (tw + pad)
            sheet.paste(im, (x, y))
            d.text((x + 4, y + im.height + 4), f"{n}  {label}", fill=(230, 230, 235), font=f)
        if o.exists() and fx.exists():
            wo, bo = stats(o)
            wf, bf = stats(fx)
            arrow = "白↓" if wf < wo - 1 else ("白↑" if wf > wo + 1 else "白=")
            d.text((pad + 4, y + th + 22),
                   f"{n}   原图 {wo}%/{bo}%   →   修复 {wf}%/{bf}%   {arrow}",
                   fill=(200, 220, 255), font=f)
            print(f"{n:<24} {wo:>6}%/{bo:<6}% {wf:>6}%/{bf:<6}% {arrow}"
                  + ("   黑↓" if bf < bo - 1 else ""))
    out = EXP / "sheets-fixed2.png"
    sheet.save(out)
    print(f"\n对照表 -> {out.name} {sheet.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
