from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def load_config(path: Path) -> Dict[str, Any]:
    """
    Load YAML config. Keeping this simple for now. Will can add schema validation later (pydantic - type hints.)
    once config stabilizes.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} did not parse to a dict.")
    return data

