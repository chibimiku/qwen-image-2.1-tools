# -*- coding: utf-8 -*-
"""把参考图引用语法的对照实验结果拼成一张对比图。"""
import os
import sys

from PIL import Image, ImageDraw

D = sys.argv[1] if len(sys.argv) > 1 else "tmp_refs"
NAMES = ["01_plain", "02_image12", "03_angle", "04_natural", "05_chinese"]
CELL = 320

items = []
for n in NAMES:
    p = os.path.join(D, n + ".png")
    if os.path.exists(p):
        items.append((n, Image.open(p).convert("RGB")))
    else:
        print("missing:", p)

if not items:
    raise SystemExit("没有可拼的图")

sheet = Image.new("RGB", (CELL * len(items), CELL + 24), (16, 16, 20))
dr = ImageDraw.Draw(sheet)
for i, (n, im) in enumerate(items):
    sheet.paste(im.resize((CELL, CELL), Image.LANCZOS), (i * CELL, 0))
    dr.text((i * CELL + 6, CELL + 6), n, fill=(235, 235, 235))
out = os.path.join(D, "compare.png")
sheet.save(out)
print("saved", out, sheet.size)
