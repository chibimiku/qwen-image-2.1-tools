export PATH=/root/miniconda3/bin:$PATH
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
python -c "import ast;ast.parse(open('service/server.py').read());print('syntax OK')"
pkill -f 'service/server.py' 2>/dev/null; sleep 1
QWEN_MODE=mock nohup python service/server.py > logs/service_smoke3.log 2>&1 &
sleep 8
python - <<'PY'
import requests, json
B="http://127.0.0.1:6006"
h=requests.get(B+"/health",timeout=20).json()
print("health keys:", sorted(h.keys()))
print("mode=%s mock=%s preload=%s peak=%s load_error=%s"%(h["mode"],h["mock"],h["preload"],h["peak_allocated_gib"],h["load_error"]))
r=requests.post(B+"/v1/images/generations",json={"prompt":"x","width":256,"height":256,"num_inference_steps":4},timeout=60)
print("t2i:",r.status_code, len(r.json()["data"][0]["b64_json"]))
PY
grep -iE 'error|traceback|deprecat' logs/service_smoke3.log | head -5
pkill -f 'service/server.py'
echo '=== download ==='
du -sh /root/autodl-tmp/Qwen-Image-2.1; find /root/autodl-tmp/Qwen-Image-2.1 -name '*.incomplete' | wc -l
tail -2 /root/qwen-image-2.1/logs/monitor.log
