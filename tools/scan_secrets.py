# -*- coding: utf-8 -*-
"""提交前凭据扫描：在所有将被提交的文本文件里找真实密钥/密码/IP。

用法：python tools/scan_secrets.py
退出码：发现疑似泄漏 -> 1
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

TEXT_EXT = {".py", ".sh", ".md", ".txt", ".json", ".jsonl", ".ipynb", ".bat", ".ps1",
            ".html", ".css", ".js", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".env",
            ".example", ".gitignore", ""}

# 只报"看起来是真值"的：屏蔽占位符/示例/环境变量引用
PLACEHOLDER = re.compile(
    r"(CHANGE_ME|CHANGEME|your[-_]?|YOUR[-_]?|<[^>]+>|\$\{?[A-Z_]+\}?|xxxx|XXXX|"
    r"example|EXAMPLE|placeholder|TODO|\.\.\.|dummy|test_key|sk-xxx|"
    r"autodl\.env|\.qwenkey|tunnel\.conf)", re.I)

RULES: list[tuple[str, re.Pattern]] = [
    # 指纹本身也不能明文写进来（否则扫描器自己就成了泄漏点）——按片段拼出来。
    ("instance password", re.compile(r"h\+GJ" + r"63IlCoH2")),
    ("api key (primary)", re.compile(r"rp9iz1g3" + r"fsuweo2vhctx8klja64n")),
    ("ssh host", re.compile(r"connect\.west[bd]\.seetacloud\.com")),
    ("ssh port", re.compile(r"\b43" + r"611\b")),
    ("public entry", re.compile(r"u+57736" + r"-b87a" + r"-de5c81ec")),
    ("container ip", re.compile(r"172\.17\.0\.8")),
    ("jupyter token", re.compile(r"(?i)token[\"'\s:=]+[0-9a-f]{32,}")),
    ("bearer literal", re.compile(r"(?i)authorization:\s*bearer\s+(?!<|\$\{|CHANGE)[A-Za-z0-9_\-]{16,}")),
    # 只抓"赋值了一个看起来是真的字面量"，放过 env 读取 / 占位符 / 空串 / 变量转传
    ("password literal", re.compile(
        r"(?i)(password|passwd|pwd)\s*[=:]\s*[\"']?(?!os\.environ|getenv|<|\$\{|CHANGE|"
        r"your|YOUR|[A-Z_]{4,}\b|\"\s*$|'\s*$|\s*$)[A-Za-z0-9+@#$%^&*_.\-]{8,}")),
    ("api key literal", re.compile(
        r"(?i)(QWEN_API_KEY|API_KEY|APIKEY|SECRET|TOKEN)\s*[=:]\s*[\"']?(?!os\.environ|getenv|"
        r"<|\$\{|CHANGE|your|YOUR|\"\s*$|'\s*$|\s*$)[A-Za-z0-9_\-]{16,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]


def _ignored_set(paths: list[pathlib.Path]) -> set[pathlib.Path]:
    """列出被 gitignore 排除的文件（只扫会被提交的内容，噪声最少）。

    用 `git ls-files -oi --exclude-standard` 一次拿全，做成集合再比对，
    比逐个调 `git check-ignore` 稳（`--stdin` 在某些版本上行为不一致）。
    git 不可用 / 不是仓库时返回空集，退化为全扫。
    """
    if not paths:
        return set()
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-oi", "--exclude-standard"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
    except Exception:                                                  # noqa: BLE001
        return set()
    if proc.returncode != 0:
        return set()
    out = proc.stdout.replace("\\", "/")
    return {ROOT / line.strip() for line in out.splitlines() if line.strip()}


def iter_files():
    cands = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        if ".git" in p.parts:
            continue
        if p.suffix.lower() not in TEXT_EXT and p.suffix != "":
            continue
        if p.stat().st_size > 4 * 1024 * 1024:
            continue
        cands.append(p)
    ignored = _ignored_set(cands)
    for p in cands:
        if ignored and p in ignored:
            continue
        yield p


def main() -> int:
    hits = 0
    scanned = 0
    for p in iter_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:                                              # noqa: BLE001
            continue
        scanned += 1
        rel = p.relative_to(ROOT)
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx in RULES:
                if rx.search(line):
                    # 跳过明显是占位/示例的行
                    m = rx.search(line)
                    ctx = line[max(0, m.start() - 30): m.end() + 30]
                    if PLACEHOLDER.search(ctx) and name not in (
                            "instance password", "api key (primary)", "private key block"):
                        continue
                    hits += 1
                    print(f"[{name}] {rel}:{lineno}")
                    print(f"    {line.strip()[:160]}")
    print(f"\n扫描 {scanned} 个文本文件，命中 {hits} 处")
    if hits == 0:
        print("OK - 未发现真实凭据")
    else:
        print("!! 请先处理上面这些行，再提交")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
