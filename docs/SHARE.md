# 镜像保存与分享

给 AutoDL 做镜像、分享给别人用的完整说明。**先看第 1 节 —— key 泄露的坑必须先堵上。**

---

## 1. 分享前必做：把 key 模式改成 auto

**不这么做的话，分享出去的镜像等于敞开大门**：控制台页面会把 key 渲染进 HTML，
谁打开页面谁就拿到 key，鉴权形同虚设。

| `QWEN_UI_KEY` | 行为 | 该用在哪 |
|---|---|---|
| `inject` | key 渲染进页面、自动填好（排障用） | **只有自己用**。打开页面 = 拿到 key |
| `auto` | 不注入；浏览器走**登录 → HttpOnly Cookie 会话** | **分享镜像 / 给别人用** ← 用这个 |
| `off` | 页面按无鉴权工作（要求 `QWEN_API_KEY` 也为空） | 明确不要鉴权时 |

`auto` 模式下页面 HTML 里**没有任何 key 明文**，key 只在登录那一次请求里出现，
之后浏览器靠 HttpOnly + SameSite=strict + Secure 的 Cookie（服务端可随时 `DELETE /v1/session` 作废）。
**注意**：这不等于"安全"—— 拿到 key 的人照样能一直用（没有配额控制），
而且能进 JupyterLab 的人可以读到 `qwen_env.sh`（里面有 key）。所以「分享给谁」要控制。

镜像里默认已经是 `auto`，确认一遍：

```bash
grep -E '^export QWEN_API_KEY|^export QWEN_UI_KEY' /root/qwen-image-2.1/qwen_env.sh
bash /root/qwen-image-2.1/scripts/serve.sh status     # 会打印当前 key 模式
```

**打镜像前建议换掉你自己在用的 key**（否则你私用的 key 会随镜像分发出去）。
不用一步到位 —— 旧 key 可以先留在 `QWEN_API_KEYS` 里做过渡，两边都能用：

```bash
NEW=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 24)
sed -i "s|^export QWEN_API_KEY=.*|export QWEN_API_KEY=\${QWEN_API_KEY:-$NEW}|" /root/qwen-image-2.1/qwen_env.sh
bash /root/qwen-image-2.1/scripts/serve.sh restart
echo "镜像内置 key（单独告诉使用者，别写进镜像说明）: $NEW"
```

`QWEN_API_KEYS` 里的旧 key 在过渡期结束后记得删掉：

```bash
sed -i 's|^export QWEN_API_KEYS=.*|export QWEN_API_KEYS=|' /root/qwen-image-2.1/qwen_env.sh
bash /root/qwen-image-2.1/scripts/serve.sh restart
```

用的人打开控制台会被**问一次 key**（之后浏览器记住）。把 key 单独发给他，
**不要**和镜像地址写在同一个地方。

> **当前没做**的防护：key 轮换、IP 白名单、请求速率限制/配额。
> 拿到 key 的人可以一直刷。公网地址只适合小圈子自用；要开放给不特定的人，得先补配额控制。

**JupyterLab 那侧也要注意**：Jupyter 有自己的 token（`/root/.jupyter`… 实际在
`/init/jupyter/jupyter_config.py` 的 `ServerApp.token`），没 token 访问 API 会 403。
但这个 token 也是平台自动生成的——如果使用者能进 JupyterLab，他就能看代码和 outputs，
也能读到 `qwen_env.sh`（**里面有 key**）。所以「分享给谁」这件事本身要控制，别公开发地址。

---

## 2. 另一个关键点：数据盘不进镜像

AutoDL 的镜像**只包含系统盘 `/`**，不包含数据盘 `/root/autodl-tmp`。

本实例的情况：

| 位置 | 内容 | 大小 | 进镜像？ |
|---|---|---|---|
| `/`（系统盘） | `/root/miniconda3` 及全部依赖、`/root/qwen-image-2.1` 代码 | 601 MB 已用（上限 30 GB） | ✅ 进 |
| `/root/autodl-tmp/Qwen-Image-2.1` | **模型权重 33 GB** | 31 GB 已用 | ❌ **不进** |

也就是说：**别人用你的镜像开新实例，第一次开机必须重新下载 33 GB 权重**（约 20~40 分钟）。
这不是缺陷，是平台的存储模型决定的；把 33 GB 塞进系统盘也不现实（系统盘只有 30 GB）。

好消息是这一步已经自动化了：

```bash
bash /root/qwen-image-2.1/scripts/bootstrap.sh
```

它会依次做：报环境信息 → 查/补依赖 → **查权重，缺了自动下载** → 起服务并等待就绪 → 打印入口。
分享时把这条命令写在说明里即可。

> 想彻底免下载：把权重放公网网盘（阿里云盘/百度网盘），让使用者用 AutoPanel 转存下载；
> 或者你自己在数据盘之外提供一个内网/对象存储地址。脚本里的 `download_model.sh` 支持换成
> `hf` 路线（`bash download_model.sh hf`，需学术加速）。

---

## 2. 保存镜像的步骤（在 AutoDL 控制台操作）

1. **先把论文/图片收好**：镜像不保存 `/root/autodl-tmp`，但会保存 `/root/qwen-image-2.1`
   （代码、日志、`outputs/` 里的出图都在系统盘上，会进镜像）。
2. **关掉在跑的服务**（避免把运行时状态固化进去，也让镜像小一点）：
   ```bash
   bash /root/qwen-image-2.1/scripts/serve.sh stop
   ```
3. **清理可再生的东西**（可选，省镜像体积）：
   ```bash
   rm -rf /root/.cache/pip           # 83 MB
   find /root/qwen-image-2.1/logs -name '*.log' -size +1M -delete
   rm -rf /root/qwen-image-2.1/service/__pycache__ /root/qwen-image-2.1/**/__pycache__
   ```
4. 控制台 →「容器实例」→ 更多 → **保存镜像** → 起个名字（如 `qwen-image-2.1-chat`）→ 等完成。
5. 之后在「我的镜像」里，可以：
   - 用它新建实例（自己用）
   - 点**分享**生成镜像码/链接，别人凭这个也能创建实例

> 保存镜像时实例需要处于关机状态（平台会提示）。建议先在控制台把实例关机，再保存。
> 保存镜像的过程与实例计费无关，但时间会长一点（几百 MB 到几 GB）。

---

## 3. 拿到镜像的人怎么用（把这段直接发给对方）

### 3.1 开机前

- 选**任意有多余显存的 48G 卡**（4090-48G / A40 48G 等）。24G 卡塞不下全 BF16，
  需要改 `QWEN_OFFLOAD=model` 走 CPU offload，会明显变慢。
- 镜像选你分享的那个。
- 数据盘留 **≥ 60 GB**（要放 33 GB 权重 + 出图）。

### 3.2 开机后一条命令

```bash
bash /root/qwen-image-2.1/scripts/bootstrap.sh
```

第一次会下载 33 GB 权重（20~40 分钟），之后每次开机只需几秒（权重留在数据盘上）。

### 3.3 打开界面

- **JupyterLab**（控制台点按钮）→ 左侧进 `qwen-image-2.1/service/ui/`
  → 打开 `Qwen-Image-2.1-console.ipynb` → 里面有启动服务、看输出、API 速查、端口说明
- **浏览器控制台**：控制台「自定义服务」里复制 `https://<实例id>-<hash>.<区域>.seetacloud.com:8443`
  直接打开，就是画图界面（**API Key 自动填好**）

### 3.4 端口一览

| 端口 | 用途 |
|---|---|
| **6006** | Qwen-Image-2.1 服务：WebUI 控制台 + REST API（AutoDL 自动映射到公网） |
| 8888 | JupyterLab（`base_url=/jupyter/`，反代规律 `/jupyter/proxy/<端口>/`） |
| 6007 | 镜像自带 TensorBoard，本项目未使用 |
| 6008 | 备用映射端口，当前空闲 |

### 3.5 鉴权

默认是镜像里预设的一串随机 key（见 `/root/qwen-image-2.1/qwen_env.sh` 的 `QWEN_API_KEY`）。
`/v1/*`、`/docs`、`/openapi.json` 需要 key：`Authorization: Bearer <你的KEY>` 或 `?key=<你的KEY>`；
`/` 控制台与 `/health` 免鉴权。

**建议对方改成自己的 key**（公网地址暴露时尤其重要）：

```bash
sed -i 's/^export QWEN_API_KEY=.*/export QWEN_API_KEY=换个随机串/' /root/qwen-image-2.1/qwen_env.sh
bash /root/qwen-image-2.1/scripts/serve.sh restart
```

---

## 4. 性能参考（供对方估算）

| 场景 | 耗时 | 显存 |
|---|---|---|
| 512×512 / 8 步 | ~1.8 s | — |
| 1024×1024 / 20~25 步 | 11~14 s（约 0.50 s/步） | 峰值 36.8 GiB |
| 2048×2048 / 40 步 | ~115 s | 峰值 32.5 GiB（**必须开分块 VAE**） |
| 图像编辑 1 张参考图 / 30~35 步 | 21~24 s | 峰值 38.8 GiB |

权重常驻 30.2 GiB；`serve.sh` 已默认带 `QWEN_TILE_VAE=1` 与
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`，别删。

---

## 5. 常见坑（本机实测踩过的）

1. **2048² 不开分块 VAE 会 OOM**，崩在 VAE 上采样层（不是 DiT）。
2. **编辑接口不吃 `width`/`height`**，真正的旋钮是 `output_resolution`。
3. **窗口版 Windows 的 OpenSSH 与远端 8.9 公钥签名不兼容**（key 被接受但验签失败），
   所以本机隧道用 `tunnel_serve.py`（paramiko）而不是 `ssh -i`。
4. **服务重启后要重新起**：实例重启不会自动拉起服务，`bootstrap.sh` 或 `serve.sh start` 都要手动跑一次。
5. **长跑后显存被缓存攥住**：调一次 `POST /v1/admin/empty_cache` 能还回来十几 GB。
