# -*- coding: utf-8 -*-
"""提交前的凭据扫描：查"值"，但**不把值写进本文件**。

  git diff --cached --name-only --output=tools/_staged.txt
  python tools/_scan_staged.py

为什么不用 `tools/scan_secrets.py`：那支按模式扫全仓库，会把已 gitignore 的
autodl*.env、.qwenkey 也报出来 —— 那些本来就不会进提交，噪音大。这支只看
**将提交的文件**。

**关键约束：本文件会被提交，所以不能出现任何明文凭据**（哪怕是以"用来搜索"的名义）。
需要比对的字面值一律从 gitignore 的文件里现读：
  · 密钥       ← tools/.qwenkey（已忽略）
  · 实例密码   ← tools/autodl*.env（已忽略）
  · 实例主机   ← 同上
这样"搜什么"和"别提交什么"用的是同一份来源，本文件自身永远是干净的。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
LIST = TOOLS / "_staged.txt"

# 会被暂存的凭据文件名（出现即报，不看内容）
CRED_FILES = {"autodl.env", "autodl2.env", "autodl_new.env", "instance.env",
              "tunnel.conf", ".qwenkey", "tools/.qwenkey"}
TEXT_SKIP = {".png", ".jpg", ".jpeg", ".webp", ".ipynb", ".kra"}

# 与具体值无关的结构性模式
STRUCTURAL = {
    "AUTODL_PASS 赋值": re.compile(r"AUTODL_PASS\s*=\s*\S+"),
    "私钥块": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    "Bearer 长串": re.compile(r"Bearer\s+[A-Za-z0-9_\-]{25,}"),
    "会话令牌": re.compile(r"qwensess=[A-Za-z0-9_\-]{10,}"),
}


def collect_secrets() -> dict[str, str]:
    """从 gitignore 的文件里读出真实凭据值，用于比对。本文件不保存它们的字面量。"""
    found: dict[str, str] = {}

    key_file = TOOLS / ".qwenkey"
    if key_file.exists():
        for line in key_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                found["API key 值"] = line
                break

    for name in ("autodl_new.env", "autodl.env", "autodl2.env"):
        p = TOOLS / name
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if k.strip() == "AUTODL_PASS" and len(v) >= 6:
                found["实例密码值"] = v
            elif k.strip() == "AUTODL_HOST" and len(v) >= 10:
                found["实例主机名"] = v

    inst = TOOLS / "instance.env"
    if inst.exists():
        for raw in inst.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if "=" in line and line.split("=", 1)[0].strip() == "SSH_PORT":
                v = line.split("=", 1)[1].strip()
                if v.isdigit():
                    found["SSH 端口"] = v
    return found


def main() -> int:
    if not LIST.exists():
        print("先跑：git diff --cached --name-only --output=tools/_staged.txt")
        return 2
    names = [n.strip() for n in LIST.read_text(encoding="utf-8").splitlines() if n.strip()]
    secrets = collect_secrets()
    print(f"将提交 {len(names)} 个文件；比对用凭据 {len(secrets)} 项"
          f"（{', '.join(sorted(secrets))}）")

    self_rel = "tools/_scan_staged.py"
    hits = []
    for n in names:
        p = ROOT / n
        if not p.exists() or p.suffix.lower() in TEXT_SKIP:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:                                        # noqa: BLE001
            print(f"  跳过（读不了）：{n} {type(exc).__name__}")
            continue
        if n == self_rel:
            continue                      # 本文件只从 gitignore 源读值，不会含明文
        for label, value in secrets.items():
            if value in text:
                i = text.index(value)
                ctx = text[max(0, i - 45):i + len(value) + 20].replace("\n", " ")
                hits.append((n, label, ctx))
        for label, pat in STRUCTURAL.items():
            m = pat.search(text)
            if m:
                ctx = text[max(0, m.start() - 45):m.end() + 25].replace("\n", " ")
                hits.append((n, label, ctx))

    leaked = [n for n in names if n.replace("\\", "/") in CRED_FILES
              or pathlib.PurePosixPath(n).name in CRED_FILES]
    if leaked:
        hits.append(("<暂存区>", "凭据文件被暂存", ", ".join(leaked)))

    if hits:
        print("!! 命中：")
        for n, label, ctx in hits:
            print(f"   {n}  [{label}]  …{ctx}…")
        return 1
    print("干净：没有凭据字面值、Bearer 长串、私钥块或会话令牌；")
    print("       也没有把 autodl*.env / instance.env / tunnel.conf / .qwenkey 暂存进来")
    return 0


if __name__ == "__main__":
    sys.exit(main())
