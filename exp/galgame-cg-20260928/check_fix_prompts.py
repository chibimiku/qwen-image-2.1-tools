# -*- coding: utf-8 -*-
"""自检 fixed-prompts.json：必须四段齐全，否则不许发出去。

  python exp/galgame-cg-20260928/check_fix_prompts.py

这个检查是补上"忘了拼四段"那个坑的护栏：
第一版只发了场景段，模型退回白底立绘，story-12 的纯白像素从 0% 涨到 88%。
"""
from __future__ import annotations

import json
import pathlib
import sys

EXP = pathlib.Path(__file__).resolve().parent
d = json.loads((EXP / "fixed-prompts.json").read_text(encoding="utf-8"))

REQUIRED = {
    "分工声明": "STYLE SAMPLE ONLY",
    "样式词": "galgame",
    "禁止清单": "Do NOT copy from <image2>",
    "角色圣经": "indigo-blue hair",
}

bad = 0
print(f"{'图':<24} {'段数':<5} {'tier':<7} 必备要素")
for name, it in sorted(d.items()):
    prompt = it["prompt"]
    secs = [x for x in prompt.split("\n\n") if x.strip()]
    missing = [k for k, v in REQUIRED.items() if v not in prompt]
    ok = len(secs) >= 4 and not missing
    if not ok:
        bad += 1
    print(f"{name:<24} {len(secs):<5} {it.get('style_tier', 'base'):<7} "
          f"{'OK' if ok else '缺 ' + ','.join(missing)}")

print()
if bad:
    print(f"!! {bad} 张不合格，不要发出去")
else:
    print(f"全部 {len(d)} 张四段齐全，要素齐备")

print("\n=== 抽查 story-12 的第四段 ===")
print(d["story-12-goodnight"]["fourth"][:700])
sys.exit(1 if bad else 0)
