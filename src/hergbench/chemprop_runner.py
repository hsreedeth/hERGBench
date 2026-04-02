from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATCHED_CHEMPROP_CLI = _REPO_ROOT / "scripts" / "chemprop_cli_patched.py"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChemPropTrainConfig:
    data_path: Path
    output_dir: Path
    smiles_col: str
    target_col: str

    task_type: str = "classification"
    metrics: Sequence[str] = ("prc", "roc")
    tracking_metric: str = "auroc"

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


def _stream_chemprop_output_enabled() -> bool:
    return os.getenv("HERGBENCH_STREAM_CHEMPROP", "0") == "1"


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    if _stream_chemprop_output_enabled():
        logger.info("Streaming ChemProp subprocess output live.")
        print("[chemprop_runner] streaming ChemProp subprocess output live.")
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ChemProp command failed:\n{' '.join(cmd)}")
        return

    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ChemProp command failed:\n{' '.join(cmd)}\n\n{proc.stdout}")


def _resolve_chemprop_python(chemprop_exe: str) -> str | None:
    try:
        with Path(chemprop_exe).open() as fh:
            shebang = fh.readline().strip()
    except OSError:
        return None

    if not shebang.startswith("#!"):
        return None

    interpreter = shebang[2:].strip()
    if not interpreter:
        return None

    parts = interpreter.split()
    if Path(parts[0]).name == "env" and len(parts) > 1:
        return shutil.which(parts[1]) or parts[1]

    return parts[0]


def _direct_chemprop_base() -> list[str]:
    chemprop_exe = shutil.which("chemprop")

    if chemprop_exe:
        print(f"[chemprop_runner] using CLI executable: {chemprop_exe}")
        return [chemprop_exe]

    print(f"[chemprop_runner] using module: {sys.executable} -m chemprop")
    return [sys.executable, "-m", "chemprop"]


def _patched_chemprop_base() -> list[str]:
    chemprop_exe = shutil.which("chemprop")
    if chemprop_exe:
        chemprop_python = _resolve_chemprop_python(chemprop_exe)
        if chemprop_python is None:
            raise RuntimeError(
                "Could not determine the Python interpreter behind the ChemProp CLI. "
                "This is required to patch ChemProp's PRC tracking bug safely."
            )
        print(
            "[chemprop_runner] using patched ChemProp CLI to fix PRC checkpoint "
            "and early-stopping directionality."
        )
        return [chemprop_python, str(_PATCHED_CHEMPROP_CLI)]

    print(
        "[chemprop_runner] using patched ChemProp module entrypoint to fix PRC "
        "checkpoint and early-stopping directionality."
    )
    return [sys.executable, str(_PATCHED_CHEMPROP_CLI)]


def _normalize_tracking_metric(tracking_metric: str) -> str:
    normalized_tracking_metric = tracking_metric.strip().lower()
    if normalized_tracking_metric not in {"auroc", "prc"}:
        raise ValueError(
            f"Unsupported tracking_metric={tracking_metric!r}. Supported values are "
            "'auroc' and 'prc'."
        )
    return normalized_tracking_metric


def _chemprop_cli_tracking_metric(tracking_metric: str) -> str:
    normalized_tracking_metric = _normalize_tracking_metric(tracking_metric)
    return "roc" if normalized_tracking_metric == "auroc" else normalized_tracking_metric


def _chemprop_train_base(tracking_metric: str) -> list[str]:
    normalized_tracking_metric = _normalize_tracking_metric(tracking_metric)
    cli_tracking_metric = _chemprop_cli_tracking_metric(normalized_tracking_metric)
    logger.info(
        "ChemProp training tracking_metric=%s (ChemProp CLI metric=%s)",
        normalized_tracking_metric,
        cli_tracking_metric,
    )
    print(
        "[chemprop_runner] training "
        f"tracking_metric={normalized_tracking_metric} (ChemProp CLI metric={cli_tracking_metric})"
    )

    if normalized_tracking_metric == "auroc":
        return _direct_chemprop_base()

    if normalized_tracking_metric == "prc":
        msg = (
            "tracking_metric=prc with ChemProp 2.2.2 requires higher_is_better "
            "patch. Consider switching to auroc. See scripts/chemprop_cli_patched.py"
        )
        logger.warning(msg)
        print(f"[chemprop_runner] WARNING: {msg}")
        return _patched_chemprop_base()
    raise AssertionError(f"Unhandled tracking_metric={normalized_tracking_metric!r}")


def chemprop_train(cfg: ChemPropTrainConfig) -> Path:
    """
    Trains a ChemProp model using user-specified splits (expects a 'split' column already in cfg.data_path).
    Returns the output_dir containing model artifacts.
    """
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    base = _chemprop_train_base(cfg.tracking_metric)

    cmd = base + [
        "train",
        "-i", str(cfg.data_path),
        "-o", str(cfg.output_dir),
        "-s", cfg.smiles_col,
        "-t", cfg.task_type,
        "--target-columns", cfg.target_col,
        "--splits-column", "split",
        "--metrics", *list(cfg.metrics),
        "--tracking-metric", _chemprop_cli_tracking_metric(cfg.tracking_metric),
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


def chemprop_predict(
    model_dir: Path,
    data_path: Path,
    smiles_col: str,
    out_path: Path,
    accelerator: str | None = None,
    devices: str | None = None,
) -> Path:
    """
    Runs ChemProp prediction. Writes a CSV with predictions.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = _direct_chemprop_base()

    cmd = base + [
        "predict",
        "-i", str(data_path),
        "--smiles-columns", smiles_col,
        "--model-path", str(model_dir),
        "-o", str(out_path),
    ]
    if accelerator:
        cmd += ["--accelerator", str(accelerator)]
    if devices:
        cmd += ["--devices", str(devices)]
    _run(cmd)
    return out_path
