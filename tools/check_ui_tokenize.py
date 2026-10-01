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

    # 函数返回类型一致性：`_parse_gen_request` 返回 dict，调用处不能当元组解包。
    # 这个错实测真的犯过 —— 端点直接 500（ValueError: too many values to unpack）。
    m = re.search(r"async def _parse_gen_request\([^)]*\)\s*->\s*([^:]+):", src)
    if m:
        ret = m.group(1).strip()
        calls = re.findall(r"^.*?=\s*await _parse_gen_request\(.*$", src, re.M)
        bad = [c.strip() for c in calls if c.count("=") > 1 and ret.startswith("Dict")]
        check(not bad, f"_parse_gen_request 返回 {ret}，调用处没有多值解包"
                       + (f"（问题行：{bad}）" if bad else ""))
    # 顺带：文件是否能过 ast（重复一次，防止后加的段落破坏语法）
    try:
        ast.parse(src)
        check(True, "server.py 语法（复检）")
    except SyntaxError as exc:
        check(False, f"server.py 语法（复检）：{exc}")
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

    # ── 「AI 自检」面板 ────────────────────────────────────────────────────
    print("=== AI 自检面板 ===")
    for needle in ('id="aiwrap"', 'id="aikey"', 'id="aibase"', 'id="aimodel"',
                   'id="airounds"', 'id="aiscore"', 'id="aistart"',
                   'function loadVisionConfig', 'function saveVisionConfig',
                   'function testVision', 'function startAutoLoop',
                   'function pollAutoLoop', "api('/v1/auto/start')",
                   "api('/v1/vision/config')", "api('/v1/vision/test')"):
        check(needle in h, f"存在 {needle}")

    # key 只进不回显：**绝不**把 key 回填进输入框。
    # 注意：`$('aikey').value = ''`（保存后清空）是允许的，甚至是必须的 ——
    # 这里只把"赋成非空值"当成违规。
    assigns = re.findall(r"\$\(\s*'aikey'\s*\)\s*\.value\s*=\s*([^;]+);", h)
    assigns += re.findall(r"getElementById\(\s*['\"]aikey['\"]\s*\)\s*\.value\s*=\s*([^;]+);", h)
    bad_assigns = [a for a in assigns if a.strip().strip("'\"") != ""]
    check(not bad_assigns,
          f"绝不把 key 回填到输入框（清空 {len(assigns) - len(bad_assigns)} 处没问题，"
          f"赋非空值 {len(bad_assigns)} 处）")

    # loadVisionConfig 只消费 has_key，不消费 api_key。
    # 切片要切到**下一个 function 定义**为止，不能只取固定长度 —— 否则会把
    # saveVisionConfig 里的 api_key 误算进来（这个坑踩过）。
    seg = h.split("async function loadVisionConfig", 1)
    if len(seg) > 1:
        rest = seg[1]
        nxt = re.search(r"\n(async\s+)?function\s", rest)
        body = rest[:nxt.start()] if nxt else rest[:2000]
        # 只查**代码用法**，不查注释 —— 注释里写"绝不碰 api_key"会被字面匹配误伤（踩过）
        code = "\n".join(l.split("//")[0] for l in body.splitlines())
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
        check("api_key" not in code, "loadVisionConfig 不消费 api_key 字段")
        check("has_key" in code, "loadVisionConfig 读 has_key 布尔值")
    else:
        check(False, "loadVisionConfig 存在")

    print()
    print(f"结论: {'通过' if not fails else '有 %d 项失败' % len(fails)}")
    for f in fails:
        print("   -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
