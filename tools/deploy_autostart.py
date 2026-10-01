# -*- coding: utf-8 -*-
"""把开机自启脚本部署到实例，并验证。

  python tools/deploy_autostart.py                 # 上传 + 语法检查 + 安装引导 + 状态
  python tools/deploy_autostart.py --check         # 只看状态，不改任何东西
  python tools/deploy_autostart.py --dry-run       # 上传和语法检查，不安装引导

为什么脚本放 /root/autodl-tmp：
  实测这台机的挂载是 —— /init 和 /root/autodl-tmp 在持久盘 /dev/md0 上，
  而 /etc、/root 走 overlay 上层，容器重建就没了（09-27 装的，10-01 重建后
  /etc 与 /init 时间戳全部刷新）。所以"能活下来的"只有 /root/autodl-tmp。

调用链：
  容器启动 → /init/bin/customer.cmd.sh（AutoDL 提供，每次重建由镜像还原）
  → /root/autodl-tmp/autostart/qwen-autostart.sh（持久，自己维护）
  → scripts/serve.sh start

`/init/bin/customer.cmd.sh` 是 AutoDL 官方的自定义命令入口：它每次启动都会执行
`bash /etc/autodl.sh`，而这台机上 /etc/autodl.sh 根本不存在（/tmp/autodl.sh.log
里留着 "No such file or directory"）。所以那个入口是空着的，我们把自己的脚本
挂上去即可 —— 不改它的原有行为，只追加一行。
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
LOCAL = ROOT / "remote" / "autostart" / "qwen-autostart.sh"
REMOTE_DIR = "/root/autodl-tmp/autostart"
REMOTE = f"{REMOTE_DIR}/qwen-autostart.sh"
MARK = "qwen-autostart"


def cfg() -> dict:
    out = {}
    for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只查状态")
    ap.add_argument("--dry-run", action="store_true", help="上传+检查，不装引导")
    a = ap.parse_args()
    rc = 0

    c = cfg()
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(c["AUTODL_HOST"], port=int(c["AUTODL_PORT"]), username=c["AUTODL_USER"],
                password=c["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)

    def sh(cmd: str, t: int = 300) -> str:
        _, o, e = cli.exec_command(cmd, timeout=t)
        return (o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")).strip()

    print(f"[目标] {c['AUTODL_HOST']}:{c['AUTODL_PORT']}")

    if not a.check:
        local_md5 = hashlib.md5(LOCAL.read_bytes()).hexdigest()
        sh(f"mkdir -p {REMOTE_DIR}")
        sftp = cli.open_sftp()
        sftp.put(str(LOCAL), REMOTE)
        sftp.close()
        sh(f"chmod +x {REMOTE}")
        got = sh(f"md5sum {REMOTE}").split()
        ok = bool(got) and got[0] == local_md5
        print(f"[上传] {REMOTE}  md5={local_md5[:12]}  {'OK' if ok else '校验失败!'}")
        if not ok:
            rc = 1

        print("[语法] bash -n …")
        syn = sh(f"bash -n {REMOTE} 2>&1; echo \"rc=$?\"")
        print("       " + syn.replace("\n", "\n       "))
        if "rc=0" not in syn:
            rc = 1

        print("[持久性] 脚本所在文件系统：")
        print("       " + sh(f"df -h {REMOTE_DIR} | tail -1"))
        print("       /init 侧：")
        print("       " + sh("df -h /init | tail -1"))

        if not a.dry_run:
            print("[安装] 引导到 /init/bin/customer.cmd.sh（AutoDL 官方钩子）+ ~/.bashrc 退路")
            print("       " + sh(f"bash {REMOTE} --install").replace("\n", "\n       "))
            print("[核对] customer.cmd.sh 尾部：")
            print("       " + sh("tail -4 /init/bin/customer.cmd.sh").replace("\n", "\n       "))

    print("[状态] 自启脚本视角：")
    print("       " + sh(f"bash {REMOTE} --status 2>&1 | head -3").replace("\n", "\n       "))
    print("[自启记录] boot.log 尾部：")
    tail = sh(f"tail -6 {REMOTE_DIR}/boot.log 2>/dev/null") or "(还没有记录)"
    print("       " + tail.replace("\n", "\n       "))
    print("[钩子核对] grep 引导行：")
    print("       " + sh(f"grep -c {MARK} /init/bin/customer.cmd.sh /root/.bashrc 2>&1"))

    cli.close()
    print()
    print("结论:", "通过" if rc == 0 else "有问题，见上")
    return rc


if __name__ == "__main__":
    sys.exit(main())
