# -*- coding: utf-8 -*-
"""把开机自启脚本部署到实例，并验证。

  python tools/deploy_autostart.py                 # 上传 + 语法检查 + 安装引导 + 状态
  python tools/deploy_autostart.py --check         # 只看状态，不改任何东西
  python tools/deploy_autostart.py --dry-run       # 上传和语法检查，不安装引导
  python tools/deploy_autostart.py --host X --port Y   # 换目标实例（默认 westd 当前实例）

为什么脚本放 /root/autodl-tmp：
  实测这台机的挂载是 —— /init 和 /root/autodl-tmp 在持久盘 /dev/md0 上，
  而 /etc、/root 走 overlay 上层，容器重建就没了（09-27 装的，10-01 重建后
  /etc 与 /init 时间戳全部刷新）。所以"能活下来的"只有 /root/autodl-tmp。

调用链（改动必须落在这条链上，否则容器重建即回退）：
  remote/autostart/qwen-autostart.sh（git 唯一真源）
    ↓ 上传
  /root/autodl-tmp/autostart/qwen-autostart.sh（持久盘，跨重建保留）
    ↓ --install 贴引导
  /init/bin/customer.cmd.sh（容器启动钩子）
  /root/.bashrc（登录退路，带 --quick，不阻塞 ssh）

注意：/root/qwen-image-2.1 下的服务代码**不是 git 仓库**，那边的更新走
tools/deploy_service.py；本脚本只管自启脚本本身。

目标实例为什么写死在 DEFAULT_* 而不是读 env 文件：
  这台机器上同时躺着两套过期配置 —— tools/tunnel.conf 指 westb:43611、
  tools/autodl_new.env 指 westc:17045，两个实例都早没了。默认值指向当前在用的
  westd 实例；要换目标用 --host/--port 覆盖，别去改那两个文件。

上传策略：**先传 .new，语法过了才替换**。远端 bash 执行一次要等会话建立
（这台机上实测见 docs/AUTOSTART.md），所以宁可多一步也不能把坏脚本盖上生产件。
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import time

import paramiko

# 本脚本输出全是中文，Windows 控制台默认 GBK 会把 emoji/生僻字打成乱码，
# 一旦重定向到文件更是灾难（排查时踩过）。统一按 UTF-8 走。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
LOCAL = ROOT / "remote" / "autostart" / "qwen-autostart.sh"
REMOTE_DIR = "/root/autodl-tmp/autostart"
REMOTE = f"{REMOTE_DIR}/qwen-autostart.sh"
STAGING = f"{REMOTE}.new"
MARK = "qwen-autostart"

# 当前在用的实例（westd 区）。改这里 = 换默认部署目标。
DEFAULT_HOST = "connect.westd.seetacloud.com"
DEFAULT_PORT = 26791
DEFAULT_USER = "root"
DEFAULT_PASS = "xzkx5EgMwhvy"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只查状态")
    ap.add_argument("--dry-run", action="store_true", help="上传+检查，不装引导")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--user", default=DEFAULT_USER)
    a = ap.parse_args()
    rc = 0

    t0 = time.time()
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(a.host, port=a.port, username=a.user, password=DEFAULT_PASS,
                timeout=30, banner_timeout=120, auth_timeout=120,
                allow_agent=False, look_for_keys=False)
    print(f"[目标] {a.host}:{a.port}  连接耗时 {time.time() - t0:.1f}s")

    def sh(cmd: str, t: int = 300) -> str:
        chan = cli.get_transport().open_session(timeout=t)
        chan.settimeout(2.0)
        chan.exec_command(f"timeout -k 5 {int(t)} bash -c " + shell_quote(cmd))
        buf = b""
        start = time.time()
        while time.time() - start < t:
            got = False
            while chan.recv_ready():
                buf += chan.recv(65536)
                got = True
            if got:
                start = time.time()
            elif chan.exit_status_ready() and not chan.recv_ready():
                time.sleep(0.3)
                while chan.recv_ready():
                    buf += chan.recv(65536)
                break
            else:
                time.sleep(0.1)
        chan.close()
        return buf.decode("utf-8", "replace").strip()

    def show(label: str, text: str) -> None:
        print(label)
        for line in text.splitlines() or [""]:
            print("       " + line)

    if not a.check:
        local_bytes = LOCAL.read_bytes()
        local_md5 = hashlib.md5(local_bytes).hexdigest()
        print(f"[本地] {LOCAL.name}  {len(local_bytes)} B  md5={local_md5[:12]}")
        sh(f"mkdir -p {REMOTE_DIR}")
        sftp = cli.open_sftp()
        sftp.put(str(LOCAL), STAGING)
        sftp.close()
        sh(f"chmod +x {STAGING}")

        got = sh(f"md5sum {STAGING}").split()
        if not got or got[0] != local_md5:
            print(f"[上传] md5 不一致：远端 {got[:1]} vs 本地 {local_md5[:12]} —— 中止，不动生产件")
            cli.close()
            return 1
        print(f"[上传] {STAGING}  md5 一致 OK")

        print("[语法] bash -n …")
        syn = sh(f"bash -n {STAGING} 2>&1; echo rc=$?")
        show("       ", syn)
        if "rc=0" not in syn:
            print("[中止] 语法不过，生产件保持原样（暂存文件留在 *.new 供排查）")
            cli.close()
            return 1

        kept = sh(f"cp -a {REMOTE} {REMOTE}.bak.$(date +%s) 2>/dev/null && echo backed-up || echo no-previous")
        print(f"[备份] {kept}")
        sh(f"mv -f {STAGING} {REMOTE} && chmod +x {REMOTE}")
        print("[替换] 已用校验过的版本覆盖生产件")

        print("[持久性] 脚本所在文件系统：")
        show("       ", sh(f"df -h {REMOTE_DIR} | tail -1"))
        print("[持久性] /init 侧：")
        show("       ", sh("df -h /init | tail -1"))

        if not a.dry_run:
            print("[安装] 引导 /init/bin/customer.cmd.sh + ~/.bashrc 退路（--quick）")
            show("       ", sh(f"bash {REMOTE} --install"))
            print("[核对] customer.cmd.sh 尾部：")
            show("       ", sh("tail -4 /init/bin/customer.cmd.sh"))
            print("[核对] .bashrc 头部：")
            show("       ", sh("head -4 /root/.bashrc"))

    print("[状态] 自启脚本视角：")
    show("       ", sh(f"bash {REMOTE} --status 2>&1 | head -3"))
    print("[自启记录] boot.log 尾部：")
    show("       ", sh(f"tail -8 {REMOTE_DIR}/boot.log 2>/dev/null") or "(还没有记录)")
    print("[钩子核对] 引导行出现次数（/init + .bashrc）：")
    show("       ", sh(f"grep -c {MARK} /init/bin/customer.cmd.sh /root/.bashrc 2>&1"))

    cli.close()
    print()
    print(f"结论: {'通过' if rc == 0 else '有问题，见上'}   总耗时 {time.time() - t0:.1f}s")
    return rc


def shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    sys.exit(main())
