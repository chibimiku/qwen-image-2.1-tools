#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 outputs 里所有图下载到 test-data/remote_outputs/，并生成一张带标签的总览图。

    python tools/pull_outputs.py            # 下载 + 出总览
    python tools/pull_outputs.py --list     # 只看远端有什么
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autodl_run                                                     # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DST = ROOT / "test-data" / "remote_outputs"
REMOTE = "/root/qwen-image-2.1/outputs"

# 每张图的来历（手工维护，方便日后回看）
NOTES = {
    "00_acceptance_lantern.png": "key 轮换后验收",
    "01_after_key_rotate.png": "轮换 key 后复测",
    "smoke_512.png": "最小烟囱测试 512²",
    "bench_1024_20steps.png": "跑分 1024²/20 步",
    "t2i_2048_40steps.png": "跑分 2048²/40 步（开分块 VAE）",
    "hug_two_people.png": "两张参考图 → 两人同框（官方多主体用法）",
    "ref_syntax_01_plain.png": "参考图语法实验 P1 不点名",
    "ref_syntax_02_image12.png": "参考图语法实验 P2 <image1>/<image2>",
    "ref_syntax_03_angle.png": "参考图语法实验 P3 编号对调",
    "ref_syntax_04_natural.png": "参考图语法实验 P4 自然语言序数",
    "ref_syntax_05_chinese.png": "参考图语法实验 P5 中文写法",
    "exp_broken_two_heads.png": "故意造的残缺图：两个头（测审图能否抓）",
    "exp_broken_three_legs.png": "故意造的残缺图：三条腿",
    "anatomy_e2e_01_before.png": "anatomy 端到端：加元数据之前的产出",
    "anatomy_e2e_02_after.png": "anatomy 端到端：加元数据之后的产出（带元数据）",
    "ui_click_check.png": "验证 WebUI 路径写元数据（我跑的回归）",
    "input_edit_1696x2528.jpg": "编辑实验的输入原图（不是产出）",
}


def ssh(cmd: str, timeout: int = 60) -> str:
    autodl_run.load_env_file()
    c = autodl_run.connect()
    try:
        _rc, out, _err = autodl_run.run(c, cmd, timeout=timeout)
        return out
    finally:
        c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-sheet", action="store_true")
    args = ap.parse_args()

    out = ssh(f"ls -1 --time-style='+%m-%d %H:%M' {REMOTE} 2>/dev/null")
    names = [n.strip() for n in out.splitlines() if n.strip()]
    if not names:
        print(f"远端 {REMOTE} 是空的")
        return 1
    print(f"远端 {REMOTE} 共 {len(names)} 个文件")
    if args.list:
        for n in names:
            print(f"  {n}")
        return 0

    DST.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in DST.iterdir() if p.is_file()}
    got = skip = 0
    for n in names:
        if n in have:
            skip += 1
            continue
        autodl_run.load_env_file()
        c = autodl_run.connect()
        try:
            sftp = c.open_sftp()
            sftp.get(f"{REMOTE}/{n}", str(DST / n))
            sftp.close()
        finally:
            c.close()
        print(f"  下载 {n}")
        got += 1
    print(f"下载 {got} 张，已在本地 {skip} 张 → {DST}")

    if not args.no_sheet:
        make_sheet()
    return 0


def make_sheet() -> None:
    from PIL import Image, ImageDraw
    files = sorted([p for p in DST.iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
    if not files:
        return
    COLS, CW, CH = 4, 260, 300
    rows = (len(files) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * CW, rows * CH), (22, 25, 31))
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(files):
        cx, cy = (i % COLS) * CW, (i // COLS) * CH
        try:
            im = Image.open(p)
            im.load()
            im = im.convert("RGB")
            im.thumbnail((CW - 16, CH - 64))
            sheet.paste(im, (cx + 8 + (CW - 16 - im.width) // 2, cy + 8))
            note = f"{im.width}x{im.height}"
        except Exception as e:                                         # noqa: BLE001
            note = f"打不开 {e}"
        d.text((cx + 8, cy + CH - 50), p.name[:34], fill=(220, 230, 240))
        d.text((cx + 8, cy + CH - 36), note, fill=(140, 200, 255))
        d.text((cx + 8, cy + CH - 22), NOTES.get(p.name, "")[:36], fill=(150, 160, 175))
    out = ROOT / "reports" / "outputs-sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"总览图：{out.relative_to(ROOT)}（{sheet.width}x{sheet.height}）")


if __name__ == "__main__":
    raise SystemExit(main())
