# 参考图引用语法实测（`<image1>` / `<image2>`）

> 目的：确认「用参考图时，prompt 里该怎么引用它」到底有没有正经语法、编号怎么对应。
> 结论：**有，官方语法就是 `<image1>`/`<image2>`…，编号 = `image` 参数的上传顺序，从 1 开始。**
> 日期：2026-09-26　实例：AutoDL 4090 48G（全 BF16 常驻，offload=none）

## 1. 源码依据（不是猜的）

`docs/upstream/diffusers-pipeline_qwenimage21.py`，`QwenImage21Pipeline.__init__` L211-220：

```python
self.prompt_template_t2i = (
    f"<|im_start|>system\n{self.sys_prompt}<|im_end|>\n"
    f"<|im_start|>user\n{{}}<|im_end|>\n"
    f"<|im_start|>assistant\n"
)
self.prompt_template_ti2i = (
    f"<|im_start|>system\n{self.sys_prompt}<|im_end|>\n"
    f"<|im_start|>user\n<image1><|vision_start|><|image_pad|><|vision_end|>{{}}<|im_end|>\n"
    f"<|im_start|>assistant\n"
)
```

`_get_qwen_prompt_embeds()` L249-259：

```python
for t in prompt:
    n_imgs = len(image)
    replace = "<image1><|vision_start|><|image_pad|><|vision_end|>"
    for i in range(2, n_imgs + 1):
        replace += f" <image{i}><|vision_start|><|image_pad|><|vision_end|>"
    template = self.prompt_template_ti2i.replace(
        "<image1><|vision_start|><|image_pad|><|vision_end|>", replace
    )
    prompts.append(template.format(t))
```

三个可直接下结论的点：

1. **`<image1>` 是占位符本身的字面量文本**，会真实出现在喂给文本编码器的 prompt 里。
   `<|vision_start|><|image_pad|><|vision_end|>` 是管线自己紧跟其后插入的视觉 token，**别手写**。
2. **编号跟着 `image` 列表走**：第 N 个上传的图 = `<imageN>`。
3. **`<image1>` 一定存在**，哪怕只有一张图。所以"不写 imageN 就没法引用"是错的，
   正确说法是：**不写就是一张图，写了才能指名道姓。**

另一处更贴近使用的官方依据，`prompt_rewrite/data/edit_example.jsonl` 的 `multi_portrait` 示例
（**正是"两张图、两个人、同框"**）：

```json
{"id": "...", "task_type": "multi_portrait",
 "prompt": "将<image1>中的人物和<image2>中的人物置入一个现代抖音直播间的场景中，生成一张两人并排坐在直播桌后共同面向镜头介绍产品的合影照片。保持两位人物的面部特征、发型和服装外观完全不变。",
 "input_images": ["images/1549226_a.png", "images/1549226_b.png"]}
```

官方 PE 的答案契约里也用它（`prompt_rewrite/pe_core.py` 顶部注释）：

```text
edit  {"rewritten_prompt": "...", "wh_ratio": "", "ratio_follow": "<image1>"}
```

而 `pe_core.build_messages()` 的 docstring 明确警告顺序不能乱：

> Images come first and in order, because the system prompt tells the model to address them as
> ``<image1>``, ``<image2>``, ... -- reordering them silently re-points every reference in the rewrite.

→ **顺序即编号，顺序错了指代就错了。**

## 2. 受控实验

设计：故意让"形状"和"颜色"互相冲突，这样合并/错指都会肉眼可见。

素材：

| 文件 | 内容 |
|---|---|
| `ref_A_red.png` | 768×1024，红圆（左） |
| `ref_B_blue.png` | 768×1024，蓝三角（右） |
| `ref_C_both.png` | 768×1024，红圆 + 蓝三角并排 |

参数：`width=768 height=1024 num_inference_steps=12 seed=1234`（固定种子，只变 prompt）。
参考图组：P1~P4 用 `[A, B]`，P5 用 `[C]`。

| # | prompt | 实测输出 |
|---|---|---|
| P1 | 左半边是一个红色圆，右半边是一个蓝色三角形。（**不点名**） | 红蓝**拼成一个融合体**，没分开 |
| P2 | `<image1>`是红色圆，`<image2>`是蓝色三角形。…左边红色圆，右边蓝色三角形。 | ✅ 左红圆 + 右蓝三角，**干净分开** |
| P3 | `<image2>`是红色圆，`<image1>`是蓝色三角形。…（**编号对调**） | ✅ 左红圆 + 右蓝三角 |
| P4 | 第一张参考图是红色圆，第二张参考图是蓝色三角形。… | ✅ 左红圆 + 右蓝三角 |
| P5 | 把这张图里同时出现的红色圆和蓝色三角形分开…（单张合成图） | 无效样本：合成图 C 本来就没重叠，见下方说明 |

原始输出：`test-data/imageN_check/P1_none.png` … `P5_singleC.png`。

### 结论与边界（不要过度外推）

- **P1 vs P2 是本实验真正的信号**：同一组参考图、同一个种子，唯一差别是 prompt 里有没有
  点名。不点名时模型把两个形状**融合成一个**；用 `<image1>`/`<image2>` 指认后两个主体被正确分开。
  → 引用语法确实影响 grounding，不是装饰。
- **P3 没有翻转**，说明色彩/形状这种强语义线索下，模型不必然被编号绑死。编号对调不是"必错"，
  而是**指代失去保障**。这一点和 PE 的注释一致：顺序乱了，"silent" 地指错，不会报错。
- **P4 说明官方那种自然语言序数（"第一张/第二张参考图"）也能工作**。所以 `<imageN>` 不是唯一写法，
  它只是**最不容易歧义**、且被官方示例和 PE 契约正式使用的那种。
- **P5 作废**：我生成合成图时把圆和三角画成了并排而非重叠，指令与画面本来就一致，测不出"拆分"能力。
  要测这个得让两个主体真的重叠/粘连，属于另一组实验。

### 实用建议（写进 UI 与文档的版本）

1. 一张图时什么都不用写。
2. 多张图、且需要分别指代时，用 `<image1>`/`<image2>`（点击上传缩略图下方的按钮插到光标处）。
3. 上传顺序就是编号，**要改顺序只能删了重加**（拖拽排序未实现）。
4. 参考图顺序还影响输出画布：管线用 `image[-1]` 算比例，**最后一张的朝向会赢**。
   想固定就显式给 `width`/`height`/`aspect_ratio`。
5. `ratio_follow` 只属于官方 PE（另一个 checkpoint `Qwen-Image-2.1-PE-I2I`），
   本服务跑的是**原始管线**，没有这一层，所以"让输出跟随 `<image1>`"没有对应参数。

## 3. curl 的坑

写 `<image1>` 时 **必须用 `--form-string`**：

```bash
# ✗ 错：curl 把 <image1>... 当成"从文件读值"，报 Couldn't open file "<image1>..."
-F 'prompt=将<image1>中的人物和<image2>中的人物放在一起'

# ✓ 对
--form-string 'prompt=将<image1>中的人物和<image2>中的人物放在一起'
```

服务端 multipart 解析器（`python-multipart`）本身完全能处理尖括号，坑只在 curl 自己。

## 4. 复现

```bash
# 实例上（KEY 由本地注入）
bash /root/_imageN_refs.sh          # 脚本源：remote/scripts/_imageN_refs.sh
```

脚本会自己用 PIL 造三张素材图，再依次跑 P1~P5，结果落在 `/root/autodl-tmp/imageN_check/`。
