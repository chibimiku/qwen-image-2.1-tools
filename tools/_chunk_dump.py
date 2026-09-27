# -*- coding: utf-8 -*-
"""One-off: dump the metadata chunk structure of a remote output PNG.

  python tools/_chunk_dump.py [remote/path.png]

Explains what the service actually writes into the PNG, so the recovery path in
exec/executor.py can be checked against reality instead of assumption.
"""
from __future__ import annotations

import base64
import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
REMOTE = sys.argv[1] if len(sys.argv) > 1 else \
    "/root/qwen-image-2.1/outputs/2026-09-27/559-1234.png"

PY = """
import json, struct, sys
p = sys.argv[1]
data = open(p, "rb").read()
print("file bytes:", len(data))
i = 8
while i + 8 <= len(data):
    ln = struct.unpack(">I", data[i:i+4])[0]
    typ = data[i+4:i+8].decode("latin1")
    body = data[i+8:i+8+ln]
    print("chunk", typ, "len", ln)
    if typ in ("iTXt", "tEXt", "zTXt"):
        print("   head:", body[:600])
    i += 12 + ln
"""

cfg = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(cfg["AUTODL_HOST"], port=int(cfg["AUTODL_PORT"]), username=cfg["AUTODL_USER"],
          password=cfg["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)


def run(cmd, t=180):
    _, out, err = c.exec_command(cmd, timeout=t)
    return out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


run("echo %s | base64 -d > /tmp/_c.py" % base64.b64encode(PY.encode()).decode())
o, e = run("export PATH=/root/miniconda3/bin:$PATH; "
           f"cd /root/qwen-image-2.1 && python /tmp/_c.py {REMOTE}")
print(o or e)
c.close()
