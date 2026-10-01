# -*- coding: utf-8 -*-
"""本地批量修复出图：按 fixed-prompts.json 重新出图，落到 fixed-2/。

  python exp/galgame-cg-20260928/run_fix.py --plan         # 只列计划
  python exp/galgame-cg-20260928/run_fix.py                # 全部跑
  python exp/galgame-cg-20260928/run_fix.py --only story-01-boutique story-06-sunset-bridge

与 batch_fix.py 的区别：
  · batch_fix 走**服务端的自检回路**（需要视觉 API key，LLM 参与判定与改 prompt）；
  · 本脚本走**本地回路**：prompt 由 prompts_fix.py 明确写好，出图后由 **agent 自己看图**判定。
    不需要任何外部 API key。

出图参数与原图保持一致（同 seed、同步数、同尺寸、同参考图），
这样"改的是 prompt"成为唯一变量。
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import sys
import threading
import time

import paramiko
import requests

EXP = pathlib.Path(__file__).resolve().parent
ROOT = EXP.parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import autodl_ssh  # noqa: E402

OUT = EXP / "out"
FIXED2 = EXP / "fixed-2"

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")
KEY = [l.strip() for l in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines()
       if l.strip() and not l.startswith("#")][0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--rerun-all", action="store_true", help="已存在也重出")
    a = ap.parse_args()

    spec_file = EXP / "fixed-prompts.json"
    if not spec_file.exists():
        print("缺 fixed-prompts.json，先跑 python prompts_fix.py --build")
        return 2
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    items = [v for k, v in spec.items() if not a.only or k in a.only]
    if not items:
        print("没有要跑的项目")
        return 0

    print(f"=== 本地修复：{len(items)} 张 ===")
    for it in items:
        print(f"  {it['name']:<24} [{it['worst'].upper()}] 修正={it['fixes'] or '(只改场景)'}"
              f"  {it['codes']}")

    if a.plan:
        return 0

    FIXED2.mkdir(parents=True, exist_ok=True)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
                password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16072), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = cli.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base = "http://127.0.0.1:16072"
    h = {"Authorization": "Bearer " + KEY}

    log_path = EXP / "run-fix-log.jsonl"
    done = 0
    try:
        for it in items:
            dst = FIXED2 / f"{it['name']}.png"
            if dst.exists() and not a.rerun_all:
                print(f"  跳过 {it['name']}（已存在）")
                done += 1
                continue

            ref_files = []
            for rn in (it.get("refs") or ["char", "style"]):
                p = EXP / "refs" / f"{rn}.png"
                if p.exists():
                    ref_files.append(("image", (p.name, open(p, "rb"), "image/png")))

            data = {"prompt": it["prompt"], "num_inference_steps": str(a.steps)}

            # 护栏：必须是完整的四段结构（分工声明 / 样式词 / 禁止清单 / 场景段）。
            # 第一版忘了这一步，只发了 scene 一段 —— 模型直接退回白底立绘，
            # story-12 的纯白像素从 0% 涨到 88%。宁可在这里报错，也不要白跑一轮。
            n_sec = len([x for x in it["prompt"].split("\n\n") if x.strip()])
            if n_sec < 4:
                print(f"  {it['name']:<24} SKIP prompt 只有 {n_sec} 段（应≥4），"
                      f"不发出去")
                continue
            if it.get("seed") is not None:
                data["seed"] = str(it["seed"])
            m = re.match(r"(\d+)x(\d+)", str(it.get("size") or "1600x896"))
            if m:
                data["width"], data["height"] = m.group(1), m.group(2)

            t0 = time.time()
            try:
                r = requests.post(base + "/v1/images/generations", headers=h,
                                  data=data, files=ref_files or None, timeout=1800)
                dt = round(time.time() - t0, 1)
                if r.status_code != 200:
                    print(f"  {it['name']:<24} FAIL {r.status_code} {r.text[:100]}")
                    continue
                j = r.json()
                item = (j.get("data") or [{}])[0]
                b64 = item.get("b64_json") or ""
                if not b64:
                    print(f"  {it['name']:<24} FAIL 响应无 b64")
                    continue
                dst.write_bytes(base64.b64decode(b64))
                rec = {"name": it["name"], "size": j.get("size"), "seconds": dt,
                       "seed": item.get("seed"), "fixes": it["fixes"], "codes": it["codes"],
                       "style_tier": it.get("style_tier"),
                       "prompt_sections": len(it["prompt"].split("\n\n")),
                       "prompt": it["prompt"],
                       "inputs": (item.get("metadata") or {}).get("inputs")}
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"  {it['name']:<24} OK {dt}s {j.get('size')} -> {dst.name}")
                done += 1
            except Exception as exc:                                    # noqa: BLE001
                print(f"  {it['name']:<24} ERR {type(exc).__name__}: {exc}")
    finally:
        try:
            fwd.shutdown()
            cli.close()
        except Exception:                                               # noqa: BLE001
            pass

    print(f"\n完成 {done}/{len(items)}")
    return 0 if done == len(items) else 1


if __name__ == "__main__":
    sys.exit(main())
