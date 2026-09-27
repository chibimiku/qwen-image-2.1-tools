# -*- coding: utf-8 -*-
"""One-off: parse the service's iTXt generation record out of a remote PNG.

  python tools/_meta_read.py <remote/path.png>

PIL does not expose this chunk as PNG text on every Pillow build, so the chunk is
read raw and the JSON payload parsed directly.
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
REMOTE = sys.argv[1] if len(sys.argv) > 1 else \
    "/root/qwen-image-2.1/outputs/2026-09-27/559-1234.png"

PY = r'''
import json, struct, sys
p = sys.argv[1]
data = open(p, "rb").read()
i = 8
found = None
while i + 8 <= len(data):
    ln = struct.unpack(">I", data[i:i+4])[0]
    typ = data[i+4:i+8].decode("latin1")
    if typ == "iTXt":
        body = data[i+8:i+8+ln]
        kw, rest = body.split(b"\x00", 1)
        comp, meth = rest[0], rest[1]
        rest = rest[2:]
        lang, rest = rest.split(b"\x00", 1)
        trans, rest = rest.split(b"\x00", 1)
        if kw.decode("latin1") == "qwen_image_21":
            found = rest.decode("utf-8", "replace")
            break
    i += 12 + ln
if not found:
    print("NO qwen_image_21 chunk")
    sys.exit(0)
d = json.loads(found)
print("top-level keys:", sorted(d.keys()))
for k in ("schema", "schema_version", "model", "seed", "steps", "size", "size_note",
          "content_sha256", "png_sha256", "saved_path"):
    if k in d:
        v = d[k]
        print(f"  {k}: {v if not isinstance(v, str) or len(v) < 90 else v[:90] + '...'}")
for k in ("generator", "model", "timing"):
    if k in d and isinstance(d[k], dict):
        print(f"  {k}: {json.dumps(d[k], ensure_ascii=False)[:220]}")
if "inputs" in d:
    print("  inputs:", json.dumps(d["inputs"], ensure_ascii=False)[:220])
if "request" in d:
    r = d["request"]
    print("  request keys:", sorted(r.keys()) if isinstance(r, dict) else type(r).__name__)
    if isinstance(r, dict):
        for k in ("seed", "seed_given", "width", "height", "num_inference_steps",
                  "true_cfg_scale", "negative_prompt", "prompt_sha256", "prompt"):
            if k in r:
                v = r[k]
                s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
                print(f"    {k}: {s[:100]}")
'''

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
_, out, err = c.exec_command(
    "echo %s | base64 -d > /tmp/_mr.py" % base64.b64encode(PY.encode()).decode(), timeout=60)
out.read()
_, out, err = c.exec_command(
    "export PATH=/root/miniconda3/bin:$PATH; cd /root/qwen-image-2.1 && "
    f"python /tmp/_mr.py {REMOTE}", timeout=180)
print(out.read().decode("utf-8", "replace"))
print(err.read().decode("utf-8", "replace"))
c.close()
