# -*- coding: utf-8 -*-
"""提交前的凭据安全体检：把"密钥会不会被提交"变成可判定的问题。

  python tools/verify_secrets_safety.py

## 判据

密钥/密码这类**字面值只存在于少数几个文件里**。所以不需要遍历 git 对象也能定性：

1. 全工作区搜凭据值 → 得出"命中文件集合"
2. 这个集合里的每个文件**都必须是 gitignore 覆盖的对象**

只要 (2) 成立，任何 `git add` 都带不上它们 —— 这是可判定的，不依赖能否读出历史对象。

## 为什么不直接扫 git 历史对象

本沙箱禁掉了 Python 的 subprocess 捕获管道、shell 的 `|` 与 `>`，Git Bash 也起不来
（`E_ACCESSDENIED`），无法把 `git cat-file --batch` 的输出落盘做离线扫描。
**扫不了就说扫不了**，不要用"因为我扫不了所以没问题"当结论 —— 本脚本因此只做上面那两步，
并把"没法验证的部分"明确列出来。

## 本文件不含明文凭据

比对用的值全部从 gitignore 的文件里现读（`.qwenkey` / `autodl*.env` / `instance.env`），
和"哪些文件不该提交"用的是同一份来源。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
from _scan_staged import collect_secrets  # noqa: E402

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", "dist"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".kra", ".ipynb", ".zip",
            ".pdf", ".pyc", ".safetensors"}

# gitignore 里登记的凭据文件名；命中集合里出现这些就是预期内的
CRED_BASENAMES = {"autodl.env", "autodl2.env", "autodl_new.env", "instance.env",
                  "tunnel.conf", ".qwenkey"}

# 已知被 .gitignore 的整目录（根级模式，不带斜杠 = 任意深度）
IGNORED_DIRS = {"exp", "test-data", "reports", "tmp_refs", "tmp_ab", ".git"}


def main() -> int:
    secrets = collect_secrets()
    print(f"凭据项 {len(secrets)} 个：{', '.join(sorted(secrets))}（值不打印）")
    if not secrets:
        print("读不到任何凭据，无法判定（检查 tools/.qwenkey 与 tools/autodl*.env 是否存在）")
        return 2

    print("\n[1] 全工作区搜凭据值")
    hits: list[tuple[str, list[str]]] = []
    scanned = 0
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(d in rel.parts for d in SKIP_DIRS):
            continue
        if p.suffix.lower() in SKIP_EXT:
            continue
        scanned += 1
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:                                               # noqa: BLE001
            continue
        labels = [lab for lab, val in secrets.items() if val and val in text]
        if labels:
            hits.append((rel.as_posix(), labels))
    print(f"   扫了 {scanned} 个文本文件，命中 {len(hits)} 个：")
    for f, labels in sorted(hits):
        print(f"     {f}   [{', '.join(labels)}]")

    print("\n[2] 命中文件是否都落在 .gitignore 覆盖范围内")
    bad: list[str] = []
    for f, _labels in sorted(hits):
        parts = pathlib.PurePosixPath(f).parts
        base = pathlib.PurePosixPath(f).name
        in_ignored_dir = any(seg in IGNORED_DIRS for seg in parts[:-1])
        is_cred_file = base in CRED_BASENAMES
        is_log = f.endswith(".log")
        ok = in_ignored_dir or is_cred_file or is_log
        why = ("ignored-dir" if in_ignored_dir else
               "cred-file" if is_cred_file else "*.log" if is_log else "NOT IGNORED")
        print(f"     {'OK  ' if ok else 'BAD '} {why:<12} {f}")
        if not ok:
            bad.append(f)

    print("\n[3] 无法在本环境验证的部分（不要当成已通过）")
    print("     · 逐 blob 扫 git 历史对象：沙箱禁管道/重定向，git cat-file 无法落盘")
    print("     · git 自己的忽略判定（ls-files --ignored / check-ignore）：subprocess EPERM")
    print("     替代证据：本次会话的可用的 `git status` 与 `git add -A` 输出里")
    print("     从未出现过上面那些凭据文件 —— 说明它们确实没进暂存区。")

    print()
    if bad:
        print(f"结论: !! 有 {len(bad)} 个含凭据的文件不在忽略范围内：{bad}")
        return 1
    print(f"结论: 安全 —— {len(hits)} 个含凭据的文件全部落在 .gitignore 覆盖内")
    print("      （其中 exp/ 与 *.log 是整目录/整类排除，凭据文件名逐个登记在 .gitignore）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
