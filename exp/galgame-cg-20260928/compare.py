# -*- coding: utf-8 -*-
"""把同一场景的各配方变体拼成带标注的对照表。

  python exp/galgame-cg-20260928/compare.py

产出 compare-street.png / compare-cafe.png / compare-closeup.png 与 compare-seeds.png。
只做拼版与标注，不改图内容（缩放仅用于展示；原图在 out/ 下原样保留）。
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

EXP = pathlib.Path(__file__).resolve().parent
OUT = EXP / "out"

# PIL 的默认位图字体没有中文字形，直接用会渲染成方框 —— 必须显式加载 CJK 字体。
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",        # 微软雅黑
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf",      # 黑体
    r"C:\Windows\Fonts\simsun.ttc",      # 宋体
]


def load_font(size: int = 15):
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:                                           # noqa: BLE001
                continue
    return ImageFont.load_default()

# 场景 -> [(标签, 文件名前缀)]
SETS = {
    "street": [
        ("A 纯文本\n无任何参考图", "textonly-03-street"),
        ("B 只给角色图\n(对照组)", "control-03-street"),
        ("C 只给画风图", "styleonly-03-street"),
        ("D 双图\n基础样式词", "story-03-street"),
        ("E 双图\n强化样式词", "boost-03-street"),
    ],
    "cafe": [
        ("B 只给角色图\n(对照组)", "control-02-cafe"),
        ("C 只给画风图", "styleonly-02-cafe"),
        ("D 双图\n基础样式词", "story-02-cafe"),
        ("E 双图\n强化样式词", "boost-02-cafe"),
    ],
    "closeup": [
        ("B 只给角色图\n(对照组)", "control-08-closeup"),
        ("C 只给画风图", "styleonly-08-closeup"),
        ("D 双图\n基础样式词", "story-08-closeup"),
        ("E 双图\n强化样式词", "boost-08-closeup"),
    ],
}


def make(name: str, items: list) -> None:
    have = [(lab, OUT / f"{n}.png") for lab, n in items if (OUT / f"{n}.png").exists()]
    if not have:
        print(f"  {name}: 没有可用文件，跳过")
        return
    font = load_font(15)
    tw, th = 700, 392
    lab_h, pad = 40, 10
    sheet = Image.new("RGB", (len(have) * tw + (len(have) + 1) * pad,
                              th + lab_h + 2 * pad), (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    for i, (lab, p) in enumerate(have):
        im = Image.open(p).convert("RGB").resize((tw, th), Image.LANCZOS)
        x = pad + i * (tw + pad)
        sheet.paste(im, (x, pad))
        for k, line in enumerate(lab.split("\n")):
            d.text((x + 4, pad + th + 6 + k * 17), line, fill=(228, 228, 232), font=font)
    out = EXP / f"compare-{name}.png"
    sheet.save(out)
    print(f"  {name}: {len(have)} 格 -> {out.name} {sheet.size}")


def main() -> int:
    print("拼对照表：")
    for name, items in SETS.items():
        make(name, items)

    # seed 稳定性：同一场景（06 桥边日落，强化词）三个 seed
    seeds = [(f"seed {s}", f"seed-{s}") for s in (42, 1234, 20260927)]
    have = [(lab, OUT / f"{n}.png") for lab, n in seeds if (OUT / f"{n}.png").exists()]
    if have:
        make("seeds", seeds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
