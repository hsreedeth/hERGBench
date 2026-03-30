#!/usr/bin/env python3
from __future__ import annotations

import sys


def main() -> int:
    try:
        import torch
    except ImportError as exc:
        print(f"[check_torch_cuda] torch import failed: {exc}", file=sys.stderr)
        return 1

    print(f"torch_version: {torch.__version__}")
    print(f"cuda_is_available: {torch.cuda.is_available()}")
    print(f"torch_cuda_version: {torch.version.cuda}")

    device_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
    print(f"device_count: {device_count}")
    for idx in range(device_count):
        print(f"device_{idx}: {torch.cuda.get_device_name(idx)}")

    if not torch.cuda.is_available() or device_count < 1:
        print("[check_torch_cuda] No CUDA device is available.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
