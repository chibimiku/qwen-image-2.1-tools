#!/usr/bin/env python3
"""Summarise the CFG/negative-prompt A/B manifest: which cells produced images."""
import collections
import json
import sys

MANIFEST = sys.argv[1] if len(sys.argv) > 1 else "/root/exp_out/manifest.jsonl"

rows = []
with open(MANIFEST, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

print("total rows:", len(rows))
ok = collections.Counter()
bad = collections.Counter()
for r in rows:
    key = (r.get("variant"), r.get("task"))
    if r.get("ok"):
        ok[key] += 1
    else:
        bad[key] += 1

print("cell  ok  fail")
for key in sorted(set(ok) | set(bad)):
    print("  %-18s %3d %5d" % ("/".join(str(x) for x in key), ok[key], bad[key]))

fails = [r for r in rows if not r.get("ok")]
if fails:
    print("first failure:", json.dumps(fails[0], ensure_ascii=False)[:600])
    print("sample errors:")
    for msg, count in collections.Counter(str(r.get("error"))[:160] for r in fails).most_common(4):
        print("  %4d  %s" % (count, msg))

print("images on disk:", end=" ")
import glob
print(len(glob.glob("/root/exp_out/*.png")))
