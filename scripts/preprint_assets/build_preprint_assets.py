#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE1_ROOT = REPO_ROOT / "hERGBench_Stage1_SignOff_v2_triple_seed11"
STAGE2_ROOT = REPO_ROOT / "hERGBench_Stage2_Cluster_None_MultiTorch_v1"
OPTIONAL_ABLATION = REPO_ROOT / "reports" / "summary" / "cluster_calibration_ablation.csv"
OUT_ROOT = REPO_ROOT / "reports" / "preprint_assets_v1"


@dataclass
class Asset:
    output_path: str
    asset_type: str
    source_files: str
    short_description: str


def ensure_dirs() -> dict[str, Path]:
    dirs = {
        "root": OUT_ROOT,
        "tables": OUT_ROOT / "tables",
        "figures": OUT_ROOT / "figures",
        "text": OUT_ROOT / "text",
        "manifests": OUT_ROOT / "manifests",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def register(assets: list[Asset], output_path: Path, asset_type: str, source_files: list[Path], description: str) -> None:
    assets.append(
        Asset(
            output_path=str(output_path.relative_to(REPO_ROOT)),
            asset_type=asset_type,
            source_files="; ".join(str(path.relative_to(REPO_ROOT)) for path in source_files),
            short_description=description,
        )
    )


def find_single(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one match for {pattern} under {root}, found {len(matches)}")
    return matches[0]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def fmt_value(value: float) -> str:
    return f"{value:.3f}"


def fmt_mean_std(mean: float, std: float) -> str:
    return f"{mean:.3f} +/- {std:.3f}"


def fmt_mean_std_tex(mean: float, std: float) -> str:
    return f"{mean:.3f} $\\pm$ {std:.3f}"


def latex_from_df(df: pd.DataFrame, output_path: Path) -> None:
    output_path.write_text(df.to_latex(index=False, escape=False), encoding="utf-8")


def save_figure(fig: plt.Figure, png_path: Path, pdf_path: Path) -> None:
    fig.tight_layout()
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)


def load_stage1_cluster() -> tuple[pd.Series, dict, list[Path]]:
    bench_path = find_single(STAGE1_ROOT, "**/benchmark_results.csv")
    meta_path = find_single(STAGE1_ROOT, "**/model_meta_cluster_seed11.json")

    bench = pd.read_csv(bench_path)
    cluster = bench.loc[bench["split_type"].eq("cluster")]
    if len(cluster) != 1:
        raise ValueError("Expected exactly one Stage 1 cluster benchmark row.")

    meta = load_json(meta_path)
    return cluster.iloc[0], meta, [bench_path, meta_path]


def load_stage2_bundle() -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    summary_path = find_single(STAGE2_ROOT, "**/stage2_cluster_none_multitorch_summary.csv")
    runs_path = find_single(STAGE2_ROOT, "**/stage2_cluster_none_multitorch_runs.csv")

    summary = pd.read_csv(summary_path)
    runs = pd.read_csv(runs_path)

    if len(summary) != 1:
        raise ValueError("Expected exactly one Stage 2 multitorch summary row.")

    return summary, runs, [summary_path, runs_path]


def build_cluster_comparison_table(
    stage1_row: pd.Series,
    stage1_meta: dict,
    stage2_summary: pd.Series,
    shared_test_prevalence: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    csv_df = pd.DataFrame(
        [
            {
                "model": "Stage 1 XGBoost ECFP4",
                "split_type": "cluster",
                "split_seed": int(stage1_row["seed"]),
                "n_runs": 1,
                "calibration_method": str(stage1_meta["calibration"]["method"]),
                "auroc": fmt_value(float(stage1_row["auroc"])),
                "auprc": fmt_value(float(stage1_row["auprc"])),
                "f1": fmt_value(float(stage1_row["f1"])),
                "balanced_acc": fmt_value(float(stage1_row["balanced_acc"])),
                "brier": fmt_value(float(stage1_row["brier"])),
                "threshold": fmt_value(float(stage1_row["threshold"])),
                "predicted_positive_rate": "NA",
                "test_prevalence": fmt_value(shared_test_prevalence),
                "notes": "Frozen single benchmark from Stage 1 signoff bundle; predicted_positive_rate not exposed in the frozen Stage 1 bundle.",
            },
            {
                "model": "Stage 2 ChemProp D-MPNN",
                "split_type": "cluster",
                "split_seed": int(stage2_summary["seed"]),
                "n_runs": int(stage2_summary["n_runs"]),
                "calibration_method": str(stage2_summary["calibration_method_saved"]),
                "auroc": fmt_mean_std(float(stage2_summary["auroc_mean"]), float(stage2_summary["auroc_std"])),
                "auprc": fmt_mean_std(float(stage2_summary["auprc_mean"]), float(stage2_summary["auprc_std"])),
                "f1": fmt_mean_std(float(stage2_summary["f1_mean"]), float(stage2_summary["f1_std"])),
                "balanced_acc": fmt_mean_std(float(stage2_summary["balanced_acc_mean"]), float(stage2_summary["balanced_acc_std"])),
                "brier": fmt_mean_std(float(stage2_summary["brier_mean"]), float(stage2_summary["brier_std"])),
                "threshold": fmt_mean_std(float(stage2_summary["threshold_mean"]), float(stage2_summary["threshold_std"])),
                "predicted_positive_rate": fmt_mean_std(
                    float(stage2_summary["predicted_positive_rate_mean"]),
                    float(stage2_summary["predicted_positive_rate_std"]),
                ),
                "test_prevalence": fmt_value(shared_test_prevalence),
                "notes": "Mean +/- SD across torch seeds on one fixed cluster_seed11 split with calibration.method=none.",
            },
        ]
    )

    tex_df = csv_df.copy()
    tex_df.loc[1, "auroc"] = fmt_mean_std_tex(float(stage2_summary["auroc_mean"]), float(stage2_summary["auroc_std"]))
    tex_df.loc[1, "auprc"] = fmt_mean_std_tex(float(stage2_summary["auprc_mean"]), float(stage2_summary["auprc_std"]))
    tex_df.loc[1, "f1"] = fmt_mean_std_tex(float(stage2_summary["f1_mean"]), float(stage2_summary["f1_std"]))
    tex_df.loc[1, "balanced_acc"] = fmt_mean_std_tex(
        float(stage2_summary["balanced_acc_mean"]), float(stage2_summary["balanced_acc_std"])
    )
    tex_df.loc[1, "brier"] = fmt_mean_std_tex(float(stage2_summary["brier_mean"]), float(stage2_summary["brier_std"]))
    tex_df.loc[1, "threshold"] = fmt_mean_std_tex(
        float(stage2_summary["threshold_mean"]), float(stage2_summary["threshold_std"])
    )
    tex_df.loc[1, "predicted_positive_rate"] = fmt_mean_std_tex(
        float(stage2_summary["predicted_positive_rate_mean"]),
        float(stage2_summary["predicted_positive_rate_std"]),
    )
    return csv_df, tex_df


def build_stage2_runs_table(stage2_runs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = stage2_runs.loc[
        :,
        [
            "pytorch_seed",
            "threshold",
            "auroc",
            "auprc",
            "f1",
            "balanced_acc",
            "brier",
            "predicted_positive_rate",
            "test_prevalence",
        ],
    ].copy()
    out = out.sort_values("pytorch_seed").reset_index(drop=True)
    tex = out.copy()
    for col in out.columns:
        if col != "pytorch_seed":
            tex[col] = tex[col].map(lambda x: f"{float(x):.3f}")
    return out, tex


def build_stage2_summary_table(stage2_summary: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = pd.DataFrame(
        [
            {
                "split_type": str(stage2_summary["split_type"]),
                "split_seed": int(stage2_summary["seed"]),
                "calibration_method": str(stage2_summary["calibration_method_saved"]),
                "n_runs": int(stage2_summary["n_runs"]),
                "auroc_mean": float(stage2_summary["auroc_mean"]),
                "auroc_std": float(stage2_summary["auroc_std"]),
                "auprc_mean": float(stage2_summary["auprc_mean"]),
                "auprc_std": float(stage2_summary["auprc_std"]),
                "f1_mean": float(stage2_summary["f1_mean"]),
                "f1_std": float(stage2_summary["f1_std"]),
                "balanced_acc_mean": float(stage2_summary["balanced_acc_mean"]),
                "balanced_acc_std": float(stage2_summary["balanced_acc_std"]),
                "brier_mean": float(stage2_summary["brier_mean"]),
                "brier_std": float(stage2_summary["brier_std"]),
                "threshold_mean": float(stage2_summary["threshold_mean"]),
                "threshold_std": float(stage2_summary["threshold_std"]),
                "predicted_positive_rate_mean": float(stage2_summary["predicted_positive_rate_mean"]),
                "predicted_positive_rate_std": float(stage2_summary["predicted_positive_rate_std"]),
                "test_prevalence": float(stage2_summary["test_prevalence"]),
            }
        ]
    )
    tex = out.copy()
    for col in out.columns:
        if col not in {"split_type", "split_seed", "calibration_method", "n_runs"}:
            tex[col] = tex[col].map(lambda x: f"{float(x):.3f}")
    return out, tex


def build_optional_ablation_table(ablation_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    ablation = pd.read_csv(ablation_path)
    keep = [
        "calibration",
        "split_type",
        "seed",
        "threshold",
        "auroc",
        "auprc",
        "f1",
        "balanced_acc",
        "brier",
        "predicted_positive_rate",
        "test_prevalence",
        "calibration_method_saved",
        "threshold_metric",
    ]
    out = ablation.loc[:, keep].copy()
    tex = out.copy()
    for col in keep:
        if col not in {"calibration", "split_type", "seed", "calibration_method_saved", "threshold_metric"}:
            tex[col] = tex[col].map(lambda x: f"{float(x):.3f}")
    return out, tex


def make_cluster_comparison_figure(stage1_row: pd.Series, stage2_summary: pd.Series) -> plt.Figure:
    metrics = ["auroc", "auprc", "f1", "balanced_acc", "brier"]
    labels = ["AUROC", "AUPRC", "F1", "Balanced Acc", "Brier"]
    stage1_values = [
        float(stage1_row["auroc"]),
        float(stage1_row["auprc"]),
        float(stage1_row["f1"]),
        float(stage1_row["balanced_acc"]),
        float(stage1_row["brier"]),
    ]
    stage2_means = [
        float(stage2_summary["auroc_mean"]),
        float(stage2_summary["auprc_mean"]),
        float(stage2_summary["f1_mean"]),
        float(stage2_summary["balanced_acc_mean"]),
        float(stage2_summary["brier_mean"]),
    ]
    stage2_stds = [
        float(stage2_summary["auroc_std"]),
        float(stage2_summary["auprc_std"]),
        float(stage2_summary["f1_std"]),
        float(stage2_summary["balanced_acc_std"]),
        float(stage2_summary["brier_std"]),
    ]

    x = list(range(len(metrics)))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar([i - width / 2 for i in x], stage1_values, width=width, label="Stage 1", color="#9aa0a6")
    ax.bar(
        [i + width / 2 for i in x],
        stage2_means,
        width=width,
        yerr=stage2_stds,
        capsize=4,
        label="Stage 2",
        color="#4c78a8",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15)
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("Metric value")
    ax.set_title("Cluster split: Stage 1 baseline vs Stage 2 ChemProp")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    return fig


def make_seed_variation_figure(stage2_runs: pd.DataFrame) -> plt.Figure:
    metrics = [
        ("auroc", "AUROC"),
        ("auprc", "AUPRC"),
        ("f1", "F1"),
        ("balanced_acc", "Balanced Acc"),
        ("brier", "Brier"),
    ]
    seeds = stage2_runs["pytorch_seed"].tolist()
    fig, axes = plt.subplots(2, 3, figsize=(10, 6))
    axes_flat = axes.flatten()
    for ax, (col, label) in zip(axes_flat, metrics):
        ax.plot(seeds, stage2_runs[col], marker="o", color="#4c78a8")
        ax.set_title(label)
        ax.set_xlabel("Torch seed")
        ax.set_ylabel(label)
        ax.grid(alpha=0.25)
        ax.set_xticks(seeds)
        ax.set_ylim(0.0, 1.0)
    axes_flat[-1].axis("off")
    fig.suptitle("Stage 2 cluster multitorch variation", y=1.02)
    return fig


def make_operating_point_figure(stage2_runs: pd.DataFrame, test_prevalence: float) -> plt.Figure:
    seeds = stage2_runs["pytorch_seed"].tolist()
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.0))

    axes[0].plot(seeds, stage2_runs["threshold"], marker="o", color="#4c78a8")
    axes[0].set_title("Decision threshold by torch seed")
    axes[0].set_xlabel("Torch seed")
    axes[0].set_ylabel("Threshold")
    axes[0].set_xticks(seeds)
    axes[0].set_ylim(0.0, 1.0)
    axes[0].grid(alpha=0.25)

    axes[1].plot(seeds, stage2_runs["predicted_positive_rate"], marker="o", color="#f58518", label="Predicted positive rate")
    axes[1].axhline(test_prevalence, color="#54a24b", linestyle="--", linewidth=1.5, label="Test prevalence")
    axes[1].set_title("Operating point by torch seed")
    axes[1].set_xlabel("Torch seed")
    axes[1].set_ylabel("Rate")
    axes[1].set_xticks(seeds)
    axes[1].set_ylim(0.0, 1.0)
    axes[1].grid(alpha=0.25)
    axes[1].legend(frameon=False)
    return fig


def make_calibration_ablation_figure(ablation: pd.DataFrame, test_prevalence: float) -> plt.Figure:
    metrics = ["auroc", "auprc", "f1", "balanced_acc", "brier"]
    labels = ["AUROC", "AUPRC", "F1", "Balanced Acc", "Brier"]
    calibrations = ablation["calibration"].tolist()
    x = list(range(len(metrics)))
    width = 0.22
    colors = {"platt": "#9aa0a6", "none": "#4c78a8", "isotonic": "#f58518"}

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

    for idx, calibration in enumerate(calibrations):
        values = [float(ablation.loc[ablation["calibration"].eq(calibration), metric].iloc[0]) for metric in metrics]
        axes[0].bar(
            [i + (idx - 1) * width for i in x],
            values,
            width=width,
            label=calibration,
            color=colors.get(calibration, "#4c78a8"),
        )
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=15)
    axes[0].set_ylim(0.0, 1.0)
    axes[0].set_ylabel("Metric value")
    axes[0].set_title("Cluster calibration ablation")
    axes[0].legend(frameon=False)
    axes[0].grid(axis="y", alpha=0.25)

    axes[1].plot(calibrations, ablation["threshold"], marker="o", color="#4c78a8", label="Threshold")
    axes[1].plot(
        calibrations,
        ablation["predicted_positive_rate"],
        marker="o",
        color="#f58518",
        label="Predicted positive rate",
    )
    axes[1].axhline(test_prevalence, color="#54a24b", linestyle="--", linewidth=1.5, label="Test prevalence")
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_ylabel("Rate / threshold")
    axes[1].set_title("Cluster operating-point behavior")
    axes[1].grid(alpha=0.25)
    axes[1].legend(frameon=False)
    return fig


def write_results_snippet(output_path: Path, stage1_row: pd.Series, stage2_summary: pd.Series, include_ablation: bool) -> None:
    text = (
        "On the frozen cluster_seed11 split, the Stage 1 ECFP4 + XGBoost baseline achieved "
        f"AUROC {float(stage1_row['auroc']):.3f}, AUPRC {float(stage1_row['auprc']):.3f}, "
        f"F1 {float(stage1_row['f1']):.3f}, balanced accuracy {float(stage1_row['balanced_acc']):.3f}, "
        f"and Brier {float(stage1_row['brier']):.3f}. "
        "The final Stage 2 ChemProp D-MPNN cluster benchmark used calibration.method = none and was repeated across "
        f"{int(stage2_summary['n_runs'])} torch seeds on the same fixed split membership; the repeated runs yielded "
        f"AUROC {float(stage2_summary['auroc_mean']):.3f} +/- {float(stage2_summary['auroc_std']):.3f}, "
        f"AUPRC {float(stage2_summary['auprc_mean']):.3f} +/- {float(stage2_summary['auprc_std']):.3f}, "
        f"F1 {float(stage2_summary['f1_mean']):.3f} +/- {float(stage2_summary['f1_std']):.3f}, "
        f"balanced accuracy {float(stage2_summary['balanced_acc_mean']):.3f} +/- {float(stage2_summary['balanced_acc_std']):.3f}, "
        f"and Brier {float(stage2_summary['brier_mean']):.3f} +/- {float(stage2_summary['brier_std']):.3f}. "
        "Relative to the frozen Stage 1 baseline, the repeated Stage 2 cluster runs showed a modest AUROC gain and "
        "higher mean balanced accuracy and F1, while AUPRC was slightly lower and Brier score was higher. "
    )
    if include_ablation:
        text += (
            "The final Stage 2 cluster policy uses calibration.method = none, which was retained after the cluster-only "
            "calibration ablation showed that platt produced an implausibly aggressive operating point and isotonic materially altered ranking behavior."
        )
    output_path.write_text(text + "\n", encoding="utf-8")


def write_captions(output_path: Path, include_ablation: bool) -> None:
    lines = [
        "# Figure Captions",
        "",
        "## fig_cluster_stage1_vs_stage2_main",
        "Cluster-split comparison of the frozen Stage 1 XGBoost ECFP4 baseline and the repeated Stage 2 ChemProp D-MPNN benchmark. Stage 1 is shown as a single frozen benchmark, whereas Stage 2 is shown as the mean with standard-deviation error bars across torch seeds on one fixed split membership.",
        "",
        "## fig_stage2_cluster_seed_variation",
        "Per-seed variation for the final Stage 2 cluster benchmark with calibration.method = none. Each point is one torch seed on the fixed cluster_seed11 split membership.",
        "",
        "## fig_stage2_cluster_operating_point",
        "Threshold and predicted-positive rate across torch seeds for the final Stage 2 cluster benchmark. The horizontal reference line marks the fixed cluster test prevalence.",
        "",
    ]
    if include_ablation:
        lines.extend(
            [
                "## fig_cluster_calibration_ablation",
                "Supplementary cluster calibration ablation comparing platt, none, and isotonic. The left panel summarizes ranking and operating-point metrics, and the right panel shows threshold and predicted-positive rate relative to the fixed cluster test prevalence.",
                "",
            ]
        )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_build_notes(output_path: Path, include_ablation: bool, assumptions: list[str]) -> None:
    lines = [
        "# Build Notes",
        "",
        f"- Stage 1 bundle root used: `{STAGE1_ROOT.relative_to(REPO_ROOT)}`",
        f"- Stage 2 bundle root used: `{STAGE2_ROOT.relative_to(REPO_ROOT)}`",
        f"- Supplementary calibration-ablation assets included: `{'yes' if include_ablation else 'no'}`",
        "",
        "## Assumptions",
    ]
    for item in assumptions:
        lines.append(f"- {item}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_asset_manifest(output_path: Path, assets: list[Asset]) -> None:
    rows = [asset.__dict__ for asset in assets]
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["output_path", "asset_type", "source_files", "short_description"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    plt.style.use("default")
    dirs = ensure_dirs()
    assets: list[Asset] = []

    stage1_row, stage1_meta, stage1_sources = load_stage1_cluster()
    stage2_summary_df, stage2_runs, stage2_sources = load_stage2_bundle()
    stage2_summary = stage2_summary_df.iloc[0]
    shared_test_prevalence = float(stage2_summary["test_prevalence"])

    assumptions = [
        "Stage 1 cluster predicted_positive_rate is marked NA because the frozen Stage 1 bundle does not contain per-example prediction CSVs.",
        "Stage 1 and Stage 2 use the same fixed cluster_seed11 split membership, so test_prevalence is treated as a split property shared across both stages.",
        "Stage 2 repeated-run variability is interpreted strictly as variation across torch seeds on one fixed split membership.",
    ]

    cluster_csv, cluster_tex = build_cluster_comparison_table(stage1_row, stage1_meta, stage2_summary, shared_test_prevalence)
    cluster_csv_path = dirs["tables"] / "table_cluster_stage1_vs_stage2.csv"
    cluster_tex_path = dirs["tables"] / "table_cluster_stage1_vs_stage2.tex"
    cluster_csv.to_csv(cluster_csv_path, index=False)
    latex_from_df(cluster_tex, cluster_tex_path)
    register(assets, cluster_csv_path, "table_csv", stage1_sources + stage2_sources, "Primary cluster Stage 1 vs Stage 2 comparison table.")
    register(assets, cluster_tex_path, "table_tex", stage1_sources + stage2_sources, "LaTeX version of the primary cluster Stage 1 vs Stage 2 comparison table.")

    runs_csv, runs_tex = build_stage2_runs_table(stage2_runs)
    runs_csv_path = dirs["tables"] / "table_stage2_cluster_multitorch_runs.csv"
    runs_tex_path = dirs["tables"] / "table_stage2_cluster_multitorch_runs.tex"
    runs_csv.to_csv(runs_csv_path, index=False)
    latex_from_df(runs_tex, runs_tex_path)
    register(assets, runs_csv_path, "table_csv", stage2_sources, "Per-seed Stage 2 cluster multitorch manuscript table.")
    register(assets, runs_tex_path, "table_tex", stage2_sources, "LaTeX version of the per-seed Stage 2 cluster multitorch manuscript table.")

    summary_csv, summary_tex = build_stage2_summary_table(stage2_summary)
    summary_csv_path = dirs["tables"] / "table_stage2_cluster_multitorch_summary.csv"
    summary_tex_path = dirs["tables"] / "table_stage2_cluster_multitorch_summary.tex"
    summary_csv.to_csv(summary_csv_path, index=False)
    latex_from_df(summary_tex, summary_tex_path)
    register(assets, summary_csv_path, "table_csv", stage2_sources, "Summary Stage 2 cluster multitorch manuscript table.")
    register(assets, summary_tex_path, "table_tex", stage2_sources, "LaTeX version of the summary Stage 2 cluster multitorch manuscript table.")

    main_fig = make_cluster_comparison_figure(stage1_row, stage2_summary)
    main_png = dirs["figures"] / "fig_cluster_stage1_vs_stage2_main.png"
    main_pdf = dirs["figures"] / "fig_cluster_stage1_vs_stage2_main.pdf"
    save_figure(main_fig, main_png, main_pdf)
    register(assets, main_png, "figure_png", stage1_sources + stage2_sources, "Main cluster comparison figure.")
    register(assets, main_pdf, "figure_pdf", stage1_sources + stage2_sources, "PDF version of the main cluster comparison figure.")

    seed_fig = make_seed_variation_figure(stage2_runs)
    seed_png = dirs["figures"] / "fig_stage2_cluster_seed_variation.png"
    seed_pdf = dirs["figures"] / "fig_stage2_cluster_seed_variation.pdf"
    save_figure(seed_fig, seed_png, seed_pdf)
    register(assets, seed_png, "figure_png", stage2_sources, "Stage 2 cluster seed-variation figure.")
    register(assets, seed_pdf, "figure_pdf", stage2_sources, "PDF version of the Stage 2 cluster seed-variation figure.")

    op_fig = make_operating_point_figure(stage2_runs, shared_test_prevalence)
    op_png = dirs["figures"] / "fig_stage2_cluster_operating_point.png"
    op_pdf = dirs["figures"] / "fig_stage2_cluster_operating_point.pdf"
    save_figure(op_fig, op_png, op_pdf)
    register(assets, op_png, "figure_png", stage2_sources, "Stage 2 cluster operating-point figure.")
    register(assets, op_pdf, "figure_pdf", stage2_sources, "PDF version of the Stage 2 cluster operating-point figure.")

    include_ablation = OPTIONAL_ABLATION.exists()
    if include_ablation:
        ablation_csv, ablation_tex = build_optional_ablation_table(OPTIONAL_ABLATION)
        ablation_csv_path = dirs["tables"] / "table_cluster_calibration_ablation.csv"
        ablation_tex_path = dirs["tables"] / "table_cluster_calibration_ablation.tex"
        ablation_csv.to_csv(ablation_csv_path, index=False)
        latex_from_df(ablation_tex, ablation_tex_path)
        register(assets, ablation_csv_path, "table_csv", [OPTIONAL_ABLATION], "Supplementary cluster calibration-ablation table.")
        register(assets, ablation_tex_path, "table_tex", [OPTIONAL_ABLATION], "LaTeX version of the supplementary cluster calibration-ablation table.")

        ablation_fig = make_calibration_ablation_figure(ablation_csv, shared_test_prevalence)
        ablation_png = dirs["figures"] / "fig_cluster_calibration_ablation.png"
        ablation_pdf = dirs["figures"] / "fig_cluster_calibration_ablation.pdf"
        save_figure(ablation_fig, ablation_png, ablation_pdf)
        register(assets, ablation_png, "figure_png", [OPTIONAL_ABLATION], "Supplementary cluster calibration-ablation figure.")
        register(assets, ablation_pdf, "figure_pdf", [OPTIONAL_ABLATION], "PDF version of the supplementary cluster calibration-ablation figure.")

    results_md = dirs["text"] / "results_cluster_comparison.md"
    write_results_snippet(results_md, stage1_row, stage2_summary, include_ablation)
    register(assets, results_md, "text_md", stage1_sources + stage2_sources + ([OPTIONAL_ABLATION] if include_ablation else []), "Concise results paragraph for manuscript drafting.")

    captions_md = dirs["text"] / "figure_captions.md"
    write_captions(captions_md, include_ablation)
    register(assets, captions_md, "text_md", [], "Draft captions for the generated figures.")

    manifest_csv = dirs["manifests"] / "asset_manifest.csv"
    build_notes = dirs["manifests"] / "build_notes.md"
    write_build_notes(build_notes, include_ablation, assumptions)
    register(assets, manifest_csv, "manifest_csv", [], "Manifest of generated preprint assets.")
    register(
        assets,
        build_notes,
        "notes_md",
        stage1_sources + stage2_sources + ([OPTIONAL_ABLATION] if include_ablation else []),
        "Build notes describing bundle inputs and assumptions.",
    )
    write_asset_manifest(manifest_csv, assets)

    print(f"[preprint_assets] Wrote assets to: {OUT_ROOT}")


if __name__ == "__main__":
    main()
