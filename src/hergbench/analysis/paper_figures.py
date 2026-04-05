# src/hergbench/analysis/paper_figures.py
"""Publication-quality figures for the hERGBench Stage 2 paper.

Figure inventory
----------------
fig1_gradient_6panel        2×3 AUROC (and Brier) heatmap-style panels,
                            dataset × split-type, ±1σ error bands.
fig2_reliability_by_bin     2×2 reliability diagrams per Tanimoto sim-bin
                            (ChEMBL scaffold by default).
fig3_ad_performance_split   Per-bin AUROC bar chart for TDC cluster, highlighting
                            D-MPNN vs XGBoost divergence across similarity zones.
fig4_cross_model_comparison Grouped dot plot: D-MPNN vs XGBoost across all
                            dataset × split combinations.
fig5_calibration_effect     Brier score before / after Platt/isotonic calibration.

Design constraints (JCIM)
--------------------------
  Single column : 3.25 in
  Double column : 7.00 in
  DPI           : 300 (PNG) + PDF vector copy
  Colours       : #3266ad (D-MPNN/blue), #D85A30 (XGBoost/coral) — colorblind-safe
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Design tokens ─────────────────────────────────────────────────────────────

BLUE = "#3266ad"    # D-MPNN / chemprop
CORAL = "#D85A30"   # XGBoost
GREY = "#888888"    # reference lines / uncalibrated
LIGHT_BLUE = "#a6c4e8"
LIGHT_CORAL = "#f0b8a0"

SIM_BIN_ORDER = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
SIM_BIN_LABELS = ["<0.3", "0.3–0.5", "0.5–0.7", ">0.7"]
# Shading from low to high similarity
SIM_BIN_COLORS = ["#d0e4f7", "#8bb8e8", "#4a8fd4", "#1a5fa8"]

SINGLE_COL = 3.25   # inches
DOUBLE_COL = 7.00   # inches

# ── Data paths ─────────────────────────────────────────────────────────────────

def _reports(repo_root: Path) -> Path:
    return repo_root / "reports"


def _load_stage1_xgboost_agg(repo_root: Path, dataset: str) -> pd.DataFrame:
    """Load Stage 1 XGBoost aggregated AD-bin results, adding 'model' and 'dataset' cols."""
    if dataset == "tdc":
        p = _reports(repo_root) / "reports" / "multiseed_analysis_tdc" / "multiseed_ad_bins_aggregated.csv"
    else:
        p = _reports(repo_root) / "reports" / "chembl_multiseed_analysis" / "multiseed_ad_bins_aggregated.csv"

    if not p.exists():
        logger.warning("Stage 1 XGBoost data not found: %s", p)
        return pd.DataFrame()

    df = pd.read_csv(p)
    df["model"] = "xgboost"
    if "dataset" not in df.columns:
        df["dataset"] = dataset
    return df


def _load_stage2_dmnn_agg(repo_root: Path, dataset: str, calibrated: bool = False) -> pd.DataFrame:
    """Load Stage 2 D-MPNN aggregated AD-bin results."""
    subdir = "chembl_stage2_multiseed_analysis" if dataset == "chembl" else "stage2_multiseed_analysis"
    suffix = "_calibrated" if calibrated else ""
    fname = f"stage2_ad_bins{suffix}_aggregated.csv"

    # Prefer the export directory if local aggregated is stale
    candidates = [
        _reports(repo_root) / subdir / fname,
    ]
    # Also look in any stage2_export_* directory
    for export_dir in sorted(repo_root.glob("stage2_export_*"), reverse=True):
        candidates.append(export_dir / "reports" / subdir / fname)

    for p in candidates:
        if p.exists():
            df = pd.read_csv(p)
            df["model"] = "chemprop_dmnn"
            if "dataset" not in df.columns:
                df["dataset"] = dataset
            return df

    label = "calibrated" if calibrated else "uncalibrated"
    logger.warning("Stage 2 D-MPNN %s data not found for dataset=%s", label, dataset)
    return pd.DataFrame()


def _load_cross_model_summary(repo_root: Path) -> pd.DataFrame:
    """Load the cross-model macro-averaged summary."""
    candidates = [
        _reports(repo_root) / "cross_model_comparison" / "cross_model_summary.csv",
    ]
    for export_dir in sorted(repo_root.glob("stage2_export_*"), reverse=True):
        candidates.append(export_dir / "reports" / "cross_model_comparison" / "cross_model_summary.csv")

    for p in candidates:
        if p.exists():
            return pd.read_csv(p)

    logger.warning("Cross-model summary CSV not found.")
    return pd.DataFrame()


def _collect_test_preds_by_bin(
    repo_root: Path,
    dataset: str,
    split_type: str,
) -> pd.DataFrame:
    """Concatenate all per-seed test_preds_{split_type}_seed*_with_sim.csv files.

    Looks in every run directory under reports/runs/ that matches the pattern.
    Returns empty DataFrame if no files are found.
    """
    runs_root = _reports(repo_root) / "runs"
    if not runs_root.exists():
        # Try export directory
        for export_dir in sorted(repo_root.glob("stage2_export_*"), reverse=True):
            candidate = export_dir / "reports" / "runs"
            if candidate.exists():
                runs_root = candidate
                break

    if not runs_root.exists():
        return pd.DataFrame()

    dfs = []
    pattern = f"*stage2_chemprop_{split_type}_*"
    if dataset == "chembl":
        pattern = f"*stage2_chemprop_{split_type}_seed*_torch42"

    for run_dir in sorted(runs_root.glob(pattern)):
        for seed_file in sorted(run_dir.glob(f"predictions/test_preds_{split_type}_seed*_with_sim.csv")):
            try:
                df = pd.read_csv(seed_file)
                # Extract seed from filename
                import re as _re
                m = _re.search(r"seed(\d+)", seed_file.name)
                df["_seed"] = int(m.group(1)) if m else 0
                dfs.append(df)
            except Exception as exc:
                logger.debug("Could not read %s: %s", seed_file, exc)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


# ── Utility ────────────────────────────────────────────────────────────────────

def _savefig(fig, output_dir: Path, stem: str, dpi: int = 300) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        path = output_dir / f"{stem}.{ext}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        logger.info("Saved %s", path)


def _sim_bin_pos(bin_label: str) -> int:
    return SIM_BIN_ORDER.index(bin_label) if bin_label in SIM_BIN_ORDER else -1


# ── Figure 1: Gradient 6-panel ────────────────────────────────────────────────

def fig_gradient_6panel(
    datasets: list[str],
    output_dir: Path,
    repo_root: Path,
    metric: str = "auroc",
    dpi: int = 300,
) -> None:
    """2×3 panel grid: rows=dataset, cols=split_type.

    Each panel plots <metric>_mean (±1σ) vs Tanimoto sim-bin for D-MPNN and XGBoost.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    split_types = ["cluster", "random", "scaffold"]
    ds_labels = {"tdc": "TDC", "chembl": "ChEMBL"}

    n_rows = len(datasets)
    fig, axes = plt.subplots(
        n_rows, 3,
        figsize=(DOUBLE_COL, n_rows * 2.4),
        sharey=False,
    )
    if n_rows == 1:
        axes = axes[np.newaxis, :]

    metric_label = metric.upper() if metric in ("auroc", "auprc") else metric.replace("_", " ").title()

    for r, ds in enumerate(datasets):
        xgb_df = _load_stage1_xgboost_agg(repo_root, ds)
        dmnn_df = _load_stage2_dmnn_agg(repo_root, ds)

        for c, st in enumerate(split_types):
            ax = axes[r, c]

            for model_df, color, lbl, facecolor in [
                (dmnn_df, BLUE, "D-MPNN", LIGHT_BLUE),
                (xgb_df, CORAL, "XGBoost", LIGHT_CORAL),
            ]:
                if model_df.empty:
                    continue
                sub = model_df[model_df["split_type"] == st].copy()
                if sub.empty:
                    continue

                # Order by sim_bin
                sub["_ord"] = sub["sim_bin"].map(lambda b: _sim_bin_pos(b) if b in SIM_BIN_ORDER else 99)
                sub = sub.sort_values("_ord")
                sub = sub[sub["sim_bin"].isin(SIM_BIN_ORDER)]

                x = np.arange(len(sub))
                y = sub[f"{metric}_mean"].to_numpy(dtype=float)
                yerr = sub[f"{metric}_std"].to_numpy(dtype=float)
                yerr = np.nan_to_num(yerr, nan=0.0)

                ax.fill_between(x, y - yerr, y + yerr, color=facecolor, alpha=0.5)
                ax.plot(x, y, "o-", color=color, linewidth=1.6, markersize=5, label=lbl)

            ax.set_xticks(range(len(SIM_BIN_ORDER)))
            ax.set_xticklabels(SIM_BIN_LABELS, fontsize=7, rotation=30, ha="right")
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
            ax.tick_params(axis="y", labelsize=7)
            ax.set_ylim(0.45, 1.02)
            ax.axhline(0.5, color="black", linewidth=0.6, linestyle="--", alpha=0.4)

            if r == 0:
                ax.set_title(st.capitalize(), fontsize=9, fontweight="bold")
            if c == 0:
                ax.set_ylabel(f"{ds_labels.get(ds, ds)}\n{metric_label}", fontsize=8)
            if r == n_rows - 1 and c == 1:
                ax.legend(loc="lower right", fontsize=7, framealpha=0.8)

    fig.tight_layout(h_pad=1.2, w_pad=0.8)
    _savefig(fig, output_dir, "fig1_gradient_6panel", dpi=dpi)
    plt.close(fig)


# ── Figure 2: Reliability by bin ──────────────────────────────────────────────

def fig_reliability_by_bin(
    output_dir: Path,
    repo_root: Path,
    dataset: str = "chembl",
    split_type: str = "scaffold",
    dpi: int = 300,
    n_bins: int = 10,
) -> None:
    """2×2 reliability diagrams per Tanimoto sim-bin.

    Uses all available seed runs for the given dataset/split_type, combined.
    Falls back to a placeholder if prediction files are unavailable.
    """
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve

    preds_df = _collect_test_preds_by_bin(repo_root, dataset, split_type)

    if preds_df.empty:
        logger.warning(
            "No per-prediction data found for %s/%s — skipping fig_reliability_by_bin.",
            dataset, split_type,
        )
        return

    fig, axes = plt.subplots(2, 2, figsize=(DOUBLE_COL, DOUBLE_COL * 0.85), sharex=True, sharey=True)
    axes = axes.ravel()

    for i, sim_bin in enumerate(SIM_BIN_ORDER):
        ax = axes[i]
        sub = preds_df[preds_df["sim_bin"] == sim_bin].copy()

        ax.plot([0, 1], [0, 1], "k--", linewidth=0.8, label="Perfect")

        if sub.empty or len(sub) < 5:
            ax.text(0.5, 0.5, "n < 5\n(insufficient data)",
                    ha="center", va="center", transform=ax.transAxes, fontsize=8, color=GREY)
        else:
            y_true = sub["y"].astype(int).to_numpy()
            p_cal = sub["p_cal"].astype(float).to_numpy()

            if y_true.sum() == 0 or y_true.sum() == len(y_true):
                ax.text(0.5, 0.5, "single class\nin bin",
                        ha="center", va="center", transform=ax.transAxes, fontsize=8, color=GREY)
            else:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        frac_pos, mean_pred = calibration_curve(y_true, p_cal, n_bins=n_bins, strategy="uniform")
                    ax.plot(mean_pred, frac_pos, "o-", color=BLUE, linewidth=1.5,
                            markersize=4, label=f"D-MPNN (n={len(sub)})")
                    ax.fill_between(mean_pred, frac_pos, mean_pred,
                                    alpha=0.15, color=BLUE, label="Calibration gap")
                except Exception as exc:
                    logger.debug("calibration_curve failed for bin %s: %s", sim_bin, exc)

        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.set_title(f"Sim bin: {SIM_BIN_LABELS[i]}", fontsize=9, fontweight="bold")
        ax.tick_params(labelsize=7)
        if i in (0, 2):
            ax.set_ylabel("Fraction positive", fontsize=8)
        if i in (2, 3):
            ax.set_xlabel("Mean predicted probability", fontsize=8)
        if not sub.empty and len(sub) >= 5:
            ax.legend(fontsize=6, loc="upper left")

    fig.suptitle(
        f"Reliability by Tanimoto bin\n({dataset.upper()} {split_type} — D-MPNN, all seeds)",
        fontsize=9, y=1.01,
    )
    fig.tight_layout()
    _savefig(fig, output_dir, "fig2_reliability_by_bin", dpi=dpi)
    plt.close(fig)


# ── Figure 3: AD performance split ───────────────────────────────────────────

def fig_ad_performance_split(
    output_dir: Path,
    repo_root: Path,
    dataset: str = "tdc",
    split_type: str = "cluster",
    dpi: int = 300,
) -> None:
    """Grouped bar chart: AUROC across sim-bins, D-MPNN vs XGBoost.

    Highlights how model performance diverges across the applicability domain
    boundary — particularly in the >0.7 high-similarity zone.
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    xgb_df = _load_stage1_xgboost_agg(repo_root, dataset)
    dmnn_df = _load_stage2_dmnn_agg(repo_root, dataset)

    if xgb_df.empty and dmnn_df.empty:
        logger.warning("No data for fig_ad_performance_split, skipping.")
        return

    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, 2.6), sharey=False)

    for ax_idx, (df, color, model_label) in enumerate([
        (dmnn_df, BLUE, "D-MPNN"),
        (xgb_df, CORAL, "XGBoost"),
    ]):
        ax = axes[ax_idx]
        if df.empty:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(model_label, fontsize=9)
            continue

        sub = df[df["split_type"] == split_type].copy()
        sub["_ord"] = sub["sim_bin"].map(lambda b: _sim_bin_pos(b) if b in SIM_BIN_ORDER else 99)
        sub = sub.sort_values("_ord")
        sub = sub[sub["sim_bin"].isin(SIM_BIN_ORDER)]

        x = np.arange(len(sub))
        y = sub["auroc_mean"].to_numpy(dtype=float)
        yerr = sub["auroc_std"].to_numpy(dtype=float)
        yerr = np.nan_to_num(yerr, nan=0.0)

        bar_colors = [SIM_BIN_COLORS[_sim_bin_pos(b)] for b in sub["sim_bin"]]
        bars = ax.bar(x, y, color=bar_colors, edgecolor="white", linewidth=0.5, zorder=2)
        ax.errorbar(x, y, yerr=yerr, fmt="none", color="black",
                    capsize=3, linewidth=1.1, zorder=3)

        ax.axhline(0.5, color="black", linestyle="--", linewidth=0.7, alpha=0.5, zorder=1)
        ax.set_ylim(0.0, 1.05)
        ax.set_xticks(x)
        ax.set_xticklabels(SIM_BIN_LABELS, fontsize=7.5, rotation=30, ha="right")
        ax.tick_params(axis="y", labelsize=7)
        ax.set_title(f"{model_label}", fontsize=9, fontweight="bold", color=color)
        if ax_idx == 0:
            ax.set_ylabel("AUROC", fontsize=8)

        # Annotate n
        ns = sub["n_total"].astype(int).tolist() if "n_total" in sub.columns else [None] * len(sub)
        for xi, ni in zip(x, ns):
            if ni is not None:
                ax.text(xi, 0.03, f"n={ni}", ha="center", va="bottom",
                        fontsize=6, color="white", fontweight="bold")

    ds_label = {"tdc": "TDC", "chembl": "ChEMBL"}.get(dataset, dataset)
    fig.suptitle(
        f"AUROC across applicability domain — {ds_label} {split_type}",
        fontsize=9, y=1.01,
    )
    fig.tight_layout(w_pad=1.2)
    _savefig(fig, output_dir, "fig3_ad_performance_split", dpi=dpi)
    plt.close(fig)


# ── Figure 4: Cross-model comparison ──────────────────────────────────────────

def fig_cross_model_comparison(
    output_dir: Path,
    repo_root: Path,
    metric: str = "auroc",
    dpi: int = 300,
) -> None:
    """Grouped dot plot: D-MPNN vs XGBoost for all dataset × split combinations.

    One row per (dataset, split_type), dots = metric_mean, error bars = ±1σ.
    """
    import matplotlib.pyplot as plt

    df = _load_cross_model_summary(repo_root)
    if df.empty:
        logger.warning("Cross-model summary not found — skipping fig_cross_model_comparison.")
        return

    metric_mean = f"{metric}_mean"
    metric_std = f"{metric}_std"
    if metric_mean not in df.columns:
        logger.error("Column %s not in cross-model summary.", metric_mean)
        return

    # Build rows: one label per (dataset, split_type)
    df["_label"] = df["dataset"].str.upper() + " / " + df["split_type"].str.capitalize()
    labels = df["_label"].unique().tolist()
    labels = sorted(labels)

    fig, ax = plt.subplots(figsize=(SINGLE_COL * 1.5, max(2.5, 0.55 * len(labels) + 0.8)))

    model_style = {
        "chemprop_dmnn": (BLUE, "D-MPNN", "o"),
        "xgboost": (CORAL, "XGBoost", "s"),
    }
    offsets = {"chemprop_dmnn": 0.18, "xgboost": -0.18}

    for i, label in enumerate(reversed(labels)):
        row = df[df["_label"] == label]
        for model, (color, model_label, marker) in model_style.items():
            m_row = row[row["model"] == model]
            if m_row.empty:
                continue
            val = float(m_row[metric_mean].values[0])
            err = float(m_row[metric_std].values[0]) if metric_std in m_row.columns else 0.0
            err = 0.0 if np.isnan(err) else err
            y = i + offsets[model]
            ax.errorbar(val, y, xerr=err, fmt=marker, color=color,
                        markersize=6, capsize=3, linewidth=1.2, elinewidth=1.0,
                        label=model_label if i == 0 else "_nolegend_")

    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(reversed(labels), fontsize=7.5)
    ax.set_xlabel(metric.upper() if metric in ("auroc", "auprc") else metric, fontsize=8)
    ax.set_xlim(0.5, 1.02)
    ax.axvline(0.5, color="black", linestyle="--", linewidth=0.6, alpha=0.4)
    ax.tick_params(axis="x", labelsize=7)

    handles = [
        plt.Line2D([0], [0], marker="o", color=BLUE, linestyle="none", markersize=7, label="D-MPNN"),
        plt.Line2D([0], [0], marker="s", color=CORAL, linestyle="none", markersize=7, label="XGBoost"),
    ]
    ax.legend(handles=handles, fontsize=7, loc="lower right", framealpha=0.85)
    ax.set_title("Cross-model comparison", fontsize=9, fontweight="bold")

    fig.tight_layout()
    _savefig(fig, output_dir, "fig4_cross_model_comparison", dpi=dpi)
    plt.close(fig)


# ── Figure 5: Calibration effect ──────────────────────────────────────────────

def fig_calibration_effect(
    datasets: list[str],
    output_dir: Path,
    repo_root: Path,
    metric: str = "brier",
    dpi: int = 300,
) -> None:
    """Paired dot/arrow plot: Brier score before vs after Platt/isotonic calibration.

    One panel per dataset; one point per (split_type × sim_bin).
    Arrows point from uncalibrated to calibrated — downward = improvement.
    """
    import matplotlib.pyplot as plt

    n_ds = len(datasets)
    fig, axes = plt.subplots(1, n_ds, figsize=(SINGLE_COL * n_ds + 0.4, 3.2), sharey=False)
    if n_ds == 1:
        axes = [axes]

    metric_mean = f"{metric}_mean"
    metric_label = "Brier score" if metric == "brier" else metric.upper()

    for ax, ds in zip(axes, datasets):
        uncal_df = _load_stage2_dmnn_agg(repo_root, ds, calibrated=False)
        cal_df = _load_stage2_dmnn_agg(repo_root, ds, calibrated=True)

        if uncal_df.empty or cal_df.empty:
            ax.text(0.5, 0.5,
                    "Calibrated data\nnot yet generated.\nRun: hergbench calibrate-stage2",
                    ha="center", va="center", transform=ax.transAxes,
                    fontsize=7.5, color=GREY, style="italic")
            ax.set_title(ds.upper(), fontsize=9)
            continue

        uncal_df = uncal_df[uncal_df["sim_bin"].isin(SIM_BIN_ORDER)]
        cal_df = cal_df[cal_df["sim_bin"].isin(SIM_BIN_ORDER)]

        merged = uncal_df.merge(
            cal_df,
            on=["dataset", "split_type", "sim_bin"],
            suffixes=("_uncal", "_cal"),
        )

        x_uncal_col = f"{metric_mean}_uncal"
        x_cal_col = f"{metric_mean}_cal"
        if x_uncal_col not in merged.columns or x_cal_col not in merged.columns:
            ax.text(0.5, 0.5, "Column mismatch", ha="center", va="center",
                    transform=ax.transAxes, fontsize=8)
            continue

        split_colors = {"cluster": "#4878cf", "random": "#6acc65", "scaffold": "#d65f5f"}
        handles_seen: set[str] = set()

        for i, row in merged.iterrows():
            x0 = row[x_uncal_col]
            x1 = row[x_cal_col]
            y = _sim_bin_pos(row["sim_bin"])
            if y < 0:
                continue
            st = row["split_type"]
            color = split_colors.get(st, GREY)
            ax.annotate(
                "", xy=(x1, y), xytext=(x0, y),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=1.3),
            )
            if st not in handles_seen:
                ax.plot([], [], "-", color=color, linewidth=2, label=st.capitalize())
                handles_seen.add(st)
            ax.plot(x0, y, "o", color=color, markersize=5, alpha=0.7, zorder=3)
            ax.plot(x1, y, "D", color=color, markersize=5, zorder=4)

        ax.set_yticks(range(len(SIM_BIN_ORDER)))
        ax.set_yticklabels(SIM_BIN_LABELS, fontsize=7.5)
        ax.set_xlabel(f"{metric_label} (↓ better)", fontsize=8)
        ax.set_title(ds.upper(), fontsize=9, fontweight="bold")
        ax.tick_params(axis="x", labelsize=7)
        ax.legend(fontsize=6.5, loc="upper right", framealpha=0.85)

        # Legend: circle=uncal, diamond=cal
        from matplotlib.lines import Line2D
        ax.legend(
            [Line2D([0], [0], marker="o", color=GREY, linestyle="none", markersize=5),
             Line2D([0], [0], marker="D", color=GREY, linestyle="none", markersize=5)]
            + [plt.Line2D([0], [0], color=c, linewidth=2, label=st.capitalize())
               for st, c in split_colors.items()],
            ["Uncalibrated", "Calibrated"]
            + [st.capitalize() for st in split_colors],
            fontsize=6, loc="upper right", framealpha=0.85,
        )

    fig.suptitle(
        f"Calibration effect on {metric_label}  (D-MPNN)",
        fontsize=9, y=1.01,
    )
    fig.tight_layout(w_pad=1.4)
    _savefig(fig, output_dir, "fig5_calibration_effect", dpi=dpi)
    plt.close(fig)


# ── Master function ────────────────────────────────────────────────────────────

def generate_all_figures(
    datasets: Optional[list[str]] = None,
    output_dir: Path = Path("reports/paper_figures"),
    repo_root: Optional[Path] = None,
    figures: Optional[list[str]] = None,
    dpi: int = 300,
) -> None:
    """Generate all five publication figures.

    Parameters
    ----------
    datasets : list of "tdc" and/or "chembl". Defaults to both.
    output_dir : directory to write PNG + PDF files.
    repo_root : repository root. Defaults to cwd.
    figures : subset of figure IDs to render ("fig1"..."fig5"). Defaults to all.
    dpi : output resolution for PNG files (default 300).
    """
    if datasets is None:
        datasets = ["tdc", "chembl"]
    if figures is None:
        figures = ["fig1", "fig2", "fig3", "fig4", "fig5"]
    if repo_root is None:
        repo_root = Path.cwd()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend for script use

    if "fig1" in figures:
        logger.info("Generating fig1_gradient_6panel ...")
        try:
            fig_gradient_6panel(datasets=datasets, output_dir=output_dir, repo_root=repo_root, dpi=dpi)
        except Exception as exc:
            logger.error("fig1 failed: %s", exc, exc_info=True)

    if "fig2" in figures:
        logger.info("Generating fig2_reliability_by_bin ...")
        try:
            fig_reliability_by_bin(
                output_dir=output_dir, repo_root=repo_root,
                dataset="chembl", split_type="scaffold", dpi=dpi,
            )
        except Exception as exc:
            logger.error("fig2 failed: %s", exc, exc_info=True)

    if "fig3" in figures:
        logger.info("Generating fig3_ad_performance_split ...")
        try:
            fig_ad_performance_split(
                output_dir=output_dir, repo_root=repo_root,
                dataset="tdc", split_type="cluster", dpi=dpi,
            )
        except Exception as exc:
            logger.error("fig3 failed: %s", exc, exc_info=True)

    if "fig4" in figures:
        logger.info("Generating fig4_cross_model_comparison ...")
        try:
            fig_cross_model_comparison(output_dir=output_dir, repo_root=repo_root, dpi=dpi)
        except Exception as exc:
            logger.error("fig4 failed: %s", exc, exc_info=True)

    if "fig5" in figures:
        logger.info("Generating fig5_calibration_effect ...")
        try:
            fig_calibration_effect(
                datasets=datasets, output_dir=output_dir, repo_root=repo_root, dpi=dpi,
            )
        except Exception as exc:
            logger.error("fig5 failed: %s", exc, exc_info=True)

    logger.info("All figures written to %s", output_dir)
