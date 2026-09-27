# -*- coding: utf-8 -*-
"""控制台改动自检：语法、端点、以及 JS 关键调用是否都接上了。

  python tools/check_ui_tokenize.py

检查项：
  · server.py 能被 ast 解析，/v1/tokenize 路由与预算常量存在
  · index.html 里计数相关的 id/函数/监听都在，且 run() 里有发送前拦截
  · JS 里用到的 log(...) 级别、$() 目标 id 都存在（改 UI 最容易踩的坑）
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER = ROOT / "service" / "server.py"
UI = ROOT / "service" / "ui" / "index.html"

fails: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fails.append(label)


def main() -> int:
    print("=== server.py ===")
    src = SERVER.read_text(encoding="utf-8")
    try:
        ast.parse(src)
        check(True, "parses")
    except SyntaxError as exc:
        check(False, f"parses ({exc})")
        return 1
    check("/v1/tokenize" in src, "路由 /v1/tokenize 存在")
    check("@app.post(\"/v1/tokenize\")" in src, "是 POST")
    check("MAX_PROMPT_POSITIONS" in src and "PROMPT_SAFE_POSITIONS" in src, "预算常量存在")
    check("_check_auth(request)" in src.split("@app.post(\"/v1/tokenize\")")[1][:900],
          "tokenize 走了鉴权守卫")
    check("Qwen3VLProcessor" in src or "AutoProcessor.from_pretrained" in src,
          "用 transformers 的 processor 分词")
    check("prompt_template_t2i" in src, "模板取自管线属性而非硬编码")
    # 路由顺序：/v1/style-docs 必须在 /v1/style-docs/{name} 之前（否则索引页被参数路由吃掉）
    i_idx = src.find('@app.get("/v1/style-docs", response_class=HTMLResponse)')
    i_var = src.find('@app.get("/v1/style-docs/{name}")')
    check(i_idx != -1 and i_var != -1 and i_idx < i_var,
          "style-docs 索引路由在参数路由之前")

    print("=== index.html ===")
    h = UI.read_text(encoding="utf-8")
    for needle in ('id="tokline"', 'id="docrow"', 'function scheduleTokenize',
                   'function requestTokenize', 'function renderTok',
                   "api('/v1/tokenize')", "addEventListener('input', scheduleTokenize)"):
        check(needle in h, f"存在 {needle}")

    run_body = h.split("async function run(){", 1)
    check(len(run_body) > 1 and "over_limit" in run_body[1][:3000],
          "run() 里有发送前长度拦截")
    check("d.over_safe" in run_body[1][:3000] if len(run_body) > 1 else False,
          "run() 里有安全线二次确认")

    # log() 支持的级别（第二个参数叫 kind，别写成 lvl）
    m = re.search(r"function log\(([^)]*)\)\s*\{", h)
    if m:
        body = h[m.start():m.start() + 600]
        kinds = set(re.findall(r"kind\s*===\s*'([a-z]+)'", body))
        for used in ("err", "ok", "warn"):
            if re.search(r"log\([^)]*,\s*'%s'\)" % used, h) or \
               re.search(r"log\(`[^`]*`[^)]*,\s*'%s'\)" % used, h, re.S):
                check(used in kinds, f"log(...,'{used}') 有专属颜色（log 识别：{sorted(kinds)}）")

    # $() 引用的 id 是否都存在（防拼错）
    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', h))
    used_ids = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", h))
    missing = sorted(u for u in used_ids if u not in ids)
    check(not missing, f"$() 引用的 id 都存在（缺：{missing}）")

    print()
    print(f"结论: {'通过' if not fails else '有 %d 项失败' % len(fails)}")
    for f in fails:
        print("   -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
