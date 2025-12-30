
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
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
    """Calibrate a prefit model on validation data without refitting the base estimator."""
    if method not in {"isotonic", "sigmoid"}:
        raise ValueError(f"Unknown calibration method: {method}")

    p_val = model.predict_proba(X_val)[:, 1]

    if method == "isotonic":
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(p_val, y_val)
    else:
        calibrator = LogisticRegression(max_iter=1000)
        calibrator.fit(p_val.reshape(-1, 1), y_val)

    return PrefitCalibratedModel(model, calibrator, method)


class PrefitCalibratedModel:
    def __init__(self, base_model, fitted_calibrator, cal_method: str):
        self.base_model = base_model
        self.calibrator = fitted_calibrator
        self.method = cal_method
        self.classes_ = np.array([0, 1], dtype=int)

    def predict_proba(self, X):
        p = self.base_model.predict_proba(X)[:, 1]
        if self.method == "isotonic":
            p_cal = self.calibrator.transform(p)
        else:
            p_cal = self.calibrator.predict_proba(p.reshape(-1, 1))[:, 1]
        p_cal = np.clip(p_cal, 0.0, 1.0)
        return np.column_stack([1.0 - p_cal, p_cal])


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

    classes = np.unique(y_true)
    binary = len(classes) == 2

    # If only one class is present, classification metrics emit warnings; return nan for those.
    out = {
        "auroc": float(roc_auc_score(y_true, p)) if binary else float("nan"),
        "auprc": float(average_precision_score(y_true, p)) if binary else float("nan"),
        "f1": float(f1_score(y_true, y_hat, zero_division=0)) if binary else float("nan"),
        "balanced_acc": float(balanced_accuracy_score(y_true, y_hat)) if binary else float("nan"),
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

    # Bin counts to show support behind each point
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    counts, _ = np.histogram(p, bins=bins)
    centers = 0.5 * (bins[:-1] + bins[1:])

    fig, (ax_curve, ax_hist) = plt.subplots(
        2, 1, figsize=(6, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )

    ax_curve.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=1)
    ax_curve.plot(mean_pred, frac_pos, marker="o")
    ax_curve.set_ylabel("Fraction of positives")
    ax_curve.set_title(title)

    bar_widths = np.diff(bins)
    ax_hist.bar(centers, counts, width=bar_widths, align="center", alpha=0.7)
    ax_hist.set_ylabel("Count")
    ax_hist.set_xlabel("Mean predicted probability (bin centers)")

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
