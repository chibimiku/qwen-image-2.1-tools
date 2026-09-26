#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测一下每次请求都调用的 torch.cuda.empty_cache() 到底要多久。

在服务进程之外测不准（干净的上下文没有碎片），所以这里造出碎片化的分配，
再计时 —— 给"该不该留在热路径上"一个数。
"""
import time

import torch

torch.zeros(1, device="cuda")                      # 初始化上下文
print("context ready")

# 造碎片：反复分配/释放不同大小的块，让 allocator 攒下大量 cached block
for i in range(12):
    x = torch.empty(200 * 1024 * 1024 // 4, dtype=torch.float32, device="cuda")  # ~200MB
    del x
print("allocated GiB", round(torch.cuda.memory_allocated() / 1024 ** 3, 2))
print("reserved  GiB", round(torch.cuda.memory_reserved() / 1024 ** 3, 2))

for i in range(5):
    t = time.time()
    torch.cuda.empty_cache()
    print(f"  empty_cache #{i}: {time.time() - t:.3f}s")

# 对比：有活跃大张量时（更接近服务进程的常态）
keep = [torch.empty(1024 * 1024 * 512 // 4, dtype=torch.float32, device="cuda") for _ in range(4)]
print("\nwith 2GiB live tensors:")
print("allocated GiB", round(torch.cuda.memory_allocated() / 1024 ** 3, 2))
print("reserved  GiB", round(torch.cuda.memory_reserved() / 1024 ** 3, 2))
for i in range(3):
    t = time.time()
    torch.cuda.empty_cache()
    print(f"  empty_cache #{i}: {time.time() - t:.3f}s")
