# Qwen-Image-2.1：negative prompt / CFG 对照测试方案

> 给后续接手者（含 DeepSeek）的执行说明。目标不是证明“参数能传进去”——源码已经能证明；
> 目标是判断它们对本项目的人体异常率是否有稳定、值得付出约双倍耗时的收益。

## 1. 先分清“支持”与“推荐”

- 官方 README / Hugging Face 模型卡的默认参数只列 `num_inference_steps=40` 和原生 2K 尺寸；
  文生图、编辑示例都没有传 `negative_prompt` 或 CFG。
- Diffusers `QwenImage21Pipeline.__call__` **确实支持** `negative_prompt` 与
  `true_cfg_scale`。源码规定：只有同时存在 negative prompt 且 `true_cfg_scale > 1` 才启用 CFG。
- 同一管线 docstring 明确写着 Qwen-Image-2.1 按“无 guidance”方式采样，默认
  `true_cfg_scale=1.0`；Diffusers 合入记录也把“40 steps, no guidance”称为推荐采样默认值。
- 官方博客介绍能力与架构，没有提供 negative prompt、CFG 推荐值或负面词表。

所以 UI 保留这些参数，但归入默认折叠的“高级实验设置”。任何负面词表都只能标为项目自编，
不能写成官方推荐。

## 2. 核心实验：同 seed 配对，而不是各看一张

每个场景至少取 12 个 seed；预算允许时用 20 个。每个 seed 都跑下面四组，其他参数完全固定：

| 组 | negative prompt | `true_cfg_scale` | 用途 |
|---|---|---:|---|
| A | 空 | 1.0 | 官方默认基线 |
| B | 项目自编人体负面词 | 2.0 | 低强度 CFG |
| C | 同 B | 2.5 | 当前 UI 快捷值 |
| D | 空 | 1.0 | 正向 prompt 按官方 PE 方法拆解/改写后的对照 |

D 组很重要：如果“把任务拆开、降低姿态交缠、明确全身入镜”的收益高于 CFG，产品上应优先优化
prompt/工作流，而不是把耗时翻倍的 CFG 放到主界面。

至少覆盖三类任务：

1. 文生图：单人全身、四肢清楚；
2. 单参考图编辑：大幅换姿态；
3. 双人或多主体编辑：拥抱、背负等肢体交叠场景（最容易暴露多肢问题）。

固定分辨率、步数、参考图顺序、prompt、模型版本和代码 commit。不要在实验请求里启用
`anatomy_check` 自动重跑，否则最终图片可能已经换 seed，A/B 配对会失效。

## 3. 评分方法

把文件随机重命名或生成盲评清单，评分者看不到 A/B/C/D。每张记录：

- `anatomy_fail`：明确多/少/融合/断裂肢体，0 或 1（主指标）；
- `prompt_following`：1~5；
- `identity`（编辑任务）：1~5；
- `aesthetic`：1~5；
- `elapsed_s`、seed、尺寸、实际 CFG（从 PNG 元数据读取）。

当前 2.2B 人体复检器只能做辅助标签，**不能当真值**：现有实测中它能数出“双头”，却仍可能给
PASS。最终结论必须以盲评为主；如果用另一个 VLM 评分，也要抽查并报告人与模型的一致率。

每组报告“异常张数 / 总张数”、各 1~5 分指标的中位数，以及耗时中位数。样本只有 12 对时不要
声称统计显著；只把结果当去留决策的工程证据。

## 4. 判定门槛

建议只有同时满足以下条件，才考虑把 CFG 方案提升出高级设置：

- B 或 C 在三类任务中至少两类的人体异常率，相对 A 稳定下降 ≥30%；
- prompt 跟随、身份和审美中位数没有下降超过 0.5 分；
- 用户能接受实测耗时增幅；
- 换一批 seed 复测后方向仍一致。

否则保留 API 能力和折叠控件即可，默认继续 `CFG=1 + negative prompt 为空`。

## 5. 执行建议

现有 `remote/scripts/_negprompt_ab.py` 可作为起点，但要做两处调整后再下结论：

1. `SEEDS` 扩到至少 12 个，并把 A/B/C/D 全部跑齐；
2. 脚本只负责生成图片和盲评 manifest，不要用 `anatomy_check` 的 PASS/FAIL 直接宣布胜负。

生成结束后保留一个 CSV/JSONL：`blind_id, variant, seed, task, elapsed_s, path`。另建评分文件只含
`blind_id` 与评分，最后再 join 回 variant，避免评分者被“CFG=2.5”暗示。

## 6. 官方依据

- Qwen 官方 README / HF 模型卡：`docs/upstream/qwen-image-2.1-github-README.md`
- Diffusers 管线参数与启用条件：`docs/upstream/diffusers-pipeline_qwenimage21.py:505`
- `negative_prompt` / `true_cfg_scale` 说明：同文件 `:540`
- CFG 实际分支：同文件 `:668`
- 官方 PE 的 prompt 写法：`docs/upstream/prompt-rewriter-I2I-system-prompt.txt`
