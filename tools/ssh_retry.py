#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在实例上跑命令，带重试 —— AutoDL 的 SSH 偶发 "Error reading SSH protocol banner"。

    python tools/ssh_retry.py "nvidia-smi"
    python tools/ssh_retry.py --tries 6 --wait 5 "tail -5 /root/x.log"
    python tools/ssh_retry.py --put local.py /root/local.py
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autodl_run                                                     # noqa: E402

RETRYABLE = ("banner", "EOFError", "Connection reset", "Socket is closed",
             "timed out", "NoValidConnectionsError", "Connection refused")


def is_retryable(text: str) -> bool:
    return any(k.lower() in text.lower() for k in RETRYABLE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", nargs="?")
    ap.add_argument("--put", nargs=2, metavar=("LOCAL", "REMOTE"))
    ap.add_argument("--get", nargs=2, metavar=("REMOTE", "LOCAL"))
    ap.add_argument("--tries", type=int, default=5)
    ap.add_argument("--wait", type=float, default=6.0)
    ap.add_argument("--timeout", type=int, default=None)
    args = ap.parse_args()

    autodl_run.load_env_file()
    last = ""
    for i in range(1, args.tries + 1):
        try:
            c = autodl_run.connect(timeout=30)
        except Exception as exc:                                       # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            if i < args.tries and is_retryable(last):
                print(f"[ssh] 第 {i} 次连接失败（{type(exc).__name__}），{args.wait}s 后重试…",
                      file=sys.stderr)
                time.sleep(args.wait)
                continue
            print(f"连接失败：{last}", file=sys.stderr)
            return 1
        try:
            if args.put:
                sftp = c.open_sftp()
                sftp.put(args.put[0], args.put[1])
                sftp.close()
                print(f"uploaded {args.put[0]} -> {args.put[1]}")
                return 0
            if args.get:
                sftp = c.open_sftp()
                sftp.get(args.get[0], args.get[1])
                sftp.close()
                print(f"downloaded {args.get[0]} -> {args.get[1]}")
                return 0
            rc, out, err = autodl_run.run(c, args.command, timeout=args.timeout)
            sys.stdout.write(out)
            if err:
                sys.stderr.write(err)
            print(f"\n[remote exit code: {rc}]")
            return rc
        finally:
            c.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
