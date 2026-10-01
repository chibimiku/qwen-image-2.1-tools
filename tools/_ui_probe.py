# -*- coding: utf-8 -*-
"""看 WebUI 的结构：面板、可复用函数、multipart 写法 —— 为插入「AI 自检」面板做准备。

  python tools/_ui_probe.py
"""
from __future__ import annotations

import pathlib
import re

h = pathlib.Path(__file__).resolve().parents[1] / "service" / "ui" / "index.html"
src = h.read_text(encoding="utf-8")
lines = src.splitlines()

print("=== details 面板 ===")
for i, l in enumerate(lines, 1):
    if "<details" in l or "<summary" in l:
        print(f"  L{i:>5}: {l.strip()[:104]}")

print("\n=== 可复用的小工具函数 ===")
for i, l in enumerate(lines, 1):
    if re.match(r"(async )?function (api|withKey|authHeaders|log|params|refRatio|on401)\b", l):
        print(f"  L{i:>5}: {l.strip()[:96]}")

print("\n=== $ 与 log 的定义 ===")
for i, l in enumerate(lines, 1):
    if re.match(r"(const \$|function \$|function log)", l):
        print(f"  L{i:>5}: {l.strip()[:96]}")

print("\n=== multipart 提交的写法 ===")
for m in re.finditer(r"fd\.append\([^\n]{0,100}", src):
    print("  ", m.group(0)[:130])

print("\n=== 生成入口 run() 里发请求的那段 ===")
i = src.find("async function run(){")
seg = src[i:i + 4200]
j = seg.find("fetch(")
print(seg[max(0, j - 400):j + 900] if j >= 0 else "(没找到 fetch)")
