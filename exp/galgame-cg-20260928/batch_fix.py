# -*- coding: utf-8 -*-
"""批量修复有缺陷的出图：逐张跑服务端的自检-修订回路，挑出更好的一版。

  python exp/galgame-cg-20260928/batch_fix.py --plan          # 只列计划，不发请求
  python exp/galgame-cg-20260928/batch_fix.py                 # 执行全部待修项
  python exp/galgame-cg-20260928/batch_fix.py --only story-06-sunset-bridge
  python exp/galgame-cg-20260928/batch_fix.py --sheet         # 只重拼对照表

输入是质检结果（`qa/DEFECTS-QA.md` + `qa/result-*.jsonl`），输出写到 `fixed/`。

为什么复用服务端的回路而不是本地重写一套：
  · 判定/修订的固定 prompt 只有一份（service/autoloop.py），改一处就够；
  · 回路已经在服务端跑通过（实测 25 项端点断言）；
  · 每轮产物服务端会落盘，这里只需把它们取回来。

**这里只做"组织与取回"**：挑哪些图要修、给多少轮、把结果下载并拼对照表。
判"哪一版更好"交给回路的判定分数，人最后看图决定要不要用。
"""
from __future__ import annotations

import argparse
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
FIXED = EXP / "fixed"
QA = EXP / "qa"

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")
KEY = [l.strip() for l in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines()
       if l.strip() and not l.startswith("#")][0]

# 每张图给多少轮、目标分多少 —— 按严重度定，P0 多给几轮
ROUNDS_BY_WORST = {"p0": 4, "P0": 4, "p1": 3, "P1": 3, "p2": 2, "P2": 2,
                   "p3": 1, "P3": 1, "?": 2, "none": 0}
SCORE_BY_WORST = {"p0": 8.0, "P0": 8.0, "p1": 7.5, "P1": 7.5, "p2": 7.0, "P2": 7.0,
                  "p3": 6.5, "P3": 6.5, "?": 7.0, "none": 0.0}


def load_records() -> dict[str, dict]:
    mf = EXP / "manifest.jsonl"
    best: dict[str, dict] = {}
    for line in mf.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("status") == "ok":
                best[r["name"]] = r
    return best


def load_defects() -> dict[str, dict]:
    """汇总所有质检结果：{图名: {"worst":…, "defects":[…]}}。"""
    out: dict[str, dict] = {}
    for f in sorted(QA.glob("result-*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:                                           # noqa: BLE001
                continue
            name = str(obj.get("file", "")).removesuffix(".png")
            if not name:
                continue
            d = out.setdefault(name, {"worst": "none", "defects": [], "sources": []})
            if f.name not in d["sources"]:
                d["sources"].append(f.name)
            for x in (obj.get("defects") or []):
                d["defects"].append(x)
            w = str(obj.get("worst") or "none").lower()
            order = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "none": 9, "?": 8}
            if order.get(w, 8) < order.get(d["worst"], 9):
                d["worst"] = w
    return out


def extract_fields(prompt: str) -> tuple[str, str]:
    """从原始 prompt 拆出（角色圣经, 场景段）。

    prompt 是四段结构，最后一段 = 角色圣经 + 场景描述。服务端会把整段当
    `scene` 用（修订时整体替换），所以这里直接把最后一段交出去。
    """
    parts = [p.strip() for p in (prompt or "").split("\n\n") if p.strip()]
    scene = parts[-1] if parts else ""
    m = re.match(r"^(The character is .*?(?:heels|dress|outfit)\.)\s*(.*)$", scene, re.S)
    bible = m.group(1) if m else ""
    return bible, scene


def build_plan(records: dict[str, dict], defects: dict[str, dict],
               only: list[str]) -> list[dict]:
    plan = []
    for name, d in sorted(defects.items()):
        if only and name not in only:
            continue
        rec = records.get(name)
        if not rec:
            print(f"  跳过 {name}：manifest 里没有它的成功记录")
            continue
        if not (OUT / f"{name}.png").exists():
            print(f"  跳过 {name}：出图文件不在")
            continue
        worst = d["worst"]
        rounds = ROUNDS_BY_WORST.get(worst, 2)
        if rounds <= 0:
            continue
        bible, scene = extract_fields(rec.get("prompt", ""))
        plan.append({
            "name": name, "worst": worst, "rounds": rounds,
            "score": SCORE_BY_WORST.get(worst, 7.0),
            "n_defects": len(d["defects"]),
            "codes": sorted({x.get("code", "?") for x in d["defects"]}),
            "scene": scene, "bible": bible,
            "refs": rec.get("refs") or ["char", "style"],
            "seed": rec.get("seed"), "size": rec.get("size"),
        })
    return plan


class Runner:
    """连实例、起隧道、驱动服务端的回路。"""

    def __init__(self) -> None:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401  仅确认可用
        self.cli = paramiko.SSHClient()
        self.cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.cli.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]),
                         username=CFG["AUTODL_USER"], password=CFG["AUTODL_PASS"],
                         timeout=25, allow_agent=False, look_for_keys=False)
        self.fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16071), autodl_ssh.Handler)
        self.fwd.dst_host, self.fwd.dst_port = "127.0.0.1", 6006
        self.fwd.transport = self.cli.get_transport()
        threading.Thread(target=self.fwd.serve_forever, daemon=True).start()
        time.sleep(0.4)
        self.base = "http://127.0.0.1:16071"
        self.h = {"Authorization": "Bearer " + KEY}

    def close(self) -> None:
        try:
            self.fwd.shutdown()
        except Exception:                                               # noqa: BLE001
            pass
        try:
            self.cli.close()
        except Exception:                                               # noqa: BLE001
            pass

    def vision_ready(self) -> tuple[bool, str]:
        r = requests.get(self.base + "/v1/vision/config", headers=self.h, timeout=30)
        if r.status_code != 200:
            return False, f"读配置失败 HTTP {r.status_code}"
        d = r.json()
        if not d.get("has_key"):
            return False, "服务端还没配视觉 API key"
        return True, f"{d.get('model')} @ {d.get('base_url')}"

    def fix_one(self, item: dict, rounds: int, score: float,
                poll: int = 5, timeout: int = 3600) -> dict:
        """对一张图跑回路，返回结果摘要。"""
        ref_files = []
        for rn in item["refs"]:
            p = EXP / "refs" / f"{rn}.png"
            if p.exists():
                ref_files.append(("image", (p.name, open(p, "rb"), "image/png")))
        if not ref_files:
            return {"name": item["name"], "ok": False, "error": "找不到参考图"}

        data = {
            "prompt": item["scene"],
            "max_rounds": str(rounds),
            "pass_score": str(score),
            "num_inference_steps": "40",
        }
        if item.get("seed") is not None:
            data["seed"] = str(item["seed"])
        # 尺寸：按原图的实际尺寸保持一致，避免"修完尺寸变了"这种无关变量
        size = item.get("size") or "1600x896"
        m = re.match(r"(\d+)x(\d+)", str(size))
        if m:
            data["width"], data["height"] = m.group(1), m.group(2)

        r = requests.post(self.base + "/v1/auto/start", headers=self.h,
                          data=data, files=ref_files, timeout=300)
        if r.status_code != 202:
            return {"name": item["name"], "ok": False,
                    "error": f"启动失败 HTTP {r.status_code}: {r.text[:200]}"}
        job = r.json()["job_id"]

        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            time.sleep(poll)
            rr = requests.get(self.base + f"/v1/auto/status/{job}", headers=self.h, timeout=60)
            if rr.status_code != 200:
                continue
            st = rr.json()
            if st.get("status") in ("done", "finished_unpassed", "failed"):
                last = st
                break
        if not last:
            return {"name": item["name"], "ok": False, "job": job, "error": "等超时"}

        res = last.get("result") or {}
        hist = res.get("history") or []
        # 取判定分最高的那一轮
        best = None
        for h in hist:
            v = h.get("verdict") or {}
            if v.get("score") is None:
                continue
            if best is None or v["score"] > (best.get("verdict") or {}).get("score", -1):
                best = h
        saved = []
        if best:
            FIXED.mkdir(parents=True, exist_ok=True)
            for i, p in enumerate(best.get("images") or []):
                nm = pathlib.Path(p).name
                fr = requests.get(self.base + f"/v1/auto/file/{job}/{nm}",
                                  headers=self.h, timeout=120)
                if fr.status_code == 200:
                    dst = FIXED / f"{item['name']}-r{best['round']}-{i+1}.png"
                    dst.write_bytes(fr.content)
                    saved.append(str(dst))
        return {
            "name": item["name"], "ok": bool(saved), "job": job,
            "status": last.get("status"), "rounds": res.get("rounds"),
            "passed": res.get("passed"), "best_round": res.get("best_round"),
            "best_score": res.get("best_score"),
            "worst_of_best": ((best or {}).get("verdict") or {}).get("worst"),
            "saved": saved, "error": last.get("error"),
            "log": (last.get("log") or [])[-8:],
        }


def make_sheet(names: list[str], font_path: list[str]) -> None:
    """把「原图 vs 修后」并排拼成对照表，供人眼决定用哪一版。"""
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for fp in font_path:
        if pathlib.Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 16)
                break
            except Exception:                                           # noqa: BLE001
                continue
    if font is None:
        font = ImageFont.load_default()

    rows = []
    for n in names:
        orig = OUT / f"{n}.png"
        fixes = sorted(FIXED.glob(f"{n}-r*.png"))
        if orig.exists():
            rows.append((n, orig, fixes))
    if not rows:
        print("没有可拼的对照")
        return

    tw = 760
    th = int(tw * 896 / 1600)
    pad, lab = 10, 26
    max_cols = max(1 + len(f[2]) for f in rows)
    W = max_cols * tw + (max_cols + 1) * pad
    H = len(rows) * (th + lab) + (len(rows) + 1) * pad
    sheet = Image.new("RGB", (W, H), (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    for ri, (n, orig, fixes) in enumerate(rows):
        y = pad + ri * (th + lab + pad)
        cells = [("原图", orig)] + [(f"修后 r{f.stem.split('-r')[-1]}", f) for f in fixes]
        for ci, (lab_txt, p) in enumerate(cells):
            x = pad + ci * (tw + pad)
            im = Image.open(p).convert("RGB")
            im = im.resize((tw, int(tw * im.height / im.width)), Image.LANCZOS)
            sheet.paste(im, (x, y))
            d.text((x + 4, y + im.height + 4), f"{n}  {lab_txt}", fill=(230, 230, 235),
                   font=font)
    out = EXP / "sheets-fixed.png"
    sheet.save(out)
    print(f"对照表 -> {out.name} {sheet.size}（{len(rows)} 行）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="只列计划")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--sheet", action="store_true", help="只重拼对照表")
    ap.add_argument("--rounds", type=int, default=0, help="覆盖轮数（调试用）")
    a = ap.parse_args()

    FONTS = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]

    records = load_records()
    defects = load_defects()
    if not defects:
        print(f"没有质检结果：{QA} 下没有 result-*.jsonl")
        return 2
    print(f"质检结果覆盖 {len(defects)} 张；manifest 有 {len(records)} 张成功记录")
    print()
    plan = build_plan(records, defects, a.only)
    if not plan:
        print("没有待修项")
        return 0

    print(f"=== 待修 {len(plan)} 张 ===")
    for p in plan:
        r = a.rounds or p["rounds"]
        print(f"  {p['name']:<24} 最严重={p['worst']:<4} 缺陷={p['n_defects']} 条"
              f" {p['codes']}  计划 {r} 轮 / 目标 {p['score']}")
    if a.plan:
        return 0

    run = Runner()
    try:
        ok, msg = run.vision_ready()
        if not ok:
            print(f"\n!! 不能开始：{msg}")
            print("   请先在控制台「AI 自检」面板里填入视觉 API key 并保存。")
            return 3
        print(f"\n视觉 API：{msg}\n")

        results = []
        for i, item in enumerate(plan, 1):
            rounds = a.rounds or item["rounds"]
            print(f"[{i}/{len(plan)}] {item['name']}  跑 {rounds} 轮…", flush=True)
            res = run.fix_one(item, rounds, item["score"])
            results.append(res)
            if res.get("ok"):
                print(f"        完成：最佳 r{res['best_round']} score={res['best_score']} "
                      f"worst={res['worst_of_best']} 通过={res['passed']}")
            else:
                print(f"        失败：{res.get('error') or res.get('status')}")
                for line in res.get("log") or []:
                    print("          " + line)
            (EXP / "batch-fix-log.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        good = [r for r in results if r.get("ok")]
        print(f"\n完成 {len(good)}/{len(plan)} 张")
        if good:
            make_sheet([r["name"] for r in good], FONTS)
        return 0 if len(good) == len(plan) else 1
    finally:
        run.close()


if __name__ == "__main__":
    sys.exit(main())
