export PATH=/root/miniconda3/bin:$PATH
TOK=$(grep -oP 'ServerApp\.token\s*=\s*"\K[^"]+' /init/jupyter/jupyter_config.py)
echo "Jupyter token 长度: ${#TOK}"
echo
echo '--- 无 token 访问 Jupyter API ---'
curl -s -o /dev/null -w '  /jupyter/api/contents           -> %{http_code}\n' \
  'http://127.0.0.1:8888/jupyter/api/contents/'
echo '--- 带 token ---'
curl -s -o /dev/null -w '  /jupyter/api/contents?token=***  -> %{http_code}\n' \
  "http://127.0.0.1:8888/jupyter/api/contents/?token=$TOK"
echo
echo '--- Jupyter 代理到服务的路径（无 token 时）---'
curl -s -o /dev/null -w '  /jupyter/proxy/6006/health       -> %{http_code}\n' \
  'http://127.0.0.1:8888/jupyter/proxy/6006/health'
curl -s -o /dev/null -w '  /jupyter/proxy/6006/v1/models    -> %{http_code}  (期望 401，说明服务鉴权在起作用)\n' \
  'http://127.0.0.1:8888/jupyter/proxy/6006/v1/models'
echo
echo '--- 服务能否读到 Jupyter 的代理前缀（排障用）---'
curl -s -D - -o /dev/null 'http://127.0.0.1:8888/jupyter/proxy/6006/health' 2>/dev/null | head -6
