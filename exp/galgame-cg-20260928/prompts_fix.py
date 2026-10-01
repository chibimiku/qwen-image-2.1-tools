# -*- coding: utf-8 -*-
"""修复用的 prompt 层：把质检发现的缺陷翻译成具体的、可执行的 prompt 改动。

  python exp/galgame-cg-20260928/prompts_fix.py --list        # 列出各条改动
  python exp/galgame-cg-20260928/prompts_fix.py --build       # 生成 fixed-prompts.json
  python exp/galgame-cg-20260928/prompts_fix.py --show <name> # 看某张的最终 prompt

**为什么要把缺陷翻译成固定措辞**：
  实测的三类高频缺陷（手与道具的接触、鞋跟被画成玻璃块、过曝死白）反复出现在
  不同图上，说明它们不是"某张图运气不好"，而是**prompt 里没写**。所以修复不是
  逐张改写，而是给这几类补上**统一的、具体的**约束句 —— 这样改一处、
  所有相关图一起受益，也便于下一轮判断到底哪句起了作用。

每条改动都标注它对应哪些缺陷代码，事后能对账（哪条改动解决了哪个缺陷）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

EXP = pathlib.Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# 通用修正句：按缺陷类型定义，可叠加
# --------------------------------------------------------------------------- #
FIXES: dict[str, dict] = {
    # ── 手与道具的接触（A8，出现 5 次，是最高频的结构缺陷）──────────────────
    # 失败特征：手指与提绳/袋子融为一体；或手在物件后面只露指尖，"像贴上去"
    "hands_grip": {
        "codes": ["A8"],
        "why": "手指与提绳焊在一起 / 手没绕住物件。原 prompt 只写 \"carrying a bag\"，"
               "没有说明手与物件的接触关系",
        "text": ("Her hand grips the bag handle properly: the four fingers are curled around "
                 "the handle from the front and the thumb comes around from the far side, "
                 "so the handle passes visibly between finger and thumb. The fingers stay "
                 "separate and readable, with visible knuckles. The bag hangs from the "
                 "handle below her hand, not fused into her palm."),
    },
    # ── 鞋跟被画成半透明玻璃块（C3，在 03/11/12 三张上重复出现）─────────────
    "shoes_opaque": {
        "codes": ["C3"],
        "why": "鞋跟被渲染成半透明玻璃块并带重影。角色圣经只写了 "
               "\"blue bow-embellished Mary Jane heels\"，没说明材质与结构",
        "text": ("The shoes are solid opaque polished leather Mary Jane heels with a plain "
                 "solid block heel of the same blue material; the heel is completely opaque "
                 "with a crisp single outline, and the shoe back is a solid closed counter. "
                 "No transparent, glassy or doubled outlines anywhere on the shoes."),
    },
    # ── 过曝死白（C1，出现 4 次）──────────────────────────────────────────
    "exposure": {
        "codes": ["C1", "C2"],
        "why": "大块死白。背景没写具体内容，模型留白；加上白底立绘参考图的平光倾向",
        "text": ("Every part of the background contains readable detail; there are no large "
                 "blank white or blown-out areas and no featureless wash. The lighting is "
                 "soft and even, with the brightest areas still holding texture and colour."),
    },
    # ── 满幅构图（修 C1 时踩出来的新问题）──────────────────────────────
    # 失败特征：模型按**竖版参考图**的构图渲染，再贴到 1600×896 的宽画布上，
    # 左右各留一条纯白（实测 story-09 变成竖幅夹在白边里，纯白像素 71%）。
    "full_bleed": {
        "codes": ["C1"],
        "why": "画面被渲染成竖幅、两侧留白。宽高是显式传的，但参考图是竖构图，"
               "模型跟着参考图的取景走了",
        "text": ("The artwork fills the entire widescreen frame edge to edge: the street and "
                 "the building facades continue across the full width of the image, out to "
                 "both the left and right edges. There are no vertical white or empty bars "
                 "on the sides and no letterboxing; the background occupies the whole frame "
                 "behind her."),
    },
    # ── 人数：多出一个人（B1，P0 级）──────────────────────────────────────
    "single_subject": {
        "codes": ["B1", "C4", "A4"],
        "why": "同一个人被画了两次 / 多出一个角色。prompt 里没有显式的人数约束",
        "text": ("Exactly one girl is in the frame, alone. There is no second person, no "
                 "distant figure, no duplicate of her, and no reflection of her elsewhere "
                 "in the scene."),
    },
    # ── 画风参考图内容泄露（B8）─────────────────────────────────────────
    "no_leak": {
        "codes": ["B8"],
        "why": "参考图的星座连线/星空地面渗进背景",
        "text": ("The background is an ordinary real location. Do not draw constellation "
                 "lines, star charts, connected star patterns, floating stars, gems, or a "
                 "starry stage floor."),
    },
    # ── 姿势：靠栏杆 / 扶栏杆没做到（B7）─────────────────────────────────
    "pose_rail": {
        "codes": ["B7"],
        "why": "要求靠栏杆，实际直立站开；手悬空没接触栏杆",
        "text": ("Both of her forearms rest on the top rail in front of her and her hands "
                 "hang loosely over the far side of the rail; her body touches the rail and "
                 "her weight leans onto it."),
    },
    # ── 姿势：双手捧杯（B7）──────────────────────────────────────────────
    "pose_two_hands": {
        "codes": ["B7"],
        "why": "要求双手捧杯，实际单手",
        "text": ("Both of her hands are wrapped around the glass, one on each side of it, "
                 "with all fingers visible against the glass."),
    },
}


def base_prompt_from(scene: str, fixes: list[str], extra: str = "") -> str:
    """把修正句插进场景段的末尾（在镜头描述之前更自然，这里简化放在最末）。"""
    parts = [scene.strip()]
    for key in fixes:
        f = FIXES.get(key)
        if f:
            parts.append(f["text"])
    if extra:
        parts.append(extra.strip())
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# 四段结构：**必须整段发出**，不能只发场景段
#
# 踩过的坑：第一版 run_fix.py 只把 `scene`（角色圣经 + 场景）发出去，
# 把分工声明 / 样式词 / 禁止清单三段丢了 —— 结果模型退回"白底立绘"，
# story-12 的纯白像素从 0% 暴涨到 88%，整张图作废。
# 所以这里把前三段**原样保留**，修正句只往第四段（场景段）里加。
# --------------------------------------------------------------------------- #
LEDGER = ("Render this in the art style of the provided style reference, applying its "
          "technique only. <image1> defines the character's identity - hair colour, "
          "hairstyle, eye colour, facial features and outfit must be preserved exactly. "
          "<image2> is a STYLE SAMPLE ONLY: borrow its linework, colouring method, light "
          "rendering and texture.")

STYLE_BASE = ("Luminous anime illustration with a polished galgame CG finish: crisp clean "
              "linework, rich saturated colour with soft pastel gradients, glowing particle "
              "sparkles, wide soft bloom on highlights, dramatic rim light separating the "
              "subject from a deep contrasty background, delicate fabric and hair highlights.")

STYLE_BOOST = ("Premium galgame event CG rendering, dark-background portraiture: the subject "
               "is lit against a deep, saturated, dark background, separated by a bright "
               "glowing rim light. Strong bloom and soft lens glow on every highlight, dense "
               "floating glitter particles and tiny bokeh stars scattered across the frame, "
               "gentle chromatic warmth in the light. Crisp thin dark linework over luminous "
               "cel-shading with airbrushed gradient soft shading, high-contrast specular "
               "highlights on hair strands and fabric folds, iridescent pastel gradients in "
               "the shadows. Polished digital painting finish.")

BAN = ("Do NOT copy from <image2>: its character, its pale blonde hair, its green eyes, its "
       "white dress, its stockings or garters, its violin strings, bow or other instruments, "
       "its constellation lines, floating stars, gems or sparkle props, its starfield stage "
       "floor, its reclining pose, its diagonal poster composition or its frame.")


# 宽屏满幅：这一句放在**样式词之后、场景段之前**，对所有图都生效。
# 理由：参考图是 832×1216 竖构图，模型会跟着它的取景走，把画面渲染成竖幅贴在
# 宽画布中间、两侧留白（实测 story-09 纯白 71%、story-03 45.9%、story-12 88%）。
# 这不是某一张的问题，是"竖参考图 + 宽输出"这个组合的通病，所以做成基础约束。
FULL_BLEED = ("The composition is a single wide landscape image that fills the whole frame "
              "horizontally; the background continues across the full width and there are no "
              "white or empty vertical bars on either side.")


def compose(scene_fourth: str, style_tier: str = "base") -> str:
    """拼成完整 prompt：分工声明 / 样式词 / 满幅要求 / 禁止清单 / 场景段。"""
    style = STYLE_BOOST if style_tier == "boost" else STYLE_BASE
    return "\n\n".join([LEDGER, style, FULL_BLEED, BAN, scene_fourth.strip()])


# --------------------------------------------------------------------------- #
# 逐图的修复计划：哪张图、用哪几条修正、场景要改什么
# --------------------------------------------------------------------------- #
PLAN: dict[str, dict] = {
    "story-01-boutique": {
        "worst": "p1", "style_tier": "boost", "codes": ["C1", "B5", "A8"],
        "fixes": ["exposure"],
        "scene_edit": (
            "She stands in front of a tall gilt-framed mirror in a bright boutique, turned "
            "so she can see herself, one hand resting lightly on the mirror frame. Around "
            "her the shop is full of readable detail: wooden clothes racks hung with pastel "
            "dresses, a velvet stool, a vase of dried flowers, a small potted plant, a warm "
            "pendant lamp overhead, and a polished wooden floor with visible planks. Soft "
            "even daylight from a tall window; the bright areas still show texture."),
        "why": "过曝 53% + 镜框碎成一根金色竖条 + 镜边两手相接。把背景列成具体物件、"
               "并要求亮部保留质感；同时把'镜面与本体手相接'改成'手轻搭镜框'",
    },
    "story-02-cafe": {
        "worst": "p2", "codes": ["B7"],
        "fixes": ["pose_two_hands"],
        "scene_edit": (
            "She sits at a small round cafe table by the window, both hands wrapped around a "
            "glass of iced tea, a slice of strawberry shortcake on a white plate beside it, "
            "smiling at someone across the table. Warm afternoon light, potted plants and "
            "blurred street traffic outside."),
        "why": "要求双手捧杯，实际只有右手",
    },
    "story-03-street": {
        "worst": "p1", "codes": ["A8", "C3"],
        "fixes": ["hands_grip", "shoes_opaque"],
        "scene_edit": (
            "She walks toward the viewer along a quiet city street carrying a small brown "
            "paper shopping bag in her right hand at her side, hair and skirt lifted by a "
            "light breeze, glancing back over her shoulder with a bright smile. Late "
            "afternoon, long warm shadows, blurred shop fronts behind her."),
        "why": "四指与提绳焊在一起 + 鞋跟成玻璃块",
    },
    "story-04-icecream": {
        "worst": "p1", "style_tier": "boost", "codes": ["C1"],
        "fixes": ["exposure"],
        "scene_edit": (
            "She holds a soft-serve ice cream cone in one hand and leans forward slightly to "
            "take a bite, eyes bright, a paper napkin in her other hand. She stands on a "
            "seaside promenade: white railings, moored boats with visible hulls, blue-green "
            "sea with small waves and whitecaps, terracotta planters, a distant lighthouse, "
            "clear sky with soft clouds. Midday sun with clean readable shadows."),
        "why": "过曝 44%；同时把'双手'改成'一手持甜筒一手拿纸巾'（原写法两只手都占住了，"
               "而模型只画了一只，索性改成明确的单手持物）",
    },
    "story-05-park": {
        "worst": "p1", "codes": ["A3", "A7", "C3"],
        "fixes": [],
        "scene_edit": (
            "She sits properly on a wooden park bench: her hips and thighs rest on the seat "
            "plane, the bench boards pass behind her legs, and her feet reach the ground in "
            "front of the bench. Her torso is upright, one arm resting along the bench back. "
            "Autumn park, golden leaves drifting, low sun raking through the trees."),
        "why": "臀腿悬在座面前方（承重关系不成立）+ 胯部结构糊",
    },
    "story-06-sunset-bridge": {
        "worst": "p0", "codes": ["B1", "C4", "A4"],
        "fixes": ["single_subject", "pose_rail"],
        "scene_edit": (
            "She leans on the railing of a pedestrian bridge in a medium shot, seen from a "
            "three-quarter angle as she turns her head to look back toward the viewer. "
            "Behind and below her: a wide river reflecting orange and violet clouds, a "
            "distant silhouetted skyline, gulls. Deep sunset sky filling the upper third."),
        "why": "同一个人被画两次（P0）+ 远景那个站在栏杆上",
    },
    "story-09-holding-hands": {
        "worst": "p2", "codes": ["A1", "B7"],
        "fixes": [],
        "scene_edit": (
            "She walks beside the viewer and offers her right hand toward the camera, palm "
            "open and fingers spread and pointing forward, each finger separate and clearly "
            "outlined, thumb raised; she is laughing, the blue dress swaying with her "
            "stride. Her other hand hangs relaxed at her side. Quiet night street, warm shop "
            "window light and soft streetlamp glow."),
        "why": "四指全向下弯、指尖粘连、手掌糊在暗背景里；把'手指朝镜头'改成"
               "'掌心张开、五指分开、每根手指轮廓清楚'",
    },
    "story-11-rooftop": {
        "worst": "p1", "codes": ["A1", "B3", "B7", "C3"],
        "fixes": ["shoes_opaque", "pose_rail"],
        "scene_edit": (
            "She leans on the low railing at the edge of a building rooftop looking out over "
            "the evening city, a white knitted cardigan worn open over her blouse, its "
            "ribbed knit texture visible, the breeze lifting her hair. Her arms rest on the "
            "rail. Blue hour sky, thousands of small city lights below, calm and content."),
        "why": "手糊 + 开衫画成大衣（补'针织罗纹质感'）+ 没倚栏杆 + 鞋跟玻璃块",
    },
    "story-12-goodnight": {
        "worst": "p1", "style_tier": "boost", "codes": ["A1", "C3", "B5"],
        "fixes": ["hands_grip", "shoes_opaque"],
        "scene_edit": (
            "She stands under a streetlamp near the station entrance saying goodbye, holding "
            "a small brown paper shopping bag by its handles in front of her with both hands, "
            "warm shy smile, one foot turned slightly inward. The bag has a clearly drawn "
            "body and two handles. Night, quiet street, soft glow around the lamp, blurred "
            "station lights behind."),
        "why": "两手粘连 + 袋子是无结构扁块 + 鞋跟玻璃块",
    },
    "fix-04-icecream": {
        "worst": "p1", "style_tier": "boost", "codes": ["B6", "C2"],
        "fixes": [],
        "scene_edit": (
            "She holds a soft-serve ice cream cone in both hands and leans in to take a bite, "
            "eyes bright, a paper napkin tucked between her fingers. She stands on a seaside "
            "promenade under a bright blue daytime sky with soft white clouds: white "
            "railings, moored boats, blue-green sea, terracotta planters, a distant "
            "lighthouse. Bright midday sun, clear blue sky, no darkness anywhere."),
        "why": "白天被画成黑背景（B6/C2）。显式写'bright blue daytime sky'并要求'no darkness'",
    },
}


def build() -> dict:
    mf = EXP / "manifest.jsonl"
    best: dict[str, dict] = {}
    for line in mf.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("status") == "ok":
                best[r["name"]] = r

    out: dict[str, dict] = {}
    for name, p in PLAN.items():
        rec = best.get(name)
        if not rec:
            print(f"  跳过 {name}：manifest 无记录")
            continue
        parts = [x.strip() for x in rec["prompt"].split("\n\n") if x.strip()]
        bible = parts[-1].split(".")[0] + "." if parts else ""
        m = re.match(r"^(The character is .*?heels\.)\s*(.*)$", parts[-1], re.S)
        bible = m.group(1) if m else ""
        scene = base_prompt_from(p["scene_edit"], p["fixes"])
        fourth = bible + " " + scene
        # 样式词档位：默认 base；这几张原来就偏亮/偏平，改用 boost 把暗调与光点压回来
        tier = p.get("style_tier", "boost")   # 默认 boost：base 那几张都出了白边
        out[name] = {
            "name": name, "worst": p["worst"], "codes": p["codes"],
            "fixes": p["fixes"], "why": p["why"],
            "fourth": fourth,                       # 第四段（角色圣经 + 场景 + 修正句）
            "prompt": compose(fourth, tier),        # 完整四段，交给 /v1/images/generations
            "style_tier": tier,
            "refs": rec.get("refs"), "seed": rec.get("seed"), "size": rec.get("size"),
            "orig_prompt": rec["prompt"],
        }
    (EXP / "fixed-prompts.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"生成 {len(out)} 条修复计划 -> fixed-prompts.json")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--show", default="")
    a = ap.parse_args()

    if a.list:
        print("=== 可用的通用修正句（按缺陷类型）===")
        for k, f in FIXES.items():
            print(f"  {k:<18} 对应 {f['codes']}  —— {f['why']}")
        print(f"\n=== 逐图修复计划（{len(PLAN)} 张）===")
        for n, p in PLAN.items():
            print(f"  {n:<24} [{p['worst'].upper()}] 修正={p['fixes'] or '(只改场景)'}")
            print(f"      理由：{p['why']}")
        return 0

    if a.show:
        d = build()
        it = d.get(a.show)
        if not it:
            print(f"没有 {a.show}")
            return 2
        print(f"=== {a.show}  {it['codes']} ===")
        print(it["scene"])
        return 0

    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
