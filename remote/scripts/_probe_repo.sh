export PATH=/root/miniconda3/bin:$PATH
echo '=== download.log tail ==='
tail -c 800 /root/qwen-image-2.1/logs/download.log | tr '\r' '\n' | tail -8
echo '=== what is on disk ==='
find /root/autodl-tmp/Qwen-Image-2.1 -maxdepth 2 | head -30
echo '=== model_index.json (modelscope) ==='
curl -sL -m 30 'https://www.modelscope.cn/api/v1/models/Qwen/Qwen-Image-2.1/repo?Revision=master&FilePath=model_index.json' | head -40
echo '=== list files via ms API ==='
curl -sL -m 30 'https://www.modelscope.cn/api/v1/models/Qwen/Qwen-Image-2.1/repo/files?Revision=master&Recursive=true' | python -c "
import sys,json
try:
    d=json.load(sys.stdin)
    files=d.get('Data',{}).get('Files',[])
    for f in files:
        print(f\"{f.get('Size',0)/1e6:10.1f} MB  {f.get('Path')}\")
    print('total files', len(files), 'bytes', sum(f.get('Size',0) for f in files)/1e9, 'GB')
except Exception as e:
    print('parse err', e)
    print(sys.stdin.read()[:500] if False else '')
"
