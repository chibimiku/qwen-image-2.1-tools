#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一眼看清实例到底回没回来：SSH 端口 + 公网入口 + 域名解析。

    python tools/probe_instance.py
"""
from __future__ import annotations

import pathlib
import socket
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import autodl_run  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                            # noqa: BLE001
        pass

PUBLIC = "u57736-b87a-de5c81ec.westb.seetacloud.com"
PUBLIC_PORT = 8443


def tcp(host: str, port: int, timeout: float = 8.0) -> str:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return f"OK  ({s.getpeername()[0]})"
    except Exception as exc:                                     # noqa: BLE001
        return f"{type(exc).__name__}"
    finally:
        s.close()


def main() -> int:
    autodl_run.load_env_file()
    print(f"SSH      {autodl_run.HOST}:{autodl_run.PORT} -> {tcp(autodl_run.HOST, autodl_run.PORT)}")
    print(f"公网入口 {PUBLIC}:{PUBLIC_PORT}      -> {tcp(PUBLIC, PUBLIC_PORT)}")
    for host in (autodl_run.HOST, PUBLIC):
        try:
            print(f"DNS      {host} -> {socket.gethostbyname(host)}")
        except Exception as exc:                                 # noqa: BLE001
            print(f"DNS      {host} -> 解析失败 {type(exc).__name__}")

    try:
        import urllib3, requests
        urllib3.disable_warnings()
        r = requests.get(f"https://{PUBLIC}:{PUBLIC_PORT}/health", timeout=20, verify=False)
        body = r.text[:120].replace("\n", " ")
        print(f"HTTP     /health -> {r.status_code} | {body}")
    except Exception as exc:                                     # noqa: BLE001
        print(f"HTTP     /health -> 失败 {type(exc).__name__}: {str(exc)[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
