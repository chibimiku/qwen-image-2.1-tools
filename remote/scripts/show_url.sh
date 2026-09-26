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
  if [ -n "$URL6006" ]; then
    for path in / /health /docs; do
      code=$(curl -sk -o /dev/null -w '%{http_code}' -m 8 "${URL6006}${path}")
      echo "  ${URL6006}${path}  -> HTTP $code"
    done
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
