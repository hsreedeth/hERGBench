from __future__ import annotations

import os
import random
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ReproConfig:
    seed: int


def set_global_seed(cfg: ReproConfig) -> None:
    """
    Set seeds for deterministic-ish behavior.

    Notes:
    - Full determinism in DL requires additional controls (torch backends, cudnn, etc.).
    - Stage 0 covers Python + NumPy, and will optionally seed torch if installed.
    """
    seed = int(cfg.seed)

    # Ensures deterministic hashing for some Python operations
    os.environ["PYTHONHASHSEED"] = str(seed)

    random.seed(seed)
    np.random.seed(seed)

    # Optional torch seeding (Stage 2+)
    try:
        import torch  # type: ignore

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        # More strict determinism (can reduce performance; GPU-specific)
        torch.use_deterministic_algorithms(False)
    except Exception:
        pass

