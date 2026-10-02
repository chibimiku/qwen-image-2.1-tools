# -*- coding: utf-8 -*-
"""按 STORY.md 生成故事用的 CG。

  python exp/galgame-cg-20260928/gen_story.py --list          # 列出规格
  python exp/galgame-cg-20260928/gen_story.py --only 07b      # 只出某一张
  python exp/galgame-cg-20260928/gen_story.py                 # 出全部
  python exp/galgame-cg-20260928/gen_story.py --rerun 07b     # 强制重出

## 两个关键决定（都有实测依据）

**1. 参考图怎么喂。** 本机是两图参考（image1 管身份、image2 管画风），
现在有三个素材（堇 / 暖暖 / 画风），位置不够。实测证据：喂两张人像参考时，
模型会把参考图里的人当成第二个角色画进去（seed-20260927 那张就是 B1+B8 叠加）。

所以：
  · 只有堇出镜 → image1=堇，image2=画风参考（**不喂暖暖**，否则她泄漏成第二个人）
  · 两人同框   → image1=堇，image2=暖暖，**不喂画风**（画风靠 boost 样式词兜）

**2. 满幅约束对所有人都加。** 画风参考是 832×1216 竖构图，模型会跟着它的取景走，
把画面渲染成竖幅贴在宽画布中间（实测 story-09 纯白 71%）。所以 FULL_BLEED 是基础约束。
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

REFS = EXP / "refs"
OUT = EXP / "story"          # 新出的故事图放这里，不动 fixed-2/ 与 out/
LOG = EXP / "story-gen-log.jsonl"

CFG = {}
for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        CFG[k.strip()] = v.strip().strip('"').strip("'")
KEY = [l.strip() for l in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines()
       if l.strip() and not l.startswith("#")][0]

# --------------------------------------------------------------------------- #
# 固定段落
# --------------------------------------------------------------------------- #
LEDGER = ("Render this in the art style of the provided style reference, applying its "
          "technique only. <image1> defines the character's identity - hair colour, "
          "hairstyle, eye colour, facial features and outfit must be preserved exactly. "
          "<image2> is a STYLE SAMPLE ONLY: borrow its linework, colouring method, light "
          "rendering and texture.")

STYLE_BOOST = ("Premium galgame event CG rendering, dark-background portraiture: the subject "
               "is lit against a deep, saturated, dark background, separated by a bright "
               "glowing rim light. Strong bloom and soft lens glow on every highlight, dense "
               "floating glitter particles and tiny bokeh stars scattered across the frame, "
               "gentle chromatic warmth in the light. Crisp thin dark linework over luminous "
               "cel-shading with airbrushed gradient soft shading, high-contrast specular "
               "highlights on hair strands and fabric folds, iridescent pastel gradients in "
               "the shadows. Polished digital painting finish.")

FULL_BLEED = ("The composition is a single wide landscape image that fills the whole frame "
              "horizontally; the background continues across the full width and there are no "
              "white or empty vertical bars on either side.")

BAN = ("Do NOT copy from the style reference: its character, its pale blonde hair, its green "
       "eyes, its white dress, its stockings or garters, its violin strings, bow or other "
       "instruments, its constellation lines, floating stars, gems or sparkle props, its "
       "starfield stage floor, its reclining pose or its diagonal poster composition.")

# 两人各自的角色圣经（要分别点名，不能混）
BIBLE_JIN = ("The character is a young woman with shoulder-length wavy indigo-blue hair, a "
             "small side bun tied at one side of her head, a small white flower hairpin above "
             "one ear, large blue-violet eyes, and soft rounded facial features. She wears a "
             "white puff-sleeve blouse under a blue denim pinafore dress with two gold buttons "
             "at the waist, the pleated skirt fading from sky blue at the waist to pale mint at "
             "the hem with a white ruffled underlayer.")

BIBLE_NUAN = ("The other woman is a different person: she has long pale-pink hair falling "
              "straight to her waist with softly curled ends, warm brown eyes, and she wears "
              "a white ribbed knit sweater with lacy bell cuffs under a pale pink "
              "check-patterned pinafore dress, with a small dark-red ribbon bow at the chest "
              "and a band of small printed letters along the hem of her skirt.")

TWO_WOMEN_RULE = (
    "Exactly two women are in the frame, and no one else. They are clearly different people "
    "- one is indigo-blue haired, the other is pale-pink haired. Do not blend their features, "
    "do not give either of them the other's hair colour, and do not add a third person. "
    "This is a single scene drawn once: draw each woman exactly one time. Do not place a "
    "second copy of either woman anywhere in the frame, do not mirror or repeat the pair, and "
    "do not render two versions side by side. The two women stand next to each other in the "
    "centre of the picture, close enough to touch.")

# 画风参考图的 starfield 元素很容易渗进背景（实测 07b 第一版整块地板变成星座连线）。
# 光在禁用清单里写"不要"不够 —— 要在**场景段**里正面描述背景长什么样。
NO_STARFIELD = (
    "The floor is a plain wooden studio floor with visible planks; the walls are plain warm "
    "grey. The background contains nothing celestial: no starfield floor, no constellation "
    "lines, no connected dots, no floating stars or gems.")

# --------------------------------------------------------------------------- #
# 逐图规格
#   who: jin | two | none
#   参考图：two → 堇 + 暖暖（不带画风）；其余 → 堇 + 画风
# --------------------------------------------------------------------------- #
SPEC: dict[str, dict] = {
    "01-entrance": {
        "who": "jin", "title": "进店（楼梯口）",
        "scene": "A small tailor's studio at the top of a wooden staircase in an old shopping "
                 "street. She stands inside the half-open doorway with one hand still on the "
                 "door handle, sizing up the visitor with a professional first glance. Behind "
                 "her: long racks of hanging garments, polished wooden floorboards, a warm "
                 "pendant lamp. Through the inner doorway a pale pink check-patterned dress "
                 "hangs on a rack. Wide cinematic composition, full body, subject off-centre.",
    },
    "02-measure": {
        "who": "jin", "title": "量肩（皮尺绕过肩）",
        # 第一版要求"她站在客人身后、两人都在画面里"，结果模型给同一个人画了两个副本
        # （深蓝发的人尤其容易配方 —— 堇本身就是深蓝发）。改成**单人视角**：
        # 客人只出现肩与后颈的上缘，主体是她的手与那段布尺。
        "scene": "Close view of a fitting in progress. Only the client's shoulder and the back "
                 "of their neck appear at the right edge of the frame, out of focus; the main "
                 "subject is the stylist herself, standing just behind and to the left, both "
                 "hands drawing a cloth measuring tape around that shoulder and pulling it "
                 "taut. Her eyes are fixed on the tape with complete concentration and her face "
                 "is close to the fabric. Nobody else is in the room and she is drawn exactly "
                 "once. Racks of hanging clothes and a tall window behind her, cool daylight.",
    },
    "03-the-question": {
        "who": "jin", "title": "那件事（她第一次抬眼）",
        "scene": "She has lowered the measuring tape and now looks up at the visitor, the tip "
                 "of her pen resting still on an open notebook. Her expression has not changed, "
                 "but her eyes have. She sits on a wooden stool in the studio, tape coiled on "
                 "the work table beside her. Soft window light. Wide cinematic composition, "
                 "medium close-up, shallow depth of field.",
    },
    "04-unbutton": {
        "who": "jin", "title": "换衣（她第一次不为工作而靠近）",
        # 第一版"她解客人的衬衫扣子"没画出来。改成**手部特写**：让动作本身成为画面主体，
        # 不靠两个人的关系构图。
        "scene": "Close view in the fitting area: her two hands at the front of an open shirt, "
                 "one hand having just released the top button and the other stopped still at "
                 "the second one. Her face is above the hands, lifted, watching the person she "
                 "is dressing, very close. Only a narrow strip of the other person's shirt front "
                 "is visible and she is drawn exactly once. Warm interior light, fitting-room "
                 "curtain behind, shallow depth of field.",
    },
    "07b-three-fitting": {
        "who": "two", "title": "两个人的量体（全篇最酸的一场）",
        # 第二版修好了"两人各画一次"，但布尺被画成"两人各拉一端"，看起来像拔河。
        # 关键：把布尺的**闭环**与**作用对象**写清楚 —— 尺子绕在暖暖身上、两端都在堇手里。
        "scene": BIBLE_NUAN + " " + TWO_WOMEN_RULE + " "
                 "The pink-haired woman stands facing slightly away with both arms held out to "
                 "the sides, standing still. The stylist stands close behind her. BOTH ends of "
                 "the measuring tape are held in the stylist's own two hands, and the tape "
                 "passes around the pink-haired woman's shoulder in a closed loop, so the tape "
                 "wraps the customer's body and never stretches between the two of them. The "
                 "stylist is reading the tape and adjusting the shoulder seam, not pulling. The "
                 "customer is holding the hem of her own skirt with one hand. "
                 + NO_STARFIELD + " "
                 "The stylist's white knit cardigan lies over the back of a chair, and spare "
                 "pink fabric is folded on the work table. Warm evening studio lamplight, deep "
                 "shadow behind the two of them. Wide cinematic composition, medium wide shot, "
                 "the two women standing one behind the other.",
    },
    "10a-unhook": {
        "who": "jin", "title": "顺着问下去（工作室·夜）",
        # 第一版没画出"背带滑落"。把服装状态写成**可验证的画面事实**（背带滑到肘部、
        # 扣环垂在手肘），而不是"one strap slipped down"这种含糊说法。
        "scene": "Late at night in the studio, lit by a single desk lamp on the work table. She "
                 "is seen from the waist up, turned three-quarters away but glancing back over "
                 "her shoulder at the viewer. Her pinafore dress hangs undone: the left strap "
                 "has slid completely off her shoulder and down her arm with the buckle dangling "
                 "at her elbow, and her hand has stopped on the second gold button at her waist. "
                 "Her white knit cardigan is draped over the chair behind her, and a folded pale "
                 "pink check-patterned dress lies on the work table under the lamp. Deep shadows "
                 "fill the rest of the room, warm rim light along her arm, shoulder and hair. "
                 "Wide cinematic composition, medium shot.",
    },
    "11-mirror-adult": {
        "who": "jin", "title": "试衣镜前（成人场景·主拍）",
        # 第一版背带没滑、裙子变成蓬裙。把服装状态写成具体事实，并压掉蓬裙倾向。
        "scene": "She stands with her back against the tall standing mirror, her head tilted "
                 "back against the glass. Both pinafore straps have slipped down off her "
                 "shoulders and hang at her elbows; her white blouse is unfastened and hangs "
                 "open on both sides, and the long pleated skirt is still fastened at her waist, "
                 "hanging straight down with its white ruffled underlayer showing at the hem. "
                 "One hand is pressed flat against the mirror glass beside her; the other hand "
                 "still holds the cloth measuring tape, which dangles down across her thigh. Her "
                 "eyes are lifted toward the reflection rather than down at herself. Single warm "
                 "lamplight from the side, deep shadow, glowing rim light along her shoulder, "
                 "arm and hair. Wide cinematic composition, medium shot, intimate framing.",
    },
    "13b-note": {
        "who": "none", "title": "把邀约放进衣服里",
        "scene": "Early morning light across a tailor's work table. Two garments lie side by "
                 "side, freshly altered: a folded pale pink check-patterned dress with a band of "
                 "small printed letters along its hem, and beside it a neatly folded man's "
                 "shirt. A small handwritten paper note is pinned to the chest of each garment. "
                 "Pins, chalk and a coiled measuring tape sit at the edge of the table. Wide "
                 "cinematic composition, still life, overhead three-quarter angle.",
    },
    "14-letter": {
        "who": "none", "title": "信（全篇落点）",
        "scene": "A wooden work table in a tailor's studio in the early morning. An unfolded "
                 "handwritten letter lies in the centre; a short leftover stub of cloth "
                 "measuring tape rests beside it. A folded white knit cardigan sits to one "
                 "side, and the hem of a pale pink check-patterned skirt is tucked under the "
                 "corner of the letter, with the row of small printed letters along that hem "
                 "just showing from under the paper's edge. Warm slanted morning light, dust in "
                 "the air. Wide cinematic composition, still life, shallow depth of field.",
    },
}


def compose_style() -> str:
    return STYLE_BOOST


def build_prompt(name: str) -> tuple[str, list[str]]:
    """返回（完整四段 prompt，参考图文件名列表）。"""
    s = SPEC[name]
    who = s["who"]
    if who == "none":
        body = s["scene"]
        refs = ["char", "style"]        # 无人物也要保持画风
    elif who == "two":
        body = s["scene"]                # scene 里已经含 BIBLE_NUAN 与 TWO_WOMEN_RULE
        refs = ["char", "nuannuan"]      # 两人身份优先，不带画风参考
    else:
        body = BIBLE_JIN + " " + s["scene"] + " She wears blue bow-embellished Mary Jane heels."
        refs = ["char", "style"]         # 带画风；**不喂暖暖**，否则她泄漏成第二个人
    prompt = "\n\n".join([LEDGER, compose_style(), FULL_BLEED, BAN, body])
    return prompt, refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--rerun", nargs="*", default=[])
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--size", default="1600x896")
    a = ap.parse_args()

    names = [n for n in SPEC if not a.only or any(o in n for o in a.only)]
    if a.list:
        print(f"=== 故事 CG 规格（{len(SPEC)} 张）===")
        for n, s in SPEC.items():
            _, refs = build_prompt(n)
            print(f"  {n:<20} [{s['who']:<4}] 参考={refs}  {s['title']}")
        print()
        for n in names:
            p, refs = build_prompt(n)
            print(f"  {n}: {len(p.split(chr(10) + chr(10)))} 段, {len(p)} 字符, refs={refs}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(CFG["AUTODL_HOST"], port=int(CFG["AUTODL_PORT"]), username=CFG["AUTODL_USER"],
                password=CFG["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", 16073), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = cli.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base = "http://127.0.0.1:16073"
    h = {"Authorization": "Bearer " + KEY}

    m = re.match(r"(\d+)x(\d+)", a.size)
    W, H = (m.group(1), m.group(2)) if m else ("1600", "896")

    done = 0
    try:
        for i, n in enumerate(names, 1):
            dst = OUT / f"{n}.png"
            if dst.exists() and not any(r in n for r in a.rerun):
                print(f"  [{i}/{len(names)}] {n:<20} 跳过（已存在）")
                done += 1
                continue
            prompt, refnames = build_prompt(n)
            nsec = len([x for x in prompt.split("\n\n") if x.strip()])
            if nsec < 5:
                print(f"  [{i}/{len(names)}] {n:<20} SKIP 只有 {nsec} 段")
                continue
            files = []
            for rn in refnames:
                p = REFS / f"{rn}.png"
                if p.exists():
                    files.append(("image", (p.name, open(p, "rb"), "image/png")))
            data = {"prompt": prompt, "num_inference_steps": str(a.steps),
                    "width": W, "height": H, "seed": str(a.seed)}
            t0 = time.time()
            try:
                r = requests.post(base + "/v1/images/generations", headers=h, data=data,
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
                        "name": n, "who": SPEC[n]["who"], "size": r.json().get("size"),
                        "seconds": dt, "seed": item.get("seed"), "refs": refnames,
                        "sections": nsec, "prompt": prompt,
                        "inputs": (item.get("metadata") or {}).get("inputs"),
                    }, ensure_ascii=False) + "\n")
                print(f"  [{i}/{len(names)}] {n:<20} OK {dt}s {r.json().get('size')} "
                      f"refs={refnames}")
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
