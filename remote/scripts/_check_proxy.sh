export PATH=/root/miniconda3/bin:$PATH
TOK=$(grep -oP 'ServerApp\.token\s*=\s*"\K[^"]+' /init/jupyter/jupyter_config.py)
echo '--- 带 Jupyter token 走代理访问服务 ---'
curl -s -o /dev/null -w '  /jupyter/proxy/6006/health?token=***  -> %{http_code}\n' \
  "http://127.0.0.1:8888/jupyter/proxy/6006/health?token=$TOK"
curl -s -o /dev/null -w '  /jupyter/proxy/6006/?token=***       -> %{http_code}\n' \
  "http://127.0.0.1:8888/jupyter/proxy/6006/?token=$TOK"
curl -s -o /dev/null -w '  /jupyter/proxy/6006/v1/models        -> %{http_code} (期望 401)\n' \
  "http://127.0.0.1:8888/jupyter/proxy/6006/v1/models?token=$TOK"
echo
echo '--- 用 Jupyter 会话 cookie 的方式（登录后浏览器就是这个行为）---'
curl -s -c /tmp/jk -o /dev/null "http://127.0.0.1:8888/jupyter/api/contents/?token=$TOK"
curl -s -b /tmp/jk -o /dev/null -w '  带 cookie /jupyter/proxy/6006/health -> %{http_code}\n' \
  'http://127.0.0.1:8888/jupyter/proxy/6006/health'
curl -s -b /tmp/jk -o /dev/null -w '  带 cookie /jupyter/proxy/6006/       -> %{http_code}\n' \
  'http://127.0.0.1:8888/jupyter/proxy/6006/'
rm -f /tmp/jk
