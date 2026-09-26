# -*- coding: utf-8 -*-
"""盘点生成/测试产物：本地产物目录 + 远端实例上的输出，逐项列出大小与用途。

只读，不删任何东西。想再生成一次清单随时跑：
    python tools/inventory_outputs.py
    python tools/inventory_outputs.py --no-remote     # 跳过 SSH（离线/无凭据时）
    python tools/inventory_outputs.py --write         # 同时写出 docs/OUTPUTS-INVENTORY.md
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# 本地产物目录 -> 用途说明
LOCAL_DIRS = [
    ("test-data", "全部测试产物：输入图、每轮输出、量化 JSON、接触表"),
    ("reports", "生成的 HTML 报告（单文件、图片内嵌，可直接外发）"),
    ("tmp_refs", "参考图引用语法实验的中间图（P1~P5）"),
]

# 远端要盘点的目录
REMOTE_DIRS = [
    "/root/qwen-image-2.1/outputs",
    "/root/autodl-tmp/imageN_check",
    "/root/autodl-tmp/fix_check",
    "/root/autodl-tmp/follow_check",
    "/root/autodl-tmp/stall_check",
    "/root/qwen-image-2.1/service/ui",
]

# 文档里引用到的产物（删掉会断链）
DOC_REF = [
    "reports/matrix-report.html",
    "reports/webui-preview.png",
    "reports/webui-public.png",
    "reports/webui-tunnel.png",
    "test-data/expr_strip.png",
    "test-data/imageN_check/P1_none.png",
    "test-data/remote_outputs/hug_two_people.png",
    "test-data/report.html",
]


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def scan_local() -> tuple[list[str], int, int]:
    lines = []
    total_bytes = total_files = 0
    for rel, desc in LOCAL_DIRS:
        d = ROOT / rel
        if not d.exists():
            continue
        files = [p for p in d.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        total_bytes += size
        total_files += len(files)
        lines.append(f"### `{rel}/` — {len(files)} 个文件，{human(size)}")
        lines.append("")
        lines.append(f"> {desc}")
        lines.append("")
        # 子目录逐个列
        subs = sorted([p for p in d.iterdir() if p.is_dir()], key=lambda p: p.name)
        if subs:
            lines.append("| 子目录 | 文件数 | 大小 |")
            lines.append("|---|---|---|")
            for s in subs:
                sf = [p for p in s.rglob("*") if p.is_file()]
                sz = sum(p.stat().st_size for p in sf)
                lines.append(f"| `{rel}/{s.name}/` | {len(sf)} | {human(sz)} |")
            lines.append("")
        tops = sorted([p for p in d.iterdir() if p.is_file()], key=lambda p: -p.stat().st_size)
        if tops:
            lines.append(f"顶层散落文件 {len(tops)} 个：")
            lines.append("")
            for p in tops:
                lines.append(f"- `{rel}/{p.name}` — {human(p.stat().st_size)}")
            lines.append("")
    return lines, total_files, total_bytes


def scan_remote() -> tuple[list[str], int, int]:
    lines = []
    try:
        import autodl_run
    except Exception as e:                                             # noqa: BLE001
        return [f"（无法导入 autodl_run：{e}）"], 0, 0
    try:
        autodl_run.load_env_file()
        c = autodl_run.connect(timeout=20)
    except Exception as e:                                             # noqa: BLE001
        return [f"（连不上实例：{e}）—— 用 --no-remote 可跳过"], 0, 0
    try:
        cmd = "; ".join(
            f"echo '___ {d}'; "
            f"if [ -d {d} ]; then find {d} -type f -printf '%s\\n' | awk '{{n++; s+=$1}} "
            f"END {{printf \"%d %d\\n\", n, s}}'; else echo '0 0'; fi"
            for d in REMOTE_DIRS)
        _rc, out, _err = autodl_run.run(c, cmd)
    finally:
        c.close()

    total_files = total_bytes = 0
    cur = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("___ "):
            cur = line[4:]
            continue
        if cur and line:
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit():
                n, s = int(parts[0]), int(parts[1])
                total_files += n
                total_bytes += s
                name = cur.replace("/root/qwen-image-2.1/", "").replace("/root/autodl-tmp/", "autodl-tmp/")
                lines.append(f"| `{name}` | {n} | {human(s)} |")
    return lines, total_files, total_bytes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-remote", action="store_true")
    ap.add_argument("--write", action="store_true", help="写出 docs/OUTPUTS-INVENTORY.md")
    args = ap.parse_args()

    local_lines, lf, lb = scan_local()
    remote_lines, rf, rb = (["（已跳过）"], 0, 0) if args.no_remote else scan_remote()

    md = []
    md.append("# 生成产物清单（只读盘点，不代表已删除）")
    md.append("")
    md.append(f"> 生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M}　"
              f"生成器：`python tools/inventory_outputs.py --write`")
    md.append(">")
    md.append(f"> 本地 {lf} 个文件 / {human(lb)}；远端 {rf} 个文件 / {human(rb)}。"
              f"**这些都不在 git 里**（`test-data/` `reports/` `tmp_refs/` 已 gitignore）。")
    md.append("")
    md.append("## 一、本地产物")
    md.append("")
    md.extend(local_lines)
    md.append("## 二、实例上的产物")
    md.append("")
    md.append("| 路径（相对根） | 文件数 | 大小 |")
    md.append("|---|---|---|")
    md.extend(remote_lines)
    md.append("")
    md.append("## 三、被文档引用的文件（删掉会导致 docs 断链）")
    md.append("")
    for r in DOC_REF:
        p = ROOT / r
        exists = "存在" if p.exists() else "**已不存在**"
        size = f" — {human(p.stat().st_size)}" if p.exists() else ""
        md.append(f"- `{r}`（{exists}{size}）")
    md.append("")
    md.append("## 四、要清理的话，对应的命令")
    md.append("")
    md.append("```bash")
    md.append("# 本地（注意：这份清单里被引用的文件会一起没掉，文档需同步改）")
    md.append("Remove-Item -Recurse -Force test-data, reports, tmp_refs")
    md.append("")
    md.append("# 远端实例：清掉实验输出（不动权重 /root/autodl-tmp/Qwen-Image-2.1）")
    md.append("python tools/autodl_run.py \"rm -rf /root/qwen-image-2.1/outputs/* "
              "/root/autodl-tmp/imageN_check /root/autodl-tmp/fix_check "
              "/root/autodl-tmp/follow_check /root/autodl-tmp/stall_check\"")
    md.append("```")
    md.append("")

    text = "\n".join(md)
    if args.write:
        out = ROOT / "docs" / "OUTPUTS-INVENTORY.md"
        out.write_text(text, encoding="utf-8")
        print(f"已写出 {out.relative_to(ROOT)}")
    else:
        print(text)

    print(f"\n小结：本地 {lf} 个 / {human(lb)}，远端 {rf} 个 / {human(rb)}")
    print("（本次没有删除任何文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
