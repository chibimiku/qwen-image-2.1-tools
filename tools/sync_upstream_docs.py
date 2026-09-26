# -*- coding: utf-8 -*-
"""把官方文档同步到本地 docs/upstream/，方便随时阅读和对照。

    python tools/sync_upstream_docs.py            # 增量下载（已存在也重下，保持最新）
    python tools/sync_upstream_docs.py --check    # 只报告本地是否齐全，不下载

来源：
  · GitHub README（QwenLM/Qwen-Image-2.1）—— 最全，含 Quick Start / 多参考图 / 架构
  · HuggingFace 模型卡（Qwen/Qwen-Image-2.1）—— 含 YAML 元数据、仓库文件清单
  · ModelScope 上的 README —— 国内可达的同一份
  · qwen.ai 官方博客 —— 发布说明
  · LICENSE（Qwen Research License）—— 商用限制的原始依据
  · diffusers 的 QwenImage21 管线源码摘录 —— 尺寸/参数行为的权威依据（从实例导出）
"""
import argparse
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "upstream")

SOURCES = [
    ("qwen-image-2.1-github-README.md", "GitHub README（官方仓库，内容最全）",
     "https://raw.githubusercontent.com/QwenLM/Qwen-Image-2.1/main/README.md"),
    ("qwen-image-2.1-hf-modelcard.md", "HuggingFace 模型卡",
     "https://huggingface.co/Qwen/Qwen-Image-2.1/raw/main/README.md"),
    ("qwen-image-2.1-modelscope-README.md", "ModelScope README（国内镜像同一份）",
     "https://modelscope.cn/api/v1/models/Qwen/Qwen-Image-2.1/repo?Revision=master&FilePath=README.md"),
    ("qwen-image-2.1-LICENSE.txt", "Qwen Research License（商用限制的原始依据）",
     "https://raw.githubusercontent.com/QwenLM/Qwen-Image-2.1/main/LICENSE"),
    ("qwen-image-2.1-blog.html", "qwen.ai 官方博客（HTML 原文，便于离线查看）",
     "https://qwen.ai/blog?id=qwen-image-2.1"),
]

# 从运行中的实例导出的权威实现（尺寸/参数逻辑的唯一真相）
LOCAL_ONLY = [
    ("diffusers-pipeline_qwenimage21.py", "diffusers 管线实现 —— 尺寸推导、参数默认值、KV cache 的唯一真相"),
    ("diffusers-transformer_qwenimage21.py", "DiT 实现（32 层 single-stream，block-causal attention）"),
    ("diffusers-autoencoder_kl_qwenimage21.py", "64 通道 RGBA VAE 实现（分块解码、上采样层的显存尖峰来源）"),
]

# 上游文档里和本项目实测有差异/需要特别注意的点
NOTES = """## 各份文档该抓什么（已核对过的事实）

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
"""


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; dsh-doc-sync/1.0)",
        "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def html_to_text(html: str) -> str:
    """粗粒度去标签，够用即可（保留段落换行）。"""
    import re
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article)>", "\n", html)
    html = re.sub(r"(?i)<li[^>]*>", "· ", html)
    text = re.sub(r"(?s)<[^>]+>", "", html)
    import html as _h
    text = _h.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查本地文件是否齐全")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    print(f"目标目录: {OUT}\n")
    ok, fail = [], []
    for name, desc, url in SOURCES:
        path = os.path.join(OUT, name)
        if a.check:
            exists = os.path.exists(path)
            size = os.path.getsize(path) if exists else 0
            print(f"  {'OK ' if exists else 'MISS'} {name:44s} {size:>8d} B   {desc}")
            (ok if exists else fail).append(name)
            continue
        try:
            raw = fetch(url)
            with open(path, "wb") as fh:
                fh.write(raw)
            note = ""
            print(f"  OK   {name:44s} {len(raw):>8d} B{note}")
            ok.append(name)
        except Exception as exc:                                      # noqa: BLE001
            print(f"  FAIL {name:44s} {type(exc).__name__}: {exc}")
            fail.append(name)
        time.sleep(0.4)

    if not a.check:
        # 写一份索引，说明每份文档的用途和读取时机
        idx = os.path.join(OUT, "INDEX.md")
        with open(idx, "w", encoding="utf-8") as fh:
            fh.write("# 官方文档本地副本\n\n")
            fh.write(f"同步时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            fh.write("这些是**上游原文**。判断模型行为时以它们为准；本项目的实测结论见 "
                     "`../MEASUREMENTS.md`，两者冲突时先看这里再复测。\n\n")
            fh.write("## 联网抓取的上游文档\n\n| 文件 | 用途 |\n|---|---|\n")
            for name, desc, url in SOURCES:
                if name.endswith(".html"):
                    fh.write(f"| `{name}` | {desc}；**正文抓不到**（SPA，HTML 里没有内容），需联网看 |\n")
                else:
                    fh.write(f"| `{name}` | {desc} |\n")
            fh.write("\n## 从实例导出的权威实现（离线可读，判断参数行为看这个）\n\n")
            fh.write("| 文件 | 用途 |\n|---|---|\n")
            for name, desc in LOCAL_ONLY:
                exists = os.path.exists(os.path.join(OUT, name))
                fh.write(f"| `{name}`{' ✓' if exists else ' （缺，需重新导出）'} | {desc} |\n")
            fh.write("\n导出命令（在实例上跑）：\n\n```bash\n"
                     "bash /root/qwen-image-2.1/scripts/export_source.sh   # 见 remote/scripts/_export_source.sh\n"
                     "```\n")
            fh.write("\n## 快速抓到某个事实\n\n```bash\n")
            fh.write("# 多参考图的官方定义\n")
            fh.write("grep -n -A6 'Multiple Reference Images' qwen-image-2.1-github-README.md\n\n")
            fh.write("# 尺寸是怎么算出来的\n")
            fh.write("grep -n -B2 -A8 'calculate_dimensions' diffusers-pipeline_qwenimage21.py\n\n")
            fh.write("# 参数默认值\n")
            fh.write("grep -n 'num_inference_steps\\|true_cfg_scale\\|output_resolution\\|use_kv_cache' \\\n"
                     "  diffusers-pipeline_qwenimage21.py | head -20\n\n")
            fh.write("# 许可证是否允许商用\n")
            fh.write("grep -in 'non-commercial\\|commercial' qwen-image-2.1-LICENSE.txt | head\n")
            fh.write("```\n")
            fh.write("\n" + NOTES)
            fh.write("\n---\n\n重新同步：`python tools/sync_upstream_docs.py`\n")
        print(f"\n  索引已写: {idx}")

    print(f"\n成功 {len(ok)} 个" + (f"，失败 {len(fail)} 个: {fail}" if fail else ""))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
