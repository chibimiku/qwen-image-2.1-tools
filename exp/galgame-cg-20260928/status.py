# -*- coding: utf-8 -*-
"""出图总账：这个包里到底有哪些图、哪个版本是成稿。

  python exp/galgame-cg-20260928/status.py

只做**清点与判定**，不产图。判定规则：
  · out/story-*.png    —— 首轮正片
  · fixed-2/*.png      —— 修复版（在 out/ 基础上重出）
  · **成稿 = 修复版存在就用修复版，否则用首轮**（修复版是针对缺陷重出的）
  · 另有对照/诊断组（control/seed/boost/styleonly/padded/bracket），它们不是成稿
"""
from __future__ import annotations

import json
import pathlib
import sys

EXP = pathlib.Path(__file__).resolve().parent
OUT = EXP / "out"
FIXED = EXP / "fixed-2"

# 正片 12 幕：id -> (标题, 一句话内容)
SCENES = [
    ("01-boutique",      "试衣间·出门前", "站在金框穿衣镜前看自己,手轻搭镜框;店内衣架/木地板"),
    ("02-cafe",          "咖啡厅",       "窗边小圆桌,双手捧冰茶杯,旁边一块草莓蛋糕"),
    ("03-street",        "街上散步",     "沿街走,右手拎牛皮纸购物袋,回头微笑"),
    ("04-icecream",      "海边吃冰淇淋", "海港步道,一手甜筒一手纸巾,背景是船与灯塔"),
    ("05-park",          "公园长椅",     "坐在木长凳上,腿在凳前,秋叶飘落"),
    ("06-sunset-bridge", "落日桥边",     "靠在天桥栏杆上看河面落日与城市剪影"),
    ("07-ferris-wheel",  "摩天轮轿厢",   "坐在轿厢里,一只手贴在窗上,窗外是夜景灯海"),
    ("08-closeup",       "近景特写",     "正脸特写,暖色散景背景"),
    ("09-holding-hands", "牵手的瞬间",   "伸手向镜头,掌心张开、五指分开,夜街"),
    ("10-fireworks",     "看烟花",       "双手交握在胸前,仰望夜空烟花,人群虚化"),
    ("11-rooftop",       "天台夜景",     "晚上加了白色针织开衫,靠在楼顶矮栏上看城市灯火"),
    ("12-goodnight",     "道别",         "路灯下,双手提着小购物袋,一只脚内撇,夜色"),
]

CONTROL_PREFIX = ("control-", "bracket-", "seed-", "boost-", "styleonly-", "padded-",
                  "textonly-")


def main() -> int:
    mf = EXP / "manifest.jsonl"
    recs: dict[str, dict] = {}
    for line in mf.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["name"]] = r

    print("=" * 96)
    print("一、正片 12 幕：内容与成稿判定")
    print("=" * 96)
    print(f"{'幕':<18}{'标题':<14}{'成稿来源':<12}{'文件':<44}缺陷")
    print("-" * 96)

    story = []
    fixed_n = orig_n = 0
    for sid, title, desc in SCENES:
        name = f"story-{sid}"
        o = OUT / f"{name}.png"
        f = FIXED / f"{name}.png"
        if f.exists():
            src, path = "修复版", f
            fixed_n += 1
        elif o.exists():
            src, path = "首轮", o
            orig_n += 1
        else:
            src, path = "**缺失**", None
        print(f"{sid:<18}{title:<14}{src:<12}{str(path.relative_to(EXP)) if path else '—':<44}")
        story.append((sid, title, desc, src, path))

    print()
    print(f"  成稿：修复版 {fixed_n} 张 + 首轮 {orig_n} 张 = {fixed_n + orig_n} 张")

    print()
    print("=" * 96)
    print("二、各幕画的是什么")
    print("=" * 96)
    for sid, title, desc, src, path in story:
        rec = recs.get(f"story-{sid}") or {}
        print(f"  {sid}  {title}")
        print(f"      {desc}")
        print(f"      尺寸 {rec.get('size', '?')}  seed {rec.get('seed', '?')}  "
              f"耗时 {rec.get('seconds', '?')}s  参考图 {rec.get('refs')}")

    print()
    print("=" * 96)
    print("三、非成稿的图（对照 / 诊断组）")
    print("=" * 96)
    groups: dict[str, list[str]] = {}
    for p in sorted(OUT.glob("*.png")):
        nm = p.stem
        if nm.startswith("story-") or nm.startswith("fix-"):
            continue
        g = next((c.rstrip("-") for c in CONTROL_PREFIX if nm.startswith(c)), "其他")
        groups.setdefault(g, []).append(nm)
    for g, items in sorted(groups.items()):
        print(f"  {g:<12} {len(items):>2} 张   {', '.join(items[:6])}"
              + (" …" if len(items) > 6 else ""))
    print(f"  合计 {sum(len(v) for v in groups.values())} 张（这些不是成稿，是对照/诊断用的）")

    print()
    print("=" * 96)
    print("四、还有哪些相关的图")
    print("=" * 96)
    others = [
        ("exp/style-reference-migration-20260927/", "另一组实验：5 画风 × 3 主题 × A–H 八组，300 张"),
        ("exp/galgame-cg-20260928/refs/", "角色图 + 画风参考图（用户素材）"),
        ("exp/galgame-cg-20260928/fixed/", "服务端回路产物（batch_fix 用，目前为空）"),
    ]
    for p, desc in others:
        full = EXP.parent / p if p.startswith("exp/") else EXP / p.split("/")[-2]
        n = len(list(full.glob("*.png"))) if full.exists() else 0
        print(f"  {p:<48} {n:>4} 张 PNG   {desc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
