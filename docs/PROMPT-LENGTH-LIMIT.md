# Prompt 长度上限实测（Qwen-Image-2.1）

> 日期：2026-09-27　实例：AutoDL 4090 48G（westc），`offload=none`，1024×1024 / 40 步
> 方法：在真实服务上逐档出图，而不是读文档猜；每档独立跑，失败后重启清上下文
> 结论：**硬上限是 DiT 位置编码表的 9216 个位置，文本 token 与参考图的 vision token 共用这一份名额**

## 1. 直接答案

| 问题 | 答案 |
|---|---|
| 官方给过长度上限吗？ | **没有**。官方 README / HF 模型卡 / 博客都没提 prompt 长度，也没给 token 上限 |
| 编码器能吃多长？ | `text_encoder.text_config.max_position_embeddings = 262144`（Qwen3-VL 文本塔），**这个不是瓶颈** |
| 实际瓶颈在哪？ | DiT 的 RoPE 频率表：`pos_index = arange(8192)` + `neg_index` 1024 条 = **9216 个位置** |
| 纯文本能写多长？ | **约 9100 token（≈ 37000 字符）通过；9200 token 越界** |
| 带一张 1024² 参考图呢？ | 视觉得占 1024 个 token，文本预算掉到 **约 8100 token（≈ 33000 字符）** |
| 越界会怎样？ | **不是报错拒绝，而是 `vectorized_gather_kernel` 越界 assert，把 CUDA 上下文弄坏**；此后连 `/health` 都 500，必须重启服务 |

## 2. 源码依据

`docs/upstream/diffusers-transformer_qwenimage21.py` L661-671：

```python
def __init__(self, theta: int, axes_dim: list[int]):
    pos_index = torch.arange(8192)
    neg_index = torch.arange(1024).flip(0) * -1 - 1
    self.freqs = [
        torch.cat([self.rope_params(pos_index, dim, theta),
                   self.rope_params(neg_index, dim, theta)], dim=0)
        for dim in axes_dim
    ]
```

表长 = 8192 + 1024 = **9216**；joint sequence（文本 + 图像 latent）的位置索引超出就 gather 越界。
这与实测边界（9100 过 / 9200 挂）一致——差的约 100 是模板与 system prompt 的固定开销。

## 3. 实测数据

### 3.1 纯文本（无参考图）

| 目标 token | 字符数 | 含模板 token | 结果 |
|---|---|---|---|
| 1000 | 4,125 | 1,033 | ✅ 23.3s |
| 4000 | 16,335 | 4,030 | ✅ 25.7s |
| 6000 | 24,475 | 6,028 | ✅ 27.6s |
| 8000 | 32,615 | 8,026 | ✅ 29.7s |
| 8500 | 34,595 | 8,512 | ✅ 30.3s |
| 8800 | 35,805 | 8,809 | ✅ 30.7s |
| 9000 | 36,685 | 9,025 | ✅ 30.8s |
| 9050 | 36,905 | 9,075 | ✅ 30.7s |
| **9100** | **37,125** | **9,122** | ✅ **30.8s（实测上限）** |
| **9200** | **37,455** | **9,222** | ❌ 越界（115s 后被 reset） |
| 16000 | 65,175 | 16,025 | ❌ 2.9s 内 500 + 上下文损坏 |

### 3.2 带一张 1024×1024 参考图

参考图的视觉 token 数是实测的，不是估的：

| 参考图边长 | vision token 数 |
|---|---|
| 512² | 256 |
| 768² | 576 |
| 1024² | **1024** |
| 1280² | 1600 |

| 文本 token | + 视觉 1024 | 合计 | 结果 |
|---|---|---|---|
| 7000 | 1024 | 8051 | ✅ 33.3s |
| 8300 | 1024 | 9346 | ❌ 越界 |

→ **文本 token 和 vision token 共用同一份 9216 名额**，不是各算各的。

### 3.3 标定：字符 → token

这份模板下 **1 token ≈ 4.075 字符**（英文散文句子重复）。中文会差很多（中文约 1 字 ≈ 1 token 量级），
所以下表只对英文有效，中文要另行量。

固定开销：system prompt 9 token，模板包装 13 token，合计 **22 token**（与用户输入长度无关）。

## 4. 越界的失效模式（这是本次最重要的发现）

越界**不会**返回 400/413 这类干净错误，而是：

```
/pytorch/aten/src/ATen/native/cuda/IndexKernelUtils.cu:16:
vectorized_gather_kernel: block: [9470,0,0], thread: [18,0,0]
Assertion `ind >=0 && ind < ind_dim_size && "vectorized gather kernel index out of bounds"` failed.
torch.AcceleratorError: CUDA error: device-side assert triggered
```

后果：

1. 该请求失败（客户端先看到连接被 reset，或 HTTP 500）；
2. **CUDA 上下文被永久污染**，之后任何请求都 500，包括免鉴权的 `/health`；
3. 只有重启服务（`serve.sh restart`）才能恢复；
4. 显存也被占住不放（实测 free 从 14 GB 掉到 1.9 GB）。

也就是说：**一个超长 prompt 会把整台服务打停**，而不是只让那一次请求失败。

## 5. 实用口径

- **安全线：合计 ≤ 9000 token。** 纯文本留出约 100 的余量给模板；带参考图时按
  `文本 token + vision token ≤ 9000` 算。
- **换算成字符（英文散文）**：
  - 无参考图：**约 36000 字符以内**
  - 一张 1024² 参考图：**约 32000 字符以内**（要再扣 1024 token）
  - 一张 2048² 参考图按面积推约 4096 vision token，文本预算掉到约 4900 token（≈ 20000 字符）——**未实测，属外推**
- **控制台/业务侧应做的事**：按 token 数算预算并在超限时**本地拒绝**，别把超长 prompt 发出去。
  目前服务端没有这个保护。
- 这个上限对正常使用**够用**：官方 PE 改写出来的 prompt 约 400-500 词（≈ 600-700 token），
  离 9216 有两个数量级。

## 6. 没测的部分（别外推）

- 中文 / 日文等非英语文本的字符→token 比例（中文通常 1 字 1 token 上下，但没实测）
- 多张参考图的 vision token 叠加（按面积线性外推，未实测）
- 其它分辨率（2048²）下的联合上限
- 官方 PE 两个 checkpoint 自身的输入长度限制（那是独立的 9B 模型，与本服务无关）

## 7. 复现

```powershell
python tools\probe_prompt_len.py --limits              # 查配置里的位置上限
python tools\_calibrate_len.py 1000 4000 8000 9100     # 标定字符↔token
python tools\_svc_sanity.py --restart                  # 体检（每档前都该先跑）
python tools\_len_boundary.py 9000 9100 9200           # 逐档找边界（失败会自动重启）
python tools\_len_withref.py 7000 8300                 # 带参考图的预算
```

产物在 `tools/_promptlen/`：`limits.txt`、`boundary.json`、`withref.json`，以及每档出的 PNG。

> 注意：`_len_boundary.py` 每跑一档失败都会重启服务，所以别在别人正用服务时跑。
