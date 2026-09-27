# 部署：从零到能出图

> 这份文档回答一件事：**把服务端（不含模型权重）装到一台新实例上，要动哪些文件、按什么顺序。**
> 模型权重是单独的一步（约 33 GB，20~40 分钟），跑 `bootstrap.sh` 会带你走完。

## 目录映射（仓库 → 实例）

仓库里的 `service/` 就是**部署载荷**，结构与实例上的 `/root/qwen-image-2.1/` 一一对应：

| 仓库 | 实例 | 作用 |
|---|---|---|
| `service/server.py` | `/root/qwen-image-2.1/service/server.py` | FastAPI 服务本体（唯一入口） |
| `service/client.py` | `.../service/client.py` | 客户端示例 |
| `service/face_fix.py` | `.../service/face_fix.py` | 人脸回贴补偿（编辑会重绘脸，用它贴回源图） |
| `service/ui/index.html` | `.../service/ui/index.html` | WebUI 控制台（单文件，无构建） |
| `service/ui/Qwen-Image-2.1-console.ipynb` | `.../service/ui/` | JupyterLab 里的排障笔记本 |
| `service/scripts/serve.sh` | `/root/qwen-image-2.1/scripts/serve.sh` | 启停：`start`/`stop`/`restart`/`status`/`fg` |
| `service/scripts/bootstrap.sh` | `.../scripts/bootstrap.sh` | 一次性环境恢复（装依赖 + 下权重 + 起服务） |
| `service/scripts/qwen_env.sh` | `/root/qwen-image-2.1/qwen_env.sh` | **环境变量集中处**（端口、key、tile_vae、offload…） |
| `service/scripts/download_model.sh` | `.../scripts/download_model.sh` | 下权重（`ms` 走 ModelScope） |
| `service/scripts/download_anatomy_model.sh` | `.../scripts/download_anatomy_model.sh` | 下人体复检小模型（可选功能，走 ModelScope + 逐个文件核对大小） |
| `service/scripts/watch_download.sh` | `.../scripts/watch_download.sh` | 下载看门狗，断流续传 |
| `service/scripts/show_url.sh` | `.../scripts/show_url.sh` | 打印公网入口与自测命令 |
| `service/scripts/export_source.sh` | `.../scripts/export_source.sh` | 导出实例上的源码快照 |
| `service/scripts/bench.py` | `.../scripts/bench.py` | 跑分 |
| `service/scripts/inspect_ckpt.py` | `.../scripts/inspect_ckpt.py` | 检查权重完整性 |
| `service/scripts/qwen-image.service` | `.../scripts/qwen-image.service` | systemd 单元（可选，AutoDL 上一般不注册） |

实例上还有几个目录由脚本自己建：`logs/`、`outputs/`、`inputs/`。

> **路径是写死的**：`serve.sh` 里 `source /root/qwen-image-2.1/qwen_env.sh`，
> `bootstrap.sh` 里 `R=/root/qwen-image-2.1`。想换安装位置得改这两个脚本。

## 依赖（没有 requirements.txt，都写在 bootstrap.sh 里）

```bash
pip install -U "transformers>=5.17" accelerate safetensors hf_transfer sentencepiece pillow \
    fastapi "uvicorn[standard]" python-multipart requests modelscope num2words
```

关键点：
- **`python-multipart` 必须装**，否则 multipart 请求全 400（上传参考图就是走这条路）。
- **`num2words`** 是可选的人体复检模型（`anatomy_check`）要的：SmolVLM2 的 processor
  会直接 `ImportError`。不用那个功能也建议装上，省得第一次开检测时炸。
- `diffusers` 得是带 `QwenImage21Pipeline` 的版本，`bootstrap.sh` 会自动验证：
  `python -c "from diffusers import QwenImage21Pipeline"`。
- torch 用镜像自带的 CUDA 版，不要重装。

### 可选：人体复检小模型（8.6 GB，不装也能跑服务）

```bash
bash /root/qwen-image-2.1/scripts/download_anatomy_model.sh      # 走 ModelScope，约 15 分钟
# 然后把服务指向本地目录（**只追加进 qwen_env.sh，别整文件覆盖**）：
echo 'export QWEN_ANATOMY_MODEL=/root/autodl-tmp/models/SmolVLM2-2.2B-Instruct' >> /root/qwen-image-2.1/qwen_env.sh
bash /root/qwen-image-2.1/scripts/serve.sh restart
```

不给绝对路径、只给仓库 id 的话，transformers 会去 HF 拉这 8.6 GB —— 同一分片实测
HF 直连 0.21 MB/s、hf-mirror 1.9 MB/s、ModelScope 9.5 MB/s，走 HF 会卡到怀疑人生。

## 三步部署

```bash
# 1) 传服务端（不含权重）。在本地仓库根目录：
python tools/deploy_service.py --host <你的实例域名> --port <端口> --password <密码>
#    或把凭据放进 git-ignored 的 tools/autodl.env，然后：python tools/deploy_service.py

# 2) 实例上装依赖 + 下权重 + 起服务（幂等，可重复跑）
ssh -p <端口> root@<实例域名> 'bash /root/qwen-image-2.1/scripts/bootstrap.sh'

# 3) 自测
curl -s localhost:6006/health | head -c 300
bash /root/qwen-image-2.1/scripts/show_url.sh     # 打印公网入口
```

## 必须知道的部署期细节

1. **`QWEN_TILE_VAE=1` 是硬需求**，不是可选优化。不开的话 2048² 会崩在 VAE 上采样层。
   `qwen_env.sh` 与 `serve.sh` 里都设了默认 1 —— 所以**别绕过 serve.sh 直接
   `python service/server.py`**，那样只会拿到 serve.sh 之外的默认值。
2. **key 是占位符**：仓库里的 `service/scripts/qwen_env.sh` 写的是 `CHANGE_ME`，
   实例上那份才是真值。部署时如果直接覆盖，会把自己的 key 换成占位符导致 401 ——
   `tools/deploy_service.py` 默认**跳过已存在的 qwen_env.sh**，要覆盖得显式加 `--force-env`。
3. **不装 systemd 单元**也行。AutoDL 重启后跑 `bash scripts/serve.sh start` 即可；
   `qwen-image.service` 只是给"有 systemd 的常规机器"备的。
4. **权重不在服务端里**：`/root/autodl-tmp/Qwen-Image-2.1`（33 GB）是独立的一步，
   换机/分享镜像后必须重下（`bootstrap.sh` 会检测并触发）。

## 对账

```bash
python tools/check_deploy.py
```

逐文件比 md5，输出「一致 / 不一致 / 本地缺 / 远端无」。
换机后、改完服务端后、以及怀疑"实例上跑的不是仓库里这版"时，先跑这个。

## 本轮清掉的一个坑

`remote/scripts/` 里曾经存着一份**陈旧的部署脚本副本**（`serve.sh`、`qwen_env.sh`、
`bootstrap.sh`、`show_url.sh` 等），与 `service/` 里的权威版不一致 —— 典型症状是
`QWEN_TILE_VAE` 默认值还是 0、启动横幅不打印鉴权状态。同一个东西两份、还差一截，
早晚会有人同步错方向。现在：

- **`service/` 是唯一权威**，结构与实例一致，一条命令可整树同步；
- `remote/scripts/` 只留实例上跑的一次性脚本（`_*.sh` 探测/测试用），不再放部署件。
