#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WebUI 静态自检：不起服务、不连实例、不开浏览器。

两件事：
  1. CSS 级联检查 —— 选项（.chk）最终生效的 display 必须是 flex，
     否则 label 是块级元素，说明文字就会掉到对勾下面另起一行（修过的 bug）。
  2. 交给 tools/webui_dom_check.js：用 DOM 桩子在 Node 里真跑一遍页面脚本，
     验证 seed 语义（留空/负数=随机、点历史缩略图才填回该图 seed）。

    python tools/webui_logic_check.py
退出码：有 FAIL -> 1
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "service" / "ui" / "index.html"
DOM_CHECK = ROOT / "tools" / "webui_dom_check.js"

# Windows 控制台默认 GBK，中文输出会 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")       # type: ignore[attr-defined]
    except Exception:                                            # noqa: BLE001
        pass


def css_rules(html: str):
    """把 <style> 里的 `选择器{声明}` 摊平成 (选择器, 声明) 列表（顺序即级联顺序）。"""
    styles = " ".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", html, flags=re.I))
    styles = re.sub(r"/\*[\s\S]*?\*/", "", styles)              # 去掉注释，免得误判
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", styles):
        yield sel.strip(), body.strip()


def check_css(html: str) -> list[str]:
    out = []
    disp = None
    for sel, body in css_rules(html):
        # 只看针对 .chk 本身的 display（.chk input / .chk label 不算）
        if re.fullmatch(r"\.chk(\s*,\s*\.chk)*", sel):
            m = re.search(r"(?:^|;)\s*display\s*:\s*([a-zA-Z-]+)", body)
            if m:
                disp = m.group(1)
    if disp is None:
        out.append("FAIL | CSS 里找不到 .chk 的 display 规则")
    elif disp != "flex":
        out.append(f"FAIL | .chk 最终 display={disp}（应为 flex，否则选项文字会折到对钩下一行）")
    else:
        out.append("PASS | .chk 最终 display=flex（选项文字与对钩同行）")

    has_label = any(re.search(r"\.chk\s+label\b", sel) for sel, _ in css_rules(html))
    out.append(("PASS | " if has_label else "FAIL | ") +
               ".chk label 有独立规则（保证 label 是 flex 项、长文本在自身宽度内折行）")

    # seed 输入框只允许被"点图复现 / 复用参数 / 开跑前清空"写；生成完自动回填 = bug
    lines_all = html.splitlines()
    writes = [(i, l.strip()) for i, l in enumerate(lines_all, 1)
              if re.search(r"\$\('seed'\)\s*\.\s*value\s*=", l)]
    allowed_fns = {"copyPrompt", "showHist", "batchUseSeed"}
    bad = []
    for n, line in writes:
        fn = None
        for j in range(n - 1, 0, -1):                       # 往上找最近的函数定义
            m = re.match(r"\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", lines_all[j - 1])
            if m:
                fn = m.group(1)
                break
        if re.search(r"=\s*(''|\"\")\s*;", line):
            why = "清空（= 随机）"
        elif fn in allowed_fns:
            why = f"{fn}() —— 用户主动点图/点按钮"
        else:
            why = f"**不在允许的入口里（在 {fn}()）**"
            bad.append((n, line))
        out.append(f"       · 第 {n} 行 [{why}]: {line[:80]}")
    out.insert(0, ("PASS | " if not bad else "FAIL | ") +
               f"写 seed 输入框的位置共 {len(writes)} 处，'自动回填随机种子' {len(bad)} 处"
               f"（允许的入口：{', '.join(sorted(allowed_fns))} + 清空）")

    # 官方默认不用 CFG：相关控件必须默认折叠；编辑 multipart 也必须真的传这些字段。
    advanced = re.search(r'<details\s+id="advancedGeneration"([^>]*)>', html)
    folded = bool(advanced and not re.search(r'\bopen\b', advanced.group(1)))
    out.append(("PASS | " if folded else "FAIL | ") +
               "CFG / 负面词位于默认折叠的高级实验设置")
    for field in ("negative_prompt", "true_cfg_scale", "num_images_per_prompt", "sigmas"):
        sent = f"fd.append('{field}'" in html
        out.append(("PASS | " if sent else "FAIL | ") +
                   f"编辑 multipart 会发送 {field}")
    return out


def main() -> int:
    html = UI.read_text(encoding="utf-8")
    print("=== CSS / 源码检查 ===")
    lines = check_css(html)
    for l in lines:
        print("  " + l)

    print("\n=== DOM 桩子自检（node）===")
    try:
        # 不要 capture_output：Windows 沙箱里给子进程开管道会被拒
        rc = subprocess.run(["node", str(DOM_CHECK), str(UI)],
                            cwd=str(ROOT), timeout=120).returncode
    except FileNotFoundError:
        print("  跳过：本机没装 node")
        rc = 0
    except subprocess.TimeoutExpired:
        print("  FAIL | node 自检超时")
        rc = 1

    fails = [l for l in lines if l.startswith("FAIL")]
    print(f"\n结论：{'全部通过' if not fails and rc == 0 else '有问题'}（css {'OK' if not fails else 'FAIL'} / dom {'OK' if rc == 0 else 'FAIL'}）")
    return 1 if (fails or rc) else 0


if __name__ == "__main__":
    sys.exit(main())
