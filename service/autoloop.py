# -*- coding: utf-8 -*-
"""出图自检-修订回路：让视觉 LLM 判定出图质量，不合格就改 prompt 重跑，最多 N 轮。

设计要点（都对应一条实际踩过的坑）

1. **判定与修订都用固定的、结构化的输出**。LLM 返回 JSON，字段受白名单约束；
   超出范围的修订建议被丢弃而不是照做 —— 否则模型会自由发挥出奇怪的 prompt。
2. **修订是"基于上一版编辑"，不是重写**。每轮把上一版的 prompt 原文给模型，
   只允许它做有限几种编辑（改写场景段 / 换样式词 / 改参考图模式 / 换 seed），
   并在建议里给出 reason。这样出问题能归因。
3. **参考图模式与样式词档位是枚举**，不给自由发挥空间：
   `refs` 只能是 char / style / char+style 三种组合之一。
4. **可注入的检查器**。真实检查走 DeepSeek 视觉 API；测试走 `ScriptedVision`，
   这样"判定→修订→重跑→停止"的回路能在没有 key 的情况下完整验证。
5. **每一步都落盘**。每轮的图、判定 JSON、修订记录都写进一个 run 目录，
   事后能复现"为什么第 2 轮把样式词换了"。
6. **绝不在日志/响应里回显 API key**；key 只在服务端内存与已 gitignore 的 env 文件里。

DeepSeek 视觉接口（依据官方文档 zh-cn/guides/vision）：
  POST {base_url}/chat/completions      base_url 默认 https://api.deepseek.com
  model = "deepseek-flash"（旧名 deepseek-v4-flash-vision-exp 已下线）
  content 为块数组，图片用 {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}
  **图片只能出现在 user 消息里**，放 system/assistant 会 400。
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# --------------------------------------------------------------------------- #
# 枚举：LLM 只能在这些档位里选，不能自创
# --------------------------------------------------------------------------- #
REF_MODES = {
    "char+style": "角色参考图 + 画风参考图（双图）",
    "char": "只给角色参考图（身份准，画风靠文字）",
    "style": "只给画风参考图（画风强，角色会被带跑）",
    "none": "不给参考图（纯文字，画风全靠样式词）",
}
STYLE_TIERS = {
    "base": "基础样式词：偏描述性的画风说明",
    "boost": "强化样式词：写具体光学特征（暗底/轮廓光/光点/高对比高光）",
}
DECISIONS = {"pass": "合格，停止", "revise": "需要修订后重跑", "giveup": "已尽力，停在这里"}

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


# --------------------------------------------------------------------------- #
# 数据契约
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    """一次判定的结果。"""
    ok: bool
    score: float                      # 0–10，越高越好
    defects: List[Dict[str, Any]] = field(default_factory=list)
    worst: str = "none"
    note: str = ""
    raw: str = ""                     # 模型原始回复，便于事后核查


@dataclass
class Revision:
    """一次修订建议。字段受限，超出范围的值会被丢弃。"""
    decision: str = "pass"            # DECISIONS 的键
    new_scene: str = ""               # 场景段改写（只改这一段）
    style_tier: str = ""              # STYLE_TIERS 的键
    ref_mode: str = ""                # REF_MODES 的键
    seed: Optional[int] = None        # 换 seed
    reason: str = ""
    raw: str = ""

    def sanitized(self) -> "Revision":
        """把越界的值清空 —— 不让 LLM 的自由发挥污染 prompt。"""
        r = Revision(**{**self.__dict__})
        if r.decision not in DECISIONS:
            r.decision = "revise"
        if r.style_tier and r.style_tier not in STYLE_TIERS:
            r.style_tier = ""
        if r.ref_mode and r.ref_mode not in REF_MODES:
            r.ref_mode = ""
        if r.new_scene:
            r.new_scene = r.new_scene.strip()[:1200]
        if r.seed is not None and not (0 <= r.seed < 2 ** 31):
            r.seed = None
        return r


# --------------------------------------------------------------------------- #
# 视觉 API 客户端
# --------------------------------------------------------------------------- #
class VisionError(RuntimeError):
    pass


class DeepSeekVision:
    """DeepSeek 视觉模型的 OpenAI 兼容客户端。

    只依赖 requests；不引入 openai SDK（容器里未必装，且这一层很薄）。
    """

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL, detail: str = "high", timeout: int = 180):
        if not api_key:
            raise VisionError("没有配置 API key")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.detail = detail if detail in ("low", "high", "original", "auto") else "high"
        self.timeout = timeout

    # -- 底层调用 ---------------------------------------------------------- #
    def chat(self, prompt: str, image_paths: List[pathlib.Path],
             max_tokens: int = 2048, temperature: float = 0.2) -> str:
        import requests

        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for p in image_paths:
            b64 = base64.b64encode(pathlib.Path(p).read_bytes()).decode("ascii")
            mime = "image/png"
            if pathlib.Path(p).suffix.lower() in (".jpg", ".jpeg"):
                mime = "image/jpeg"
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": self.detail},
            })
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],   # 图片只能在 user 里
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        r = requests.post(f"{self.base_url}/chat/completions",
                          headers={"Authorization": f"Bearer {self.api_key}",
                                   "Content-Type": "application/json"},
                          json=body, timeout=self.timeout)
        if r.status_code != 200:
            # 不回显 key；只报状态码与响应体前若干字符
            raise VisionError(f"HTTP {r.status_code}: {r.text[:300]}")
        j = r.json()
        try:
            return j["choices"][0]["message"]["content"] or ""
        except Exception as exc:                                        # noqa: BLE001
            raise VisionError(f"响应结构异常：{str(j)[:300]}") from exc

    # -- 判定 -------------------------------------------------------------- #
    def judge(self, prompt: str, image_paths: List[pathlib.Path],
              character_bible: str = "", extra: str = "") -> Verdict:
        text = build_judge_prompt(prompt, character_bible, extra)
        raw = self.chat(text, image_paths)
        return parse_verdict(raw)

    # -- 修订 -------------------------------------------------------------- #
    def revise(self, prompt: str, verdict: Verdict, round_no: int,
               image_paths: Optional[List[pathlib.Path]] = None) -> Revision:
        text = build_revise_prompt(prompt, verdict, round_no)
        raw = self.chat(text, image_paths or [], max_tokens=1600)
        return parse_revision(raw)


# --------------------------------------------------------------------------- #
# 固定 prompt：判定
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = """你是出图质检员。你会看到一张出图，以及它被要求画什么、角色设定是什么。

按下面的检查表逐项核对，**先人体结构、再语义内容、最后渲染画质**：
A 人体结构：A1 手指数量与形态 / A2 手臂数量与连接 / A3 腿 / A4 脚与地面和鞋 /
  A5 头颈肩 / A6 五官 / A7 躯干与比例 / A8 与道具的接触
B 语义内容：B1 人数 / B2 角色身份 / B3 服装 / B4 鞋型 / B5 道具缺失 /
  B6 场景与时间 / B7 动作未照做 / B8 画风参考图内容泄露 / B9 角色参考图内容泄露
C 渲染画质：C1 过曝死白 / C2 欠曝死黑 / C3 糊或结构不可辨 / C4 复制粘贴感 / C5 文字水印边框

严重度：P0 人体结构崩坏或人数不符（整张作废）/ P1 结构明显可疑或关键内容错 /
P2 渲染缺陷或细节缺失 / P3 轻微瑕疵。

**只报你真的在图里看到证据的缺陷**，给出位置与所见。看不清就不要报，不要臆测 ——
误报会让整份报告失去可信度。不要因为画风好看就放过结构错误。

只输出 JSON，不要任何解释文字：
{"ok": false, "score": 4.5, "worst": "P0",
 "defects": [{"code": "A1", "severity": "P0", "where": "画面中部，双手提袋处",
              "what": "手指粘连成一团", "confident": "high"}],
 "note": "一句话总结"}
score 为 0–10 的整体可用度（10 = 可直接交付）。没有任何缺陷时 ok 为 true、worst 为 "none"。"""


def build_judge_prompt(prompt: str, character_bible: str = "", extra: str = "") -> str:
    parts = [JUDGE_SYSTEM, "", "## 这张图被要求画什么（原始 prompt）", "", "```",
             prompt.strip(), "```"]
    if character_bible:
        parts += ["", "## 角色设定（用来核对身份是否漂移）", "", character_bible.strip()]
    if extra:
        parts += ["", "## 额外说明", "", extra.strip()]
    parts += ["", "现在只输出 JSON。"]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 固定 prompt：修订（基于上一版编辑，不是重写）
# --------------------------------------------------------------------------- #
REVISE_SYSTEM = """你是 prompt 修订员。上一轮出图被判为不合格，你要在**上一版 prompt 的基础上做最小编辑**，
让下一轮出图更好。

**只允许改这几处**，其余原样保留（尤其不要把整段重写、不要删掉已有的约束）：
1. `new_scene`：改写「场景段」。这是 prompt 最后那段，包含角色圣经 + 场景描述。
   它必须**仍然包含完整的角色圣经**，你只改动作/镜头/环境那部分。
   针对缺陷的具体做法：手部缺陷就把手在做什么写清楚（每只手分别说明）；
   人数错就显式写 "Exactly one girl in the frame, alone"；
   过曝就点名背景要有 3–4 个具体环境元素、并去掉会让画面发白的高亮描述。
2. `style_tier`：换样式词档位，可选 base / boost。
   画面太亮、失去暗调与光点 → 换 boost（强化光学描述）。画风已经够了但内容被压 → 换 base。
3. `ref_mode`：换参考图组合，可选 char+style / char / style / none。
   角色身份漂移 → 保留 char。画风完全没进来 → 试 char+style 或 style。
   参考图内容泄露（出现参考图里的东西）→ 退到 char 或 none。
4. `seed`：换一个种子（整数）。同类缺陷反复出现时值得换。

如果判断再怎么改也救不回来，`decision` 用 "giveup"。已经合格就用 "pass"。

只输出 JSON，不要任何解释文字：
{"decision": "revise", "new_scene": "……完整的新场景段……",
 "style_tier": "boost", "ref_mode": "char+style", "seed": 1234,
 "reason": "为什么这样改，一句话"}"""


def build_revise_prompt(prompt: str, verdict: Verdict, round_no: int) -> str:
    defects = "\n".join(
        f"- [{d.get('code')}/{d.get('severity')}] {d.get('where', '')}：{d.get('what', '')}"
        for d in verdict.defects) or "（无）"
    return "\n".join([
        REVISE_SYSTEM, "",
        f"## 这是第 {round_no} 轮修订", "",
        "## 上一版 prompt（原文，请在此基础上编辑）", "", "```", prompt.strip(), "```", "",
        "## 上一轮出图的判定", "",
        f"- 是否合格：{verdict.ok}",
        f"- 可用度评分：{verdict.score}",
        f"- 最严重等级：{verdict.worst}",
        f"- 总结：{verdict.note}",
        "- 缺陷明细：", defects, "",
        "现在只输出 JSON。",
    ])


# --------------------------------------------------------------------------- #
# 解析（宽容但受控）
# --------------------------------------------------------------------------- #
def _first_json_object(text: str) -> Optional[dict]:
    """从回复里抠出第一个 JSON 对象（容忍 ```json 围栏与前后解释）。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    depth, start = 0, None
    for i, ch in enumerate(t):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(t[start:i + 1])
                    if isinstance(obj, dict):
                        return obj
                except Exception:                                       # noqa: BLE001
                    pass
                start = None
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:                                                   # noqa: BLE001
        return None


def parse_verdict(text: str) -> Verdict:
    obj = _first_json_object(text)
    if not obj:
        # 解析不出来时**不能当合格** —— 保守判定为"需要人工看"
        return Verdict(ok=False, score=0.0, worst="?",
                       note="判定结果无法解析，按不合格处理", raw=text)
    defects = obj.get("defects") or []
    if not isinstance(defects, list):
        defects = []
    clean = []
    for d in defects:
        if not isinstance(d, dict):
            continue
        code = str(d.get("code", "")).strip().upper()
        if not re.fullmatch(r"[ABC][1-9]", code):
            continue
        sev = str(d.get("severity", "")).strip().upper()
        if sev not in ("P0", "P1", "P2", "P3"):
            sev = "P3"
        clean.append({
            "code": code, "severity": sev,
            "where": str(d.get("where", ""))[:200],
            "what": str(d.get("what", ""))[:400],
            "confident": str(d.get("confident", ""))[:10],
        })
    try:
        score = float(obj.get("score", 0))
    except Exception:                                                   # noqa: BLE001
        score = 0.0
    score = max(0.0, min(10.0, score))
    worst = str(obj.get("worst", "") or "").upper()
    if worst not in ("P0", "P1", "P2", "P3", "NONE"):
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        worst = min((d["severity"] for d in clean), key=lambda s: order[s]) if clean else "none"
    return Verdict(ok=bool(obj.get("ok")) and not clean,
                   score=score, defects=clean, worst=worst.lower(),
                   note=str(obj.get("note", ""))[:400], raw=text)


def parse_revision(text: str) -> Revision:
    obj = _first_json_object(text)
    if not obj:
        return Revision(decision="giveup", reason="修订建议无法解析", raw=text)
    seed = obj.get("seed")
    try:
        seed = int(seed) if seed is not None and str(seed).strip() != "" else None
    except Exception:                                                   # noqa: BLE001
        seed = None
    return Revision(
        decision=str(obj.get("decision", "revise")).strip().lower(),
        new_scene=str(obj.get("new_scene", "") or ""),
        style_tier=str(obj.get("style_tier", "") or "").strip().lower(),
        ref_mode=str(obj.get("ref_mode", "") or "").strip().lower(),
        seed=seed,
        reason=str(obj.get("reason", ""))[:400],
        raw=text,
    ).sanitized()


# --------------------------------------------------------------------------- #
# 回路
# --------------------------------------------------------------------------- #
class StopLoop(RuntimeError):
    """用户请求停止 —— 不是失败，要干净收尾而不是记成 error。

    `run_loop` 捕获 `StopIteration` 来识别停止请求，所以注入的 `generate`
    应当抛 `StopIteration`（见服务端 `_auto_worker` 的写法：它把停止标志转成
    `StopIteration`）。这个异常类只是给调用方一个语义清楚的名字。
    """


@dataclass
class LoopSettings:
    max_rounds: int = 3               # 最多修订几轮（含首轮）
    pass_score: float = 7.0           # 判定分数 >= 这个就算过
    allow_p0_stop: bool = True        # 出现 P0 直接停（省得白跑）
    stop_on_giveup: bool = True


def run_loop(
    *,
    generate: Callable[[dict], Dict[str, Any]],
    judge: Callable[[Dict[str, Any]], Verdict],
    revise: Callable[[Dict[str, Any], Verdict, int], Revision],
    initial: Dict[str, Any],
    settings: LoopSettings,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """跑自检-修订回路。

    三个回调都从外面注入，所以：
      · 生产环境 = 真实出图 + DeepSeek 视觉判定 + DeepSeek 修订
      · 测试环境 = 假出图 + ScriptedVision，**不需要 key 就能验证整条回路**

    `generate(state) -> {"images": [path...], "meta": {...}}`
    `judge(result) -> Verdict`
    `revise(state, verdict, round_no) -> Revision`
    """
    state = dict(initial)
    history: List[Dict[str, Any]] = []

    def _run_generate(rnd: int) -> Optional[Dict[str, Any]]:
        """跑一次出图。返回 None 表示应当停止整条回路。"""
        log(f"[round {rnd}] 出图：refs={state.get('refs')} style={state.get('style_tier')} "
            f"seed={state.get('seed')}")
        try:
            return generate(state)
        except StopIteration:
            log(f"[round {rnd}] 收到停止请求 → 结束")
            return None
        except Exception as exc:                                        # noqa: BLE001
            log(f"[round {rnd}] 出图失败：{type(exc).__name__}: {exc}")
            history.append({"round": rnd, "stage": "generate", "error": str(exc)})
            return None

    for rnd in range(1, settings.max_rounds + 1):
        t0 = time.time()
        result = _run_generate(rnd)
        if result is None:
            break
        gen_s = round(time.time() - t0, 2)
        images = result.get("images") or []
        log(f"[round {rnd}] 出图完成 {gen_s}s，{len(images)} 张")

        v = judge({"state": state, "result": result, "round": rnd})
        log(f"[round {rnd}] 判定：ok={v.ok} score={v.score} worst={v.worst} "
            f"缺陷 {len(v.defects)} 条")
        for d in v.defects:
            log(f"          - [{d['code']}/{d['severity']}] {d['where']}：{d['what']}")

        entry = {
            "round": rnd, "state": {k: (str(x) if isinstance(x, pathlib.Path) else x)
                                    for k, x in state.items()},
            "images": [str(p) for p in images], "seconds": gen_s,
            "verdict": {"ok": v.ok, "score": v.score, "worst": v.worst,
                        "defects": v.defects, "note": v.note},
            "revision": None,
        }

        if v.ok or v.score >= settings.pass_score:
            log(f"[round {rnd}] 通过（score {v.score} >= {settings.pass_score}）→ 停止")
            history.append(entry)
            break
        if settings.allow_p0_stop and v.worst == "p0":
            log(f"[round {rnd}] 出现 P0（整张作废级）→ 直接进修订")

        if rnd >= settings.max_rounds:
            log(f"[round {rnd}] 已达最大轮数 {settings.max_rounds} → 停在最后一张")
            history.append(entry)
            break

        rev = revise(state, v, rnd)
        log(f"[round {rnd}] 修订：decision={rev.decision} "
            f"style={rev.style_tier or '(不变)'} refs={rev.ref_mode or '(不变)'} "
            f"seed={rev.seed if rev.seed is not None else '(不变)'}")
        log(f"          理由：{rev.reason}")
        entry["revision"] = {"decision": rev.decision, "style_tier": rev.style_tier,
                             "ref_mode": rev.ref_mode, "seed": rev.seed,
                             "new_scene": rev.new_scene, "reason": rev.reason}
        history.append(entry)

        if rev.decision == "giveup" and settings.stop_on_giveup:
            log(f"[round {rnd}] 模型认为改不动了 → 停止")
            break
        if rev.decision == "pass":
            log(f"[round {rnd}] 模型建议直接放行 → 停止")
            break

        # 应用修订（字段受限，已在 sanitized 里挡过越界值）
        if rev.new_scene:
            state["scene"] = rev.new_scene
        if rev.style_tier:
            state["style_tier"] = rev.style_tier
        if rev.ref_mode:
            state["refs"] = rev.ref_mode
        if rev.seed is not None:
            state["seed"] = rev.seed

    best = max(history, key=lambda h: (h.get("verdict") or {}).get("score", -1)
               ) if history else {}
    last = history[-1] if history else {}
    return {
        "rounds": len(history),
        "history": history,
        "passed": bool((last.get("verdict") or {}).get("ok")),
        "best_score": (best.get("verdict") or {}).get("score"),
        "best_round": best.get("round"),
        "final_state": {k: (str(x) if isinstance(x, pathlib.Path) else x)
                        for k, x in state.items()},
    }


# --------------------------------------------------------------------------- #
# 测试替身：没有 key 也能验证整条回路
# --------------------------------------------------------------------------- #
class ScriptedVision:
    """按预设脚本返回判定与修订，用于测试与离线演示。

    真实模型与它实现相同的两个方法，所以回路代码不需要知道用的是哪个。
    """

    def __init__(self, verdicts: List[Verdict], revisions: List[Revision]):
        self.verdicts = list(verdicts)
        self.revisions = list(revisions)
        self.calls = {"judge": 0, "revise": 0}

    def judge(self, prompt: str, image_paths, character_bible: str = "",
              extra: str = "") -> Verdict:                              # noqa: ANN001
        i = min(self.calls["judge"], len(self.verdicts) - 1)
        self.calls["judge"] += 1
        return self.verdicts[i]

    def revise(self, prompt: str, verdict: Verdict, round_no: int,
               image_paths=None) -> Revision:                           # noqa: ANN001
        i = min(self.calls["revise"], len(self.revisions) - 1)
        self.calls["revise"] += 1
        return self.revisions[i]


def config_from_env(getenv: Callable[[str], str]) -> Dict[str, Any]:
    """从环境变量读视觉 API 配置。key 不落盘、不回显。"""
    return {
        "base_url": getenv("QWEN_VISION_BASE_URL") or DEFAULT_BASE_URL,
        "model": getenv("QWEN_VISION_MODEL") or DEFAULT_MODEL,
        "detail": getenv("QWEN_VISION_DETAIL") or "high",
        "has_key": bool(getenv("QWEN_VISION_API_KEY")),
        "max_rounds": int(getenv("QWEN_AUTO_MAX_ROUNDS") or 3),
        "pass_score": float(getenv("QWEN_AUTO_PASS_SCORE") or 7.0),
    }
