#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""人体复检（anatomy_check）专项端到端验证。

    python tools/anatomy_e2e.py --base https://<公网入口> --key 1730
    python tools/anatomy_e2e.py --base http://127.0.0.1:16006        # 走 SSH 隧道

做三件事（都可单独关掉）：
  1. GET /health            —— 看服务是否 loaded、以及 anatomy_checker 的加载状态
  2. POST /v1/images/generations（anatomy_check=true）—— 真实跑一次带复检的出图
  3. 把响应里的 anatomy_check 元数据完整打印出来（attempts / retries / history / verdicts）

默认出 768x1024、12 步，约 10 秒一张，失败重跑最多 1 次，避免把 48G 卡占太久。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or os.getcwd()))
sys.path.insert(0, HERE)
try:                       # 在实例上跑时没有 tools/keys.py，走 --key 参数即可
    import keys            # noqa: E402
except ImportError:        # pragma: no cover
    keys = None

# 远端/Windows 控制台默认 GBK，中文 JSON 直接打印会炸
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")       # type: ignore[attr-defined]
    except Exception:                                            # noqa: BLE001
        pass


def show(title, obj):
    print(f"\n===== {title} =====")
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:4000])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("QWEN_BASE", "http://127.0.0.1:16006"))
    ap.add_argument("--key", default=os.environ.get("QWEN_API_KEY")
                    or (keys.api_key() if keys else ""))
    ap.add_argument("--prompt", default="a full body photo of one woman standing, "
                                       "natural proportions, both legs visible")
    ap.add_argument("--width", type=int, default=768)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--steps", type=int, default=12)
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--skip-health", action="store_true")
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--out", default="")
    a, _unknown = ap.parse_known_args()   # 允许被 run_tunnel / fwd 之类的外层脚本注入多余 argv

    base = a.base.rstrip("/")
    auth = {"Authorization": f"Bearer {a.key}"}
    print(f"BASE   = {base}")
    print(f"KEY    = {'已配置' if a.key else '未配置'}（长度 {len(a.key)}，不回显内容）")

    if not a.skip_health:
        try:
            r = requests.get(f"{base}/health", timeout=20)
            show(f"GET /health  HTTP {r.status_code}", r.json())
        except Exception as exc:                                     # noqa: BLE001
            print("health 请求失败：", type(exc).__name__, exc)
            return 1

    if a.skip_generate:
        return 0

    body = {
        "prompt": a.prompt,
        "width": a.width, "height": a.height,
        "num_inference_steps": a.steps,
        "anatomy_check": True,
        "anatomy_max_retries": a.retries,
    }
    print(f"\n===== POST /v1/images/generations（anatomy_check=true, retries={a.retries}）=====")
    t0 = time.time()
    try:
        r = requests.post(f"{base}/v1/images/generations", headers=auth, json=body, timeout=900)
    except Exception as exc:                                          # noqa: BLE001
        print("出图请求失败：", type(exc).__name__, exc)
        return 1
    dt = time.time() - t0
    print(f"HTTP {r.status_code}  用时 {dt:.1f}s")
    if r.status_code != 200:
        print(r.text[:2000])
        return 1

    data = r.json()
    items = data.get("data") or []
    print(f"返回 {len(items)} 张图")
    for i, item in enumerate(items):
        if a.out and item.get("b64_json"):
            p = a.out if len(items) == 1 else a.out.replace(".png", f"_{i}.png")
            with open(p, "wb") as fh:
                fh.write(base64.b64decode(item["b64_json"]))
            print(f"  写出 {p}（{item.get('width')}x{item.get('height')}, seed={item.get('seed')}）")
        show(f"item[{i}].anatomy_check", item.get("anatomy_check") or "（没有该字段！）")
        show(f"item[{i}].timing", item.get("timing") or {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
