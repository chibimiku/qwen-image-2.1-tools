export PATH=/root/miniconda3/bin:$PATH
echo '=== 服务实际绑定的地址（uvicorn 日志） ==='
grep -m2 'Uvicorn running on' /root/qwen-image-2.1/logs/service.log
echo '=== 容器内用容器 IP 访问（验证是否 0.0.0.0） ==='
curl -s -o /dev/null -w 'http://172.17.0.1:6006/  http=%{http_code}\n' -m 5 http://172.17.0.1:6006/
echo '=== 8000/8080/8888 端口是否有别的服务 ==='
for p in 6006 6008 8000 8080 8888 8443; do
  timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/$p" 2>/dev/null && echo "  127.0.0.1:$p 开" || echo "  127.0.0.1:$p 关"
done
echo '=== 容器 IP 上这些端口 ==='
for p in 6006 6008 8888; do
  timeout 2 bash -c "echo > /dev/tcp/172.17.0.1/$p" 2>/dev/null && echo "  172.17.0.1:$p 开" || echo "  172.17.0.1:$p 关"
done
echo '=== 容器内能否解析/访问 AutoDL 域名 ==='
getent hosts seetacloud.com || echo 'no seetacloud.com in dns'
curl -s -o /dev/null -w 'www.autodl.com http=%{http_code}\n' -m 8 https://www.autodl.com/ || echo '外网 https 不可达'
