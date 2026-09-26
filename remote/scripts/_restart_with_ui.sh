export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
pkill -f 'service/server.py' 2>/dev/null; sleep 3
nohup python service/server.py > logs/service.log 2>&1 &
echo $! > service.pid
echo "pid=$(cat service.pid)"
for i in $(seq 1 40); do
  H=$(curl -s -m 5 localhost:6006/health 2>/dev/null)
  case "$H" in *'"loaded":true'*) echo "READY"; break;; esac
  sleep 5
done
echo '=== WebUI 自检 ==='
curl -s -o /tmp/ui.html -w 'GET /        http=%{http_code} bytes=%{size_download}\n' localhost:6006/
curl -s -o /dev/null -w 'GET /ui      http=%{http_code}\n' localhost:6006/ui
curl -s -o /dev/null -w 'GET /docs    http=%{http_code}\n' localhost:6006/docs
curl -s -o /dev/null -w 'GET /health  http=%{http_code}\n' localhost:6006/health
grep -c 'Qwen-Image-2.1 控制台' /tmp/ui.html || true
head -c 200 /tmp/ui.html
