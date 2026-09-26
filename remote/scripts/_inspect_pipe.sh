export PATH=/root/miniconda3/bin:$PATH
python - <<'PY'
import inspect
from diffusers import QwenImage21Pipeline, QwenImage21Transformer2DModel
sig = inspect.signature(QwenImage21Pipeline.__call__)
print("=== QwenImage21Pipeline.__call__ ===")
for n, p in sig.parameters.items():
    if n == "self":
        continue
    print(f"  {n:28s} default={p.default!r}")

print()
print("=== image handling / mask support in source ===")
src = inspect.getsource(QwenImage21Pipeline.__call__)
import re
for kw in ("mask", "inverted_mask", "ignore", "max_area", "MAX_AREA", "strength", "denoise"):
    hits = [l.strip() for l in src.splitlines() if kw in l][:4]
    print(f"-- {kw}: {len(hits)} hit(s)")
    for h in hits:
        print("    ", h[:150])
print()
print("=== class docstring head ===")
print((QwenImage21Pipeline.__doc__ or "")[:1500])
PY
