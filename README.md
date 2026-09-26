# qwen-image-2.1-tools

Qwen-Image-2.1（7B DiT + Qwen3-VL 8B 编码器 + RGBA VAE）在 AutoDL 上的部署、封装与能力实测工具箱。
所有结论都是在**真实机器 + 真实权重**上跑出来的，不是估算表。

```
2026-09-26 起   AutoDL 西部 B 区 · RTX 4090 48G（魔改，单卡，sm_89）
镜像           PyTorch 2.8.0 + cu128 + Python 3.12.3
权重           /root/autodl-tmp/Qwen-Image-2.1  共 33.13 GB
依赖           transformers 5.17.0 · diffusers 0.41.0.dev0(git main) · accelerate 1.15.0
```

---

## 目录结构

| 目录 | 内容 |
|---|---|
| `docs/` | **[docs/README.md](docs/README.md) 总说明** · [API.md](docs/API.md) 接口定义 · [MEASUREMENTS.md](docs/MEASUREMENTS.md) 全部实测数据 · [SHARE.md](docs/SHARE.md) **镜像保存与分享** · [CASE-dress-shell.md](docs/CASE-dress-shell.md) 专项案例 · [CHANGELOG.md](docs/CHANGELOG.md) 改动记录 |
| `docs/upstream/` | **官方文档本地副本**（GitHub README / HF 模型卡 / ModelScope / LICENSE / diffusers 管线源码），索引见 [docs/upstream/INDEX.md](docs/upstream/INDEX.md)。同步：`python tools/sync_upstream_docs.py` |
| `service/` | `server.py` HTTP 服务 · `client.py` 调试客户端 · `face_fix.py` 人脸回贴 · `bench.py` 跑分 · `inspect_ckpt.py` 权重校验 · `qwen_env.sh` 环境变量 |
| `remote/scripts/` | 在实例上用的运维脚本：`serve.sh` 启停 · `download_model.sh` 下权重 · `bootstrap.sh` 一键恢复 · `watch_download.sh` 断流续传 · 以及部署期用过的一次性探测脚本（`_*.sh`） |
| `tools/` | 测试与报告生成脚本（本机跑，经 SSH 隧道调用远端服务） |
| `test-data/` | 全部测试产物：输入图、每轮输出、量化 JSON、接触表 |
| `reports/` | 生成的 HTML 报告（单文件、图片内嵌，可直接外发） |

---

## 快速开始

```bash
# 1. 起隧道（把远端 6006 映射到本地 16008）
python tools/run_tunnel.py <某个测试脚本>.py

# 2. 或者直接看服务状态
python tools/autodl_ssh.py health          # 读 tools/autodl.env 里的实例信息
python tools/autodl_ssh.py run "nvidia-smi"
```

服务端（实例内）：

```bash
source /root/qwen-image-2.1/qwen_env.sh
bash /root/qwen-image-2.1/scripts/serve.sh start
curl -s localhost:6006/health | python -m json.tool
```

---

## 已经跑出来的核心结论

1. **能跑，24s/张（35 步，832×1248）**；1024×1024/20 步只要 10.9s，2048×2048/40 步 115.3s。
   **2048² 必须开分块 VAE 解码**（`QWEN_TILE_VAE=1`），否则在 VAE 上采样层 OOM。
2. **每一步编辑都会重绘整张图，包括脸。** 只改姿势的那一步，人脸区域漂移 0.180 ≈ 整图漂移 0.177；
   提示词里写 KEEP 段落（长句 vs 清单式）数值几乎逐位重合——**措辞锁不住人脸**。
   空指令基线（"什么都别改"）与输入图的 MAD 也有 0.104，说明"重绘"是这个模型的默认行为。
3. **人脸只能靠链路之外补**：`service/face_fix.py` 把源图人脸按羽化椭圆贴回，7 个样本全部改善
   0.029~0.044。但**自动定位人脸不可行**（Haar/模板匹配/肤色连通域三种方案实测全败），
   报告里给了一个浏览器内拖拽框选的手动对齐工具。
4. **指令响应有明确的强弱分层**（见 `reports/matrix-report.html`）：
   - 可靠：背景替换、服装换色/改款、整体画风、姿势改造、多指令叠加
   - 不可靠：表情（笑/哭两张图互相只差 0.004）、单个道具增删、照片写实化
5. **编辑输出尺寸被钉在 1MP 档位**（832×1248 / 1056×1568），真正的旋钮是管线参数
   `output_resolution`；提高它只是让耗时翻倍，不改善保真度。
6. **参考图引用有官方语法：`<image1>` / `<image2>` …**，编号 = `image` 参数的上传顺序。
   管线会把这些占位符真的写进文本编码器的 prompt（`prompt_template_ti2i`），
   官方多人物示例（`prompt_rewrite/data/edit_example.jsonl`）用的就是这个写法。
   受控实验显示：**不点名时两个主体会被融成一个，点名后正确分开**。
   详见 [docs/EXPERIMENT-ref-syntax.md](docs/EXPERIMENT-ref-syntax.md)。
   WebUI 上传参考图后，缩略图下方会出现 `<image1>`/`<image2>` 按钮，点一下插到 prompt 光标处。

细节和原始数据见 `docs/MEASUREMENTS.md`，逐步骤图文对比见 `reports/` 下的 HTML。

---

## 文档索引

- [docs/README.md](docs/README.md) —— 环境怎么建的、服务怎么起、测试怎么跑
- [docs/API.md](docs/API.md) —— HTTP 接口完整定义（含错误码、环境变量、上游对接片段）
- [docs/EXPERIMENT-ref-syntax.md](docs/EXPERIMENT-ref-syntax.md) —— 参考图 `<imageN>` 引用语法：源码依据 + 受控实验
- [docs/UI-AUDIT.md](docs/UI-AUDIT.md) —— WebUI 说明文案与参数选项逐项核查
- [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) —— 性能表、显存账、每一轮实验的数据与结论
- [docs/CHANGELOG.md](docs/CHANGELOG.md) —— 脚本目录调整、修过的 bug、接口变更
- `reports/matrix-report.html` —— 指令响应矩阵报告
- `test-data/report.html` —— 人脸补偿 + 表情专项分步对比报告

> `test-data/`、`reports/`、`tmp_refs/` 里是约 300 MB 的实验产物，**没有进仓库**（见 `.gitignore`）。
> 需要图就照 `docs/MEASUREMENTS.md` 里的命令重跑，或自己留着本地副本。
