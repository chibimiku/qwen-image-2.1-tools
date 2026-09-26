# 官方文档本地副本

同步时间：2026-09-26 19:16:36

这些是**上游原文**。判断模型行为时以它们为准；本项目的实测结论见 `../MEASUREMENTS.md`，两者冲突时先看这里再复测。

## 联网抓取的上游文档

| 文件 | 用途 |
|---|---|
| `qwen-image-2.1-github-README.md` | GitHub README（官方仓库，内容最全） |
| `qwen-image-2.1-hf-modelcard.md` | HuggingFace 模型卡 |
| `qwen-image-2.1-modelscope-README.md` | ModelScope README（国内镜像同一份） |
| `qwen-image-2.1-LICENSE.txt` | Qwen Research License（商用限制的原始依据） |
| `qwen-image-2.1-blog.html` | qwen.ai 官方博客（HTML 原文，便于离线查看）；**正文抓不到**（SPA，HTML 里没有内容），需联网看 |

## 从实例导出的权威实现（离线可读，判断参数行为看这个）

| 文件 | 用途 |
|---|---|
| `diffusers-pipeline_qwenimage21.py` ✓ | diffusers 管线实现 —— 尺寸推导、参数默认值、KV cache 的唯一真相 |
| `diffusers-transformer_qwenimage21.py` ✓ | DiT 实现（32 层 single-stream，block-causal attention） |
| `diffusers-autoencoder_kl_qwenimage21.py` ✓ | 64 通道 RGBA VAE 实现（分块解码、上采样层的显存尖峰来源） |

导出命令（在实例上跑）：

```bash
bash /root/qwen-image-2.1/scripts/export_source.sh   # 见 remote/scripts/_export_source.sh
```

## 快速抓到某个事实

```bash
# 多参考图的官方定义
grep -n -A6 'Multiple Reference Images' qwen-image-2.1-github-README.md

# 尺寸是怎么算出来的
grep -n -B2 -A8 'calculate_dimensions' diffusers-pipeline_qwenimage21.py

# 参数默认值
grep -n 'num_inference_steps\|true_cfg_scale\|output_resolution\|use_kv_cache' \
  diffusers-pipeline_qwenimage21.py | head -20

# 许可证是否允许商用
grep -in 'non-commercial\|commercial' qwen-image-2.1-LICENSE.txt | head
```

## 各份文档该抓什么（已核对过的事实）

| 事实 | 出处 | 原文 |
|---|---|---|
| 多参考图 = 多主体合成 | GitHub README | *Image Editing (Multiple Reference Images)*：`image=[ref_0, ref_1, ref_2]`，*"up to 10 reference images for multi-subject composition"* |
| 许可证非商用 | HF 模型卡 front-matter | `license: other` / `license_name: qwen-research` / `license_link: LICENSE`（**不是 Apache 2.0**） |
| 默认 2K | HF 模型卡 Quick Start | `width=2048, height=2048` 直接写进示例 |
| 默认 40 步 | 两份 README | `num_inference_steps=40` |
| 7 个原生 2K 档位 | 两份 README | `1:1 2048×2048` … `9:16 1536×2752` |
| 透明图提示词前缀 | 两份 README | *"This is an RGBA image with transparency. …"* |
| 尺寸推导规则 | diffusers 源码 | `calculate_dimensions(output_resolution², image[-1] 的比例)`，显式 width/height 优先 |
| `image` 是"一组图" | diffusers docstring | *"A list is one set of images shared by every prompt in the batch, not one entry per prompt."* |
| 默认不做 CFG | diffusers docstring | *"Qwen-Image 2.1 is meant to be sampled without guidance, hence the default of 1.0."*（`true_cfg_scale=1.0`） |
| `output_resolution` 也缩放参考图 | diffusers docstring | *"Target side length used to derive height/width and to resize condition images."* |
| prefix KV cache 默认开 | diffusers docstring | `use_kv_cache=True`；开关它不会逐比特复现（reduced precision 下 tile 不同），都在 fp32 容差内 |
| 管线类名 | HF 模型卡 / 源码 | `QwenImage21Pipeline` |

## 已知抓不到的东西

- **qwen.ai 博客正文**：那是 SPA，HTML 里只有壳（`__NEXT_DATA__` 都没有，正文走接口异步加载），
  所以 `qwen-image-2.1-blog.txt` 是空的。要看博客只能联网打开 URL；本文档目录里的
  GitHub README + HF 模型卡覆盖了博客里所有技术内容。
- **官方示例图**：README 里的图挂在 `qianwen-res.oss-*.aliyuncs.com`，没下载（体积大又非必要）。
- **ComfyUI 工作流 JSON**：属于另一条部署路线，本项目走 diffusers，暂不下载；
  需要时从 `github.com/Comfy-Org/workflow_templates` 取。

---

重新同步：`python tools/sync_upstream_docs.py`

### Prompt 改写模型（PE）的 system prompt

官方把「prompt rewriting」列为最佳实践第一条（README「Prompt Rewriting」）。
这两个 9B checkpoint 各自带一份 system prompt，是**官方的改写方法论原文**，
对"怎么把口语指令写成模型吃得准的指令"很有参考价值 —— docs/PROMPT-ANATOMY.md 引用了它。

| 文件 | 用途 |
|---|---|
| prompt-rewriter-T2I-system-prompt.txt | 文生图改写（Qwen-Image-2.1-PE-T2I） |
| prompt-rewriter-I2I-system-prompt.txt | 编辑改写（Qwen-Image-2.1-PE-I2I），含 Attribute Disentanglement 准则 |

来源：https://huggingface.co/Qwen/Qwen-Image-2.1-PE-T2I/raw/main/system_prompt.txt（同 I2I）
