export PATH=/root/miniconda3/bin:$PATH
DIR=/root/autodl-tmp/Qwen-Image-2.1
TARGET=33135
for i in $(seq 1 40); do
  LEFT=$(find $DIR -name '*.incomplete' | wc -l)
  MB=$(du -sm $DIR | cut -f1)
  echo "$(date '+%H:%M:%S') ${MB}MB/$TARGET MB unfinished=$LEFT"
  if [ "$LEFT" -eq 0 ]; then echo "=== ALL SHARDS COMPLETE ==="; break; fi
  sleep 30
done
echo '=== shard integrity (safetensors header parse) ==='
python - <<'PY'
import glob, os, struct, json
bad = 0
for f in sorted(glob.glob('/root/autodl-tmp/Qwen-Image-2.1/**/*.safetensors', recursive=True)):
    with open(f, 'rb') as fh:
        n = struct.unpack('<Q', fh.read(8))[0]
        try:
            hdr = json.loads(fh.read(n))
            n_tensors = len(hdr) - (1 if '__metadata__' in hdr else 0)
            print(f"OK   {os.path.getsize(f)/1e9:6.2f} GB  {n_tensors:5d} tensors  {os.path.relpath(f, '/root/autodl-tmp/Qwen-Image-2.1')}")
        except Exception as e:
            bad += 1
            print(f"BAD  {f}: {e}")
print("bad files:", bad)
PY
echo '=== quick load test (CPU, weights only) ==='
python - <<'PY'
import time, torch
t0=time.time()
from diffusers import QwenImage21Pipeline
pipe = QwenImage21Pipeline.from_pretrained('/root/autodl-tmp/Qwen-Image-2.1',
                                           torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
def n(m): return sum(p.numel() for p in m.parameters())/1e9 if m is not None else 0
print(f"load {time.time()-t0:.1f}s")
print(f"transformer  {n(pipe.transformer):5.2f}B  {type(pipe.transformer).__name__}")
print(f"text_encoder {n(pipe.text_encoder):5.2f}B  {type(pipe.text_encoder).__name__}")
print(f"vae          {n(pipe.vae):5.2f}B  {type(pipe.vae).__name__}  latent_ch={pipe.vae.config.latent_channels}")
print("scheduler:", type(pipe.scheduler).__name__)
tok = pipe.tokenizer("sanity check", return_tensors="pt")
print("tokenizer ids:", tuple(tok.input_ids.shape))
PY
echo '=== start service in AUTO mode (will be mock while GPU absent) ==='
source /root/qwen-image-2.1/qwen_env.sh
cd /root/qwen-image-2.1
bash scripts/serve.sh start
sleep 6
curl -s -m 8 localhost:6006/health
echo
echo '=== disk ==='
df -h / /root/autodl-tmp | sed -n '1,4p'
echo '=== sizes ==='
du -sh $DIR
