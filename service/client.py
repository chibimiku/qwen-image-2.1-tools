#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tiny client for the Qwen-Image-2.1 HTTP service.

    python client.py t2i "a capybara reading a book by candlelight" -o out.png
    python client.py t2i "..." --transparent --aspect-ratio 16:9 --steps 20
    python client.py edit in.png "make the sky sunset" -o edited.png
    python client.py job  "..."            # async submit + poll
    python client.py health

Point it somewhere else with --base-url (e.g. an SSH tunnel on 127.0.0.1:16006).
"""
import argparse
import base64
import json
import sys
import time

import requests

DEFAULT_BASE = "http://127.0.0.1:6006"


def save(item, path):
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(item["b64_json"]))
    print(f"saved {path}  {item['width']}x{item['height']} mode={item.get('mode')} "
          f"seed={item.get('seed')} elapsed={item.get('elapsed_s')}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["t2i", "edit", "job", "health"])
    ap.add_argument("prompt", nargs="?", default=None)
    ap.add_argument("image", nargs="?", default=None, help="input image for 'edit' (placed before prompt in usage)")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("-o", "--out", default="out.png")
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--aspect-ratio", default=None, help="1:1 4:3 3:4 3:2 2:3 16:9 9:16")
    ap.add_argument("--transparent", action="store_true")
    ap.add_argument("--format", default="png", choices=["png", "jpeg", "webp"])
    a = ap.parse_args()

    base = a.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {a.api_key}"} if a.api_key else {}

    if a.cmd == "health":
        r = requests.get(base + "/health", headers=headers, timeout=30)
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        return

    if a.cmd == "edit":
        if not a.image or not a.prompt:
            print("usage: client.py edit <image.png> '<prompt>' -o out.png", file=sys.stderr)
            sys.exit(2)
        with open(a.image, "rb") as fh:
            files = [("image", (a.image, fh.read(), "image/png"))]
        data = {"prompt": a.prompt, "num_inference_steps": str(a.steps),
                "output_format": a.format, "transparent": str(a.transparent).lower()}
        if a.seed is not None:
            data["seed"] = str(a.seed)
        r = requests.post(base + "/v1/images/edits", files=files, data=data, headers=headers, timeout=1800)
        r.raise_for_status()
        save(r.json()["data"][0], a.out)
        return

    if not a.prompt:
        print("prompt is required", file=sys.stderr)
        sys.exit(2)

    body = {"prompt": a.prompt, "num_inference_steps": a.steps, "output_format": a.format,
            "transparent": a.transparent}
    for k in ("seed", "width", "height", "aspect_ratio"):
        v = getattr(a, k)
        if v is not None:
            body[k] = v

    if a.cmd == "t2i":
        r = requests.post(base + "/v1/images/generations", json=body, headers=headers, timeout=3600)
        r.raise_for_status()
        save(r.json()["data"][0], a.out)
        return

    # async
    r = requests.post(base + "/v1/jobs", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    job_id = r.json()["id"]
    print("job", job_id)
    t0 = time.time()
    while True:
        time.sleep(3)
        j = requests.get(f"{base}/v1/jobs/{job_id}", headers=headers, timeout=60).json()
        st = j["status"]
        print(f"  [{time.time()-t0:6.1f}s] {st}")
        if st == "succeeded":
            save(j["result"][0], a.out)
            break
        if st in ("failed", "canceled"):
            print(json.dumps(j, indent=2, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
