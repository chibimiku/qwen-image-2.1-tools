# -*- coding: utf-8 -*-
"""提交前检查：复制进仓库的官方文档是否会被 git 的行尾规范化改坏。

  python tools/_check_doc_copy.py

背景：`.gitattributes` 里是 `* text=auto eol=lf`，会用工作区的行尾重算 blob 的
规范化形式。`docs/upstream` 与 `service/ui/docs` 的这两份必须**逐字节一致**——
部署脚本是按 md5 判等的，行尾被规范化就意味着源与副本对不上。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = [
    ("prompt-rewriter-T2I-system-prompt.txt", "docs/upstream", "service/ui/docs"),
    ("prompt-rewriter-I2I-system-prompt.txt", "docs/upstream", "service/ui/docs"),
    ("qwen-image-2.1-hf-modelcard.md", "docs/upstream", "service/ui/docs"),
]
EXTRA = [
    "service/ui/docs/qwen-image-2.1-prompt-rewriting.md",
    "service/ui/docs/README.md",
    "docs/PROMPT-LENGTH-LIMIT.md",
]


def report(rel: str) -> dict:
    b = (ROOT / rel).read_bytes()
    try:
        b.decode("utf-8")
        enc = "utf-8"
    except UnicodeDecodeError as exc:                                   # noqa: PERF203
        enc = f"NOT-UTF8: {exc}"
    return {"path": rel, "bytes": len(b), "crlf": b.count(b"\r\n"),
            "bom": b[:3] == b"\xef\xbb\xbf", "enc": enc,
            "md5": hashlib.md5(b).hexdigest()}


def main() -> int:
    bad = 0
    print("=== 源 ↔ 副本 ===")
    for name, src_dir, dst_dir in PAIRS:
        a = report(f"{src_dir}/{name}")
        b = report(f"{dst_dir}/{name}")
        same = a["md5"] == b["md5"]
        bad += 0 if same else 1
        print(f"  {'一致' if same else '不一致'}  {name}")
        print(f"        upstream {a['bytes']}B CRLF={a['crlf']} {a['enc']} {a['md5'][:10]}")
        print(f"        ui/docs  {b['bytes']}B CRLF={b['crlf']} {b['enc']} {b['md5'][:10]}")

    print("=== 新增文本文件 ===")
    for rel in EXTRA:
        r = report(rel)
        flag = "OK  " if r["enc"] == "utf-8" and not r["bom"] else "BAD "
        if flag == "BAD ":
            bad += 1
        print(f"  {flag} {rel}  {r['bytes']}B CRLF={r['crlf']} BOM={r['bom']} {r['enc']}")

    print()
    print(f"结论: {'通过' if not bad else '%d 项有问题' % bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
