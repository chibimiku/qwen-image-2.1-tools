# -*- coding: utf-8 -*-
"""对比"活的实验包"与 dist/ 里那份解包快照，确认哪些文件不同步。

  python tools/verify_exp_dist_snapshot.py

背景：zip 已被解压到 `dist/style-reference-migration-20260927/`，原 zip 已删除。
快照是在打包那一刻做的，之后实验包里的文件继续被改过（如 REPORT.md 更大、
ANALYSIS 里多了 rate-sheets 等），所以**快照不是权威副本**。
这个脚本逐文件比 md5，把差异列清楚，避免有人误删活的包。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "exp" / "style-reference-migration-20260927"
SNAP = PKG / "dist" / PKG.name

SKIP_DIRS = {"dist", "__pycache__", ".git"}


def md5(p: pathlib.Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def walk(root: pathlib.Path) -> dict[str, pathlib.Path]:
    out = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        out[rel.as_posix()] = p
    return out


def main() -> int:
    if not SNAP.exists():
        print(f"没有解包快照：{SNAP}")
        return 2
    live = walk(PKG)
    snap = walk(SNAP)
    print(f"活包 {len(live)} 个文件（不含 dist/）")
    print(f"快照 {len(snap)} 个文件")

    only_live = sorted(set(live) - set(snap))
    only_snap = sorted(set(snap) - set(live))
    common = sorted(set(live) & set(snap))

    diff = []
    for rel in common:
        if md5(live[rel]) != md5(snap[rel]):
            diff.append(rel)

    print(f"\n只在活包里（快照之后新增/改动）：{len(only_live)}")
    for r in only_live[:15]:
        print(f"   + {r}")
    if len(only_live) > 15:
        print(f"   … 其余 {len(only_live) - 15} 个")

    print(f"\n内容不同（同名但 md5 不一样）：{len(diff)}")
    for r in diff[:20]:
        a, b = live[r].stat().st_size, snap[r].stat().st_size
        print(f"   ≠ {r}   活包 {a:,} B / 快照 {b:,} B")
    if len(diff) > 20:
        print(f"   … 其余 {len(diff) - 20} 个")

    print(f"\n只在快照里：{len(only_snap)}")
    for r in only_snap[:10]:
        print(f"   - {r}")

    print("\n[结论]")
    if diff or only_live or only_snap:
        print("   快照落后于活包 —— 它是打包那一刻的副本，不是权威版本。")
        print("   **不要删活的实验包**（exp/style-reference-migration-20260927/ 下除 dist/ 的部分），")
        print("   那是本次实验唯一的权威产物；dist/ 里这份是历史归档，可留可删。")
    else:
        print("   两者一致（除 dist/ 自身外无差异）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
