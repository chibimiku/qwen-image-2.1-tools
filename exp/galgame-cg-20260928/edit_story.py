# -*- coding: utf-8 -*-
"""后期修图（edit）：把已出的 CG 当参考图喂回去，只改需要改的地方。

  python exp/galgame-cg-20260928/edit_story.py --list
  python exp/galgame-cg-20260928/edit_story.py --only 11        # 单张试验
  python exp/galgame-cg-20260928/edit_story.py                  # 全部

## 为什么走这条路（而不是重写 prompt 重出）

服务端里 `/v1/images/edits` 与 `/v1/images/generations` **是同一个实现**
（它自己的 docstring 写明"两条路径都走 _parse_gen_request，行为完全一致"）。
所以所谓 edit = **把已经出的图当参考图再喂回去**，由提示词说明"只改哪里"。

这么做的好处是**保住已经画对的部分**：11 那张的背带滑落、手撑镜面、
光影都对，只有"衬衫敞开"和"裙长"要改。重出会把这些重新交给运气。

## 一条规则

提示词要写成**"保持……只改……"**，而且**只描述要改的那一点**。
不要重述整个画面 —— 重述等于让它重画。

## 铁律（踩过的）

**必须显式声明画面里有几个人。** 实测：把已出的图当参考图喂回去时，
模型极易把参考图里的人**当成第二个角色**画进去（story-06 / seed-20260927 都是这么坏的）。
所以每次 edit 都强制带一句人数声明。
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import sys
import threading
import time

import paramiko
import requests

EXP = pathlib.Path(__file__).resolve().parent
ROOT = EXP.parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import autodl_ssh  # noqa: E402

STORY = EXP / "story"
EDITED = EXP / "story-edited"
LOG = EXP / "edit-log.jsonl"

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")
KEY = [l.strip() for l in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines()
       if l.strip() and not l.startswith("#")][0]

KEEP = ("Change only what is described below. Keep everything else identical to the source "
        "image: the same face, the same hair, the same pose, the same camera angle, the same "
        "framing and the same lighting.")

SINGLE = ("Exactly one woman is in the frame, drawn exactly once. Do not add a second person, "
          "do not duplicate her, and do not draw a reflection of her elsewhere.")

# --------------------------------------------------------------------------- #
# 逐张 edit 规格
#
# 判定依据来自 STORY-GEN-REPORT.md：哪些部分已经画对（别动）、哪些要改。
# --------------------------------------------------------------------------- #
SPEC: dict[str, dict] = {
    "04-unbutton": {
        "why": "被画成「她扣自己衬衫并对镜头笑」。要把动作改回「她的手停在另一个人的衬衫上」。",
        "keep": "the studio, the window light, the warm tone",
        "change": (
            "Her two hands are now working at the front of a different person's white shirt "
            "instead of her own clothing. An open men's white shirt front fills the space "
            "between her and the camera: the top button is already undone and her fingers are "
            "stopped still on the second button. She is not smiling; her lips are closed and "
            "her expression is intent and a little unsettled, watching the person she is "
            "dressing from very close."),
    },
    "10a-unhook": {
        "why": "背带位置、扣环、台灯、开衫、粉裙都对；只有表情要改（现在是甜笑）。",
        "keep": "the strap hanging off her shoulder and down her arm with the buckle at her "
                "elbow, her hand on the waist button, the desk lamp, the cardigan on the chair, "
                "the folded pink dress, the dark room",
        "change": (
            "Her expression is no longer a bright smile. She is looking back over her shoulder "
            "with a level, unreadable gaze, lips together, a faint tension around her eyes, as "
            "though she has just said something she cannot take back."),
    },
    "11-mirror-adult": {
        "why": "背带滑落、手撑镜面、光影都对；要改「衬衫没敞开」与「裙长变短」。",
        "keep": "her pose against the mirror, the hand pressed flat on the glass, the measuring "
                "tape dangling from her other hand, the single warm lamp, the deep shadow",
        "change": (
            "Her white blouse is unfastened and hangs open on both sides, revealing the "
            "camisole underneath; and the skirt is long and pleated, reaching down past her "
            "knees with its white ruffled underlayer showing at the hem, instead of the short "
            "flared skirt. Her eyes are lifted toward the reflection with a steady, slightly "
            "startled look rather than a cheerful smile."),
    },
}

# --------------------------------------------------------------------------- #
# 旧图的三处改动（底图在 out/ 与 fixed-2/，不是 story/）
#
# 这三张来自旧的那批出图（12 幕正片），用的是旧样式档位，所以不重出 ——
# 重出会把它换成新档位、与已验收的版本不连续。只改需要改的那一处。
# --------------------------------------------------------------------------- #
OLD_SPEC: dict[str, dict] = {
    "07a-icecream": {
        "src": "fixed-2/story-04-icecream.png",
        "why": "剧本把这一幕定位在「下午偏晚」，但原图是正午强光，插在「午后咖啡厅」之后不连续。",
        "keep": "her pose, both hands holding the cone and the napkin, the promenade, the boats, "
                "the lighthouse, the sea, the railing, her outfit and her hair",
        "change": ("The light is now late-afternoon golden hour instead of harsh midday sun: the "
                   "sun sits low behind her, long soft shadows stretch toward the camera, the "
                   "sky near the horizon warms to pale gold and the sea catches warm highlights, "
                   "while the upper sky stays light blue."),
    },
    "12-closeup": {
        "src": "out/story-08-closeup.png",
        "why": "剧本要求「衬衫领口还没扣好 + 锁骨上一道浅浅的印子」——身体已经答过了，"
               "她却偏要再听一次。原图是常规特写，没有这个信息。",
        "keep": "her face, her eyes, her hairstyle and the white flower hairpin, the pose, "
                "the blurred warm street bokeh background, the framing",
        "change": ("Her blouse collar is unbuttoned and hangs slightly open at the throat, and "
                   "a faint mark is visible on her collarbone. She is looking straight at the "
                   "viewer with a small uncertain smile, more nervous than cheerful."),
    },
    "13a-goodnight": {
        "src": "fixed-2/story-12-goodnight.png",
        "why": "与 11 同一类问题：整体气质被净化、偏可爱立绘，要压向「夜色里的克制」。",
        "keep": "her pose, both hands on the bag, the bag, the streetlamp, the street, "
                "the building behind, her outfit and shoes",
        "change": ("The mood is quieter and more restrained: her expression is a small closed "
                   "smile with a hint of nerves rather than a bright cheerful one, and the "
                   "night around her is deeper and more saturated, with the lamp casting a "
                   "tighter pool of warm light and the background falling darker."),
    },
}


def build(name: str) -> str:
    s = SPEC.get(name) or OLD_SPEC[name]
    return " ".join([KEEP, SINGLE, s["change"]])


def source_of(name: str) -> pathlib.Path | None:
    """底图路径：新图在 story/，旧图按 OLD_SPEC 的 src。"""
    if name in SPEC:
        p = STORY / f"{name}.png"
        return p if p.exists() else None
    s = OLD_SPEC.get(name)
    if not s:
        return None
    p = EXP / s["src"]
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--old", action="store_true", help="改用旧图的三处改动（OLD_SPEC）")
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--keep-original", action="store_true",
                    help="把原图作为 image2 也喂进去（默认不喂）")
    a = ap.parse_args()

    table = OLD_SPEC if a.old else SPEC
    if a.list:
        print(f"=== {'旧图改动' if a.old else '后期修图'}规格（{len(table)} 张）===")
        for n, s in table.items():
            src = source_of(n)
            print(f"\n  {n}  {'(底图在) ' + str(src.relative_to(EXP)) if src else '(缺底图!)'}")
            print(f"    为什么改：{s['why']}")
            print(f"    保持不变：{s['keep']}")
            print(f"    改成：{s['change'][:110]}…")
        return 0

    names = [n for n in table if (not a.only or any(o in n for o in a.only))]
    EDITED.mkdir(parents=True, exist_ok=True)

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
                password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16074), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = cli.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base_url = "http://127.0.0.1:16074"
    h = {"Authorization": "Bearer " + KEY}

    done = 0
    try:
        for i, n in enumerate(names, 1):
            src = source_of(n)
            if src is None:
                print(f"  [{i}/{len(names)}] {n:<20} 跳过：没有底图")
                continue
            dst = EDITED / f"{n}.png"
            files = [("image", (src.name, open(src, "rb"), "image/png"))]
            prompt = build(n)
            data = {"prompt": prompt, "num_inference_steps": str(a.steps),
                    "seed": str(a.seed), "width": "1600", "height": "896"}
            t0 = time.time()
            try:
                r = requests.post(base_url + "/v1/images/edits", headers=h, data=data,
                                  files=files, timeout=1800)
                dt = round(time.time() - t0, 1)
                if r.status_code != 200:
                    print(f"  [{i}/{len(names)}] {n:<20} FAIL {r.status_code} {r.text[:90]}")
                    continue
                item = (r.json().get("data") or [{}])[0]
                b64 = item.get("b64_json") or ""
                if not b64:
                    print(f"  [{i}/{len(names)}] {n:<20} FAIL 无 b64")
                    continue
                dst.write_bytes(base64.b64decode(b64))
                with LOG.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "name": n, "source": str(src.relative_to(EXP)), "seconds": dt,
                        "seed": item.get("seed"), "size": r.json().get("size"),
                        "prompt": prompt,
                    }, ensure_ascii=False) + "\n")
                print(f"  [{i}/{len(names)}] {n:<20} OK {dt}s -> story-edited/{dst.name}")
                done += 1
            except Exception as exc:                                    # noqa: BLE001
                print(f"  [{i}/{len(names)}] {n:<20} ERR {type(exc).__name__}: {exc}")
    finally:
        try:
            fwd.shutdown()
            cli.close()
        except Exception:                                               # noqa: BLE001
            pass

    print(f"\n完成 {done}/{len(names)}")
    return 0 if done == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
