#!/usr/bin/env python
"""Create publication-style ChEMBL split-distribution figures by similarity bin.

This script uses the canonical cross-model AD-bin summary as its primary input,
deduplicates the repeated model rows to recover one count per split/bin, then
creates three new manuscript-style figures:

1. Stacked count bars
2. 100% stacked proportion bars
3. Extreme-bin proportion comparison (<0.3 vs >0.7)

No existing artifacts are overwritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from hergbench.analysis.paper_figures import DOUBLE_COL, SIM_BIN_LABELS
except Exception:
    DOUBLE_COL = 7.00
    SIM_BIN_LABELS = ["<0.3", "0.3–0.5", "0.5–0.7", ">0.7"]

DATASET = "chembl"
SPLIT_ORDER = ["random", "scaffold", "cluster"]
SPLIT_LABELS = {
    "random": "Random",
    "scaffold": "Scaffold",
    "cluster": "Cluster",
}
SIM_BIN_ORDER = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
SIM_BIN_COLORS = {
    "<0.3": "#D85A30",
    "0.3-0.5": "#E6A66A",
    "0.5-0.7": "#8BB8E8",
    ">0.7": "#3266AD",
}
SIM_BIN_TEXT_COLORS = {
    "<0.3": "white",
    "0.3-0.5": "black",
    "0.5-0.7": "black",
    ">0.7": "white",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create ChEMBL split-distribution figures by similarity bin."
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Optional cross-model AD-bin CSV. Defaults to the canonical reports path.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "reports" / "cross_model_comparison"),
        help="Directory for new output figures.",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="Optional suffix appended to output stems, for example 'refined'.",
    )
    return parser.parse_args()


def resolve_input_path(explicit_input: str | None) -> Path:
    if explicit_input is not None:
        path = Path(explicit_input).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input CSV not found: {path}")
        return path

    candidates = [REPO_ROOT / "reports" / "cross_model_comparison" / "cross_model_ad_bins.csv"]
    for export_dir in sorted(REPO_ROOT.glob("stage2_export_*"), reverse=True):
        candidates.append(export_dir / "reports" / "cross_model_comparison" / "cross_model_ad_bins.csv")

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError("Could not locate canonical cross_model_ad_bins.csv")


def resolve_validation_paths() -> list[Path]:
    return [
        REPO_ROOT / "reports" / "reports" / "chembl_multiseed_analysis" / "multiseed_ad_bins_aggregated.csv",
        REPO_ROOT / "reports" / "chembl_stage2_multiseed_analysis" / "stage2_ad_bins_aggregated.csv",
    ]


def ensure_new_outputs(paths: list[Path]) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing output artifact(s):\n" + "\n".join(existing)
        )


def load_cross_model_rows(input_path: Path) -> pd.DataFrame:
    df = pd.read_csv(input_path)
    required = {"dataset", "split_type", "sim_bin", "model", "n_mean", "n_seeds"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Input CSV missing required columns: {missing}")

    rows = df[
        (df["dataset"] == DATASET)
        & (df["split_type"].isin(SPLIT_ORDER))
        & (df["sim_bin"].isin(SIM_BIN_ORDER))
    ].copy()
    rows["split_type"] = pd.Categorical(rows["split_type"], categories=SPLIT_ORDER, ordered=True)
    rows["sim_bin"] = pd.Categorical(rows["sim_bin"], categories=SIM_BIN_ORDER, ordered=True)
    rows = rows.sort_values(["split_type", "sim_bin", "model"]).reset_index(drop=True)

    expected_rows = len(SPLIT_ORDER) * len(SIM_BIN_ORDER) * 2
    if len(rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} ChEMBL rows in cross-model summary, found {len(rows)}.")

    per_group_models = rows.groupby(["split_type", "sim_bin"], observed=True)["model"].nunique()
    if (per_group_models != 2).any():
        raise ValueError("Each ChEMBL split/bin group must contain exactly two model rows.")

    return rows


def deduplicate_count_rows(rows: pd.DataFrame) -> pd.DataFrame:
    grouped = rows.groupby(["split_type", "sim_bin"], observed=True)
    summary = grouped.agg(
        model_rows=("model", "size"),
        n_mean_unique=("n_mean", "nunique"),
        n_seeds_unique=("n_seeds", "nunique"),
        n_mean=("n_mean", "first"),
        n_seeds=("n_seeds", "first"),
    ).reset_index()

    if not (summary["n_mean_unique"] == 1).all():
        raise ValueError("n_mean is not identical across model rows for at least one split/bin group.")
    if not (summary["n_seeds_unique"] == 1).all():
        raise ValueError("n_seeds is not identical across model rows for at least one split/bin group.")

    summary["n_total_float"] = summary["n_mean"].astype(float) * summary["n_seeds"].astype(float)
    summary["n_total"] = summary["n_total_float"].round().astype(int)

    mismatch = (summary["n_total_float"] - summary["n_total"]).abs() > 1e-8
    if mismatch.any():
        bad = summary.loc[mismatch, ["split_type", "sim_bin", "n_total_float"]]
        raise ValueError(
            "Could not safely reconstruct integer n_total from n_mean × n_seeds:\n"
            + bad.to_string(index=False)
        )

    summary["proportion"] = summary.groupby("split_type", observed=True)["n_total"].transform(
        lambda s: s / s.sum()
    )
    return summary[
        ["split_type", "sim_bin", "n_mean", "n_seeds", "n_total", "proportion"]
    ].sort_values(["split_type", "sim_bin"]).reset_index(drop=True)


def validate_reconstructed_counts(count_df: pd.DataFrame, validation_paths: list[Path]) -> list[tuple[Path, pd.DataFrame]]:
    validated_tables: list[tuple[Path, pd.DataFrame]] = []

    compare_cols = ["split_type", "sim_bin", "n_total", "n_mean", "n_seeds"]
    expected = count_df[compare_cols].copy()

    for path in validation_paths:
        if not path.exists():
            continue
        ref = pd.read_csv(path)
        needed = {"split_type", "sim_bin", "n_total", "n_mean", "n_seeds"}
        if not needed.issubset(ref.columns):
            continue
        if "dataset" in ref.columns:
            ref = ref[ref["dataset"] == DATASET].copy()
        ref = ref[compare_cols].copy()
        merged = expected.merge(
            ref,
            on=["split_type", "sim_bin"],
            how="outer",
            suffixes=("_expected", "_ref"),
            indicator=True,
        )
        if len(merged) != len(expected):
            raise ValueError(f"Validation file has unexpected row count: {path}")
        if not (merged["_merge"] == "both").all():
            raise ValueError(f"Validation file is missing split/bin rows: {path}")
        if not np.allclose(
            merged["n_mean_expected"].to_numpy(dtype=float),
            merged["n_mean_ref"].to_numpy(dtype=float),
            atol=1e-10,
        ):
            raise ValueError(f"n_mean mismatch versus validation file: {path}")
        if not np.array_equal(
            merged["n_total_expected"].to_numpy(dtype=int),
            merged["n_total_ref"].to_numpy(dtype=int),
        ):
            raise ValueError(f"n_total mismatch versus validation file: {path}")
        if not np.array_equal(
            merged["n_seeds_expected"].to_numpy(dtype=int),
            merged["n_seeds_ref"].to_numpy(dtype=int),
        ):
            raise ValueError(f"n_seeds mismatch versus validation file: {path}")
        validated_tables.append((path, ref.sort_values(["split_type", "sim_bin"]).reset_index(drop=True)))

    return validated_tables


def build_pivot(count_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    pivot = (
        count_df.pivot(index="split_type", columns="sim_bin", values=value_col)
        .reindex(index=SPLIT_ORDER, columns=SIM_BIN_ORDER)
        .astype(float)
    )
    pivot.index = [SPLIT_LABELS[idx] for idx in pivot.index]
    return pivot


def format_rows_for_print(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    out["split_type"] = out["split_type"].astype(str).map(SPLIT_LABELS)
    return out[
        ["dataset", "split_type", "sim_bin", "model", "n_mean", "n_seeds"]
    ]


def format_count_table_for_print(count_df: pd.DataFrame) -> pd.DataFrame:
    out = count_df.copy()
    out["split_type"] = out["split_type"].astype(str).map(SPLIT_LABELS)
    out["proportion_pct"] = out["proportion"] * 100.0
    return out[
        ["split_type", "sim_bin", "n_total", "n_mean", "n_seeds", "proportion_pct"]
    ]


def apply_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#444444",
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 8.5,
            "legend.title_fontsize": 8.5,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def annotate_counts(ax: plt.Axes, x: np.ndarray, pivot: pd.DataFrame, totals: np.ndarray) -> None:
    bottoms = np.zeros(len(x), dtype=float)
    max_total = float(totals.max())
    for sim_bin in SIM_BIN_ORDER:
        heights = pivot[sim_bin].to_numpy(dtype=float)
        for idx, height in enumerate(heights):
            if height < max(150.0, 0.06 * max_total):
                continue
            ax.text(
                x[idx],
                bottoms[idx] + height / 2.0,
                f"{int(round(height)):,}",
                ha="center",
                va="center",
                fontsize=8,
                color=SIM_BIN_TEXT_COLORS[sim_bin],
                fontweight="bold",
            )
        bottoms += heights


def annotate_proportions(ax: plt.Axes, x: np.ndarray, pivot: pd.DataFrame) -> None:
    bottoms = np.zeros(len(x), dtype=float)
    for sim_bin in SIM_BIN_ORDER:
        heights = pivot[sim_bin].to_numpy(dtype=float)
        for idx, height in enumerate(heights):
            if height < 0.075:
                continue
            ax.text(
                x[idx],
                bottoms[idx] + height / 2.0,
                f"{height * 100:.1f}%",
                ha="center",
                va="center",
                fontsize=8,
                color=SIM_BIN_TEXT_COLORS[sim_bin],
                fontweight="bold",
            )
        bottoms += heights


def save_count_figure(count_df: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    pivot = build_pivot(count_df, "n_total")
    x = np.arange(len(pivot.index))
    width = 0.62

    fig, ax = plt.subplots(figsize=(DOUBLE_COL * 0.72, 4.1))
    bottoms = np.zeros(len(x), dtype=float)
    for sim_bin, label in zip(SIM_BIN_ORDER, SIM_BIN_LABELS):
        heights = pivot[sim_bin].to_numpy(dtype=float)
        ax.bar(
            x,
            heights,
            width=width,
            bottom=bottoms,
            color=SIM_BIN_COLORS[sim_bin],
            edgecolor="white",
            linewidth=0.8,
            label=label,
        )
        bottoms += heights

    annotate_counts(ax, x, pivot, bottoms)

    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index)
    ax.set_ylabel("Total test molecules across 5 seeds")
    fig.suptitle(
        "ChEMBL test-set composition by train–test similarity",
        y=0.97,
        fontsize=10.5,
    )
    ax.yaxis.set_major_formatter(mticker.StrMethodFormatter("{x:,.0f}"))
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    fig.legend(
        title="Train–test similarity bin",
        ncol=2,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.91),
    )
    fig.subplots_adjust(top=0.79)
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, dpi=300, bbox_inches="tight")
    plt.close(fig)


def save_proportion_figure(count_df: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    pivot = build_pivot(count_df, "proportion")
    x = np.arange(len(pivot.index))
    width = 0.62

    fig, ax = plt.subplots(figsize=(DOUBLE_COL * 0.72, 4.1))
    bottoms = np.zeros(len(x), dtype=float)
    for sim_bin, label in zip(SIM_BIN_ORDER, SIM_BIN_LABELS):
        heights = pivot[sim_bin].to_numpy(dtype=float)
        ax.bar(
            x,
            heights,
            width=width,
            bottom=bottoms,
            color=SIM_BIN_COLORS[sim_bin],
            edgecolor="white",
            linewidth=0.8,
            label=label,
        )
        bottoms += heights

    annotate_proportions(ax, x, pivot)

    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index)
    ax.set_ylabel("Proportion of test molecules")
    fig.suptitle(
        "Relative ChEMBL test-set composition by train–test similarity",
        y=0.97,
        fontsize=10.5,
    )
    ax.set_ylim(0.0, 1.0)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    fig.legend(
        title="Train–test similarity bin",
        ncol=2,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.91),
    )
    fig.subplots_adjust(top=0.79)
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, dpi=300, bbox_inches="tight")
    plt.close(fig)


def save_extremes_figure(count_df: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    extremes = count_df[count_df["sim_bin"].isin(["<0.3", ">0.7"])].copy()
    pivot = build_pivot(extremes, "proportion")[["<0.3", ">0.7"]]
    counts_pivot = build_pivot(extremes, "n_total")[["<0.3", ">0.7"]]
    x = np.arange(len(pivot.index))
    width = 0.28

    fig, ax = plt.subplots(figsize=(DOUBLE_COL * 0.62, 3.7))
    offsets = {"<0.3": -width / 2.0, ">0.7": width / 2.0}
    legend_labels = {"<0.3": "<0.3 (novel chemistry)", ">0.7": ">0.7 (familiar chemistry)"}

    for sim_bin in ["<0.3", ">0.7"]:
        heights = pivot[sim_bin].to_numpy(dtype=float)
        counts = counts_pivot[sim_bin].to_numpy(dtype=float)
        ax.bar(
            x + offsets[sim_bin],
            heights,
            width=width,
            color=SIM_BIN_COLORS[sim_bin],
            edgecolor="white",
            linewidth=0.8,
            label=legend_labels[sim_bin],
        )
        for idx, (height, count) in enumerate(zip(heights, counts)):
            ax.text(
                x[idx] + offsets[sim_bin],
                height + 0.018,
                f"{height * 100:.1f}%\n(n={int(round(count)):,})",
                ha="center",
                va="bottom",
                fontsize=7.5,
                color="#333333",
            )

    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index)
    ax.set_ylabel("Proportion of test molecules")
    fig.suptitle(
        "Extreme train–test similarity regimes shift from Random to Cluster",
        y=0.97,
        fontsize=10.5,
    )
    ax.set_ylim(0.0, 0.82)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    fig.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.91), ncol=2)
    fig.subplots_adjust(top=0.81)
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    input_path = resolve_input_path(args.input)
    output_dir = Path(args.output_dir).expanduser().resolve()
    suffix = f"_{args.tag}" if args.tag else ""

    outputs = [
        output_dir / f"figure_split_similarity_distribution_counts{suffix}.png",
        output_dir / f"figure_split_similarity_distribution_counts{suffix}.pdf",
        output_dir / f"figure_split_similarity_distribution_proportions{suffix}.png",
        output_dir / f"figure_split_similarity_distribution_proportions{suffix}.pdf",
        output_dir / f"figure_split_similarity_distribution_extremes{suffix}.png",
        output_dir / f"figure_split_similarity_distribution_extremes{suffix}.pdf",
    ]
    ensure_new_outputs(outputs)

    apply_plot_style()
    rows = load_cross_model_rows(input_path)
    count_df = deduplicate_count_rows(rows)
    validated_tables = validate_reconstructed_counts(count_df, resolve_validation_paths())

    print(f"Input file used: {input_path}")
    print(
        "Deduplication logic: cross_model_ad_bins.csv contains one row per model; "
        "for each ChEMBL split_type × sim_bin, both model rows had identical n_mean "
        "and n_seeds, so counts were deduplicated to one row and n_total was reconstructed "
        "as round(n_mean × n_seeds)."
    )
    if validated_tables:
        print("Validation files matched reconstructed counts:")
        for path, _ in validated_tables:
            print(f"  - {path}")
    else:
        print("Validation note: no auxiliary aggregated count files were available, so only the cross-model summary was used.")

    print("\nRows used from cross_model_ad_bins.csv:")
    print(format_rows_for_print(rows).to_string(index=False))

    print("\nFinal split × similarity-bin count table used for plotting:")
    print(format_count_table_for_print(count_df).to_string(index=False))

    print("\nWide count table:")
    print(build_pivot(count_df, "n_total").to_string())

    output_dir.mkdir(parents=True, exist_ok=True)
    save_count_figure(count_df, outputs[0], outputs[1])
    save_proportion_figure(count_df, outputs[2], outputs[3])
    save_extremes_figure(count_df, outputs[4], outputs[5])

    print("\nOutput paths written:")
    for path in outputs:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
