# Qwen-Image-2.1 工具箱 · 使用说明

本目录是对 Qwen-Image-2.1 在 AutoDL 单卡 48G 环境下的部署、服务化与能力实测记录。
工程侧从零搭建到跑通，全部结论都有原始数据和产物可追溯。

---

## 一、环境是怎么建起来的

### 1.1 机器与镜像

| 项 | 值 |
|---|---|
| 实例 | `ssh -p <端口> root@connect.<区域>.seetacloud.com`（凭据见 `tools/autodl.env`） |
| GPU | RTX 4090 48G（魔改，单卡，无 NVLink，sm_89，驱动 595.71.05） |
| 镜像 | PyTorch 2.8.0 + cu128 + Python 3.12.3，conda 在 `/root/miniconda3` |
| 系统盘 | 30 GB（只放依赖，够用） |
| 数据盘 | `/root/autodl-tmp` 100 GB（放权重 33 GB，余 70 GB） |

> **无卡模式**下 `/dev/nvidia*` 不存在，`torch.cuda.is_available()` 为 False；服务会自动判定成
> mock 模式（`QWEN_MODE=auto` 的默认行为），只验证接口契约，不碰 GPU。
> 无卡模式下**不能**在同一台机器上跑 `bench.py`（它要独占整张卡）。

### 1.2 依赖

镜像自带的 torch 不动，只补上层：

```bash
source /etc/network_turbo                 # GitHub / HuggingFace 走代理才通
pip install -U "transformers>=5.17" accelerate safetensors hf_transfer \
    sentencepiece pillow fastapi "uvicorn[standard]" python-multipart requests modelscope
pip install git+https://github.com/huggingface/diffusers.git    # QwenImage21Pipeline 在 main 上
```

装完自检：

```bash
python -c "from diffusers import QwenImage21Pipeline; print('pipeline OK')"
```

### 1.3 权重下载（33.13 GB）

HF 直连只有 24 KB/s，hf-mirror 同样 24 KB/s，**ModelScope 单点 12~34 MB/s**，所以走 ModelScope：

```bash
python -c "from modelscope import snapshot_download; \
  snapshot_download('Qwen/Qwen-Image-2.1', local_dir='/root/autodl-tmp/Qwen-Image-2.1', max_workers=16)"
```

坑：ModelScope 的续传是**整文件粒度**的，中途断流会从 0 重下那个分片。
`remote/scripts/watch_download.sh` 是看门狗，掉线自动重拉。

---

## 二、服务怎么起

**方式一：JupyterLab 点鼠标（推荐）**

实例上放了笔记本 `/root/qwen-image-2.1/service/ui/Qwen-Image-2.1-控制台.ipynb`。
JupyterLab 左侧文件树进 `qwen-image-2.1/service/ui/` 打开它，按顺序点：

1. 第 1 格：`ACTION = "start"` 然后运行 → 启动服务（约 1~2 分钟灌权重），状态自动显示
2. 第 2 格：点链接打开 WebUI（走 `/jupyter/proxy/6006/`，key 自动填好）
3. 第 4 格：预览 `outputs/` 里的出图
4. 第 8 格：**API 速查 + 端口一览**（不用翻文档）

按钮在某些 JupyterLab 版本不灵，所以每个功能都有"改 ACTION 再运行"的稳定入口，
不依赖按钮也能用。

**方式二：命令行**

```bash
# 实例内
source /root/qwen-image-2.1/qwen_env.sh
bash /root/qwen-image-2.1/scripts/serve.sh start     # 后台启动，默认 6006 端口
bash /root/qwen-image-2.1/scripts/serve.sh status    # 看进程 + /health
bash /root/qwen-image-2.1/scripts/show_url.sh        # 打印公网入口 + 端口自测
curl -s localhost:6006/health | python -m json.tool
```

`serve.sh` 已经带上两个必需项：
- `QWEN_TILE_VAE=1` —— 2K 出图必须分块 VAE 解码，否则崩在 VAE 上采样层
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` —— 缓解碎片化 OOM

`QWEN_PRELOAD=1`（默认）会在启动时把 33 GB 权重灌进显存，约 2 分钟，之后首个请求就是正常速度。

### 对外接入

服务监听 `0.0.0.0:6006`。三种接法：

1. **AutoDL 自定义服务**：控制台复制 `https://<实例ID>-<hash>.<区域>.seetacloud.com:8443`，
   给其他机器调用用这个（6006 端口自带公网映射）。
2. **同实例内**：`http://127.0.0.1:6006`。
3. **SSH 隧道**（本地开发）：`ssh -p <端口> -L 16006:127.0.0.1:6006 root@<域名> -N`，
   然后打 `http://127.0.0.1:16006`。本目录的 `tools/run_tunnel.py` 会自动起这个转发。

接口定义见 [API.md](API.md)。

#### 浏览器控制台（WebUI）

同一个 6006 端口上还挂了一个单页控制台，**根路径就是**：

| 地址 | 说明 |
|---|---|
| `https://<实例ID>.westb.seetacloud.com:8443/` | **本实例当前公网入口**，浏览器直接开 |
| `https://<端口6008前缀>-<实例ID>.westb.seetacloud.com:8443/` | 备用端口 6008 的映射，指向同一个容器 |
| `http://127.0.0.1:6006/` | 实例内部 |
| `http://127.0.0.1:16006/` | 走 SSH 隧道时 |

公网域名不用去控制台翻，平台把它写在容器里，打印即可：

```bash
bash /root/qwen-image-2.1/scripts/show_url.sh
```

实测（2026-09-26）经公网入口：`/` 17690 字节、`/health` 258ms、`/docs`、`/v1/models` 全 200。

功能：文生图 / 图像编辑两个模式切换、prompt、宽高与官方宽高比档位、步数滑杆、seed、
透明 RGBA、异步排队开关、编辑专用的 `output_resolution`；右侧显示耗时 / 尺寸 / seed / 峰值显存，
支持下载、复用参数、本次会话历史（缩略图可点开）。页面纯静态（`service/ui/index.html`），
没有构建步骤，也不依赖 Gradio。

**鉴权**：服务启用了 `QWEN_API_KEY`（本实例 `<你的KEY>`）。`/v1/*`、`/docs`、`/openapi.json`
需要 key（`Authorization: Bearer <你的KEY>` 或 `?key=<你的KEY>`）；`/` 控制台与 `/health` 放行。
**控制台会把 key 自动填进「API Key」输入框**，打开页面直接就能用，不用手输。
换 key 只改服务端 `QWEN_API_KEY` 再重启，页面自动同步。

#### 从自己电脑访问（SSH 隧道）

桌面上有个快捷方式 **「Qwen 控制台」**，双击即可：

1. 在本机 `16006` 端口建立到实例的 SSH 隧道
2. 自动打开浏览器到 `http://127.0.0.1:16006/`

关闭那个黑窗口 = 断开隧道。也可以直接双击：

```
D:\workspace\dsh-default\qwen-image-2.1-tools\tools\qwen-tunnel.bat
```

命令行等价物：

```powershell
cd D:\workspace\dsh-default\qwen-image-2.1-tools\tools
python tunnel_serve.py                       # 读同目录 tunnel.conf
python tunnel_serve.py --local-port 16006    # 也可以覆盖参数
```

**为什么用密码而不是密钥**：Windows 自带的 OpenSSH 9.5 与远端 OpenSSH 8.9 在
`publickey-hostbound-v00` 扩展签名上不兼容——服务端会打印 `Server accepts key`，
但随后验签失败（ed25519 和 RSA 都试过，症状一致）。`tunnel_serve.py` 走 paramiko
密码通道，实测稳定。若哪天要改成密钥，把私钥路径写进 `tunnel.conf` 的 `key=` 即可。

自检脚本（会开隧道 + 无头浏览器真跑一次出图，并留下截图）：

```bash
python tools/webui_check.py --steps 12 --size 1024     # 端到端验证
python tools/tunnel_test.py                            # 只验证隧道链路
python tools/webui_shot.py --out reports/webui-preview.png   # 只截图
```

截图见 `reports/webui-preview.png`（隧道）、`reports/webui-tunnel.png`（隧道渲染）、
`reports/webui-public.png`（公网地址）。

---

## 三、测试怎么跑

所有测试脚本都用同一个模式：**本地跑脚本，经 SSH 隧道调远端服务**。

```bash
cd qwen-image-2.1-tools
python tools/run_tunnel.py matrix_test.py        # 指令响应矩阵（约 6.5 分钟）
python tools/run_tunnel.py qwen_chain.py         # 四步编辑链 + 漂移量化
python tools/run_tunnel.py qwen_anchor_test.py   # 身份锚定对照实验
python tools/run_tunnel.py qwen_pose_test.py     # 姿势变体 + 多 seed
python tools/matrix_report.py                    # 由结果出 HTML 报告
python tools/qwen_report.py                      # 人脸补偿 + 表情专项报告
```

`tools/autodl_ssh.py` 是底层 SSH 封装（凭据读 `tools/autodl.env`）：

```bash
python tools/autodl_ssh.py health                 # 服务状态 + GPU + 日志尾部
python tools/autodl_ssh.py run "nvidia-smi"       # 远端执行命令
python tools/autodl_ssh.py fwd <本地脚本.py>       # 起转发并跑脚本（run_tunnel 的前身）
```

### 脚本清单

| 脚本 | 作用 |
|---|---|
| `matrix_test.py` | 16 条指令的响应矩阵（姿势/服装/背景/物体/表情/头部/画风/多指令） |
| `matrix_report.py` | 矩阵结果 → HTML 报告 + 接触表 |
| `qwen_chain.py` | 四步编辑链，逐步量化 SSIM 与人脸漂移 |
| `qwen_anchor_test.py` | 单参考图 vs 原图锚定 vs 提高 output_resolution 的对照 |
| `qwen_pose_test.py` | 姿势提示词 × 多 seed |
| `qwen_facefix_test.py` | 人脸回贴补偿前后量化 |
| `qwen_facefix_diag.py` | 画框可视化：源图脸框 / 检出的脸框 / 实际贴回位置 |
| `qwen_facefix_sanity.py` | 自检：贴回后中心区域应与源图逐像素相等 |
| `qwen_skin_probe.py` | 肤色连通域定位人脸（失败方案留档） |
| `qwen_template_probe.py` | 多种模板匹配度量对比（失败方案留档） |
| `qwen_report.py` | 跑表情专项 + 出综合 HTML 报告（含浏览器内手动对齐工具） |
| `qwen_nsfw_test.py` | 姿势阶梯测试（露出度递增，用于定位模型的失效边界） |

---

## 四、目录约定

- **测试产物一律进 `test-data/`**，不要散落在工作区其他地方。
- 新脚本放 `tools/`，用 `import config as C` 取路径（`C.TEST_DATA` / `C.INPUT_EDIT` / `C.REPORT` / `C.REGIONS`）。
- 给实例用的 shell 脚本放 `remote/scripts/`。
- HTML 报告放 `reports/`，保持单文件自包含（图片 base64 内嵌），方便外发。
- 命名：`<阶段>_<对象>_<变体>.png`，例如 `poseA_thighs_open_11.png`、`nsfw_L1_open_pose.png`。

---

## 五、踩过的坑（给后来的自己）

1. **`nohup … &` 之后立刻 `python -c "import torch"` 会拿到未初始化的 CUDA**，判定 GPU 可用性要在服务进程里做，不在探测脚本里做。
2. **`torch.cuda.mem_get_info()` 的 free 值受缓存分配器影响**：长跑的服务进程会攥住十几 GB 不放，
   显存预检必须在 `empty_cache()` **之后**做，否则会把正常请求误判成 OOM。
3. **显存预检不能把常驻权重算进"需要多少"**，权重已经在显存里了。第一版预检就是这么写的，
   导致所有 1024 请求被误判 507。
4. **`diffusers` 0.41 把 `torch_dtype` 改名成 `dtype`**，但 `from_pretrained` 的签名里两个都不认
   （走的是 `**kwargs`），所以不能靠签名探测，直接用 `torch_dtype` 即可（会打 FutureWarning，无害）。
5. **Haar 人脸检测在 anime 上没有意义**，会把人体的任何部分和背景花丛当成脸。
6. **`json.dump` 默认用系统编码**，在中文 Windows 上是 GBK，写中文会崩；所有 JSON 落盘都显式 `encoding="utf-8"`。
7. **PowerShell 里 `export PATH=...; cmd` 这种内联 bash 会被吃引号**，一律改成写临时脚本再 `bash 跑`。
