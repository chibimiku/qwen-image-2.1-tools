#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从本机直接探公网入口：判断"SSH 挂"还是"整台实例挂了"。

本沙箱里 schannel 的证书凭证被禁（curl -k 会报 AcquireCredentialsHandle），
但 python 的 ssl 走 OpenSSL，能连通。实例活着 → /health 200。
"""
import sys
import urllib3
import requests

urllib3.disable_warnings()

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "https://u57736-b87a-de5c81ec.westb.seetacloud.com:8443"
for path in ("/health", "/"):
    url = BASE + path
    try:
        r = requests.get(url, timeout=25, verify=False)
        body = r.text[:220].replace("\n", " ")
        print(f"{path:8s} -> HTTP {r.status_code} | {body}")
    except Exception as exc:                                     # noqa: BLE001
        print(f"{path:8s} -> 失败 {type(exc).__name__}: {str(exc)[:140]}")
