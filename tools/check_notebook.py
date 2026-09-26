#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验生成的笔记本：JSON 可解析、每个代码格语法正确、关键 API 都提到。

    python tools\check_notebook.py
"""
import ast
import json
import os
import re
import sys

NB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "service", "ui", "Qwen-Image-2.1-console.ipynb")

REQUIRED_SNIPPETS = [
    "/v1/images/generations", "/v1/images/edits", "/v1/jobs", "/v1/progress",
    "/health", "QWEN_API_KEY", "6006", "8888", "output_resolution", "serve.sh",
    "jupyter/proxy/6006", "分块 VAE",
]


def main():
    if not os.path.exists(NB):
        print("笔记本不存在:", NB)
        return 1
    nb = json.load(open(NB, encoding="utf-8"))
    print(f"文件: {os.path.basename(NB)}  {os.path.getsize(NB)} bytes")
    print(f"nbformat {nb['nbformat']}.{nb['nbformat_minor']} · {len(nb['cells'])} 格 "
          f"({sum(1 for c in nb['cells'] if c['cell_type']=='code')} code / "
          f"{sum(1 for c in nb['cells'] if c['cell_type']=='markdown')} md)")

    bad = 0
    for i, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code":
            continue
        src = "".join(c["source"])
        try:
            ast.parse(src)
            preview = src.strip().splitlines()[0][:58] if src.strip() else "(空)"
            print(f"  [{i:2d}] OK      {preview}")
        except SyntaxError as e:
            bad += 1
            print(f"  [{i:2d}] SYNTAX  {e.msg} (line {e.lineno})")
            for n, line in enumerate(src.splitlines(), 1):
                if abs(n - (e.lineno or 0)) <= 2:
                    print(f"        {n:3d}| {line}")

    allmd = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
    allcode = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    everything = allmd + "\n" + allcode
    print("\n必需内容检查:")
    for s in REQUIRED_SNIPPETS:
        print(f"  {'✓' if s in everything else '✗'} {s}")
        if s not in everything:
            bad += 1

    print("\n空输出检查（笔记本必须没有预置输出）:")
    outs = [i for i, c in enumerate(nb["cells"]) if c.get("outputs")]
    print("  " + ("没有任何预置输出 ✓" if not outs else f"有输出的格子: {outs} ✗"))

    print("\n结论:", "通过" if bad == 0 else f"{bad} 个问题")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
