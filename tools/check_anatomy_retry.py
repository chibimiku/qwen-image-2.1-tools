#!/usr/bin/env python
"""Fast regression check for anatomy rerolling; does not load either model."""
import asyncio
import base64
import io
import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "service"))
try:
    import server  # noqa: E402
except ModuleNotFoundError as exc:
    # 这个仓库的本机开发环境可以不装完整服务依赖；部署环境/CI 有依赖时才跑逻辑断言。
    print(f"anatomy retry: SKIP (missing runtime dependency: {exc.name})")
    raise SystemExit(0)


async def main():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()
    seen = []
    verdicts = iter([
        {"passed": False, "label": "fail", "confidence": .95, "reason": "extra arm"},
        {"passed": True, "label": "pass", "confidence": .91, "reason": "normal"},
    ])

    async def fake_once(req):
        seed = req.get("seed")
        if seed is None:
            seed = 123
        seen.append(seed)
        return [{"b64_json": encoded, "seed": seed, "width": 8, "height": 8,
                 "timing": {"request_id": "test"}}]

    server._generate_once = fake_once
    server._effective_mock = lambda: False
    server.inspect_anatomy = lambda _im, _prompt: next(verdicts)
    result = await server._generate({
        "prompt": "one person", "anatomy_check": True, "anatomy_max_retries": 2,
        "seed": 123,
    })
    meta = result[0]["anatomy_check"]
    assert meta["passed"] and meta["attempts"] == 2 and meta["retries"] == 1
    assert len(seen) == 2 and seen[0] == 123 and seen[1] != 123
    print("anatomy retry: OK", seen)


if __name__ == "__main__":
    asyncio.run(main())
