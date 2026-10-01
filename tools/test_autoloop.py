# -*- coding: utf-8 -*-
"""自检-修订回路的测试：**不需要 API key**就能验证整条链路。

  python tools/test_autoloop.py

覆盖：
  1. 判定 JSON 的解析（正常 / 带 ```json 围栏 / 前后有解释 / 残缺 / 越界代码）
  2. 修订 JSON 的解析与**越界值清洗**（LLM 自创 style_tier / ref_mode 必须被丢弃）
  3. 回路的四种走法：首轮通过 / 修订后通过 / 跑满 N 轮 / 模型放弃
  4. 修订是否真的应用到下一轮（scene / style_tier / refs / seed）
  5. 出图抛异常时不能崩，要记录并停
  6. 解析不出来时**不能当合格**（保守判定）
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "service"))
import autoloop as A  # noqa: E402

fails: list[str] = []
checks = 0


def check(cond: bool, label: str, extra: str = "") -> None:
    global checks
    checks += 1
    print(("  OK   " if cond else "  FAIL ") + label + (("  " + extra) if extra else ""))
    if not cond:
        fails.append(label)


# --------------------------------------------------------------------------- #
print("=== 1. 判定解析 ===")
v = A.parse_verdict('{"ok": false, "score": 4.5, "worst": "P0", "defects": ['
                    '{"code": "A1", "severity": "P0", "where": "中部", "what": "手指粘连",'
                    ' "confident": "high"}], "note": "手崩了"}')
check(not v.ok and v.score == 4.5 and v.worst == "p0", "正常 JSON")
check(len(v.defects) == 1 and v.defects[0]["code"] == "A1", "缺陷被保留")

v2 = A.parse_verdict('这是分析：\n```json\n{"ok": true, "score": 9, "defects": [],'
                     ' "worst": "none", "note": "好"}\n```\n以上。')
check(v2.ok and v2.score == 9.0, "容忍 markdown 围栏与前后解释")

v3 = A.parse_verdict('我看看这张图……好像没什么问题')
check(not v3.ok and v3.worst == "?", "解析不出来时保守判为不合格（不能当通过）")

v4 = A.parse_verdict('{"ok": true, "score": 99, "defects": ['
                     '{"code": "Z9", "severity": "PX", "what": "瞎报"}], "worst": "P9"}')
check(v4.score == 10.0, "score 越界被夹到 0–10")
check(len(v4.defects) == 0, "非法缺陷代码 Z9 被丢弃")

v5 = A.parse_verdict('{"ok": true, "score": 8, "defects": ['
                     '{"code": "a1", "severity": "p1", "what": "小写代码"}]}')
check(len(v5.defects) == 1 and v5.defects[0]["code"] == "A1"
      and v5.defects[0]["severity"] == "P1", "小写代码/等级被规范化")

v6 = A.parse_verdict('{"ok": true, "score": 8, "defects": [{"code": "A1", "severity": "P1"}]}')
check(not v6.ok, "ok=true 但有缺陷 → 强制判为不合格（不信模型自相矛盾的说法）")

# --------------------------------------------------------------------------- #
print("\n=== 2. 修订解析与越界清洗 ===")
r = A.parse_revision('{"decision": "revise", "new_scene": "新的场景段", '
                     '"style_tier": "boost", "ref_mode": "char", "seed": 1234,'
                     ' "reason": "换暗调"}')
check(r.decision == "revise" and r.style_tier == "boost" and r.ref_mode == "char"
      and r.seed == 1234, "正常修订")

r2 = A.parse_revision('{"decision": "revise", "style_tier": "ultra-mega",'
                      ' "ref_mode": "triple-image", "seed": "abc"}')
check(r2.style_tier == "" and r2.ref_mode == "", "LLM 自创的档位被丢弃（不让自由发挥污染 prompt）")
check(r2.seed is None, "非法 seed 被丢弃")

r3 = A.parse_revision('{"decision": "banana"}')
check(r3.decision == "revise", "非法 decision 归为 revise")

r4 = A.parse_revision('随便写点什么')
check(r4.decision == "giveup", "修订解析不出来 → giveup（宁可停，不要瞎改）")

r5 = A.parse_revision('{"decision": "revise", "seed": -5}')
check(r5.seed is None, "负数 seed 被丢弃")

# --------------------------------------------------------------------------- #
print("\n=== 3. 回路：首轮通过 ===")
def gen_ok(state):
    return {"images": [pathlib.Path("/tmp/a.png")], "meta": {}}


sv = A.ScriptedVision([A.Verdict(True, 9.0, [], "none", "很好")], [])
res = A.run_loop(generate=gen_ok,
                 judge=lambda d: sv.judge("", []),
                 revise=lambda s, v, n: sv.revise("", v, n),
                 initial={"scene": "s", "refs": "char+style", "style_tier": "base", "seed": 1},
                 settings=A.LoopSettings(max_rounds=3), log=lambda *_: None)
check(res["rounds"] == 1 and res["passed"], "第 1 轮就通过 → 只跑 1 轮")
check(sv.calls["revise"] == 0, "通过时不该调用修订")

# --------------------------------------------------------------------------- #
print("\n=== 4. 回路：修订后通过，且修订真的被应用 ===")
states: list[dict] = []


def gen_capture(state):
    states.append(dict(state))
    return {"images": [pathlib.Path("/tmp/b.png")], "meta": {}}


sv2 = A.ScriptedVision(
    [A.Verdict(False, 3.0, [{"code": "C1", "severity": "P2", "where": "左侧",
                             "what": "死白", "confident": "high"}], "p2", "过曝"),
     A.Verdict(True, 8.5, [], "none", "好了")],
    [A.Revision(decision="revise", new_scene="新的场景：Exactly one girl in the frame.",
                style_tier="boost", ref_mode="char", seed=777, reason="改暗调")])
res2 = A.run_loop(generate=gen_capture,
                  judge=lambda d: sv2.judge("", []),
                  revise=lambda s, v, n: sv2.revise("", v, n),
                  initial={"scene": "旧场景", "refs": "char+style",
                           "style_tier": "base", "seed": 1},
                  settings=A.LoopSettings(max_rounds=3), log=lambda *_: None)
check(res2["rounds"] == 2 and res2["passed"], "第 1 轮不合格 → 修订 → 第 2 轮通过")
check(states[0]["scene"] == "旧场景" and states[1]["scene"].startswith("新的场景"),
      "scene 被替换")
check(states[1]["style_tier"] == "boost", "style_tier 被替换")
check(states[1]["refs"] == "char", "refs 被替换")
check(states[1]["seed"] == 777, "seed 被替换")
check(len(res2["history"]) == 2 and res2["history"][0]["revision"]["reason"] == "改暗调",
      "修订记录留在 history 里（可归因）")

# --------------------------------------------------------------------------- #
print("\n=== 5. 回路：一直不合格 → 跑满 N 轮停下 ===")
sv3 = A.ScriptedVision([A.Verdict(False, 3.0, [{"code": "A1", "severity": "P0",
                                                "where": "中", "what": "手崩",
                                                "confident": "high"}], "p0", "差")],
                       [A.Revision(decision="revise", style_tier="boost", reason="再试")])
res3 = A.run_loop(generate=gen_ok,
                  judge=lambda d: sv3.judge("", []),
                  revise=lambda s, v, n: sv3.revise("", v, n),
                  initial={"scene": "s", "refs": "char+style", "style_tier": "base", "seed": 1},
                  settings=A.LoopSettings(max_rounds=2), log=lambda *_: None)
check(res3["rounds"] == 2 and not res3["passed"], "max_rounds=2 → 正好跑 2 轮后停")
check(sv3.calls["revise"] == 1, "最后一轮不再请求修订（省一次调用）")
check(res3["best_score"] == 3.0 and res3["best_round"] == 1, "记录最佳轮次")

# --------------------------------------------------------------------------- #
print("\n=== 6. 回路：模型主动放弃 ===")
sv4 = A.ScriptedVision([A.Verdict(False, 2.0, [{"code": "B1", "severity": "P0",
                                                "where": "全图", "what": "两个人",
                                                "confident": "high"}], "p0", "人数错")],
                       [A.Revision(decision="giveup", reason="参考图主体太强，改不动")])
res4 = A.run_loop(generate=gen_ok,
                  judge=lambda d: sv4.judge("", []),
                  revise=lambda s, v, n: sv4.revise("", v, n),
                  initial={"scene": "s", "refs": "char+style", "style_tier": "base", "seed": 1},
                  settings=A.LoopSettings(max_rounds=3), log=lambda *_: None)
check(res4["rounds"] == 1, "模型说 giveup → 立即停，不白跑后面两轮")

# --------------------------------------------------------------------------- #
print("\n=== 7. 回路：出图抛异常 ===")
def gen_boom(state):
    raise RuntimeError("OOM")


res5 = A.run_loop(generate=gen_boom,
                  judge=lambda d: A.Verdict(True, 9, [], "none", ""),
                  revise=lambda s, v, n: A.Revision(),
                  initial={"scene": "s", "refs": "char+style", "style_tier": "base", "seed": 1},
                  settings=A.LoopSettings(max_rounds=3), log=lambda *_: None)
check(res5["rounds"] == 1 and not res5["passed"], "出图异常 → 记录后停，不崩")
check(res5["history"][0].get("error") == "OOM", "异常被记进 history")

# --------------------------------------------------------------------------- #
print("\n=== 8. 配置读取不回显 key ===")
env = {"QWEN_VISION_API_KEY": "sk-secret-value", "QWEN_VISION_MODEL": "deepseek-flash"}
cfg = A.config_from_env(env.get)
check(cfg["has_key"] is True, "has_key=True")
check("sk-secret-value" not in str(cfg), "配置字典里不含 key 本身")

print()
print(f"断言 {checks} 项，失败 {len(fails)} 项")
for f in fails:
    print("   -", f)
print("结论:", "全部通过" if not fails else "有失败")
sys.exit(0 if not fails else 1)
