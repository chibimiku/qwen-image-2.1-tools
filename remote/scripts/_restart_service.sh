#!/bin/bash
# 重启服务并等到"模型已加载"为止。放成脚本是因为 pkill 会连自己所在的 ssh 会话一起命中，
# 直接内联执行会把自己的连接打断（exit -1）。
set -u
cd /root/qwen-image-2.1

pkill -f 'service/server.py' 2>/dev/null
for i in $(seq 1 20); do
  pgrep -f 'service/server.py' >/dev/null || break
  sleep 1
done
pkill -9 -f 'service/server.py' 2>/dev/null
sleep 2

: > /root/qwen-image-2.1/logs/service.log
setsid nohup bash scripts/serve.sh start >> /root/qwen-image-2.1/logs/service.log 2>&1 < /dev/null &
echo "launched pid=$!"

# 端口/健康端点都以脚本里的默认值为准（QWEN_PORT 默认 6006，端点是 /health 不是 /healthz）
PORT="${QWEN_PORT:-6006}"

# 等 /health 能应答（最长 10 分钟：要重新加载 33G 权重）
for i in $(seq 1 120); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/health" || true)
  if [ "$code" = "200" ]; then
    echo "health 200 after $((i * 5))s"
    curl -s "http://127.0.0.1:${PORT}/health"
    echo
    exit 0
  fi
done
echo "TIMEOUT waiting for health"
tail -30 /root/qwen-image-2.1/logs/service.log
exit 1
