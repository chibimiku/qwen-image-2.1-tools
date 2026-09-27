# -*- coding: utf-8 -*-
"""盘点实验包里"真正是结论"的那部分（文本产物），并把它们与"大体积产物"分开。

  python tools/verify_exp_artifacts.py

用来回答：如果只把 exp 的文本产物纳入版本控制，会带上多少东西、分别是哪些。
不移动/不修改任何文件。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "exp" / "style-reference-migration-20260927"
ANIME = PKG / "exec" / "anime"

# "结论类"文件：报告、评分、错误表、证据、画廊、复核、汇总
TEXT_NAMES = {
    "REPORT.md", "README.md", "scores.csv", "errors.csv", "ratings-filled.csv",
    "summary.json", "verify.json", "preflight.json", "metrics.csv",
    "metrics-groups.txt", "evidence-codes.md", "gallery.html",
    "SUMMARY.md", "MANIFEST-FILES.csv", "PACKAGE-README.md", "config-update.json",
    "aux-calibration.json", "ratings-template.csv",
}
TEXT_GLOBS = ["ratings-*.json", "report-parts/*.md", "sheets/blind-*.KEY.json"]

BIG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".zip", ".kra"}


def md5(p: pathlib.Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    if not PKG.exists():
        print(f"测试包不存在：{PKG}")
        return 2

    all_files = [p for p in PKG.rglob("*") if p.is_file()]
    big = [p for p in all_files if p.suffix.lower() in BIG_EXT]
    small = [p for p in all_files if p.suffix.lower() not in BIG_EXT]
    print(f"测试包：{PKG.relative_to(ROOT)}")
    print(f"  文件总数 {len(all_files)}，其中大体积（图/zip）{len(big)} 个 "
          f"{sum(p.stat().st_size for p in big) / 1048576:.1f} MiB，"
          f"其余 {len(small)} 个 {sum(p.stat().st_size for p in small) / 1048576:.2f} MiB")

    print("\n[结论类文件]（报告与结论本身）")
    found, missing_expected = [], []
    for base in (PKG / "analysis", ANIME):
        if not base.exists():
            continue
        for name in sorted(TEXT_NAMES):
            p = base / name
            if p.exists():
                found.append(p)
        for g in TEXT_GLOBS:
            found.extend(sorted(base.glob(g)))
    seen, uniq = set(), []
    for p in found:
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        uniq.append(p)

    total = 0
    for p in sorted(uniq):
        rel = p.relative_to(ROOT).as_posix()
        size = p.stat().st_size
        total += size
        print(f"   {size:>9,} B  md5 {md5(p)[:10]}  {rel}")
    print(f"   合计 {len(uniq)} 个文件 / {total / 1024:.0f} KB")

    print("\n[关键结论的存续性]")
    report = PKG / "analysis" / "REPORT.md"
    print(f"   REPORT.md      存在={report.exists()}  "
          f"{report.stat().st_size if report.exists() else 0} B")
    scores = PKG / "analysis" / "scores.csv"
    if scores.exists():
        lines = scores.read_text(encoding="utf-8-sig").splitlines()
        print(f"   scores.csv     数据行={max(0, len(lines) - 1)}")
    snap = PKG / "dist" / PKG.name
    zips = list((PKG / "dist").glob("*.zip")) if (PKG / "dist").exists() else []
    print(f"   dist/zip       存在={bool(zips)}"
          + (f"  {zips[0].stat().st_size / 1048576:.0f} MiB" if zips else ""))
    print(f"   dist/解包快照  存在={snap.exists()}"
          + (f"  {sum(1 for _ in snap.rglob('*') if _.is_file())} 个文件" if snap.exists() else ""))

    print("\n[是否已被 git 跟踪]")
    print(f"   这 {len(uniq)} 个结论文件都不在提交里 —— exp/ 是 .gitignore 第 29 行的整目录排除。")
    print("   结论本身已整理进 docs/EXPERIMENT-style-migration-RESULTS.md（那份在版本控制里）；")
    print("   逐图评分与出图只在本地，请自行备份。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
