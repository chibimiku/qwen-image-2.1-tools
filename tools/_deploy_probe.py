# -*- coding: utf-8 -*-
"""Check the instance's deployment layout for the pieces the new UI buttons need.

  python tools/_deploy_probe.py
"""
from __future__ import annotations

import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
          password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)

CMDS = [
    ("root layout", "ls -1 /root/qwen-image-2.1/"),
    ("service", "ls -1 /root/qwen-image-2.1/service/ | head -20"),
    ("ui dir", "ls -1 /root/qwen-image-2.1/service/ui/"),
    ("docs present?", "ls -1d /root/qwen-image-2.1/docs 2>&1 | head -3"),
    ("upstream present?", "ls -1 /root/qwen-image-2.1/docs/upstream/ 2>&1 | head -20"),
    ("repo lineage", "ls -1 /root/qwen-image-2.1/.git 2>&1 | head -3; "
                     "git -C /root/qwen-image-2.1 remote -v 2>&1 | head -3"),
    ("server.py head", "head -12 /root/qwen-image-2.1/service/server.py"),
]
for label, cmd in CMDS:
    _, out, err = c.exec_command(cmd, timeout=60)
    o = out.read().decode("utf-8", "replace").rstrip()
    e = err.read().decode("utf-8", "replace").rstrip()
    print(f"--- {label} ---")
    print(o or e or "(empty)")
    print()
c.close()
