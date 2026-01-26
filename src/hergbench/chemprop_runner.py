from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ChemPropTrainConfig:
    data_path: Path
    output_dir: Path
    smiles_col: str
    target_col: str

    task_type: str = "classification"
    metrics: Sequence[str] = ("prc", "roc")
    tracking_metric: str = "prc"

    epochs: int = 80
    patience: int = 10
    batch_size: int = 64
    num_workers: int = 0

    message_hidden_dim: int = 300
    depth: int = 3
    dropout: float = 0.0

    init_lr: float = 1e-4
    max_lr: float = 1e-3
    final_lr: float = 1e-4
    warmup_epochs: int = 2

    data_seed: int = 42
    pytorch_seed: int = 42

    accelerator: str = "auto"
    devices: str = "auto"


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ChemProp command failed:\n{' '.join(cmd)}\n\n{proc.stdout}")


def chemprop_train(cfg: ChemPropTrainConfig) -> Path:
    """
    Trains a ChemProp model using user-specified splits (expects a 'split' column already in cfg.data_path).
    Returns the output_dir containing model artifacts.
    """
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    chemprop_exe = shutil.which("chemprop")
    if chemprop_exe:
        base = [chemprop_exe]
        print(f"[chemprop_runner] using CLI executable: {chemprop_exe}")
    else:
        # Use the chemprop module from the current Python environment.
        base = [sys.executable, "-m", "chemprop"]
        print(f"[chemprop_runner] using module: {sys.executable} -m chemprop")

    cmd = base + [
        "train",
        "-i", str(cfg.data_path),
        "-o", str(cfg.output_dir),
        "-s", cfg.smiles_col,
        "-t", cfg.task_type,
        "--target-columns", cfg.target_col,
        "--splits-column", "split",
        "--metrics", *list(cfg.metrics),
        "--tracking-metric", cfg.tracking_metric,
        "--epochs", str(cfg.epochs),
        "--patience", str(cfg.patience),
        "-b", str(cfg.batch_size),
        "-n", str(cfg.num_workers),
        "--message-hidden-dim", str(cfg.message_hidden_dim),
        "--depth", str(cfg.depth),
        "--dropout", str(cfg.dropout),
        "--init-lr", str(cfg.init_lr),
        "--max-lr", str(cfg.max_lr),
        "--final-lr", str(cfg.final_lr),
        "--warmup-epochs", str(cfg.warmup_epochs),
        "--data-seed", str(cfg.data_seed),
        "--pytorch-seed", str(cfg.pytorch_seed),
        "--accelerator", cfg.accelerator,
        "--devices", cfg.devices,
    ]

    _run(cmd)
    return cfg.output_dir


def chemprop_predict(model_dir: Path, data_path: Path, smiles_col: str, out_path: Path) -> Path:
    """
    Runs ChemProp prediction. Writes a CSV with predictions.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chemprop_exe = shutil.which("chemprop")
    if chemprop_exe:
        base = [chemprop_exe]
        print(f"[chemprop_runner] using CLI executable: {chemprop_exe}")
    else:
        base = [sys.executable, "-m", "chemprop"]
        print(f"[chemprop_runner] using module: {sys.executable} -m chemprop")

    cmd = base + [
        "predict",
        "-i", str(data_path),
        "--smiles-columns", smiles_col,
        "--model-path", str(model_dir),
        "-o", str(out_path),
    ]
    _run(cmd)
    return out_path
