# -*- coding: utf-8 -*-
"""一次性的诊断：verify_sync 的 protected_remote 与 find 输出为什么对不上。

  python tools/_diag_sync.py
"""
from __future__ import annotations

import posixpath
import sys
import pathlib

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import deploy_manifest as M  # noqa: E402
import verify_sync as V  # noqa: E402

cfg = V.env_cfg()
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(cfg["AUTODL_HOST"], port=int(cfg["AUTODL_PORT"]), username=cfg["AUTODL_USER"],
          password=cfg["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)


def sh(cmd, t=120):
    _, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")


print("PROTECTED_BASENAMES =", M.PROTECTED_BASENAMES)
print("FILE_OVERRIDE       =", M.FILE_OVERRIDE)
print("repo_to_remote(service/scripts/qwen_env.sh) =",
      repr(M.repo_to_remote("service/scripts/qwen_env.sh")))
print("basename 判定 =",
      posixpath.basename(M.repo_to_remote("service/scripts/qwen_env.sh"))
      in M.PROTECTED_BASENAMES)

expect = posixpath.join(M.REMOTE_ROOT, M.repo_to_remote("service/scripts/qwen_env.sh"))
print("期望的 remote 字符串 =", repr(expect))
print()
print("find scripts/ 的原始输出（repr，看有没有空白/CR）：")
out = sh(f"find {posixpath.join(M.REMOTE_ROOT, 'scripts')} -type f 2>/dev/null")
for line in out.splitlines():
    print("   ", repr(line), "| 与期望相等:", line.strip() == expect)
print()
print("root 下是否还有一份 qwen_env.sh：")
print(sh(f"ls -la {M.REMOTE_ROOT}/qwen_env.sh 2>&1"))

c.close()
