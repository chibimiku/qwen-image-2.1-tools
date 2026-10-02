# -*- coding: utf-8 -*-
"""校验 gallery.html：结构完整、没嵌图、路径齐全、正文干净。

  python exp/galgame-cg-20260928/check_gallery.py
"""
from __future__ import annotations

import os
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

print("\n=== 图片显示方式 ===")
# 「不嵌图」的正确含义：**不把图塞进 HTML**（不做 base64 内联），
# 而是用 <img src=相对 URL> 引用文件。这样页面只有 30 KB，图按需加载。
# 第一版我把这条理解成"不显示图"，把 <img> 整个去掉了 —— 那是错的。
check("data:image" not in t, "没有 base64 内联图（这是「不嵌图」的本意）")
check("<img" in t, "用 <img> 直接显示图")
srcs = re.findall(r"<img\s+src='([^']+)'", t)
check(len(srcs) >= 16, f"<img> 数量 {len(srcs)}")
check(all(not s.startswith("/") for s in srcs), "src 是相对路径（不是绝对路径）")
# src 相对**页面自身**：link 模式下站点镜像了工作区目录结构，所以形如
# `story/01-entrance.png`（一轮目录，不是裸文件名，也不是 `gallery/...`）。
check(all(s.split("/")[0] in ("story", "story-edited", "fixed-2") for s in srcs),
      "src 的第一段是工作区里的图片目录（story / story-edited / fixed-2）",
      f"异常：{[s for s in srcs if s.split('/')[0] not in ('story','story-edited','fixed-2')]}")
check(not any(s.startswith("gallery/") for s in srcs),
      "src 没有多带站点那一层（`gallery/…` 会 404）")
check(all(s.endswith(".png") for s in srcs), "所有 src 都指向 .png")
check("loading='lazy'" in t, "图片懒加载")
check("alt=" in t, "有 alt 文本（可访问性）")

print("\n=== 站点是链接还是拷贝 ===")
# link 模式：站点里应该是符号链接，指回工作区 —— 这样改图立刻生效、零重复。
SITE = pathlib.Path(os.environ.get("GALLERY_ROOT", r"C:\Users\ashsu\Documents\black\gallery"))
if SITE.exists():
    links, real = [], []
    for s in srcs:
        p = SITE / s
        if p.is_symlink():
            links.append(s)
        elif p.exists():
            real.append(s)
    check(len(links) + len(real) == len(srcs), f"站点里 {len(srcs)} 张图都在",
          f"缺 {len(srcs) - len(links) - len(real)}")
    check(not real, "站点里没有真副本（link 模式应当全是符号链接）",
          f"真文件：{real[:3]}" if real else f"符号链接 {len(links)} 个")
    # 断链检查：链接建了但目标没了，浏览器会 404
    broken = [s for s in links if not (SITE / s).exists()]
    check(not broken, "没有断链（链接目标都还在）",
          f"断链：{broken[:3]}" if broken else "")
else:
    print(f"  --   跳过（站点目录不可见：{SITE}）")

print("\n=== 相对路径解析（浏览器视角）===")
# 这一条是本轮的核心教训：src 的写法本身对，但**相对什么**很关键。
# 页面在 /gallery/，src='gallery/01.png' 会解析成 /gallery/gallery/01.png → 404。
# 我第一次测的是根路径 /gallery/01.png 所以没暴露。
# 所以这里按**浏览器的方式**把 src 相对页面 URL 解析一次，再全部取一遍。
import urllib.parse
import urllib.request

PAGE = os.environ.get("GALLERY_URL", "http://127.0.0.1/gallery/")
resolved = [urllib.parse.urljoin(PAGE, s) for s in srcs]
bad_prefix = [r for r in resolved if "/gallery/gallery/" in r]
check(not bad_prefix, "没有出现重复目录（/gallery/gallery/…）",
      f"重复：{bad_prefix[:2]}" if bad_prefix else "")

try:
    fails_http = []
    for r in resolved:
        req = urllib.request.Request(r, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    fails_http.append((r, resp.status))
        except Exception as exc:                                        # noqa: BLE001
            code = getattr(exc, "code", "?")
            fails_http.append((r, code))
    check(not fails_http, f"浏览器视角下 {len(resolved)} 张图全部 HTTP 200",
          f"失败：{fails_http[:3]}" if fails_http else "（站点在跑）")
except Exception as exc:                                                # noqa: BLE001
    print(f"  --   跳过 HTTP 检查（连不上 {PAGE}：{exc}）")

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
