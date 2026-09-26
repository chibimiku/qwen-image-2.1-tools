export PATH=/root/miniconda3/bin:$PATH
echo '=== jupyter 配置 ==='
cat /init/jupyter/jupyter_config.py 2>/dev/null | head -40
echo '=== 平台代理配置里和 jupyter/端口有关的部分 ==='
python - <<'PY'
import glob, os, re
for f in glob.glob('/init/proxy/*.ini') + glob.glob('/init/autopanel/*') + glob.glob('/init/others/*'):
    try:
        t = open(f, 'rb').read().decode('utf-8', 'replace')
    except Exception as e:
        print(f, 'ERR', e); continue
    keys = [l for l in t.splitlines() if re.search(r'jupyter|proxy|port|domain|url|8888|6006', l, re.I)]
    if keys:
        print('---', f)
        for l in keys[:12]:
            print('   ', l[:160])
PY
echo '=== 是否有 jupyterlab 在监听 ==='
timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/8888" 2>/dev/null && echo '8888 开' || echo '8888 关'
pgrep -af 'jupyter-lab|jupyter_server' | grep -v pgrep | head -3
echo '=== /init 目录结构 ==='
find /init -maxdepth 2 | head -30
