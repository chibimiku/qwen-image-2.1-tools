# -*- coding: utf-8 -*-
"""把 out/ 里的出图按"配方分组"拼成检查表，用于逐格排查缺陷。

  python exp/galgame-cg-20260928/sheets.py

分组理由：同一组内的图**只差一个变量**（喂了哪张参考图 / 用了哪套样式词 / 哪个尺寸），
所以组内一眼就能看出"哪一格不对劲"。跨组拼在一张表上会淹没差异。

产出 sheets-<组名>.png，只做拼版与标注，不改图。
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

EXP = pathlib.Path(__file__).resolve().parent
OUT = EXP / "out"

FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
         r"C:\Windows\Fonts\simsun.ttc"]


def font(size: int = 16):
    for p in FONTS:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:                                           # noqa: BLE001
                continue
    return ImageFont.load_default()


# 组名 -> [(标签, 文件名)]
GROUPS = {
    "1-bracket": [
        ("1536x864", "bracket-1536x864"),
        ("1600x896", "bracket-1600x896"),
        ("1600x1024→1504x960", "bracket-1600x1024"),
        ("1600x1152→1408x1024", "bracket-1600x1152"),
        ("1792x1024→1600x896", "bracket-1792x1024"),
        ("2048x1152→1600x896", "bracket-2048x1152"),
        ("2560x1440→1600x896", "bracket-2560x1440"),
    ],
    "2-cafe-四联": [
        ("B 只角色图", "control-02-cafe"),
        ("C 只画风图", "styleonly-02-cafe"),
        ("D 双图基础词", "story-02-cafe"),
        ("E 双图强化词", "boost-02-cafe"),
    ],
    "3-street-五联": [
        ("A 纯文本", "textonly-03-street"),
        ("B 只角色图", "control-03-street"),
        ("C 只画风图", "styleonly-03-street"),
        ("D 双图基础词", "story-03-street"),
        ("E 双图强化词", "boost-03-street"),
    ],
    "4-closeup-四联": [
        ("B 只角色图", "control-08-closeup"),
        ("C 只画风图", "styleonly-08-closeup"),
        ("D 双图基础词", "story-08-closeup"),
        ("E 双图强化词", "boost-08-closeup"),
    ],
    "5-seeds": [
        ("seed 42", "seed-42"),
        ("seed 1234", "seed-1234"),
        ("seed 20260927", "seed-20260927"),
    ],
    "6-padded": [
        ("16:9 裁切参考图 街景", "padded-03-street"),
        ("16:9 裁切参考图 近景", "padded-08-closeup"),
    ],
    "7-正片-上": [
        ("01 试衣镜", "story-01-boutique"),
        ("02 咖啡厅", "story-02-cafe"),
        ("03 街道", "story-03-street"),
        ("04 冰淇淋", "story-04-icecream"),
        ("05 公园", "story-05-park"),
        ("06 落日桥", "story-06-sunset-bridge"),
    ],
    "8-正片-下": [
        ("07 摩天轮", "story-07-ferris-wheel"),
        ("08 近景", "story-08-closeup"),
        ("09 牵手", "story-09-holding-hands"),
        ("10 烟花", "story-10-fireworks"),
        ("11 天台", "story-11-rooftop"),
        ("12 道别", "story-12-goodnight"),
    ],
    "9-修补": [
        ("fix 01 试衣镜", "fix-01-boutique"),
        ("fix 04 冰淇淋", "fix-04-icecream"),
        ("fix 06 落日桥", "fix-06-sunset-bridge"),
    ],
}


def build(name: str, items: list, cols: int, tw: int = 780) -> None:
    have = [(lab, OUT / f"{n}.png") for lab, n in items if (OUT / f"{n}.png").exists()]
    if not have:
        print(f"  {name}: 无文件，跳过")
        return
    f = font(15)
    th = int(tw * 896 / 1600)
    rows = (len(have) + cols - 1) // cols
    pad, lab_h = 8, 24
    sheet = Image.new("RGB",
                      (cols * tw + (cols + 1) * pad, rows * (th + lab_h) + (rows + 1) * pad),
                      (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    for i, (lab, p) in enumerate(have):
        im = Image.open(p).convert("RGB")
        im = im.resize((tw, int(tw * im.height / im.width)), Image.LANCZOS)
        c, r = i % cols, i // cols
        x = pad + c * (tw + pad)
        y = pad + r * (th + lab_h + pad)
        sheet.paste(im, (x, y))
        d.text((x + 4, y + im.height + 4), lab, fill=(228, 228, 232), font=f)
    out = EXP / f"sheets-{name}.png"
    sheet.save(out)
    print(f"  {name}: {len(have)} 格 {cols}列 -> {out.name} {sheet.size}")


def main() -> int:
    print("拼检查表：")
    for name, items in GROUPS.items():
        cols = 2 if len(items) <= 3 else (3 if len(items) <= 12 else 4)
        build(name, items, cols)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
