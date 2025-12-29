from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml


def make_run_id(seed: int, run_name: str | None = None) -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = f"{ts}_seed{seed}"
    return f"{base}_{run_name}" if run_name else base


def setup_logger(log_path: Path, level: str = "INFO") -> logging.Logger:
    """
    Create a run-scoped logger that writes both to console and a file.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("hergbench")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")

    # File handler
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.propagate = False
    return logger


def _git_commit_hash() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return None


def _pip_freeze() -> list[str]:
    try:
        out = subprocess.check_output([sys.executable, "-m", "pip", "freeze"])
        return out.decode("utf-8").splitlines()
    except Exception:
        return []


def write_run_metadata(run_dir: Path, config: dict[str, Any]) -> None:
    """
    Write a metadata.json capturing environment + provenance.
    This is the basis for auditability and reproducibility claims.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    meta: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "git_commit": _git_commit_hash(),
        "pip_freeze": _pip_freeze(),
        "config": config,
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Also snapshot the resolved config in YAML for human readability
    (run_dir / "config.resolved.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

