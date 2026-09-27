# -*- coding: utf-8 -*-
"""Inventory (and optionally delete) this experiment's remote output images.

  python tools/_remote_outputs.py                 # inventory + cross-check
  python tools/_remote_outputs.py --delete        # remove the day dirs that hold
                                                  # only our images

Ownership is decided by the strongest key the service writes into the PNG's
`qwen_image_21` iTXt chunk:

  1. timing.request_id  — we set X-Request-Id to the job id or the recovery id,
                          the service stores it verbatim
  2. output.prompt_sha256 / request.prompt — exact prompt text equality
  3. otherwise the file is NOT ours and is never touched

A directory is deleted only when every *.png in it is ours and none of the
hand-named historical files are inside it.

Note: PIL does not surface this chunk through Image.info on every Pillow build,
so the chunk is parsed from the raw bytes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import sys

import paramiko

TOOLS = pathlib.Path(__file__).resolve().parent
PKG = TOOLS.parent / "exp" / "style-reference-migration-20260927"
OUT_DIR = "/root/qwen-image-2.1/outputs"

REMOTE_PY = r'''
import hashlib, json, os, struct, sys

def chunk_meta(path):
    try:
        data = open(path, "rb").read(1 << 20)      # the iTXt chunk sits before IDAT
    except Exception:
        return None
    i = 8
    while i + 8 <= len(data):
        ln = struct.unpack(">I", data[i:i+4])[0]
        typ = data[i+4:i+8].decode("latin1", "replace")
        if typ == "iTXt":
            body = data[i+8:i+8+ln]
            try:
                kw, rest = body.split(b"\x00", 1)
                rest = rest[2:]
                rest = rest.split(b"\x00", 1)[1]
                rest = rest.split(b"\x00", 1)[1]
                if kw.decode("latin1") == "qwen_image_21":
                    return json.loads(rest.decode("utf-8", "replace"))
            except Exception:
                return None
        if typ == "IDAT":
            break
        i += 12 + ln
    return None

root = "/root/qwen-image-2.1/outputs"
out = []
for dirpath, _, files in os.walk(root):
    for fn in sorted(files):
        if not fn.endswith(".png"):
            continue
        p = os.path.join(dirpath, fn)
        rec = {"path": p, "name": fn, "bytes": os.path.getsize(p)}
        meta = chunk_meta(p)
        if meta is None:
            rec["meta"] = "none"
        else:
            rec["meta"] = "ok"
            rec["request_id"] = (meta.get("timing") or {}).get("request_id")
            req = meta.get("request") or {}
            rec["seed"] = req.get("seed")
            rec["size"] = f'{req.get("width")}x{req.get("height")}'
            rec["prompt_sha"] = hashlib.sha256(
                str(req.get("prompt") or "").encode("utf-8")).hexdigest()
            rec["prompt_len"] = len(str(req.get("prompt") or ""))
            rec["inputs"] = meta.get("inputs") or []
        out.append(rec)
print(json.dumps(out))
'''


def connect():
    cfg = {}
    for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(cfg["AUTODL_HOST"], port=int(cfg["AUTODL_PORT"]), username=cfg["AUTODL_USER"],
              password=cfg["AUTODL_PASS"], timeout=25, banner_timeout=30, auth_timeout=30,
              allow_agent=False, look_for_keys=False)
    return c


def run(c, cmd, timeout=600):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    return (out.read().decode("utf-8", "replace"),
            err.read().decode("utf-8", "replace"),
            out.channel.recv_exit_status())


def our_jobs() -> dict:
    """job id -> prompt hash, for every request this session sent."""
    jobs = {}
    for man in (PKG / "manifest.json", PKG / "exec" / "anime" / "manifest.json"):
        if not man.exists():
            continue
        m = json.loads(man.read_text(encoding="utf-8"))
        for job in m["jobs"]:
            txt = (PKG / job["prompt_file"]).read_text(encoding="utf-8")
            jobs[job["id"]] = hashlib.sha256(txt.encode("utf-8")).hexdigest()
    # the recovery ids used when a client timeout had to be resolved
    for jid in list(jobs):
        jobs.setdefault(f"sm_{jid}"[:63], jobs[jid])
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true")
    a = ap.parse_args()

    c = connect()
    run(c, "echo %s | base64 -d > /tmp/_inv2.py" % base64.b64encode(
        REMOTE_PY.encode()).decode())
    out, err, rc = run(c, "export PATH=/root/miniconda3/bin:$PATH; "
                          "cd /root/qwen-image-2.1 && python /tmp/_inv2.py 2>/dev/null")
    files = json.loads(out or "[]")
    print(f"[remote] {len(files)} PNG under {OUT_DIR}")

    ours = our_jobs()
    total = sum(f["bytes"] for f in files)
    mine, theirs, unknown = [], [], []
    for f in files:
        rid = f.get("request_id")
        if f.get("meta") == "ok" and (rid in ours or f.get("prompt_sha") in set(ours.values())):
            f["matched_by"] = "request_id" if rid in ours else "prompt_hash"
            mine.append(f)
        elif f.get("meta") == "ok":
            theirs.append(f)
        else:
            unknown.append(f)

    def mib(items):
        return sum(x["bytes"] for x in items) / 1048576

    print(f"   ours  : {len(mine):>4} files  {mib(mine):>8.1f} MiB")
    print(f"   other : {len(theirs):>4} files  {mib(theirs):>8.1f} MiB")
    print(f"   no meta: {len(unknown):>2} files  {mib(unknown):>8.1f} MiB")
    print(f"   total : {len(files):>4} files  {total / 1048576:>8.1f} MiB")

    by_dir: dict[str, list[dict]] = {}
    for f in files:
        by_dir.setdefault(str(pathlib.PurePosixPath(f["path"]).parent), []).append(f)

    print("\n   per directory:")
    deletable = []
    for d, items in sorted(by_dir.items()):
        n_mine = sum(1 for x in items if x in mine)
        n_other = len(items) - n_mine
        if n_other == 0 and n_mine:
            verdict, note = "DELETE", ""
            deletable.append(d)
        elif n_mine and n_other:
            verdict, note = "keep", "mixed: contains files that are not ours"
        else:
            verdict, note = "keep", "nothing of ours in here"
        print(f"   {d:<48} {len(items):>4} files  ours={n_mine:<4} other={n_other:<4} "
              f"{verdict:<7} {note}")

    if theirs:
        print("\n   not-ours samples (never touched):")
        for f in theirs[:5]:
            print(f"     {f['path']}  size={f.get('size')} seed={f.get('seed')} "
                  f"rid={f.get('request_id')}")
    if unknown:
        print("\n   files without a generation record:")
        for f in unknown[:8]:
            print(f"     {f['path']}")

    if not a.delete:
        print(f"\n[dry-run] would delete {len(mine)} file(s), {mib(mine):.1f} MiB")
        for d in deletable:
            print(f"          whole directory (contains only ours): {d}")
        print("          rerun with --delete to remove exactly those files")
        c.close()
        return 0

    # Delete per file, never a directory that holds anything else.
    paths = [f["path"] for f in mine]
    BATCH = 60
    removed_total = 0
    for i in range(0, len(paths), BATCH):
        chunk = paths[i:i + BATCH]
        listing = "\n".join(chunk)
        cmd = ("/root/miniconda3/bin/python - <<'PYEOF'\n"
               "import os\n"
               "paths = " + repr(listing) + ".splitlines()\n"
               "ok = missing = 0\n"
               "for p in paths:\n"
               "    try:\n"
               "        os.remove(p)\n"
               "        ok += 1\n"
               "    except FileNotFoundError:\n"
               "        missing += 1\n"
               "print(f'removed={ok} already_gone={missing}')\n"
               "PYEOF")
        o2, e2, rc2 = run(c, cmd)
        line = (o2.strip() or e2.strip())
        print(f"   batch {i // BATCH + 1}: {line}")
        if "removed=" in line:
            removed_total += int(line.split("removed=")[1].split()[0])

    run(c, "rm -f /tmp/_inv2.py /tmp/_c.py /tmp/_m.py /tmp/_mr.py")
    o3, _, _ = run(c, f"du -sh {OUT_DIR} 2>/dev/null; echo '--- remaining png:'; "
                      f"find {OUT_DIR} -name '*.png' | wc -l; echo '--- names:'; "
                      f"ls -1 {OUT_DIR} | head -20")
    print(f"\n[deleted] {removed_total} file(s) actually removed "
          f"(planned {len(paths)}, ~{sum(f['bytes'] for f in mine) / 1048576:.1f} MiB)")
    print("[remote after]")
    for line in o3.strip().splitlines():
        print("   " + line)
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
