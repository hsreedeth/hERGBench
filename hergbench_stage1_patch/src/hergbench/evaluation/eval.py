
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    roc_auc_score,
)


@dataclass(frozen=True)
class CalibrationConfig:
    method: str = "isotonic"  # isotonic or sigmoid
    threshold_metric: str = "youden"  # youden or f1
    n_bins: int = 10


def calibrate_prefit(model, X_val: np.ndarray, y_val: np.ndarray, method: str):
    """Calibrate a prefit model on validation data."""
    if method not in {"isotonic", "sigmoid"}:
        raise ValueError(f"Unknown calibration method: {method}")
    cal = CalibratedClassifierCV(model, method=method, cv="prefit")
    cal.fit(X_val, y_val)
    return cal


def select_threshold(y_true: np.ndarray, p: np.ndarray, metric: str) -> float:
    """Select a decision threshold on validation data, then lock it."""
    metric = metric.lower()
    thresholds = np.linspace(0.01, 0.99, 99)

    best_t = 0.5
    best_v = -1e9

    y_true = y_true.astype(int)

    for t in thresholds:
        y_hat = (p >= t).astype(int)
        if metric == "f1":
            v = f1_score(y_true, y_hat, zero_division=0)
        elif metric == "youden":
            # Youden J = TPR - FPR
            tp = int(((y_hat == 1) & (y_true == 1)).sum())
            fp = int(((y_hat == 1) & (y_true == 0)).sum())
            tn = int(((y_hat == 0) & (y_true == 0)).sum())
            fn = int(((y_hat == 0) & (y_true == 1)).sum())
            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            v = tpr - fpr
        else:
            raise ValueError(f"Unknown threshold metric: {metric}")

        if v > best_v:
            best_v = v
            best_t = float(t)

    return best_t


def compute_metrics(y_true: np.ndarray, p: np.ndarray, threshold: float) -> Dict[str, float]:
    y_true = y_true.astype(int)
    y_hat = (p >= threshold).astype(int)

    out = {
        "auroc": float(roc_auc_score(y_true, p)) if len(np.unique(y_true)) == 2 else float("nan"),
        "auprc": float(average_precision_score(y_true, p)) if len(np.unique(y_true)) == 2 else float("nan"),
        "f1": float(f1_score(y_true, y_hat, zero_division=0)),
        "balanced_acc": float(balanced_accuracy_score(y_true, y_hat)),
        "brier": float(brier_score_loss(y_true, p)),
    }
    return out


def bootstrap_ci(
    y_true: np.ndarray,
    p: np.ndarray,
    threshold: float,
    B: int,
    seed: int,
) -> Dict[str, Tuple[float, float, float]]:
    """Bootstrap CI for each metric over test predictions."""
    rng = np.random.default_rng(seed)
    n = len(y_true)
    idx = np.arange(n)

    metrics = {"auroc": [], "auprc": [], "f1": [], "balanced_acc": [], "brier": []}
    for _ in range(B):
        sample = rng.choice(idx, size=n, replace=True)
        m = compute_metrics(y_true[sample], p[sample], threshold)
        for k in metrics:
            metrics[k].append(m[k])

    out: Dict[str, Tuple[float, float, float]] = {}
    for k, vals in metrics.items():
        arr = np.array(vals, dtype=float)
        out[k] = (float(np.nanmean(arr)), float(np.nanpercentile(arr, 2.5)), float(np.nanpercentile(arr, 97.5)))
    return out


def plot_reliability(
    y_true: np.ndarray,
    p: np.ndarray,
    n_bins: int,
    out_path: Path,
    title: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frac_pos, mean_pred = calibration_curve(y_true, p, n_bins=n_bins, strategy="uniform")

    plt.figure()
    plt.plot([0, 1], [0, 1])
    plt.plot(mean_pred, frac_pos, marker="o")
    plt.xlabel("Mean predicted probability")
    plt.ylabel("Fraction of positives")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()


def plot_generalization_gap(
    df_results: pd.DataFrame,
    metric: str,
    out_path: Path,
    title: str,
    split_order: List[str] | None = None,
) -> None:
    """Plot metric degradation across split types."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if split_order is None:
        split_order = ["random", "scaffold", "cluster"]

    agg = (
        df_results.groupby(["split_type"])[metric]
        .agg(["mean", "std"])
        .reindex(split_order)
        .reset_index()
    )

    x = np.arange(len(agg))
    plt.figure()
    plt.errorbar(x, agg["mean"].values, yerr=agg["std"].values, fmt="o-")
    plt.xticks(x, agg["split_type"].tolist())
    plt.ylabel(metric)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()
