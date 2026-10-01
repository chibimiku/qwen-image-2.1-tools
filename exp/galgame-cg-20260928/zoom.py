# -*- coding: utf-8 -*-
"""对单张出图做局部放大，用于确认缺陷（缩略图会把问题糊掉）。

  python exp/galgame-cg-20260928/zoom.py <文件名> <区域> [更多区域...]

区域写法：x,y,w,h（像素，相对原图）。也支持预设：
  head  上半身    hands  手部区域    feet  脚部    mirror 镜子区域
  center 中央 60%  left 左半    right 右半

例：
  python zoom.py story-01-boutique head,mirror
  python zoom.py story-06-sunset-bridge left,right center
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

EXP = pathlib.Path(__file__).resolve().parent
OUT = EXP / "out"

FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]


def font(size: int = 18):
    for p in FONTS:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:                                           # noqa: BLE001
                continue
    return ImageFont.load_default()


def preset(name: str, W: int, H: int) -> tuple:
    return {
        "head": (int(W * 0.30), 0, int(W * 0.45), int(H * 0.45)),
        "hands": (int(W * 0.20), int(H * 0.30), int(W * 0.60), int(H * 0.55)),
        "feet": (int(W * 0.25), int(H * 0.60), int(W * 0.55), int(H * 0.40)),
        "mirror": (0, 0, int(W * 0.45), int(H * 0.80)),
        "center": (int(W * 0.20), int(H * 0.10), int(W * 0.60), int(H * 0.80)),
        "left": (0, 0, int(W * 0.50), H),
        "right": (int(W * 0.50), 0, int(W * 0.50), H),
    }.get(name, (0, 0, W, H))


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    stem = sys.argv[1].removesuffix(".png")
    src = OUT / f"{stem}.png"
    if not src.exists():
        print(f"找不到 {src}")
        return 2

    im = Image.open(src).convert("RGB")
    W, H = im.size
    regions = []
    for spec in sys.argv[2:]:
        if "," in spec and spec.split(",")[0].strip().lstrip("-").isdigit():
            x, y, w, h = (int(v) for v in spec.split(","))
            regions.append((f"{x},{y},{w},{h}", (x, y, w, h)))
        else:
            regions.append((spec, preset(spec, W, H)))

    f = font(18)
    zs = []
    for label, (x, y, w, h) in regions:
        x = max(0, min(x, W - 8))
        y = max(0, min(y, H - 8))
        w = max(16, min(w, W - x))
        h = max(16, min(h, H - y))
        crop = im.crop((x, y, x + w, y + h))
        z = 2 if max(crop.size) < 700 else 1
        if z > 1:
            crop = crop.resize((crop.width * z, crop.height * z), Image.LANCZOS)
        zs.append((f"{label}  ({w}x{h} @{x},{y}  x{z})", crop))

    pad, lab = 10, 26
    total_w = sum(c.width for _, c in zs) + pad * (len(zs) + 1)
    total_h = max(c.height for _, c in zs) + lab + pad * 2
    sheet = Image.new("RGB", (total_w, total_h), (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    x = pad
    for label, c in zs:
        sheet.paste(c, (x, pad))
        d.text((x + 2, pad + c.height + 4), label, fill=(230, 230, 235), font=f)
        x += c.width + pad

    name = f"zoom-{stem}-{'-'.join(r[0] for r in regions)}.png".replace(",", "_")
    out = EXP / name
    sheet.save(out)
    print(f"{src.name} {W}x{H} -> {out.name} {sheet.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
