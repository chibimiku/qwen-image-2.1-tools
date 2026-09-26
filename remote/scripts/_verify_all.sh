export PATH=/root/miniconda3/bin:$PATH
echo '=== A) bootstrap dry-run（不起服务，只体检）==='
SKIP_START=1 SKIP_DOWNLOAD=1 bash /root/qwen-image-2.1/scripts/bootstrap.sh 2>&1
echo
echo '=== B) bootstrap 语法检查 ==='
bash -n /root/qwen-image-2.1/scripts/bootstrap.sh && echo '  bootstrap.sh 语法 OK'
bash -n /root/qwen-image-2.1/scripts/serve.sh && echo '  serve.sh 语法 OK'
bash -n /root/qwen-image-2.1/scripts/show_url.sh && echo '  show_url.sh 语法 OK'
echo
echo '=== C) JupyterLab 能否识别笔记本（用 token 调 Jupyter API）==='
TOK=$(grep -oP 'ServerApp\.token\s*=\s*"\K[^"]+' /init/jupyter/jupyter_config.py)
curl -s -m 10 "http://127.0.0.1:8888/jupyter/api/contents/qwen-image-2.1/service/ui?token=$TOK" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('  目录:', d.get('path'), ' 类型:', d.get('type'))
for it in d.get('content', []):
    print(f\"    {it['type']:5s} {it['name']:34s} {it.get('size', 0):>8d} bytes  writable={it.get('writable')}\")
"
echo
echo '=== D) 笔记本内容抽查（Jupyter 视角）==='
curl -s -m 10 "http://127.0.0.1:8888/jupyter/api/contents/qwen-image-2.1/service/ui/Qwen-Image-2.1-console.ipynb?token=$TOK" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
nb = d.get('content') or {}
cells = nb.get('cells', [])
print('  nbformat:', nb.get('nbformat'), '| 单元格:', len(cells),
      '| code:', sum(1 for c in cells if c['cell_type']=='code'))
print('  前 3 个 markdown 标题:')
n = 0
for c in cells:
    if c['cell_type'] == 'markdown':
        for line in c['source']:
            if line.startswith('#'):
                print('   ', line.strip()[:70]); n += 1; break
    if n >= 3: break
"
echo
echo '=== E) 服务与显存现状 ==='
curl -s -m 5 localhost:6006/health | python3 -c "
import sys, json
h = json.load(sys.stdin)
print('  loaded:', h['loaded'], '| mode:', h['mode'], '| queue:', h['queue_depth'])
g = h['gpu']
print(f\"  GPU: {g['name']}  {g['free_gb']}G 空闲 / {g['reserved_gb']}G 已用 / {g['total_gb']}G 总\")
"
nvidia-smi --query-gpu=memory.used --format=csv,noheader
