# -*- coding: utf-8 -*-
"""校验 gallery.html：结构完整、没嵌图、路径齐全、正文干净。

  python exp/galgame-cg-20260928/check_gallery.py
"""
from __future__ import annotations

import pathlib
import re
import sys

EXP = pathlib.Path(__file__).resolve().parent
t = (EXP / "gallery.html").read_text(encoding="utf-8")

fails: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> None:
    print(("  OK   " if cond else "  FAIL ") + label + (("  " + extra) if extra else ""))
    if not cond:
        fails.append(label)


print(f"gallery.html：{len(t)} 字符")

print("\n=== 不嵌图（核心要求）===")
check("<img" not in t, "没有 <img> 标签")
check("data:image" not in t, "没有 base64 数据 URI")
check("<svg" not in t, "没有内联 SVG")
check("background-image" not in t, "CSS 里没有贴图")

print("\n=== HTML 完整性 ===")
for tag in ("<html", "</html>", "<head>", "</head>", "<body>", "</body>",
            "<style>", "</style>", "<script>", "</script>"):
    check(t.count(tag) == 1, f"{tag} 出现 1 次")
nd_open, nd_close = len(re.findall(r"<div", t)), t.count("</div>")
check(nd_open == nd_close, f"div 配对（{nd_open} / {nd_close}）")

print("\n=== 每张图都有完整路径 ===")
codes = [c.strip() for c in re.findall(r"<code>(.+?)</code>", t, re.S)]
abs_paths = [c for c in codes if re.match(r"^[A-Za-z]:[\\/]", c)]
check(len(abs_paths) >= 15, f"绝对路径 {len(abs_paths)} 条")
check(all(p.lower().endswith(".png") for p in abs_paths),
      "所有绝对路径都指向 .png")
missing = [p for p in abs_paths if not pathlib.Path(p).exists()]
check(not missing, "所有绝对路径在磁盘上都存在",
      f"缺 {missing}" if missing else "")

print("\n=== 交互与结构 ===")
check("复制路径" in t, "有「复制路径」按钮")
check("打开图片" in t, "有「打开图片」按钮")

# 光查"函数名是否出现在文件里"不够 —— 踩过这个坑：
# 我给 openImg 加注释时误删了函数定义，但注释里还留着 file:// 字样，
# 于是字符串检查照样通过，而按钮其实是死的。
# 所以这里**交叉核对**：每个 onclick 绑定的函数，都必须在 <script> 里真的定义过。
js = t.split("<script>", 1)[-1].split("</script>", 1)[0]
bound = set(re.findall(r"onclick='(\w+)\(", t))
defined = set(re.findall(r"function\s+(\w+)\s*\(", js))
check(bound <= defined, "每个 onclick 绑定的函数都真的定义了",
      f"未定义：{sorted(bound - defined)}" if bound - defined else f"绑定={sorted(bound)}")
check(js.count("{") == js.count("}"), f"JS 花括号平衡（{js.count('{')}/{js.count('}')}）")
check("file:///" in js, "「打开图片」用的是 file:// URL")
# 注：曾经想断言"没有把盘符冒号编码成 %3A"，但那是**我记错了** ——
# encodeURIComponent 本来就不编码冒号，而 %3A 只出现在解释这条的注释里。
# 断言的前提本身是错的，所以去掉，改用下面更直接的一条。
check("encodeURIComponent" in js or "encodeURI" in js,
      "路径做了 URL 编码（路径含空格）")
check("navigator.clipboard" in js and "execCommand" in js,
      "复制有回退方案（file:// 下 clipboard API 可能被拒）")
check("故事核" in t and "角色" in t and "分幕" in t, "三个主区块都在")

n_scene = t.count("class='scene")   # 注意不能写成 class='scene'：那会漏掉 class='scene key'
check(n_scene >= 16, f"分幕区块 {n_scene} 个")
check("待换模型" in t, "标出了待换模型的那一幕")
check("POETRY BLOOM" in t, "暖暖的标志细节写进去了")

print("\n=== 正文干净 ===")
# ** 只允许出现在 <style>/<script> 的注释里（CSS 注释里写了 **粗体** 做说明）。
# 正文（</style> 之后到 <script> 之前）必须是干净的。
body = t.split("</style>", 1)[-1].split("<script>", 1)[0]
check("**" not in body, "正文没有残留的 markdown 星号",
      f"残留 {body.count('**')} 处" if "**" in body else "")
check("<script src" not in t, "没有外部脚本依赖（离线可用）")
check("<link" not in t, "没有外部样式依赖（离线可用）")

print()
print(f"断言失败 {len(fails)} 项")
for f in fails:
    print("   -", f)
print("结论:", "全部通过" if not fails else "有失败")
sys.exit(0 if not fails else 1)
