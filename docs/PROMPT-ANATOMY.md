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

### 3.1 负向提示词 + CFG：你一次都没用过

用元数据统计你已生成的 34 张图：**`negative_prompt` 0 次、`true_cfg_scale > 1` 0 次**。

管线签名支持这两项（`diffusers-pipeline_qwenimage21.py`），语义是：

- `negative_prompt` 只在 `true_cfg_scale > 1` 时**才生效**（L668-674 会 warning 提示）
- 官方默认 `true_cfg_scale = 1.0` = **不用引导**（"meant to be sampled without guidance"）

所以对"多余肢体"这种明确的负面项，理论上可用：

```
negative_prompt: extra limbs, extra legs, extra arms, fused limbs, merged legs,
                 malformed hands, missing limbs, conjoined figures, distorted anatomy
true_cfg_scale: 2.5
```

⚠️ **代价**：官方说这个模型是按"无引导"设计的，开了 CFG 可能整体变僵、色彩变差。
实测里开 CFG 的那两组耗时从 16s 涨到 34s（多了一次前向），画面风格也变了。
**当兜底用，不是默认开。**

### 3.2 分辨率：不是主因，但会改变风格

同 prompt / 同 seed，只改像素总数（0.63→1.66MP）：**解剖都没崩**，
但审图对结果的描述从 "cartoon" 变成了 "**3D render**" —— 分辨率会改变风格走向。
所以分辨率不是"多条腿"的主因（别指望靠调它解决），但它确实影响观感一致性。
选法见 [RESOLUTION.md](RESOLUTION.md)。

### 3.3 你已有的两个缓解手段（都在跑）

- **审图重试**（`anatomy_check` + `anthropic_retries`）：抓明显畸形后换 seed 重跑。
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

## 六、复现与复核

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
