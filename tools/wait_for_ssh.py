#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""等实例的 SSH 端口重新可用（AutoDL 关机 / 制镜像期间端口会直接 refused）。

    python tools/wait_for_ssh.py --minutes 30          # 通了印 OK 并返回 0，超时返回 1

凭据从 tools/autodl.env 读（同 autodl_run.py）。轮询的是 TCP 可达性，
不是完整握手 —— 端口开了但网关还在抖的情况交给 autodl_retry 去重试。
"""
from __future__ import annotations

import argparse
import pathlib
import socket
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autodl_run  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                            # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--interval", type=float, default=20)
    a = ap.parse_args()

    autodl_run.load_env_file()
    host, port = autodl_run.HOST, autodl_run.PORT
    deadline = time.time() + a.minutes * 60
    n = 0
    print(f"等待 {host}:{port} 可用（最多 {a.minutes} 分钟，每 {a.interval}s 探一次）", flush=True)
    while time.time() < deadline:
        n += 1
        s = socket.socket()
        s.settimeout(6)
        try:
            s.connect((host, port))
            print(f"  第 {n} 次探测：端口已开（{(time.time() - (deadline - a.minutes * 60)):.0f}s）", flush=True)
            return 0
        except Exception as exc:                                 # noqa: BLE001
            print(f"  第 {n} 次：{type(exc).__name__}", flush=True)
        finally:
            s.close()
        time.sleep(a.interval)
    print(f"  {a.minutes} 分钟内端口一直没开", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
