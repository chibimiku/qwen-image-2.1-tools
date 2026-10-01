# 开机自启：实例重启后服务自己起来

**结论先说**：AutoDL 这台机器上 **systemd 用不了**（PID 1 是 `bash /init/boot/boot.sh`），
所以自启挂在 AutoDL 官方的 `/init/bin/customer.cmd.sh` 上，脚本本体放**持久盘**
`/root/autodl-tmp/`。已验证两条链路各自可用、并发触发不重复起实例。

---

## 一、这台机的启动机制（实测）

| 事实 | 证据 |
|---|---|
| PID 1 是 bash，不是 systemd | `readlink -f /proc/1/exe` → `/usr/bin/bash`；`systemctl is-system-running` → `offline` |
| systemd 装了但没在跑 | `systemctl status` → `System has not been booted with systemd as init system` |
| 没有 `/etc/rc.local` | 不存在 |
| AutoDL 的注入点是 `/init/bin/customer.cmd.sh` | 它每次启动执行 `bash /etc/autodl.sh` |
| `/etc/autodl.sh` 一直是空的 | `/tmp/autodl.sh.log` 里留着 `bash: /etc/autodl.sh: No such file or directory` |

> **所以别照抄"写个 systemd unit"这种通用做法** —— 在这台机上它永远不会被调用。

### 持久化边界（决定脚本放哪）

```
/init                → /dev/md0（持久）  ← AutoDL 每次重建会由镜像还原
/root/autodl-tmp     → /dev/md0（持久）  ← 放这里
/                    → overlay 上层      ← 容器重建即丢
  /etc、/root、/usr 都在 overlay 上
```

实测：09-27 装好的服务，10-01 容器重建后 `/etc` 与 `/init` 的时间戳全部刷新，
但 `/root/autodl-tmp` 里的权重（33 GB）完好。

**推论**：脚本必须住 `/root/autodl-tmp`；`/init` 侧只留一行引导 —— 它是镜像还原的，
丢了用 `--install` 重贴即可。

---

## 二、调用链

```
容器启动
  └─ /init/bin/customer.cmd.sh        （AutoDL 提供，镜像每次还原）
       └─ /root/autodl-tmp/autostart/qwen-autostart.sh   （持久盘，自己维护）
            └─ /root/qwen-image-2.1/scripts/serve.sh start

退路（任何 shell 都触发一次，脚本内部幂等）
  └─ /root/.bashrc 里的一行
```

挂上之后 `customer.cmd.sh` 的尾部就是：

```bash
# --- qwen-autostart ---
bash /root/autodl-tmp/autostart/qwen-autostart.sh >/dev/null 2>&1   # qwen-autostart
```

---

## 三、判断链（顺序不能换）

```
1. /health 返回 ok            → 有人在正常服务，直接退出，绝不抢
2. pidfile 指向的进程还在     → 大概率正在加载权重（要十几秒）
                                给它 180s 宽限期；就绪就退出；
                                到期仍不就绪也**不动它**（宁可少起，不可起两个抢显存）
3. pidfile 是陈旧的           → 清掉，往下走
4. houseclean：清残留进程 + 等显存真正释放
5. serve.sh start
```

第 2、4 步都是**踩出来的**，不是设计时想到的，见下一节。

---

## 四、跑测试才发现的四个坑

### 1. `serve.sh stop` 不等待 → 起新实例必撞车

`serve.sh` 的 stop 是 `kill`（SIGTERM）后**立刻返回**，但常驻 33 GB 权重的进程
要**几秒到几十秒**才真正退出。此时起新的，日志里就是：

```
ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 6006): address already in use
[startup] preload failed: OutOfMemoryError ... Process 11145 has 19.70 GiB memory in use
```

最后留下一个 "活着但 `loaded:false`" 的僵尸服务，pidfile 还指向早就死掉的 pid。

→ 加了 `houseclean()`：起之前先清掉残留的 server.py、等显存真的放掉（free ≥ 30 GB）。

### 2. 陈旧 pidfile 会静默掐死自启

服务 OOM 挂掉后 pidfile 还在，`serve.sh` 认为 "already running" 直接退出 ——
**自启就此失效，而且不报错**。

→ 起之前检查 pidfile 指向的进程是否还在，不在就清掉。

### 3. 清 pidfile 需要宽限期

服务从启动到 `/health` 200 要十几秒，这期间 `alive()` 是 false。若此时直接删 pidfile
再起一个，会把**正在加载权重的那个实例挤掉** —— 实测跑出过 pid 5285→5647 的换进程。

→ 给 180 秒宽限期；到期仍不就绪就退出，交给人工判断。

### 4. 判据不能用 pidfile，也不能用 `/dev/tcp`

- 只看 pidfile：会被陈旧文件骗到（坑 2）
- `/dev/tcp`：**函数里拿不到子 shell 的退出码**，实测 `running` 恒为假，于是又拉一个

→ 改用 **`/health` 的 HTTP 探测**。服务真在跑的话它一定回答 200，比任何本地状态可靠。

另外：**这个镜像没有 `ss`，也没有 `netstat`**，要看监听端口得读 `/proc/net/tcp`
（6006 = `0x1776`，状态 `0A` = LISTEN）。

---

## 五、日常用法

```bash
# 看状态（自启脚本视角）
bash /root/autodl-tmp/autostart/qwen-autostart.sh --status

# 重贴引导（容器重建、或换了新容器之后）
bash /root/autodl-tmp/autostart/qwen-autostart.sh --install

# 看自启记录
tail -20 /root/autodl-tmp/autostart/boot.log
```

从本机（仓库里）：

```bash
python tools/deploy_autostart.py          # 上传 + 语法检查 + 装引导 + 状态
python tools/deploy_autostart.py --check  # 只看状态
python tools/_autostart_e2e.py            # 端到端验证（会停一次服务，约 3 分钟）
python tools/_svc_procs.py                # 精确看进程与显存占用
python tools/_svc_watch_load.py 240       # 盯权重加载到 loaded=true
```

### 可调的环境变量

| 变量 | 默认 | 含义 |
|---|---|---|
| `QWEN_AUTOSTART_GPU_WAIT` | 600 | 等 GPU 就绪的最大秒数（无卡模式直接跳过，避免起成 mock） |
| `QWEN_AUTOSTART_GRACE` | 180 | 已有实例在加载时，等它就绪的最大秒数 |
| `QWEN_AUTOSTART_KILL_WAIT` | 60 | 清残留进程后等显存释放的最大秒数 |

---

## 六、排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 重启后服务没起来 | 引导行被容器重建冲掉了 | `--install` 重贴；看 `boot.log` 有没有触发记录 |
| `health` 是 ok 但不出图 | 权重没加载完，或加载失败 | **看 `loaded` 字段**，失败原因写在 `load_error` 里 |
| 日志有 `address already in use` | 旧实例还在退出中 | 跑一次自启脚本（它会 houseclean），或 `_svc_procs.py` 看谁占着 |
| 日志有 `OutOfMemoryError` | 有孤儿进程占显存 | `_svc_procs.py` 确认，`pkill -f 'service/server\.py'` 后重起 |
| 起来了但是 mock 模式 | 容器在无卡模式 | 正常行为 —— 脚本故意不占端口，等有卡再起 |

> **`/health` 在权重加载完成之前就返回 `status:"ok"`。** 判"能不能出图"必须看
> `"loaded":true`，光看 health 会误判。

---

## 七、验证记录

`tools/_autostart_e2e.py` 的 15 项断言，全部通过：

- 链路 1（`customer.cmd.sh`）：服务被拉起、是真实模式而非 mock
- 链路 2（`~/.bashrc` 退路）：在**非交互 shell** 路径下也能拉起（已确认插在第 2 行、
  `[ -z "$PS1" ] && return` 在第 10 行）
- 并发触发：加载窗口内重复触发**没有换进程**（pid 13960 → 13960）
- 幂等：就绪状态下重复触发不换进程、6006 只有一个 LISTEN、GPU 上只有一个服务进程
- 陈旧 pidfile：伪造死 pid 后能识破并正常拉起
- 收尾：`loaded:true`、无 `load_error`、真实模式、公网入口 200
