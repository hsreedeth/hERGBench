#!/usr/bin/env python
"""Create a ChEMBL-only AUROC/Brier companion figure from cross-model AD-bin summaries.

This script reads the canonical cross-model AD-bin summary, filters to the
24 ChEMBL rows needed for the three split types and four similarity bins, then
creates two new figures:

1. Dual-axis companion figure:
   - AUROC on the left y-axis
   - Brier score on the right y-axis
2. Stacked backup figure:
   - top row AUROC
   - bottom row Brier

No existing artifacts are overwritten. The script raises if any target output
path already exists.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from hergbench.analysis.paper_figures import (
        BLUE,
        CORAL,
        DOUBLE_COL,
        LIGHT_BLUE,
        LIGHT_CORAL,
        SIM_BIN_LABELS,
        SIM_BIN_ORDER,
    )
except Exception:
    BLUE = "#3266ad"
    CORAL = "#D85A30"
    LIGHT_BLUE = "#a6c4e8"
    LIGHT_CORAL = "#f0b8a0"
    DOUBLE_COL = 7.00
    SIM_BIN_ORDER = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
    SIM_BIN_LABELS = ["<0.3", "0.3–0.5", "0.5–0.7", ">0.7"]

SPLIT_ORDER = ["cluster", "random", "scaffold"]
MODEL_ORDER = ["chemprop_dmnn", "xgboost"]
MODEL_LABELS = {
    "chemprop_dmnn": "D-MPNN",
    "xgboost": "XGBoost",
}
SPLIT_LABELS = {
    "cluster": "CLUSTER",
    "random": "RANDOM",
    "scaffold": "SCAFFOLD",
}
MODEL_STYLES = {
    "chemprop_dmnn": {
        "color": BLUE,
        "fill": LIGHT_BLUE,
        "marker": "o",
    },
    "xgboost": {
        "color": CORAL,
        "fill": LIGHT_CORAL,
        "marker": "o",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Make a ChEMBL-only AUROC/Brier companion figure from cross-model AD-bin summaries."
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Optional input CSV. Defaults to the canonical cross_model_ad_bins.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "reports" / "cross_model_comparison"),
        help="Directory for new output figures.",
    )
    return parser.parse_args()


def resolve_input_path(explicit_input: str | None) -> Path:
    if explicit_input is not None:
        path = Path(explicit_input).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input CSV not found: {path}")
        return path

    candidates = [
        REPO_ROOT / "reports" / "cross_model_comparison" / "cross_model_ad_bins.csv",
    ]
    for export_dir in sorted(REPO_ROOT.glob("stage2_export_*"), reverse=True):
        candidates.append(export_dir / "reports" / "cross_model_comparison" / "cross_model_ad_bins.csv")

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError("Could not locate cross_model_ad_bins.csv in canonical reports locations.")


def load_plot_rows(input_path: Path) -> pd.DataFrame:
    df = pd.read_csv(input_path)

    required_cols = {
        "dataset",
        "split_type",
        "sim_bin",
        "model",
        "auroc_mean",
        "auroc_std",
        "brier_mean",
        "brier_std",
    }
    missing = sorted(required_cols - set(df.columns))
    if missing:
        raise ValueError(f"Input CSV missing required columns: {missing}")

    plot_df = df[
        (df["dataset"] == "chembl")
        & (df["split_type"].isin(SPLIT_ORDER))
        & (df["sim_bin"].isin(SIM_BIN_ORDER))
        & (df["model"].isin(MODEL_ORDER))
    ].copy()

    plot_df["split_type"] = pd.Categorical(plot_df["split_type"], categories=SPLIT_ORDER, ordered=True)
    plot_df["sim_bin"] = pd.Categorical(plot_df["sim_bin"], categories=SIM_BIN_ORDER, ordered=True)
    plot_df["model"] = pd.Categorical(plot_df["model"], categories=MODEL_ORDER, ordered=True)
    plot_df = plot_df.sort_values(["split_type", "sim_bin", "model"]).reset_index(drop=True)

    expected_rows = len(SPLIT_ORDER) * len(SIM_BIN_ORDER) * len(MODEL_ORDER)
    if len(plot_df) != expected_rows:
        raise ValueError(f"Expected {expected_rows} ChEMBL plotting rows, found {len(plot_df)}.")

    counts = plot_df.groupby(["split_type", "sim_bin"], observed=True)["model"].nunique()
    if (counts != len(MODEL_ORDER)).any():
        raise ValueError("Not all split/bin groups contain both D-MPNN and XGBoost rows.")

    return plot_df


def compute_brier_limits(plot_df: pd.DataFrame) -> tuple[float, float]:
    lower = pd.to_numeric(plot_df["brier_mean"], errors="coerce") - pd.to_numeric(plot_df["brier_std"], errors="coerce").fillna(0.0)
    upper = pd.to_numeric(plot_df["brier_mean"], errors="coerce") + pd.to_numeric(plot_df["brier_std"], errors="coerce").fillna(0.0)
    low = float(np.nanmin(lower.to_numpy()))
    high = float(np.nanmax(upper.to_numpy()))
    margin = max(0.01, 0.08 * (high - low))
    return max(0.0, low - margin), high + margin


def ensure_new_outputs(paths: list[Path]) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing output artifact(s):\n" + "\n".join(existing)
        )


def print_rows_used(plot_df: pd.DataFrame) -> None:
    printable = plot_df.copy()
    printable["split_type"] = printable["split_type"].astype(str).map(SPLIT_LABELS)
    printable["model"] = printable["model"].astype(str).map(MODEL_LABELS)
    print("Rows used for plotting:")
    print(
        printable[
            [
                "dataset",
                "split_type",
                "sim_bin",
                "model",
                "n_mean",
                "n_seeds",
                "auroc_mean",
                "auroc_std",
                "brier_mean",
                "brier_std",
            ]
        ].to_string(index=False)
    )


def build_series_handles() -> list[Line2D]:
    return [
        Line2D([0], [0], color=BLUE, marker="o", linestyle="-", linewidth=1.8, markersize=5, label="D-MPNN AUROC"),
        Line2D([0], [0], color=CORAL, marker="o", linestyle="-", linewidth=1.8, markersize=5, label="XGBoost AUROC"),
        Line2D([0], [0], color=BLUE, marker="o", linestyle="--", linewidth=1.6, markersize=4, alpha=0.9, label="D-MPNN Brier"),
        Line2D([0], [0], color=CORAL, marker="o", linestyle="--", linewidth=1.6, markersize=4, alpha=0.9, label="XGBoost Brier"),
    ]


def save_dual_axis_figure(plot_df: pd.DataFrame, output_png: Path, output_pdf: Path) -> None:
    brier_limits = compute_brier_limits(plot_df)
    x = np.arange(len(SIM_BIN_ORDER))

    fig, axes = plt.subplots(1, 3, figsize=(DOUBLE_COL, 2.7), sharey=True)
    twin_axes = []

    for idx, split_type in enumerate(SPLIT_ORDER):
        ax = axes[idx]
        ax2 = ax.twinx()
        twin_axes.append(ax2)
        split_df = plot_df[plot_df["split_type"] == split_type]

        for model in MODEL_ORDER:
            style = MODEL_STYLES[model]
            series = split_df[split_df["model"] == model].sort_values("sim_bin")

            auroc = series["auroc_mean"].to_numpy(dtype=float)
            auroc_std = np.nan_to_num(series["auroc_std"].to_numpy(dtype=float), nan=0.0)
            brier = series["brier_mean"].to_numpy(dtype=float)
            brier_std = np.nan_to_num(series["brier_std"].to_numpy(dtype=float), nan=0.0)

            ax.fill_between(x, auroc - auroc_std, auroc + auroc_std, color=style["fill"], alpha=0.28)
            ax.plot(
                x,
                auroc,
                color=style["color"],
                marker=style["marker"],
                linewidth=1.8,
                markersize=5,
            )

            ax2.fill_between(x, brier - brier_std, brier + brier_std, color=style["fill"], alpha=0.16)
            ax2.plot(
                x,
                brier,
                color=style["color"],
                marker=style["marker"],
                linewidth=1.6,
                markersize=4,
                linestyle="--",
                alpha=0.9,
            )

        ax.set_title(SPLIT_LABELS[split_type], fontsize=9, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(SIM_BIN_LABELS, fontsize=8, rotation=30, ha="right")
        ax.set_ylim(0.45, 1.02)
        ax.axhline(0.5, color="black", linewidth=0.7, linestyle="--", alpha=0.45)
        ax.tick_params(axis="y", labelsize=8)
        ax2.set_ylim(*brier_limits)
        ax2.tick_params(axis="y", labelsize=8)

    axes[0].set_ylabel("AUROC", fontsize=9)
    twin_axes[-1].set_ylabel("Brier score\n(lower is better)", fontsize=9)

    fig.legend(
        handles=build_series_handles(),
        loc="lower center",
        ncol=4,
        frameon=False,
        fontsize=8,
        bbox_to_anchor=(0.5, -0.02),
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1), w_pad=0.9)
    fig.savefig(output_png, dpi=300, bbox_inches="tight")
    fig.savefig(output_pdf, bbox_inches="tight")
    plt.close(fig)


def save_stacked_backup_figure(plot_df: pd.DataFrame, output_png: Path, output_pdf: Path) -> None:
    brier_limits = compute_brier_limits(plot_df)
    x = np.arange(len(SIM_BIN_ORDER))

    fig, axes = plt.subplots(2, 3, figsize=(DOUBLE_COL, 4.5), sharex=True)

    for col, split_type in enumerate(SPLIT_ORDER):
        split_df = plot_df[plot_df["split_type"] == split_type]
        auroc_ax = axes[0, col]
        brier_ax = axes[1, col]

        for model in MODEL_ORDER:
            style = MODEL_STYLES[model]
            series = split_df[split_df["model"] == model].sort_values("sim_bin")

            auroc = series["auroc_mean"].to_numpy(dtype=float)
            auroc_std = np.nan_to_num(series["auroc_std"].to_numpy(dtype=float), nan=0.0)
            brier = series["brier_mean"].to_numpy(dtype=float)
            brier_std = np.nan_to_num(series["brier_std"].to_numpy(dtype=float), nan=0.0)

            auroc_ax.fill_between(x, auroc - auroc_std, auroc + auroc_std, color=style["fill"], alpha=0.28)
            auroc_ax.plot(
                x,
                auroc,
                color=style["color"],
                marker=style["marker"],
                linewidth=1.8,
                markersize=5,
            )
            brier_ax.fill_between(x, brier - brier_std, brier + brier_std, color=style["fill"], alpha=0.22)
            brier_ax.plot(
                x,
                brier,
                color=style["color"],
                marker=style["marker"],
                linewidth=1.6,
                markersize=4,
                linestyle="--",
                alpha=0.9,
            )

        auroc_ax.set_title(SPLIT_LABELS[split_type], fontsize=9, fontweight="bold")
        auroc_ax.set_ylim(0.45, 1.02)
        auroc_ax.axhline(0.5, color="black", linewidth=0.7, linestyle="--", alpha=0.45)
        auroc_ax.tick_params(axis="y", labelsize=8)

        brier_ax.set_ylim(*brier_limits)
        brier_ax.tick_params(axis="y", labelsize=8)
        brier_ax.set_xticks(x)
        brier_ax.set_xticklabels(SIM_BIN_LABELS, fontsize=8, rotation=30, ha="right")

    axes[0, 0].set_ylabel("AUROC", fontsize=9)
    axes[1, 0].set_ylabel("Brier score\n(lower is better)", fontsize=9)

    fig.legend(
        handles=build_series_handles(),
        loc="lower center",
        ncol=4,
        frameon=False,
        fontsize=8,
        bbox_to_anchor=(0.5, -0.01),
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1), h_pad=1.0, w_pad=0.9)
    fig.savefig(output_png, dpi=300, bbox_inches="tight")
    fig.savefig(output_pdf, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    input_path = resolve_input_path(args.input)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dual_png = output_dir / "figure_dual_axis_auroc_brier_chembl.png"
    dual_pdf = output_dir / "figure_dual_axis_auroc_brier_chembl.pdf"
    stacked_png = output_dir / "figure_stacked_auroc_brier_chembl.png"
    stacked_pdf = output_dir / "figure_stacked_auroc_brier_chembl.pdf"
    ensure_new_outputs([dual_png, dual_pdf, stacked_png, stacked_pdf])

    plot_df = load_plot_rows(input_path)

    print(f"Input file used: {input_path}")
    print_rows_used(plot_df)

    save_dual_axis_figure(plot_df, dual_png, dual_pdf)
    save_stacked_backup_figure(plot_df, stacked_png, stacked_pdf)

    print("Output paths written:")
    print(f"  {dual_png}")
    print(f"  {dual_pdf}")
    print(f"  {stacked_png}")
    print(f"  {stacked_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
