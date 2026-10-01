# -*- coding: utf-8 -*-
"""galgame CG 双图配方实测驱动。

  python exp/galgame-cg-20260928/run.py --phase bracket     # 分辨率选型（3 张）
  python exp/galgame-cg-20260928/run.py --phase story       # 正片故事集
  python exp/galgame-cg-20260928/run.py --phase seeds       # 同场景多 seed 稳定性
  python exp/galgame-cg-20260928/run.py --phase control     # 只传角色图对照

设计要点：

- **不做任何本地后处理**：出图原样落盘，尺寸/seed/耗时全部记录进 manifest.jsonl。
- **不硬编码密钥**：从 tools/.qwenkey 读，只放进请求头，不落盘不打印。
- **上传一次即缓存**：参考图按 md5 判断是否已在实例上，避免重复 SFTP。
- **超时先查任务状态再决定重发**（沿用本项目的既有约定）。

两个踩过的协议坑（写在这里免得再犯）：

1. **带参考图必须走 multipart**（`files=`）。用 `data=` 发的是
   x-www-form-urlencoded，服务端在 `_parse_gen_request` 里会去 `request.json()`
   解析并直接 500 (JSONDecodeError)。
2. **响应是 JSON + base64**，不是图片字节。图在 `data[0].b64_json`，
   元数据在 `data[0].metadata`（含 inputs 的 sha256 与尺寸、实际 seed、实际 size）。
3. **尺寸会被吸附到 64 的倍数**（1008→992、1104→1088、2752×1536→2560×1440）。
   所以宽高要按 64 的倍数给，并读响应里的实际 `size` 为准。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import sys
import threading
import time

import paramiko
import requests

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXP = ROOT / "exp" / "galgame-cg-20260928"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import autodl_ssh  # noqa: E402

REMOTE_REF_DIR = "/root/galgame-refs"
LOCAL_PORT = 16066


def cfg() -> dict:
    out = {}
    for raw in (TOOLS / "autodl_new.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def api_key() -> str:
    for line in (TOOLS / ".qwenkey").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.strip().startswith("#"):
            return line.strip()
    raise SystemExit("tools/.qwenkey 里没有 key")


def md5(p: pathlib.Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# prompt 组装：严格按 docs/RECIPE-character-plus-style.md 第 3.2 节的四段结构
# --------------------------------------------------------------------------- #
CHARACTER = (
    "The character is a young woman with shoulder-length wavy indigo-blue hair, a small "
    "side bun tied at one side of her head, a small white flower hairpin above one ear, "
    "large blue-violet eyes, and soft rounded facial features. She wears a white "
    "puff-sleeve blouse under a blue denim pinafore dress with two gold buttons at the "
    "waist, the pleated skirt fading from sky blue at the waist to pale mint at the hem "
    "with a white ruffled underlayer, and blue bow-embellished Mary Jane heels."
)

STYLE_SHORT = (
    "Luminous anime illustration with a polished galgame CG finish: crisp clean linework, "
    "rich saturated colour with soft pastel gradients, glowing particle sparkles, wide soft "
    "bloom on highlights, dramatic rim light separating the subject from a deep contrasty "
    "background, delicate fabric and hair highlights."
)

# 强化版样式词：第一轮双图出来的画面偏"干净动画插画"，参考图那种发光/深底压边/
# 舞台感的质感没被接住。这里把参考图的可借技法写得更具体、更"光学"，
# 并点名"深色背景 + 亮主体"的对比结构 —— 这是参考图最显著的特征。
STYLE_SHORT_BOOST = (
    "Premium galgame event CG rendering, dark-background portraiture: the subject is lit "
    "against a deep, saturated, dark background, separated by a bright glowing rim light. "
    "Strong bloom and soft lens glow on every highlight, dense floating glitter particles "
    "and tiny bokeh stars scattered across the frame, gentle chromatic warmth in the light. "
    "Crisp thin dark linework over luminous cel-shading with airbrushed gradient soft "
    "shading, high-contrast specular highlights on hair strands and fabric folds, "
    "iridescent pastel gradients in the shadows. Polished digital painting finish."
)

BAN = (
    "Do NOT copy from <image2>: its character, its pale blonde hair, its green eyes, its "
    "white dress, its stockings or garters, its violin strings, bow or other instruments, "
    "its constellation lines, floating stars, gems or sparkle props, its starfield stage "
    "floor, its reclining pose, its diagonal poster composition or its frame."
)

LEDGER = (
    "Render this in the art style of the provided style reference, applying its technique "
    "only. <image1> defines the character's identity - hair colour, hairstyle, eye colour, "
    "facial features and outfit must be preserved exactly. <image2> is a STYLE SAMPLE ONLY: "
    "borrow its linework, colouring method, light rendering and texture."
)

# 强化版分工句：把"技法"进一步钉死在光学与质感上，并明确排除参考图的内容属性
LEDGER_BOOST = (
    "Apply the RENDERING TECHNIQUE of the provided style reference image. <image1> defines "
    "the character's identity - hair colour, hairstyle, eye colour, facial features and "
    "outfit must be preserved exactly and must NOT be altered toward the reference. <image2> "
    "is a STYLE SAMPLE ONLY and contributes technique exclusively: its lighting model, its "
    "glow and bloom, its particle density, its shading gradient, its contrast structure and "
    "its line quality. Nothing else from <image2> may appear."
)


# 修补：正片里三张有明确缺陷，重写 prompt 后重出。
#   06 出现两个同角色（硬伤）→ 加"画面中只有一个人"
#   01/04 背景大片纯白留白 → 补足环境描述
SCENES_FIX = [
    ("06-sunset-bridge", "Exactly one girl in the frame, alone. She leans on the railing of a "
     "pedestrian bridge, seen from a three-quarter angle as she turns her head to look back "
     "toward the viewer, both hands resting on the rail. Behind and below her: a wide river "
     "reflecting orange and violet clouds, a distant silhouetted skyline, gulls. Deep sunset "
     "sky filling the upper third. Wide cinematic composition, medium shot, single subject."),
    ("01-boutique", "She stands before a tall gilt-framed mirror in a boutique, turning to "
     "check her reflection, one hand at the skirt hem, a pleased little smile. Around her: "
     "wooden clothes racks hung with pastel garments, a velvet stool, a vase of dried flowers, "
     "a warm pendant lamp overhead, polished wooden floor. Bright daylight from a tall window "
     "on the left. Wide cinematic composition, full body, rich interior detail."),
    ("04-icecream", "She holds a soft-serve cone in both hands and leans in to take a bite, "
     "eyes bright, a paper napkin tucked between her fingers. She stands on a seaside "
     "promenade: white railings, moored boats, a blue-green sea with small waves, terracotta "
     "planters, a distant lighthouse, bright midday sun and clean shadows. Wide cinematic "
     "composition, full body, vivid outdoor scene."),
]


def build_prompt(scene: str, boost: bool = False) -> str:
    if boost:
        return "\n\n".join([LEDGER_BOOST, STYLE_SHORT_BOOST, BAN, CHARACTER + " " + scene])
    return "\n\n".join([LEDGER, STYLE_SHORT, BAN, CHARACTER + " " + scene])


SCENES = [
    ("01-boutique", "She stands in front of a tall gilt-framed mirror in a bright boutique "
     "changing room, turning slightly to check her reflection, one hand touching the skirt hem, "
     "quietly pleased. Warm daylight from a large window, racks of clothes blurred behind her. "
     "Wide cinematic composition, subject placed slightly off-centre, full body."),
    ("02-cafe", "She sits at a small round cafe table by a window, both hands wrapped around a "
     "glass cup of iced tea, a slice of strawberry shortcake on a white plate beside it, "
     "smiling at someone across the table. Warm afternoon light, potted plants and blurred "
     "street traffic outside. Wide cinematic composition, upper body, shallow depth of field."),
    ("03-street", "She walks toward the viewer along a quiet city street carrying a small paper "
     "shopping bag, hair and skirt lifted by a light breeze, glancing back over her shoulder "
     "with a bright smile. Late afternoon, long warm shadows, blurred shop fronts behind her. "
     "Wide cinematic composition, full body, subject off-centre."),
    ("04-icecream", "She holds a soft-serve ice cream cone in both hands and leans forward "
     "slightly to take a bite, eyes bright with anticipation, a paper napkin tucked in her "
     "fingers. A riverside promenade with railings and far boats behind her, clear blue sky. "
     "Wide cinematic composition, upper body, warm rim light."),
    ("05-park", "She sits sideways on a wooden park bench with her legs crossed at the ankle, "
     "looking up at falling leaves, one hand raised to catch them, gentle wonder on her face. "
     "Autumn park, golden leaves drifting, low sun raking through the trees behind her. "
     "Wide cinematic composition, full body, subject placed to one side."),
    ("06-sunset-bridge", "She leans on the railing of a pedestrian bridge and looks out over "
     "the water, hands clasped on the rail, a faint smile as she listens to the person beside "
     "her. Deep orange and violet sunset, silhouetted far skyline, gentle lens glow. "
     "Wide cinematic composition, medium shot from behind at three-quarter angle."),
    ("07-ferris-wheel", "She sits inside a ferris wheel gondola looking out through the glass "
     "at the city lights spread below, one hand pressed to the window, city glow reflected in "
     "her eyes. Twilight blue hour, bokeh of distant streetlights, warm interior light on her "
     "face. Wide cinematic composition, medium close-up, shallow depth of field."),
    ("08-closeup", "Close-up of her face as she turns to look directly at the viewer with a "
     "soft warm smile, loose strands of hair across her cheek, the small white flower hairpin "
     "catching the light. Blurred festive street background with warm bokeh lights. "
     "Wide cinematic composition, close-up, very shallow depth of field."),
    ("09-holding-hands", "She walks beside the viewer and reaches out to take their hand, "
     "fingers extended toward the camera, laughing, the blue dress swaying with her stride. "
     "Quiet night street, warm shop window light and soft streetlamp glow. Wide cinematic "
     "composition, medium shot, subject on one side with leading lines."),
    ("10-fireworks", "She stands with both hands clasped at her chest watching fireworks burst "
     "across the night sky, face lit by the coloured flashes, eyes wide with delight. Crowd "
     "blurred behind her, night sky full of expanding firework blooms. Wide cinematic "
     "composition, upper body, subject off-centre, dramatic rim light."),
    ("11-rooftop", "She leans on a low railing of a building rooftop looking out over the "
     "evening city, a white knit cardigan now worn open over her blouse, the breeze lifting her "
     "hair. Blue hour sky, thousands of small city lights below, calm and content. Wide "
     "cinematic composition, full body, wide establishing view."),
    ("12-goodnight", "She stands under a streetlamp near the station entrance saying goodbye, "
     "both hands holding her small shopping bag in front of her, warm shy smile, one foot "
     "turned slightly inward. Night, quiet street, moths and soft glow around the lamp, "
     "blurred station lights behind. Wide cinematic composition, full body, centred."),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True,
                    choices=["bracket", "story", "seeds", "control", "boost",
                             "styleonly", "padded", "fix"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--width", type=int, default=2048)
    ap.add_argument("--height", type=int, default=1152)
    args = ap.parse_args()

    c = cfg()
    key = api_key()
    EXP.joinpath("out").mkdir(parents=True, exist_ok=True)
    manifest = EXP / "manifest.jsonl"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(c["AUTODL_HOST"], port=int(c["AUTODL_PORT"]), username=c["AUTODL_USER"],
                   password=c["AUTODL_PASS"], timeout=25, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()

    def sh(cmd, t=180):
        _, o, e = client.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")

    # ── 上传参考图（按 md5 跳过已存在的） ──────────────────────────────────
    sh(f"mkdir -p {REMOTE_REF_DIR}")
    remote_refs = {}
    for name in ("char", "style"):
        lp = EXP / "refs" / f"{name}.png"
        rp = f"{REMOTE_REF_DIR}/{name}.png"
        local_md5 = md5(lp)
        existing = sh(f"md5sum {rp} 2>/dev/null").split()
        if existing and existing[0] == local_md5:
            print(f"[ref] {name}.png 已在实例上（md5 相同）")
        else:
            sftp.put(str(lp), rp)
            got = sh(f"md5sum {rp} 2>/dev/null").split()
            ok = got and got[0] == local_md5
            print(f"[ref] {name}.png 上传 {'OK' if ok else '校验失败!'} md5={local_md5[:12]}")
        remote_refs[name] = rp
    sftp.close()

    # ── 隧道 ───────────────────────────────────────────────────────────────
    fwd = autodl_ssh.ForwardServer(("127.0.0.1", LOCAL_PORT), autodl_ssh.Handler)
    fwd.dst_host, fwd.dst_port = "127.0.0.1", 6006
    fwd.transport = client.get_transport()
    threading.Thread(target=fwd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{LOCAL_PORT}"
    hdr = {"Authorization": "Bearer " + key}

    # ── 任务表 ─────────────────────────────────────────────────────────────
    jobs: list[dict] = []
    if args.phase == "bracket":
        # 全部取 64 的倍数（否则服务端会吸附），宽屏候选，同一场景同一 seed 只变尺寸。
        # 1600x896 = 1.43MP 是上一轮实测被"编辑红线 1.92MP"放过的最大值附近；
        # 1792x1024 = 1.84MP 补上 1.43~1.92 之间的空白，看宽屏能否比竖版吃得更多。
        for w, h in ((1536, 864), (1600, 896), (1600, 1024), (1600, 1152), (1792, 1024)):
            jobs.append({"name": f"bracket-{w}x{h}", "scene": SCENES[1][1],
                         "scene_id": SCENES[1][0], "width": w, "height": h,
                         "seed": args.seed, "refs": ["char", "style"]})
    elif args.phase == "story":
        for sid, scene in SCENES:
            jobs.append({"name": f"story-{sid}", "scene": scene, "scene_id": sid,
                         "width": args.width, "height": args.height, "seed": args.seed,
                         "refs": ["char", "style"]})
    elif args.phase == "seeds":
        for sd in (42, 1234, 20260927):
            jobs.append({"name": f"seed-{sd}", "scene": SCENES[5][1], "scene_id": SCENES[5][0],
                         "width": args.width, "height": args.height, "seed": sd,
                         "refs": ["char", "style"], "boost": True})
    elif args.phase == "boost":
        # 强化样式词 + 强化分工句，同样三个场景，与 story/control 同 seed 可直接并排
        for sid, scene in (SCENES[1], SCENES[2], SCENES[7]):
            jobs.append({"name": f"boost-{sid}", "scene": scene, "scene_id": sid,
                         "width": args.width, "height": args.height, "seed": args.seed,
                         "refs": ["char", "style"], "boost": True})
    elif args.phase == "styleonly":
        # 只发画风图、不发角色图：量出这张参考图**单独**能贡献什么。
        # 与 control 并排，就能把"参考图的贡献"和"角色图的作用"分开。
        for sid, scene in (SCENES[1], SCENES[2], SCENES[7]):
            jobs.append({"name": f"styleonly-{sid}", "scene": scene, "scene_id": sid,
                         "width": args.width, "height": args.height, "seed": args.seed,
                         "refs": ["style"]})
    elif args.phase == "padded":
        # 参考图是 832x1216 竖版，输出是 1600x896 横版 —— 比例差得很远，
        # 怀疑参考图在预处理里被缩到很小、影响被稀释。
        # 这里把参考图**首尾补边**到 16:9（画面居中、两侧补纯黑），比例对齐后再发。
        for sid, scene in (SCENES[2], SCENES[7]):
            jobs.append({"name": f"padded-{sid}", "scene": scene, "scene_id": sid,
                         "width": args.width, "height": args.height, "seed": args.seed,
                         "refs": ["char", "style16x9"]})
    elif args.phase == "fix":
        # 正片三处缺陷的修补，统一用强化样式词（与 boost 组一致的观感）
        for sid, scene in SCENES_FIX:
            jobs.append({"name": f"fix-{sid}", "scene": scene, "scene_id": sid,
                         "width": args.width, "height": args.height, "seed": args.seed,
                         "refs": ["char", "style"], "boost": True})
        # 顺便把 02-cafe 也出一张强化版，和 control/story/boost 组成完整四联对照
        jobs.append({"name": "boost-02-cafe", "scene": SCENES[1][1], "scene_id": SCENES[1][0],
                     "width": args.width, "height": args.height, "seed": args.seed,
                     "refs": ["char", "style"], "boost": True})
    else:  # control：只传角色图，不加画风图
        for sid, scene in (SCENES[1], SCENES[2], SCENES[7]):
            jobs.append({"name": f"control-{sid}", "scene": scene, "scene_id": sid,
                         "width": args.width, "height": args.height, "seed": args.seed,
                         "refs": ["char"]})

    print(f"\n[{args.phase}] {len(jobs)} 个任务，steps={args.steps}\n")
    records = []
    for i, job in enumerate(jobs, 1):
        prompt = build_prompt(job["scene"], job.get("boost", False))
        data = {"prompt": prompt, "width": str(job["width"]), "height": str(job["height"]),
                "num_inference_steps": str(args.steps), "true_cfg_scale": "1.0",
                "seed": str(job["seed"])}
        # 参考图字节：直接发本地原图（与实例上那份 md5 已校验一致），
        # 避免为了发 multipart 再把文件从实例读回来。
        files = [("image", (f"{r}.png", open(EXP / "refs" / f"{r}.png", "rb"), "image/png"))
                 for r in job["refs"]]
        t0 = time.time()
        try:
            r = requests.post(base + "/v1/images/generations", headers=hdr,
                              data=data, files=files, timeout=3600)
            dt = time.time() - t0
            if r.status_code == 200 and r.headers.get("content-type", "").startswith(
                    "application/json"):
                j = r.json()
                item = (j.get("data") or j.get("images") or [{}])[0]
                b64 = item.get("b64_json") or item.get("b64") or item.get("image")
                if not b64:
                    raise RuntimeError("响应里没有 b64_json：%s" % sorted(item))
                raw = base64.b64decode(b64)
                out = EXP / "out" / f"{job['name']}.png"
                out.write_bytes(raw)
                meta = item.get("metadata") or {}
                rec = {"name": job["name"], "scene_id": job["scene_id"],
                       "phase": args.phase, "boost": job.get("boost", False),
                       "req_size": f"{job['width']}x{job['height']}",
                       "size": j.get("size") or f"{item.get('width')}x{item.get('height')}",
                       "seed": item.get("seed", job["seed"]), "steps": args.steps,
                       "refs": job["refs"], "prompt": prompt, "status": "ok",
                       "bytes": len(raw), "seconds": round(dt, 2),
                       "elapsed_s": item.get("elapsed_s"),
                       "per_step_s": (item.get("timing") or {}).get("per_step_s"),
                       "request_id": (item.get("timing") or {}).get("request_id"),
                       "saved_path": item.get("saved_path"),
                       "inputs": meta.get("inputs"), "mode": item.get("mode"),
                       "png_sha256": meta.get("png_sha256")}
                note = "" if rec["size"] == rec["req_size"] else f"  (被吸附到 {rec['size']})"
                print(f"  [{i}/{len(jobs)}] {job['name']:<18} OK   {dt:6.2f}s  "
                      f"{len(raw)/1024:8.0f} KB  {rec['size']}{note}")
            else:
                body = r.content[:300].decode("utf-8", "replace")
                rec = {**{k: job[k] for k in ("name", "scene_id", "seed", "refs")},
                       "status": "fail", "http": r.status_code, "body": body,
                       "seconds": round(dt, 2)}
                print(f"  [{i}/{len(jobs)}] {job['name']:<18} FAIL {r.status_code} {body[:140]}")
        except Exception as exc:                                        # noqa: BLE001
            rec = {**{k: job[k] for k in ("name", "scene_id", "seed", "refs")},
                   "status": "error", "error": f"{type(exc).__name__}: {exc}",
                   "seconds": round(time.time() - t0, 2)}
            print(f"  [{i}/{len(jobs)}] {job['name']:<18} ERR  {type(exc).__name__}: {exc}")
        records.append(rec)
        with manifest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    ok = sum(1 for r in records if r["status"] == "ok")
    print(f"\n完成 {ok}/{len(records)} 成功")
    if ok:
        times = [r["seconds"] for r in records if r["status"] == "ok"]
        print(f"耗时 {min(times):.1f}-{max(times):.1f}s，平均 {sum(times)/len(times):.1f}s")
    print("GPU:", sh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader").strip())
    fwd.shutdown()
    try:
        client.close()
    except Exception:                                                   # noqa: BLE001
        pass
    return 0 if ok == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
