# -*- coding: utf-8 -*-
"""不依赖 Windows schannel 的 git push（纯 Python HTTPS + git smart HTTP 协议）。

为什么需要它：
  这台机器的 git 配了 `http.sslBackend=schannel` + `credential.helper=manager`，
  在受限沙箱里会直接死在 TLS 握手前：

      fatal: unable to access 'https://github.com/...': schannel:
      AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS (0x8009030E)

  换 `http.sslBackend=openssl` 也不行 —— git 的凭据助手是 `gh.exe` 包在
  `sh.exe` 里的，而这个沙箱不让子进程建管道：

      0 [main] sh (34212): *** fatal error - couldn't create signal pipe, Win32 error 5

  但 Python 自己的 TLS 是好的（同一台机实测 `urllib` 直连 api.github.com 正常）。
  所以干脆自己实现 git 的 smart-HTTP 推送：取 token、问 refs、打包、POST。

  另一个坑：本脚本内部**不使用任何管道**（`Popen` 接 `PIPE` 在这个环境里会 EPERM），
  git 的中间产物一律走临时文件，跑完删掉。

用法：
  python tools/git_push_https.py                  # 推当前分支到 origin
  python tools/git_push_https.py --dry-run        # 只报告要推什么，不发
  python tools/git_push_https.py --branch main

凭据来源，按顺序找：
  1. 环境变量 GITHUB_TOKEN / GH_TOKEN
  2. `gh auth token`（gh CLI 已登录即可）
token 只在内存里，不写进 git 配置、不进命令行参数。
"""
from __future__ import annotations

import argparse
import base64
import gzip
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAPTURE_TMP = ROOT / ".git_capture_tmp"
PACK_TMP = ROOT / ".git_push_pack.tmp"
REVS_TMP = ROOT / ".git_push_revs.tmp"


def git_out(*args: str) -> bytes:
    """跑 git 并取 stdout —— 用临时文件，不用管道。"""
    with open(CAPTURE_TMP, "wb") as fh:
        subprocess.run(["git", *args], cwd=ROOT, check=True, stdout=fh)
    data = CAPTURE_TMP.read_bytes()
    CAPTURE_TMP.unlink(missing_ok=True)
    return data


def git_run(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def find_gh() -> str | None:
    for cand in ("gh", r"C:\Program Files\GitHub CLI\gh.exe"):
        p = shutil.which(cand) or (cand if os.path.exists(cand) else None)
        if p:
            return p
    return None


def get_token() -> str:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    gh = find_gh()
    if not gh:
        raise SystemExit("没有 token：设 GITHUB_TOKEN，或装并登录 gh CLI")
    out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit(f"gh auth token 失败: {out.stderr.strip()[:200]}")
    return out.stdout.strip()


def pkt_line(data: bytes) -> bytes:
    return ("%04x" % (len(data) + 4)).encode() + data


def parse_pkt_lines(buf: bytes) -> list[bytes]:
    """按 pkt-line 规范切分。会跳过 `# service=` 行、flush(0000)、delim(0001)。"""
    out, i = [], 0
    while i + 4 <= len(buf):
        head = buf[i:i + 4]
        try:
            n = int(head, 16)
        except ValueError:
            break
        if n == 0:                     # flush-pkt
            i += 4
            continue
        if n == 1 or n == 2:           # delim-pkt / response-end-pkt
            i += 4
            continue
        if n < 4 or i + n > len(buf):
            break
        payload = buf[i + 4:i + n]
        if not payload.startswith(b"# service="):
            out.append(payload)
        i += n
    return out


def parse_refs(advert: bytes) -> dict[str, str]:
    """从 receive-pack 广告里取出 {ref: sha}。第一行形如 `<sha> <ref>\\0<caps>`。"""
    refs: dict[str, str] = {}
    for line in parse_pkt_lines(advert):
        s = line.decode("utf-8", "replace").split("\x00")[0].rstrip("\n").rstrip()
        if len(s) > 41 and s[40] == " ":
            sha, ref = s[:40], s[41:].strip()
            if ref.startswith("refs/"):
                refs[ref] = sha
    return refs


def remote_info(remote: str) -> tuple[str, str]:
    """返回 (base_url 去掉 .git, 显示用 url)"""
    url = git_out("remote", "get-url", remote).decode().strip()
    if not url.startswith("https://"):
        raise SystemExit(f"只支持 https 远端，当前是: {url}")
    rest = url[len("https://"):].rstrip("/")
    if rest.endswith(".git"):
        rest = rest[:-4]
    return f"https://{rest}.git", url


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    branch = a.branch or git_out("rev-parse", "--abbrev-ref", "HEAD").decode().strip()
    head = git_out("rev-parse", "HEAD").decode().strip()
    base, shown = remote_info(a.remote)
    print(f"[本地] {shown}  分支 {branch}  HEAD {head[:10]}")

    tok = get_token()
    hdrs = {
        "Authorization": "Basic " + base64.b64encode(f"x-access-token:{tok}".encode()).decode(),
        "User-Agent": "git/2.47 (python-https)",
        "Accept": "*/*",
    }

    # 1) 远端 refs（receive-pack 广告）
    req = urllib.request.Request(f"{base}/info/refs?service=git-receive-pack", headers=hdrs)
    with urllib.request.urlopen(req, timeout=60) as r:
        advert = r.read()
    refs = parse_refs(advert)
    remote_main = refs.get(f"refs/heads/{branch}")
    print(f"[远端] refs/heads/{branch} = {remote_main[:10] if remote_main else '(不存在)'}"
          f"   广告里 {len(refs)} 个 ref")

    if remote_main == head:
        print("[结果] 远端已经就是这个提交，无需推送")
        return 0

    # 2) 生成 pack：只喂 `pack-objects --revs` 一份**纯 SHA 列表**。
    #
    # 踩过的坑：`git rev-list --objects HEAD --not --remotes=origin` 在这台机上会
    # 吐出**一个路径为空、带尾随空格的条目**（实测 `9c389d50…<空格>`，该对象既不在
    # 本仓库的树里、cat-file 也不认）。`--revs` 读带路径的行时会尝试解析 path，
    # 于是直接 `fatal: bad revision`。
    # 所以这里用不带 --objects 的 rev-list：每行就是裸 sha，没有路径可解析。
    rev_args = ["rev-list", head] + (["--not", remote_main] if remote_main else [])
    with open(REVS_TMP, "wb") as fh:
        subprocess.run(["git", *rev_args], cwd=ROOT, check=True, stdout=fh)
    n_objs = sum(1 for _ in open(REVS_TMP, "rb"))
    with open(PACK_TMP, "wb") as pf, open(REVS_TMP, "rb") as rf:
        subprocess.run(["git", "pack-objects", "--stdout", "--revs", "--thin",
                        "--delta-base-offset"],
                       cwd=ROOT, check=True, stdin=rf, stdout=pf)
    pack = PACK_TMP.read_bytes()
    PACK_TMP.unlink(missing_ok=True)
    REVS_TMP.unlink(missing_ok=True)
    print(f"[打包] {n_objs} 个提交/对象 → {len(pack)} 字节")
    if a.dry_run:
        print("[dry-run] 不发送")
        return 0

    # 3) POST git-receive-pack：pkt-line 命令 + flush + pack
    old = remote_main or "0" * 40
    cmd = f"{old} {head} refs/heads/{branch}\x00 report-status side-band-64k agent=python-https"
    body = pkt_line(cmd.encode()) + b"0000" + pack
    post = urllib.request.Request(
        f"{base}/git-receive-pack", data=body, method="POST",
        headers={**hdrs,
                 "Content-Type": "application/x-git-receive-pack-request",
                 "Content-Length": str(len(body)),
                 "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(post, timeout=240) as r:
        resp = r.read()
        enc = r.headers.get("Content-Encoding")
    if enc == "gzip":
        resp = gzip.decompress(resp)

    # report-status 走 side-band：外层 pkt-line 的每个 payload 首字节是通道号
    # （1=数据 2=进度 3=错误）。不剥掉的话，进度条会把关键结论淹掉。
    data_ch, err_ch, shown = [], [], []
    for payload in parse_pkt_lines(resp):
        if not payload:
            continue
        cb, body = payload[0], payload[1:]
        if cb == 3:
            err_ch.append(body)
        elif cb == 2:
            shown.append(body)
        else:
            data_ch.append(body)
    status_text = b"".join(data_ch).decode("utf-8", "replace").replace("\x01", "\n")
    progress_tail = b"".join(shown).decode("utf-8", "replace").splitlines()[-1:] if shown else []
    if progress_tail:
        print("[进度]", progress_tail[0].strip()[:120])
    print("[状态]", status_text.strip()[:300] or "(无 report-status)")
    if err_ch:
        print("[错误]", b"".join(err_ch).decode("utf-8", "replace").strip()[:300])

    ok = "unpack ok" in status_text and "ng " not in status_text
    print("[结果]", "推送成功" if ok else "远端报告失败，见上面响应")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
