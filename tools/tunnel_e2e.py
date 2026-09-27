#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""带重试的 SSH 端口转发跑本地脚本（``autodl_ssh.py fwd`` 的加固版）。

AutoDL 网关偶发"连上就断"（paramiko: Error reading SSH protocol banner），
``autodl_ssh.py`` 遇到这种抖动直接退出。这里复用 autodl_retry 的重试建连，
建立 本地端口 → 远端 6006 的转发，再把目标脚本 exec 起来。

目标脚本可以看到：
  * 全局 ``BASE``（例如 http://127.0.0.1:16006）
  * 环境变量 ``QWEN_BASE``（同样的值，给用 argparse/env 的脚本读）

    python tools/tunnel_e2e.py tools/anatomy_e2e.py --port 16006
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import threading

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autodl_retry      # noqa: E402
import autodl_ssh        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--port", type=int, default=16006)
    ap.add_argument("--remote-port", type=int, default=6006)
    a = ap.parse_args()

    c = autodl_retry.connect_hard()
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", a.port), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", a.remote_port
    fwd.transport = c.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{a.port}"
    os.environ["QWEN_BASE"] = base
    print(f"[fwd] {base} -> remote 127.0.0.1:{a.remote_port} over ssh", flush=True)

    path = a.script if os.path.isabs(a.script) else str(HERE.parent / a.script)
    ns = {"__name__": "__main__", "__file__": path, "BASE": base, "argv": []}
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        exec(compile(src, path, "exec"), ns)
        return 0
    finally:
        fwd.shutdown()
        c.close()
        print("[fwd] closed", flush=True)


if __name__ == "__main__":
    sys.exit(main())
