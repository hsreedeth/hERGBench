"""
Reliability diagram split by Tanimoto similarity to nearest training neighbour.
Cluster-split test set only.

Usage:
    conda run -n hergbench-tdc python scripts/plot_reliability_by_sim.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

RUN_DIR = Path("reports/runs/2026-03-31_160747_seed42_stage1_signoff")
PRED_CSV = RUN_DIR / "predictions" / "test_preds_cluster_seed11_with_sim.csv"
OUT_PATH  = RUN_DIR / "figures" / "reliability_by_sim_cluster.png"

THRESHOLD = 0.56          # decision boundary used throughout the project
LOW_SIM_MAX  = 0.5        # "novel" compounds
HIGH_SIM_MIN = 0.7        # "familiar" compounds

COLORS = {
    "high": "#2166ac",    # blue
    "low":  "#d6604d",    # red-orange
    "mid":  "#999999",    # grey (shown muted in background)
}

SEED = 42

# ── helpers ──────────────────────────────────────────────────────────────────

def bootstrap_calibration(y: np.ndarray, p: np.ndarray,
                           n_bins: int = 5, strategy: str = "quantile",
                           n_boot: int = 2000, rng: np.random.Generator = None):
    """
    Returns (bin_centers, frac_pos, lower_ci, upper_ci) using bootstrap.
    strategy: 'uniform' | 'quantile'
    """
    if rng is None:
        rng = np.random.default_rng(SEED)

    def _calibrate(y_, p_):
        if strategy == "quantile":
            quantiles = np.linspace(0, 1, n_bins + 1)
            edges = np.quantile(p_, quantiles)
            edges[-1] += 1e-9          # include right edge
        else:
            edges = np.linspace(p_.min(), p_.max() + 1e-9, n_bins + 1)

        centers, fracs = [], []
        for lo, hi in zip(edges[:-1], edges[1:]):
            mask = (p_ >= lo) & (p_ < hi)
            if mask.sum() == 0:
                continue
            centers.append(p_[mask].mean())
            fracs.append(y_[mask].mean())
        return np.array(centers), np.array(fracs)

    centers, fracs = _calibrate(y, p)

    boot_fracs = []
    n = len(y)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        _, bf = _calibrate(y[idx], p[idx])
        if len(bf) == len(fracs):
            boot_fracs.append(bf)

    if boot_fracs:
        boot_arr = np.array(boot_fracs)
        lo_ci = np.percentile(boot_arr, 2.5, axis=0)
        hi_ci = np.percentile(boot_arr, 97.5, axis=0)
    else:
        lo_ci = fracs - 0.15
        hi_ci = fracs + 0.15

    return centers, fracs, lo_ci, hi_ci


# ── load data ─────────────────────────────────────────────────────────────────

df = pd.read_csv(PRED_CSV)

high = df[df["max_sim_to_train"] >= HIGH_SIM_MIN].copy()
low  = df[df["max_sim_to_train"] <  LOW_SIM_MAX].copy()
mid  = df[(df["max_sim_to_train"] >= LOW_SIM_MAX) &
          (df["max_sim_to_train"] <  HIGH_SIM_MIN)].copy()

n_high, n_low, n_mid = len(high), len(low), len(mid)

# ── calibration curves ────────────────────────────────────────────────────────

rng = np.random.default_rng(SEED)

# Low-sim: enough for 5 quantile bins
low_centers, low_fracs, low_lo, low_hi = bootstrap_calibration(
    low["y"].values, low["p_cal"].values,
    n_bins=5, strategy="quantile", rng=rng
)

# High-sim: only 4 points — aggregate to a single calibration point
high_y = high["y"].values
high_p = high["p_cal"].values
high_mean_p   = high_p.mean()
high_frac_pos = high_y.mean()

# ── figure layout ─────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(10, 4.6))
gs  = gridspec.GridSpec(1, 2, width_ratios=[1.45, 1], wspace=0.38,
                        left=0.08, right=0.97, top=0.88, bottom=0.14)

ax_cal  = fig.add_subplot(gs[0])   # reliability diagram
ax_dist = fig.add_subplot(gs[1])   # predicted-probability distributions

# ── Panel A: Reliability diagram ──────────────────────────────────────────────

p_all = df["p_cal"].values
p_lo_global = p_all.min()
p_hi_global = p_all.max()

# perfect calibration line — span the full predicted range with a margin
pad = 0.02
diag_lo = max(0, p_lo_global - pad)
diag_hi = min(1, p_hi_global + pad)
ax_cal.plot([diag_lo, diag_hi], [diag_lo, diag_hi],
            color="#444444", lw=1.2, ls="--", label="Perfect calibration", zorder=1)

# Shade no-skill band around 0.5 (full [0,1] y-range reference at the threshold)
ax_cal.axhline(0.5, color="#bbbbbb", lw=0.8, ls=":", zorder=0)

# Low-sim calibration curve with bootstrap CI
ax_cal.fill_between(low_centers, low_lo, low_hi,
                    color=COLORS["low"], alpha=0.18, zorder=2)
ax_cal.plot(low_centers, low_fracs,
            color=COLORS["low"], lw=2, marker="o", ms=6, zorder=3,
            label=f"Low similarity (<{LOW_SIM_MAX}), n={n_low}")

# Annotate bin counts
for xc, yc in zip(low_centers, low_fracs):
    ax_cal.annotate("", xy=(xc, yc), xytext=(xc, yc))   # just markers

# High-sim: single aggregated calibration point (n=4 too small to bin further)
ax_cal.scatter([high_mean_p], [high_frac_pos],
               color=COLORS["high"], s=90, zorder=5, marker="D",
               label=f"High similarity (≥{HIGH_SIM_MIN}), n={n_high} (single bin)",
               edgecolors="white", linewidths=0.8)
ax_cal.annotate(f"frac+={high_frac_pos:.2f}", xy=(high_mean_p, high_frac_pos),
                xytext=(high_mean_p + 0.0004, high_frac_pos - 0.1),
                fontsize=7.5, color=COLORS["high"],
                arrowprops=dict(arrowstyle="-", color=COLORS["high"], lw=0.8))

# Annotate the probability collapse
x_mid = (p_lo_global + p_hi_global) / 2
ax_cal.annotate(
    f"All predicted\nprobabilities lie\nin [{p_lo_global:.3f}, {p_hi_global:.3f}]\n(range = {p_hi_global-p_lo_global:.3f})",
    xy=(x_mid, 0.08),
    fontsize=7.5, color="#555555", ha="center",
    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cccccc", lw=0.8),
)

# Collapsed range bracket on x-axis
ax_cal.annotate("", xy=(p_hi_global, -0.04), xytext=(p_lo_global, -0.04),
                xycoords=("data", "axes fraction"),
                textcoords=("data", "axes fraction"),
                arrowprops=dict(arrowstyle="<->", color="#888888", lw=1.1),
                annotation_clip=False)

ax_cal.set_xlim(p_lo_global - 0.003, p_hi_global + 0.003)
ax_cal.set_ylim(-0.05, 1.1)
ax_cal.set_xlabel("Mean predicted probability", fontsize=10)
ax_cal.set_ylabel("Fraction positive (observed)", fontsize=10)
ax_cal.set_title("A  Reliability diagram — cluster split", fontsize=10.5, loc="left", fontweight="bold")
ax_cal.legend(fontsize=8, framealpha=0.9, loc="upper left")
ax_cal.tick_params(labelsize=8.5)

# Threshold marker
ax_cal.axvline(THRESHOLD, color="#777777", lw=0.9, ls=":", alpha=0.7)
ax_cal.text(THRESHOLD + 0.0002, 1.04, f"threshold\n({THRESHOLD})",
            fontsize=7, color="#777777", ha="left", va="top")

# ── Panel B: Predicted probability distributions ──────────────────────────────

groups = [
    (df[df["max_sim_to_train"] <  LOW_SIM_MAX],  COLORS["low"],  f"Low sim <{LOW_SIM_MAX}\n(n={n_low})"),
    (df[(df["max_sim_to_train"] >= LOW_SIM_MAX) &
        (df["max_sim_to_train"] <  HIGH_SIM_MIN)], COLORS["mid"], f"Mid sim\n(n={n_mid})"),
    (df[df["max_sim_to_train"] >= HIGH_SIM_MIN], COLORS["high"], f"High sim ≥{HIGH_SIM_MIN}\n(n={n_high})"),
]

yticks, ylabels = [], []
for i, (sub, col, lbl) in enumerate(groups):
    p_vals = sub["p_cal"].values
    y_base = i * 1.0

    # KDE-like strip using kernel density estimate
    from scipy.stats import gaussian_kde
    if len(p_vals) >= 3:
        try:
            kde = gaussian_kde(p_vals, bw_method=0.2)
            x_grid = np.linspace(p_vals.min() - 0.001, p_vals.max() + 0.001, 300)
            dens   = kde(x_grid)
            dens   = dens / dens.max() * 0.38        # normalise height
            ax_dist.fill_between(x_grid, y_base, y_base + dens, color=col, alpha=0.35)
            ax_dist.plot(x_grid, y_base + dens, color=col, lw=1.4)
        except Exception:
            pass

    # Rug
    jit = np.random.default_rng(SEED + i).uniform(-0.02, 0.02, size=len(p_vals))
    ax_dist.scatter(p_vals, y_base + 0.02 + jit, color=col, s=16, alpha=0.7, zorder=3)

    # Median marker
    ax_dist.axvline(np.median(p_vals), ymin=y_base / (len(groups) * 1.0 + 0.3),
                    ymax=(y_base + 0.45) / (len(groups) * 1.0 + 0.3),
                    color=col, lw=1.5, ls="--", alpha=0.8)

    yticks.append(y_base + 0.15)
    ylabels.append(lbl)

ax_dist.axvline(THRESHOLD, color="#777777", lw=0.9, ls=":", alpha=0.8,
                label=f"Threshold ({THRESHOLD})")
ax_dist.set_xlabel("Predicted probability", fontsize=10)
ax_dist.set_yticks(yticks)
ax_dist.set_yticklabels(ylabels, fontsize=8.5)
ax_dist.set_xlim(p_lo_global - 0.004, p_hi_global + 0.004)
ax_dist.set_title("B  Predicted-probability collapse", fontsize=10.5, loc="left", fontweight="bold")
ax_dist.tick_params(axis="x", labelsize=8.5)
ax_dist.legend(fontsize=8, loc="upper right", framealpha=0.9)

# Annotate range
ax_dist.annotate(
    f"Total range: {p_hi_global - p_lo_global:.4f}",
    xy=(x_mid, len(groups) * 1.0 - 0.15),
    fontsize=8, ha="center", color="#555555",
    bbox=dict(boxstyle="round,pad=0.25", fc="#f8f8f8", ec="#cccccc", lw=0.8),
)

# ── save ──────────────────────────────────────────────────────────────────────

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT_PATH, dpi=180, bbox_inches="tight")
print(f"Saved → {OUT_PATH}")
