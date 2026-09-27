# 官方 Prompt Rewriting 一节（节选自 Qwen-Image-2.1 仓库 README）

> 来源：`QwenLM/Qwen-Image-2.1` 的 README「Prompt Rewriting」一节，全文镜像在
> 仓库的 `docs/upstream/qwen-image-2.1-github-README.md`。这里只摘相关部分，
> 方便控制台直接打开。原文未做改写。

## Prompt Rewriting

For best results, we recommend using the official **prompt rewriting models** to expand
short prompts into detailed, high-quality descriptions. Two fine-tuned Qwen3.5-VL 9B
checkpoints are provided — one for text-to-image, one for image editing — sharing a
unified codebase that auto-detects the mode from input.

The rewriting code and weights are available at:

- **T2I**: [Qwen/Qwen-Image-2.1-PE-T2I](https://huggingface.co/Qwen/Qwen-Image-2.1-PE-T2I)
- **Edit**: [Qwen/Qwen-Image-2.1-PE-I2I](https://huggingface.co/Qwen/Qwen-Image-2.1-PE-I2I)
- **Code**: `prompt_rewrite/` — unified codebase with `--task t2i` or `--task edit`

```text
prompt_rewrite/
├── run_transformers.py       # Local inference, batch size 1
├── run_vllm.py               # vLLM offline batch (recommended at scale)
├── serve.sh + client.py      # vLLM server + client
├── pe_core.py                # Task profiles, parsing, output records
├── requirements.txt
└── data/                     # Example inputs (t2i + edit with images)
```

### Text-to-Image

```bash
cd prompt_rewrite
pip install -r requirements.txt

# vLLM batch (recommended)
python run_vllm.py --task t2i \
    --ckpt Qwen/Qwen-Image-2.1-PE-T2I \
    --input data/t2i_example.jsonl --output out.jsonl

# Or local transformers
python run_transformers.py --task t2i \
    --ckpt Qwen/Qwen-Image-2.1-PE-T2I \
    --input data/t2i_example.jsonl --output out.jsonl
```

Output:

```json
{
  "rewritten_prompt": "<long detailed English prompt>",
  "wh_ratio": "16:9"
}
```

### Image Editing

```bash
python run_vllm.py --task edit \
    --ckpt Qwen/Qwen-Image-2.1-PE-I2I \
    --input data/edit_example.jsonl --output out.jsonl
```

Input format (JSONL):

```json
{"id": "abc123", "prompt": "make the sky sunset", "input_images": ["images/photo.png"]}
```

Output:

```json
{
  "rewritten_prompt": "Replace the daytime sky with a warm sunset ...",
  "wh_ratio": "",
  "ratio_follow": "<image1>"
}
```

- `wh_ratio` — model chose a new aspect ratio (e.g. `"16:9"`)
- `ratio_follow` — output inherits the specified input image's aspect ratio (e.g. `"<image1>"`)

### vLLM Server

```bash
CKPT=Qwen/Qwen-Image-2.1-PE-T2I bash serve.sh
# then:
python client.py --task t2i --model Qwen/Qwen-Image-2.1-PE-T2I \
    "a corgi playing guitar in the rain"
```

### Integration with the Pipeline

```python
import json
import torch
from diffusers import QwenImage21Pipeline

WH_RATIO_TO_SIZE = {
    "1:1": (2048, 2048), "4:3": (2400, 1792), "3:4": (1792, 2400),
    "3:2": (2528, 1696), "2:3": (1696, 2528), "16:9": (2752, 1536),
    "9:16": (1536, 2752),
}

# After running the rewriter, read the output
rewrite = {"rewritten_prompt": "...", "wh_ratio": "16:9"}  # from run_vllm.py output
prompt = rewrite["rewritten_prompt"]
width, height = WH_RATIO_TO_SIZE.get(rewrite["wh_ratio"], (2048, 2048))

pipe = QwenImage21Pipeline.from_pretrained(
    "Qwen/Qwen-Image-2.1", torch_dtype=torch.bfloat16
).to("cuda")

image = pipe(
    prompt=prompt,
    width=width, height=height,
    num_inference_steps=40,
    generator=torch.Generator("cuda").manual_seed(42),
).images[0]

image.save("rewritten_example.png")
```

## 与本项目这个服务的关系

**本服务不含 PE 层。** 它跑的是 `QwenImage21Pipeline` 原始管线，收到 prompt 直接编码，
不会替你改写。两个 PE checkpoint 是独立的 9B VL 模型，要么另起一个服务，要么离线跑一遍
拿回 `rewritten_prompt` 再送进来。

所以控制台上摆着的那两份 system prompt（`prompt-rewriter-T2I/I2I-system-prompt.txt`）
的用法是：**当写作规范照抄**——按它的八步法/属性解缠规则自己写 prompt，
等于手工走了一遍官方 PE，且零额外推理开销。

`wh_ratio` / `ratio_follow` 两个字段也只属于 PE：本服务没有对应参数，
比例只能通过显式 `width`/`height`/`aspect_ratio` 控制，或让最后一张参考图决定
（这是本服务自己的行为，不是 PE 的 `ratio_follow`）。
