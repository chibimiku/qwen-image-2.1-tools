# CFG / 负面提示词 A/B 实验 —— 结果与结论

实验设计见 `docs/CFG-NEGATIVE-AB-TEST.md`。本文是**实测结果**，包含一次失败重跑、
两个被发现的代码缺陷，以及最终按人眼判图得到的结论。

**一句话结论：这个实验没能回答"CFG 是否减少肢体崩坏"，因为用来回答它的两个
测量工具都失效了；而且按 1:1 分辨率逐格复核后，我原本据以立项的"多腿"现象
大部分是把垂在身侧的手臂误判成了多余的腿。所以不建议据此把 CFG 提升出高级设置。**

---

## 1. 样本与客观数据

- 3 类任务 × 4 组 × 12 个 seed = **144 张**（最终全量成功，0 失败）
- 1024×1024，20 步，固定参考图与 prompt，配对设计（同一 seed 跑完 4 组）
- 机器：单卡 RTX 4090 46068 MiB，`QWEN_TILE_VAE=1`，权重常驻
- 未启用 `anatomy_check` 重试（会换 seed，破坏配对）

| 任务 | A 默认 | B 负向+2.0 | C 负向+2.5 | D PE 改写 |
|---|---|---|---|---|
| t2i（文生图） | 11.5s | 22.2s | 22.2s | 11.6s |
| edit1（单参考图大改姿势） | 13.8s | 26.5s | 26.5s | 13.8s |
| edit2（双人肢体交叠） | 13.8s | 26.5s | 26.5s | 13.8s |

**耗时是本次唯一站得住的测量结果，且结论明确：**

- 开启 CFG（`true_cfg_scale > 1` + `negative_prompt`）**耗时约翻倍**（11.5→22.2s，13.8→26.5s）。
  这是必然的：CFG 每步要额外跑一次无条件分支，采样成本近似 ×2。
- 这项开销与 `true_cfg_scale` 是 2.0 还是 2.5 **无关**（B 与 C 的耗时逐位相同）。
- 组 D（按官方 PE 方法改写 prompt、不开 CFG）**耗时与 A 完全一致** —— 因为它没动采样配置。
  换句话说：**改进 prompt 是零成本的，开 CFG 是双倍成本的。**

---

## 2. 两个失效的测量工具（这才是本次最有价值的产出）

### 2.1 自动标签工具：144 张全部 fail-open 归零，没有任何信息量

`_cfg_ab_score.py` 用 `service/anatomy_check.py` 的 SmolVLM2-2.2B 逐张判图。
它跑完给出的汇总是：

```
| edit1 | A 默认 | 12 | 0 | 0% | 13.8s | 0.00 |
... 12 行全部 FAIL 0%、平均置信度 0.00
```

**"0% 异常"看起来像好消息，实际是模型一张都没判过。** 复核 `auto_labels.jsonl`：

```
样本: 144
label 分布: {'unavailable': 144}
passed 分布: {True: 144}
confidence: 全为 0 吗？ True  取值集合: [0.0]
reason 前 3 条:
  - OSError: We couldn't connect to 'https://huggingface.co' to load the f...
```

根因：`inspect_image()` 是**故意 fail-open** 的（加载失败就返回 `passed=True`，
避免审图模型把出图流程整个拖死）。这在线上是对的，在**离线评分场景下却把
"工具坏了"伪装成了"结果很好"**。集群内网连不出外网，而 `from_pretrained`
默认会为每个文件向 huggingface.co 发 HEAD 查更新 → 5 次重试后抛 OSError。

已在 `service/anatomy_check.py` 修掉，并加了本地回归脚本 `_anatomy_sanity.py`：

```python
# 本地目录 → 导入期就设离线。放模块级而非 _load() 里：
# huggingface_hub 在 import 时读一次 HF_HUB_OFFLINE 存进常量，之后改 os.environ 可能不生效
if is_local_dir(MODEL_ID):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
```

修复后：离线加载成功（6s），模型**确实在作答**。

> **教训（值得写进方法论）：fail-open 的工具必须自带"我还活着吗"的探针。
> 判据是 `label == "unavailable"`，不是 `passed`** ——
> 一个永远返回 PASS 的评分器和一个真的没发现问题的评分器，在汇总表里长得一模一样。

### 2.2 修好之后，这个审图模型对这组实验**依然没有区分力**

加载正常后，用两张人为构造的图做灵敏度测试（`_anatomy_sanity.py`，含渐变/描边，
尽量接近真实渲染）：

```
三条腿的图: passed=True  label=pass  conf=1.00   reason: The image is a cartoon
两条腿的图: passed=True  label=pass  conf=1.00   reason: The image is a cartoon
```

它不是"卡"了，是**按指令办事**：模型自己的 prompt 里写着
`PASS if ... the image is stylized`。本项目的出图风格恰好是插画/动漫，
所以它对这类图**结构性地一律 PASS**，哪怕明显多一条腿。

**结论：2.2B 审图模型不能作为本项目的异常率判据。** 它对"真人照片风格的严重畸形"
或许有区分力，但对本项目的实际输出风格没有。它当初在线上能拦下一些东西，
说明它对**更严重的**崩坏有效；但**微小到"多一条腿"这一档，测不出来**。

---

## 3. 人眼复核：我原本的假设被自己的数据推翻了

既然两个自动工具都不可用，就只能人眼看。为了能真的数腿，专门生成了
1:1 原分辨率的并排对照图（`_ab_crop_cells.py`）：

```
/root/exp_out/sheets_zoom/cells/cell_<task>_<seed>.jpg    # 同一 seed，4 个变体并排，腰以下 1:1
/root/exp_out/sheets_zoom/legs_<task>.jpg                 # 12 seed × 4 变体总览
```

### 3.1 先说一个必须记录的**过程错误**

在 260px/格的总览图上，我一度把多处判为"多一条腿"。按 1:1 放大逐格复核后，
**大部分是误判**：那些"多出来的肢体"是**垂在身侧的手臂和手**。

列 4 尤其明显 —— 它输出的是**线稿风格**，手臂只有细线轮廓、没有肤色填充，
在缩略图里就糊成了一条"腿"。放大后看得很清楚：`t2i seed 404` 的列 4 是
两条腿 + 两条手臂，解剖结构正确。

**所以"经常出现多腿"这个立项前提，在本次样本里没有被证实。**
（这不等于不存在 —— 用户观察到的是真实体验。但要定量，需要可靠判据。）

### 3.2 复核后**确实**稳定复现的问题：组 B/C/D 的观感大幅退化

这是本轮唯一在我逐格核对中**反复出现**的系统性差异：

- **A 组**（官方默认：无负面词、CFG=1）：正常的插画上色稿，有肤色、有阴影层次。
- **B / C 组**（负面词 + CFG 2.0/2.5）：变成**线稿/淡彩**，大面积留白，颜色发灰发淡。
- **D 组**（PE 改写 prompt，无负面词、CFG=1）：同样偏线稿、偏淡。

也就是说：**负面提示词 + CFG 的副作用不是"修好解剖"，而是把画面推向线稿化、
降低完成度**。这与方案里"prompt 跟随 / 身份 / 审美中位数下降不超过 0.5 分"这一条
门槛直接冲突 —— 而且下降幅度肉眼可见，不像 0.5 分以内。

### 3.3 组 D 的另一个观察

D 组（按官方 PE 方法把"该变的/该保持的"拆开写）在**保持身份一致性**上表现不错
（`edit2` 里两个人的衣着、发型、配色都跟参考图对得上），但同样有线稿化倾向。
由于 D 与 A 的耗时相同，如果要用 prompt 工程，方向应落在 D 这条路上，
而不是把 CFG 打开。

---

## 4. 对照判定门槛（方案第四节）

| # | 门槛 | 本次结果 |
|---|---|---|
| 1 | B 或 C 在 ≥2 类任务异常率相对 A 下降 ≥30% | **无法判定** —— 唯一可用的自动判据无区分力（§2.2），人眼复核又把"异常"证伪了大半（§3.1） |
| 2 | prompt 跟随 / 身份 / 审美下降 ≤0.5 分 | **不满足** —— B/C/D 出现肉眼可见的线稿化与降饱和（§3.2） |
| 3 | 用户能接受耗时增幅 | **不满足** —— CFG 使耗时翻倍（§1） |
| 4 | 换一批 seed 方向一致 | 未做 —— 当前结论已足以否掉门槛 2、3，复测没必要 |

### 决定

**不把 CFG / 负面提示词提升出「高级实验设置」。** 保持它们在高级设置里、
默认关闭、并在 UI 上标注"耗时翻倍、会明显改变画面风格"。

理由不是"CFG 有害"，而是：**没有任何一条门槛被满足，其中第 2、3 条被明确证伪。**

---

## 5. 下一步该怎么做（可执行的）

1. **别再用 2.2B 审图模型当异常率判据。** 需要真判据的话，选项是：
   换一个对本项目画风有区分力的模型；或改判据本身 ——
   不判"有没有多腿"，改判**可量化的东西**（见 2）。
2. **用可测量的代理指标替代主观判分**，例如：
   - 输出与参考图在**下半身区域**的边缘/骨架一致性（需要 pose 估计）
   - 肢体区域面积、连通域个数（能抓"融合成一片"和"断裂"，抓不住多一条腿）
   - 与同 seed 组 A 的感知差异（LPIPS）—— 顺便能量化 §3.2 的线稿化
3. **把"线稿化"当成一个真问题来查。** 它比"多腿"更容易定量、也更容易复现：
   同一 seed 只改 `true_cfg_scale` 就该能画出一条曲线。
4. **prompt 工程优先于采样参数。** 官方 PE 方法（`docs/PROMPT-ANATOMY.md`、
   `docs/upstream/prompt-rewriter-I2I-system-prompt.txt`）零额外耗时，
   而 CFG 是双倍耗时换一个没验证出来的收益。
5. **给 fail-open 的工具加活着探针**（本次已加），并且**汇总表里必须显示
   "多少张是没判过的"**，否则 0% 会被读成好消息。

---

## 6. 产物清单

远端 `/root/exp_out/`：

| 文件 | 内容 |
|---|---|
| `manifest.jsonl` | 144 行，含 variant（**内部用，别给评分者**） |
| `blind.jsonl` | 只含 `blind_id` 与路径 —— 盲评用这个 |
| `design.json` | 实验设计（seed 表、变体定义） |
| `auto_labels.jsonl` | 自动标签，**已确认全部 unavailable，无信息量** |
| `REPORT.md` | 脚本自动汇总（含那张会误导人的 0% 表，保留作对照） |
| `sheets/` | 3.2MB PNG 盲评表 × 7（原始） |
| `sheets_small/` | JPEG 紧凑版 + `score_sheet.json`（144 格评分模板） |
| `sheets_zoom/legs_*.jpg` | 12 seed × 4 变体，腰以下总览 |
| `sheets_zoom/cells/cell_*.jpg` | **1:1 原分辨率并排对照（最终判据）** |

本地 `exp/`：盲评表、放大表与 1:1 对照图的副本。

复现全部产物：

```bash
# 生成（可只跑一类：python _cfg_ab_generate.py t2i；manifest 会追加不会覆盖）
KEY=<api_key> /root/miniconda3/bin/python -u /root/_cfg_ab_generate.py
# 自动标签 + 盲评表 + 汇总（**必须先设离线**，否则 144 张全 unavailable）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /root/miniconda3/bin/python -u /root/_cfg_ab_score.py
# 人眼判图要用的放大表与 1:1 对照
/root/miniconda3/bin/python -u /root/_ab_zoom_sheets.py
/root/miniconda3/bin/python -u /root/_ab_crop_cells.py t2i 101 303 404 808
# fail-open 工具的自检（必须先看到模型真的在作答）
/root/miniconda3/bin/python -u /root/_anatomy_sanity.py
/root/miniconda3/bin/python -u /root/_ab_recheck_labels.py
```

---

## 附：本次顺带修掉的代码缺陷

跑这个实验暴露了两个真 bug，都已修并加了回归测试，详见 `docs/CHANGELOG.md` 第三十二批：

1. **JSON 请求体里的字符串宽高导致 HTTP 500**（`"1024" * "1024"`）。
   multipart 分支有 `int()`、JSON 分支没有 —— 同一个接口换个 Content-Type 结果不同。
   这正是本次 t2i 那 48 张全灭的原因。
2. **OpenAI 的 `size` 字段被静默忽略**，标准写法 `{"size":"1024x1024"}` 会悄悄按
   官方 2K 出图（差 4 倍像素）。静默按别的尺寸出图比直接报错难查得多。
