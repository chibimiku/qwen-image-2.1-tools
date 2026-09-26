#!/bin/bash
# 打印当前实例的公网访问入口（AutoDL 把映射地址写在 /init/others/help 里）
#   bash /root/qwen-image-2.1/scripts/show_url.sh
export PATH=/root/miniconda3/bin:$PATH

echo "=== AutoDL 平台分配的入口 ==="
if [ -f /init/others/help ]; then
  grep -E 'AutoDLService|AutoDLRegion|AutoDLContainerUUID' /init/others/help | sed 's/^export //'
  URL6006=$(grep -E '^export AutoDLService6006URL=' /init/others/help | cut -d= -f2-)
  URL6008=$(grep -E '^export AutoDLService6008URL=' /init/others/help | cut -d= -f2-)
  echo
  echo "WebUI / API（6006）: ${URL6006:-未分配}"
  echo "备用端口（6008）   : ${URL6008:-未分配}"
  echo "Swagger 文档        : ${URL6006:-}/docs"
  echo
  echo "=== 入口自测 ==="
  echo "  注意：容器内经代理访问公网入口常被网关拦（403），这不代表服务有问题。"
  echo "  更可靠的自测是打本机 127.0.0.1:6006，以及对映射域名做 DNS 解析："
  echo
  host=$(echo "$URL6006" | sed -E 's#https?://([^/:]+).*#\1#')
  if [ -n "$host" ]; then
    if getent hosts "$host" >/dev/null 2>&1; then
      echo "  DNS 解析 $host -> $(getent hosts "$host" | awk '{print $1}' | head -1)  OK"
    else
      echo "  DNS 解析 $host -> 失败（平台上该映射未分配或已回收）"
    fi
  fi
  for path in / /health; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 "http://127.0.0.1:6006${path}")
    printf '  本机 %-22s -> HTTP %s   （免鉴权）\n' "127.0.0.1:6006${path}" "$code"
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 "http://127.0.0.1:6006/docs")
  printf '  本机 %-22s -> HTTP %s   （无 key 时 401 是正常的）\n' "127.0.0.1:6006/docs" "$code"
  if [ -n "${QWEN_API_KEY:-}" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 "http://127.0.0.1:6006/v1/models?key=$QWEN_API_KEY")
    printf '  本机 %-22s -> HTTP %s   （带 key，401 说明 key 不对）\n' "/v1/models?key=***" "$code"
  fi
else
  echo "没找到 /init/others/help，说明不是 AutoDL 容器或平台改了实现"
fi

echo
echo "=== 本地 SSH 隧道（无企业认证时的替代方案）==="
echo "  ssh -p \${端口} -L 16006:127.0.0.1:6006 root@\${实例域名} -N"
echo "  然后浏览器打开 http://127.0.0.1:16006/"

echo
echo "=== 本机进程状态 ==="
if [ -f /root/qwen-image-2.1/service.pid ] && kill -0 "$(cat /root/qwen-image-2.1/service.pid)" 2>/dev/null; then
  echo "  服务在跑 pid=$(cat /root/qwen-image-2.1/service.pid)"
else
  echo "  服务没在跑 —— 先执行 bash /root/qwen-image-2.1/scripts/serve.sh start"
fi
