export PATH=/root/miniconda3/bin:$PATH
echo '=== 监听情况 ==='
ss -ltnp 2>/dev/null | grep -E '6006|6008|8888' || netstat -ltnp 2>/dev/null | grep -E '6006|6008|8888'
echo '=== 服务是否在跑 ==='
pgrep -af 'service/server.py' | grep -v pgrep
echo '=== 容器内自测 ==='
curl -s -o /dev/null -w 'localhost:6006/  http=%{http_code}\n' http://127.0.0.1:6006/
curl -s -o /dev/null -w 'health           http=%{http_code}\n' http://127.0.0.1:6006/health
echo '=== 内网 IP ==='
hostname -I 2>/dev/null
ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -5
echo '=== 主机名 / 区域线索 ==='
hostname
cat /etc/hosts | head -5
echo '=== AutoDL 是否给了映射提示 ==='
ls /init/autopanel 2>/dev/null; cat /init/proxy/*.ini 2>/dev/null | head -3
echo '=== 端口开放相关的平台文件 ==='
find / -maxdepth 3 -name '*proxy*' -o -maxdepth 3 -name '*domain*' 2>/dev/null | head -10
