# -*- coding: utf-8 -*-
"""本地 ↔ 实例双向对账：服务和 UI 到底同不同步。

  python tools/verify_sync.py            # 对账 + 退出码（0 = 完全一致）
  python tools/verify_sync.py --json     # 机器可读

比的是 MD5，方向双向：
  · 本地有、远端不同 → drift（部署脚本会传上去）
  · 本地有、远端没有 → missing
  · 远端有、本地没有 → extra（**部署是单向的，本地删掉不会从远端删**）

`deploy_service.py` 只按 md5 跳过"相同"的文件、从不清理远端多出来的文件，
所以只跑部署并不能证明两边一致；这个脚本才是判据。
额外检查 `tools/deploy_manifest.py` 的映射覆盖：载荷里的每个文件都必须能映射到远端路径，
不然它会被部署脚本静默跳过（`remote_path_for` 返回 None 就 continue）。

**注意 `scripts/qwen_env.sh` 会永远显示 drift**：本地是 `CHANGE_ME` 占位符，
实例那份含真实 key，部署脚本有意不覆盖它（`PROTECTED_BASENAMES`）。这一处不同是设计如此，
判据里把它单独列成 `expected_drift`，不参与 verdict。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import posixpath
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
SRC = ROOT / "service"

sys.path.insert(0, str(TOOLS))
import deploy_manifest as M  # noqa: E402

SKIP_DIRS = {"__pycache__", ".ipynb_checkpoints", ".git", ".pytest_cache"}
SKIP_EXT = {".pyc", ".pyo", ".log"}


def env_cfg() -> dict:
    for name in ("autodl_new.env", "autodl.env"):
        p = TOOLS / name
        if not p.exists():
            continue
        cfg = {}
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
        if cfg.get("AUTODL_HOST"):
            cfg["_file"] = name
            return cfg
    raise SystemExit("找不到 autodl_new.env / autodl.env")


def local_files() -> list[tuple[str, pathlib.Path, str]]:
    out = []
    for p in sorted(SRC.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in SKIP_EXT:
            continue
        rel = p.relative_to(SRC).as_posix()
        out.append((rel, p, hashlib.md5(p.read_bytes()).hexdigest()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cfg = env_cfg()
    remote_root = M.REMOTE_ROOT
    files = local_files()

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(cfg["AUTODL_HOST"], port=int(cfg["AUTODL_PORT"]), username=cfg["AUTODL_USER"],
              password=cfg["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
              allow_agent=False, look_for_keys=False)

    def sh(cmd, t=300):
        _, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")

    sftp = c.open_sftp()

    def remote_md5(path: str):
        try:
            st = sftp.stat(path)
        except IOError:
            return None
        try:
            with sftp.file(path, "rb") as fh:
                h = hashlib.md5()
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:                                               # noqa: BLE001
            return None

    same, drift, missing, unmapped = [], [], [], []
    expected_drift = []
    expected_remote = set()
    protected_remote = set()
    for rel, local, lmd5 in files:
        rp = M.repo_to_remote(f"service/{rel}")
        if rp is None:
            unmapped.append(rel)
            continue
        remote = posixpath.join(remote_root, rp)
        expected_remote.add(remote)
        rmd5 = remote_md5(remote)
        # 远端含真实密钥、部署脚本有意不覆盖的那份：差异是设计如此，不算 drift
        if posixpath.basename(rp) in M.PROTECTED_BASENAMES:
            expected_drift.append((rel, remote, lmd5, rmd5))
            protected_remote.add(remote)
            continue
        if rmd5 is None:
            missing.append((rel, remote))
        elif rmd5 == lmd5:
            same.append(rel)
        else:
            drift.append((rel, remote, lmd5, rmd5))

    # 远端多出来的（只关心 service/ 与 scripts/ 两棵部署树）
    #
    # 三类要排除，否则会把"本来就该在的文件"报成多出来：
    #   1. 精确匹配到本地载荷路径的
    #   2. 受保护文件（单独记在 expected_drift，免得同一处差异报两次）
    #   3. 相对路径与本地载荷同名的 —— 覆盖调度的坑：`service/scripts/qwen_env.sh`
    #      被映射到远端**根** `qwen_env.sh`（FILE_OVERRIDE），但 `scripts/` 里可能
    #      还留着旧的那份；它不是部署管的东西，也不算 repo 里的代码
    local_rel = {posixpath.relpath(p, remote_root) for p in expected_remote}
    local_names = {posixpath.basename(p) for p in expected_remote}
    extra = []
    for tree in (posixpath.join(remote_root, "service"),
                 posixpath.join(remote_root, "scripts")):
        out = sh(f"find {tree} -type f 2>/dev/null")
        for line in out.splitlines():
            line = line.strip()
            if not line or line in expected_remote or line in protected_remote:
                continue
            if any(seg in line for seg in ("/__pycache__/", ".pyc", ".ipynb_checkpoints")):
                continue
            rel_to_root = posixpath.relpath(line, remote_root)
            if rel_to_root in local_rel or posixpath.basename(line) in local_names:
                continue
            extra.append(line)

    sftp.close()
    c.close()

    result = {
        "instance": f"{cfg['AUTODL_HOST']}:{cfg['AUTODL_PORT']} ({cfg['_file']})",
        "remote_root": remote_root,
        "local_files": len(files),
        "same": len(same), "drift": len(drift), "missing": len(missing),
        "unmapped": unmapped, "extra_remote": extra,
        "expected_drift": [{"file": r, "remote": p,
                            "why": "含真实密钥，部署脚本有意不覆盖（PROTECTED_BASENAMES）"}
                           for r, p, _l, _m in expected_drift],
        "drift_detail": [{"file": r, "remote": p, "local_md5": l[:10], "remote_md5": m[:10]}
                         for r, p, l, m in drift],
        "missing_detail": [{"file": r, "remote": p} for r, p in missing],
        "verdict": "IN_SYNC" if not (drift or missing or extra or unmapped) else "DIFFERS",
    }

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[对账] {result['instance']}  root={remote_root}")
        print(f"  本地载荷 {len(files)} 个文件")
        print(f"  一致     {len(same)}")
        print(f"  不同     {len(drift)}")
        print(f"  本地有远端无 {len(missing)}")
        print(f"  远端多出 {len(extra)}")
        print(f"  映射不到 {len(unmapped)}")
        for r, p, l, m in expected_drift:
            print(f"    预期差异 {r}（远端含真实 key，部署不覆盖）")
        for r, p, l, m in drift:
            print(f"    drift   {r}  local={l[:10]} remote={m[:10]}")
        for r, p in missing:
            print(f"    missing {r}  -> {p}")
        for e in extra:
            print(f"    extra   {e}")
        for u in unmapped:
            print(f"    unmapped {u}（deploy_manifest 没给映射，会被静默跳过）")
        print(f"  结论：{result['verdict']}")

    return 0 if result["verdict"] == "IN_SYNC" else 1


if __name__ == "__main__":
    sys.exit(main())
