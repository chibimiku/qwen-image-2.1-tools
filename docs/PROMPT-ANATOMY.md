# 人体崩坏（多条腿之类）：诊断与优化

> 用户反馈"经常出现多条腿"。这份是**代码 + 官方文档 + 对照实验**三方面的结论，
> 不是一个"试试这么写"的建议清单。实验脚本与产物见 `remote/scripts/_pose_ab.py`、
> `_mp_ab.py`，图在 `tmp_ab/`（本地）。

## 一、先复现出来，才好谈优化

用你那条 prompt 的**写法特征**（整场景从零描述 + 复杂姿态 + 动作词），
配一张"紧身衣三视图"参考图，同 seed 连跑几组，稳定复现：

| 现象 | 表现 |
|---|---|
| 肢体绞成一团 | 两人抱在一起时，腿的归属读不出来，观感就是"多了一条腿" |
| 参考图被**同时重绘** | 中间是新的双人场景，背景里左边正视图、右边背视图**还在**，等于一张图里画了两件事 |
| 服装被凭空指定 | prompt 里没提衣服，参考图是紧身衣，输出给人物换成了连衣裙/裤子 |

这三条都不是"分辨率不够"或"seed 不好"，是**提示词结构导致的**。

## 二、根因：三种"让模型重画整个身体"的写法

### 根因 1（最主要）：把"重建角色"和"改姿态"写在同一句里

你的 prompt 开头是：

```
<image1> is a three-view reference of the female character. Strictly reconstruct her face,
hair, body proportions and anime art style based on the three-view, keep high consistency.
... She is being held up by an adult man, legs wrapped around his waist ...
```

前半句要求"按三视图严格重建她的**身体比例**"，后半句要求"她被抱起、腿绕在腰上"——
**身体形态被要求同时"保持"和"大改"**。模型只能重画整个身体，而重画就给了肢体出错的空间。

官方 PE 的第一条准则正好说这件事（`docs/upstream/prompt-rewriter-I2I-system-prompt.txt` L24）：

> **How much you build is intent-branched.** When the user wants *this picture changed*
> (a local object/attribute/background edit…) **clarify and constrain**: say exactly what
> changes, and let everything else stand. When the user wants *a new picture of this subject*
> (placing a subject in a new scene, compositing across images…) **construct actively**.

你这条把两件事混在一起了：既想"改这张图"，又想"用这个角色画一张全新场景"。
**混在一起的代价就是模型的自由度最大 → 崩坏概率最高。**

### 根因 2：preservation 写得太具体，反而变成"生成指令"

官方另一条（同文件 L41）：

> **Say what stays, without repainting it.** … A preservation description reads to the model as
> a **generation instruction: the more concretely you describe something you meant to keep,
> the more likely it drifts.** Describe appearance concretely only for what you are actually changing.

`Strictly reconstruct her face, hair, body proportions and anime art style based on the
three-view, keep high consistency` —— 这句话把"脸、头发、身体比例、画风"逐项点名了。
按官方说法，这**恰好是最容易让它漂**的写法。而且：

> **Identity is the hardest invariant.** … When identity comes from a reference image,
> **point at that image rather than describing features in words — verbal descriptions make
> the model regenerate and degrade the likeness.**

所以正确写法是**指着图**（`as in <image1>`），而不是用词去描述它。

### 根因 3：一句话里塞了太多"同时要改"的东西

你那条实际包含：换姿态 + 加一个人 + 两人交缠 + 大幅度运动 + 表情 + 液体效果 + 画风锁定 + 构图锁定。
每一项都要模型在同一个 latent 里协调。官方准则（L47）：**Only what was asked** ——
反过来同样成立：**要得越多，每项得到的容量越少。**

## 三、代码层面查到的、能用的杠杆

### 3.1 负向提示词 + CFG：**官方没有给负面词，也没建议用它**

先把来源说清楚，避免把"我们编的"当成"官方推荐的"。

**官方关于负面提示词只有两句**，都在管线 docstring（`docs/upstream/diffusers-pipeline_qwenimage21.py` L540-544）：

```
L540:  negative_prompt (`str` or `list[str]`, *optional*):
L541:      The prompt not to guide image generation. Ignored when `true_cfg_scale` is not greater than 1.
L542:  true_cfg_scale (`float`, *optional*, defaults to 1.0):
L543:      Classifier-free guidance scale. Enabled by `true_cfg_scale > 1` together with a negative prompt.
L544:      Qwen-Image 2.1 is meant to be sampled without guidance, hence the default of 1.0.
```

就这些。**官方没有给过任何推荐负面词表**，而且在其它所有官方材料里也找不到：

| 材料 | `guidance` / `negative` 命中 |
|---|---|
| 官方 README | guidance 仅 1 处：示例里的 `--guidance-scale 1`；**negative 0 处** |
| README「Default Parameters」表 | **只列了 `num_inference_steps` 和 `width/height`，根本没有 guidance 这一项** |
| HF 模型卡 | 0 处 |
| ModelScope README | 0 处 |
| 官方博客（92 KB） | guidance / true_cfg / CFG / negative 全部 **0 处** |
| 两个 PE 的 system prompt | 未提负面词 |
| 管线签名 | `true_cfg_scale: float = 1.0`（默认就是不开引导） |

**所以准确的表述是**：

- 官方**唯一的立场**是"这个模型按无引导采样设计"（L544）+ 示例用 `guidance-scale 1`。
- 要用负面词，**机制上必须**把 `true_cfg_scale` 调到 >1（L541/L543），这属于**偏离官方默认路线**。
- **不能说"官方建议别用"** —— 原文没这么讲，那是把它读重了。
  （这句话我一开始说过了头，这里更正。）

**我们 UI 里那两串负面词是自编的经验值，不是官方推荐**：

```
人体：extra limbs, extra legs, extra arms, fused limbs, merged legs,
      malformed hands, missing limbs, conjoined figures, distorted anatomy
画质：blurry, lowres, jpeg artifacts, watermark, signature, text, logo,
      oversaturated, oversharpened, photorealistic
```

界面上已标明「自编」，只当**起点**，按自己的结果改。

用法与代价：

```
negative_prompt: <你的词>
true_cfg_scale: 2.5        # 必须 >1，否则负面词被忽略（L541）
```

⚠️ **代价**：① 每步多跑一次前向，**耗时约 ×2**（实测 16s → 34s）；
② 官方按无引导设计，开大了画面可能变僵、色彩变闷。**当兜底用，不是默认开。**

⚠️ **它有没有效，我还没有可靠数据**。做过的对照实验里，每个变体只跑 1 个 seed，
而生成是概率性的 —— 那种样本量判定不了对错。多 seed 统计见下面的实验记录（若有）。

### 3.2 分辨率：不是主因，但会改变风格

同 prompt / 同 seed，只改像素总数（0.63→1.66MP）：**解剖都没崩**，
但审图对结果的描述从 "cartoon" 变成了 "**3D render**" —— 分辨率会改变风格走向。
所以分辨率不是"多条腿"的主因（别指望靠调它解决），但它确实影响观感一致性。
选法见 [RESOLUTION.md](RESOLUTION.md)。

### 3.3 你已有的两个缓解手段（都在跑）

- **审图重试**（`anatomy_check` + `anatomy_max_retries`）：抓明显畸形后换 seed 重跑。
  ⚠️ **但它的判据很保守** —— 实测里连"肢体绞在一起"这种都能 PASS
  （INSTRUCTION 明确写 "PASS if … you are uncertain"）。当兜底可以，别当质量保证。
- **人脸回贴**（`service/face_fix.py`）：编辑会重绘脸，它按羽化椭圆贴回源图脸，
  实测 7 个样本全部改善 0.029~0.044。**这是唯一能真正锁住身份的机制**（见坑 4）。

## 四、优化清单（按性价比排序）

### 第 1 优先：拆成两步，别让模型同时做"重建 + 换姿态"

这是官方 intent-branched 准则的直接应用，也是本文件里最有把握的一条：

```text
第一步（只改姿态，不给它重建身体的任务）
  把 <image1> 中的人物改成被一个成年男性抱起的姿势，她的双腿绕在他腰上。
  人物的脸、发型、服装、画风保持与 <image1> 一致。
  全身入镜，两个人都在画面内，广角，不裁切。
  纯动画风格，线条干净。

第二步（在第一步结果上继续，可选）
  把两人的表情改成惊讶，背景换成简洁的浅色。
  其余部分与 <image1> 保持一致。
```

**要点**：一次性只改一件事，其余用**一句笼统的保持句**带过（而不是逐项描述）。

### 第 2 优先：改写法

| 别这么写 | 改成 |
|---|---|
| `Strictly reconstruct her face, hair, body proportions and anime art style based on the three-view, keep high consistency` | `保持 <image1> 的脸、发型与画风`（指着图，不逐项描述） |
| 整场景从零描述（`She is being held up by…`） | 操作在句首：`把 <image1> 中的人物改成…` |
| `Aggressive movement, large motion, dramatic expression` | 只留一个可观察的点：`表情惊讶`。动作词堆叠会让肢体解算更乱 |
| 不提服装 | 要么明确写（`服装保持与 <image1> 一致`），要么接受模型自选 |
| `no cropping` 这类否定式构图词 | 用正面描述：`全身入镜，两人都在画面内` |

### 第 3 优先：姿态难度

"被抱起 + 双腿绕腰 + 大幅度运动"是**肢体交缠 + 双人**的叠加，是这类模型最容易失手的构图。
如果连续崩，先降一档：改成**并肩站立 / 单人腾空**这类不交缠的姿态，确认解剖没问题后
再往上加复杂度。

### 第 4 优先：身份靠链路外补

官方明说 `Strictly reconstruct her face` 这种**文字描述反而会让 likeness 退化**。
要锁脸就用 `service/face_fix.py` 把源图的脸贴回，别指望 prompt。

### 可选兜底

- 负向提示词 + `true_cfg_scale` 2~2.5 试一次，看整体是否变僵
- 开 `anatomy_check`（默认重试 2 次）当自动兜底

## 五、坑与限制（别期待过高）

| 坑 | 说明 |
|---|---|
| 以为写好 prompt 就必然不崩 | 这是生成模型的固有概率问题；prompt 优化是**降低概率**，不是消除 |
| 以为 OPEN 词（`multiple`, `several`）安全 | 任何让"肢体数量"变模糊的词都会提升多肢概率 |
| 以为审图一定能抓 | 实测它连"腿绞成一团"都 PASS（保守判据 + 不确定即 PASS） |
| 以为 prompt 能锁身份 | 官方明确说文字描述会**退化** likeness；只能靠 face_fix 这类链路外手段 |
| 以为加 CFG 一定更好 | 官方：该模型按无引导设计。开 CFG 可能变僵，且每次多一遍前向（耗时约 ×2） |
| 让参考图里"多视图"同时入镜 | 参考图是三视图/多视图时，模型可能把"多个视图"当成"要画多个"，或把参考图一起重绘进背景 |

## 六、WebUI 上现在能调什么（与"怎么选"）

管线参数已全部梳理过一遍，**值得暴露且此前缺失的四个已经加上**：

| 控件 | 默认 | 什么时候动它 |
|---|---|---|
| `negative_prompt` | 空 | **人体崩坏时**。两个快捷按钮：「填入人体负面词」「填入画质负面词」（点它会把 CFG 一起设成 2.5，因为负面词需要 CFG>1 才生效） |
| `true_cfg_scale` | 1 | **只在负面词必须发挥作用时**调到 2~2.5。代价：耗时约 ×2（每步多一次前向），官方说该模型按无引导设计，开大了画面可能变僵 |
| `num_images_per_prompt` | 1 | **要挑一张时**用 2~4。管线按 batch 并行去噪；每张使用 `seed+i`、各自可复现和落盘。张数会明显增加显存占用，不等于低成本队列 |
| `sigmas` | 空 | 进阶玩法，**平时别动**。给了就取代按步数生成的调度；服务端会校验（递减、0~1、≥2 点），不合格静默忽略 |

界面上做了**联动提示**（`cfgnote` 那行），把两种常见的"白填"直接标出来：

- 填了负面词但 CFG=1 → `⚠ 负面词不会生效`
- CFG>1 但没填负面词 → `⚠ 管线不会启用引导，这个数值会被忽略`
- 两个都给了 → `CFG=2.5 + 负面词：引导生效，耗时约 ×2`

**为什么不暴露 `use_kv_cache`**：官方 docstring 明说"切换它不会逐比特复现同一张图"，
它是性能开关不是画质开关，暴露出去只会让人误以为能调出不同效果。保持内部默认。

**为什么 `attention_kwargs` / `*_embeds` 不暴露**：前者要传张量描述、后者要求你自己做编码，
都不属于"点一下就能用"的范畴，做进去只会增加误操作面。

### 推荐组合（按场景）

| 场景 | 建议 |
|---|---|
| 日常出图 | 全默认：CFG=1、无负面词、1 张 |
| 反复出多余肢体 | 人体负面词 + CFG=2.5，同时按第四节拆两步写 prompt |
| 要挑一张满意的 | `num_images_per_prompt=3~4`，配合固定 seed 让每张都可复现 |
| 要更贴负面词 | CFG 试 3（>3 容易变僵，别超过） |

## 七、复现与复核
```bash
# 对照实验（在实例上；需要 HF_HOME 指向本地缓存，否则会去连 HF）
HF_HOME=/root/autodl-tmp/hf HF_HUB_OFFLINE=1 \
  python /root/_pose_ab.py          # 姿态复杂度对照
  python /root/_mp_ab.py            # 分辨率对照

# 你自己的历史：把每张图的 prompt/negative/CFG 全捞出来
python /root/_dump_prompts.py
```

官方依据位置：

| 内容 | 位置 |
|---|---|
| intent-branched（重建 vs 局部改） | `docs/upstream/prompt-rewriter-I2I-system-prompt.txt:24` |
| Attribute Disentanglement | `docs/upstream/prompt-rewriter-I2I-system-prompt.txt:26` |
| preservation 描述会变成生成指令 | `docs/upstream/prompt-rewriter-I2I-system-prompt.txt:41` |
| identity 要点图、别描述 | `docs/upstream/prompt-rewriter-I2I-system-prompt.txt:43` |
| Only what was asked | `docs/upstream/prompt-rewriter-I2I-system-prompt.txt:47` |
| 操作放句首 | `docs/upstream/prompt-rewriter-I2I-system-prompt.txt:51` |
| prompt rewriting 是官方最佳实践 | `docs/upstream/qwen-image-2.1-github-README.md:170` |
| CFG 只在 true_cfg_scale>1 且有 negative 时生效 | `docs/upstream/diffusers-pipeline_qwenimage21.py:668` |
| token = 16×16 像素（分辨率为何敏感） | `docs/upstream/diffusers-pipeline_qwenimage21.py:199` |
