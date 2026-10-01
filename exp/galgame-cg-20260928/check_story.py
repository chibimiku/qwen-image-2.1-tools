# -*- coding: utf-8 -*-
"""校验 STORY.md：只查高价值、不易误报的东西。

  python exp/galgame-cg-20260928/check_story.py

为什么把检查降得这么简单：前几版想"精确解析表格结构与清单对账"，
结果每次我自己调整文档格式，正则就失效并报假失败（连着误报三次）。
**文档校验的价值在于抓真错，不在于把结构写死** —— 所以这里只保留：
分镜编号齐全、markdown 平衡、CG 名有定义、分级与标记存在。
"""
from __future__ import annotations

import pathlib
import re
import sys

EXP = pathlib.Path(__file__).resolve().parent
t = (EXP / "STORY.md").read_text(encoding="utf-8")
lines = t.splitlines()

fails: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> None:
    print(("  OK   " if cond else "  FAIL ") + label + (("  " + extra) if extra else ""))
    if not cond:
        fails.append(label)


print(f"STORY.md：{len(t)} 字符 / {len(lines)} 行")

print("\n=== 分镜 ===")
scenes = re.findall(r"^####\s+(\d+\w?)\s*·?\s*(.*)$", t, re.M)
nums = sorted({s.lower() for s, _ in scenes})
for sid, title in scenes:
    print(f"  {sid:<5} {title}")
check(len(scenes) >= 14, f"分镜 {len(scenes)} 条（应≥14）")

# 编号体系：主编号 01–14；分支幕用字母后缀（07A/07B、10A/10B、13A/13B），
# 这种幕**没有**独立的纯数字标题，所以不能要求 01..14 全部单独出现。
base = {re.match(r"^(\d+)", n).group(1) for n in nums if re.match(r"^\d+", n)}
want_base = {f"{i:02d}" for i in range(1, 15)}
missing_base = sorted(want_base - base, key=int)
check(not missing_base, f"主编号覆盖 01–14（缺 {missing_base or '无'}）")
branches = sorted(n for n in nums if not n.isdigit())
check(len(branches) >= 4, f"分支编号 {branches}（应≥4）")

print("\n=== markdown 平衡 ===")
bad = [i for i, l in enumerate(lines, 1) if l.count("**") % 2 == 1]
check(not bad, "粗体标记成对", f"问题行 {bad}" if bad else "")
# 反引号要**排除代码块围栏行** —— ``` 是三连，会破坏奇偶检查（踩过这个误报）
body = [l for l in lines if not l.strip().startswith("```")]
bad_tick = [i for i, l in enumerate(body, 1) if l.count("`") % 2 == 1]
check(not bad_tick, "正文反引号成对（已排除代码块围栏）",
      f"问题行 {bad_tick}" if bad_tick else "")
check(t.count("```") % 2 == 0, "代码块围栏成对")

print("\n=== CG 名有定义 ===")
# 正文里提到的 CG 名，必须在某处被"定义"过（清单表或分镜标题里出现同名前缀）
mentioned = {m for m in re.findall(r"`(\d+\w?[-a-z0-9]*)`", t) if re.match(r"^\d", m)}
defined = {s.lower() for s, _ in scenes} | set(
    re.findall(r"^\|\s*(\d+\w?)\s*\|", t, re.M))
undefined = sorted(m for m in mentioned
                   if m.split("-")[0].lower() not in defined)
check(not undefined, f"引用的 CG 名都有定义", f"未定义：{undefined}" if undefined else "")

print("\n=== 分级与标记 ===")
for tag in ("显式", "轻度", "一般"):
    n = t.count(tag)
    print(f"  {tag}：出现 {n} 次")
check(t.count("R18") > 0, "标注了分级 R18")
check(t.count("需补") > 0, f"标注了需补的图（{t.count('需补')} 次）")
check("已有" in t, "标注了可复用的图")

print("\n=== 剧本要素 ===")
for key, desc in (("故事核", "有故事核"),
                  ("女主角设定", "有角色设定（跨图一致性基准）"),
                  ("分支点", "有分支设计"),
                  ("连续性", "有连续性检查表"),
                  ("台词", "有台词/旁白")):
    check(key in t, desc)

print()
print(f"断言失败 {len(fails)} 项")
for f in fails:
    print("   -", f)
print("结论:", "全部通过" if not fails else "有失败")
sys.exit(0 if not fails else 1)
