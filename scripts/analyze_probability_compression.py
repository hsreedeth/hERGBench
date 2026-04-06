#!/usr/bin/env python
"""Analyze probability compression from saved test-set prediction artifacts.

This script:
1. Discovers canonical saved prediction files for Stage 2 D-MPNN runs from the
   checked-in run manifests.
2. Discovers the highest-coverage canonical Stage 1 XGBoost run set from
   checked-in run directories.
3. Builds pooled and per-seed compression summaries directly from the saved
   `test_preds_*_with_sim.csv` files without re-training models.
4. Writes reproducible figures, tables, and README summaries under
   `reports/analysis/probability_compression/`.

Important design choice
-----------------------
The current repo checkout does not contain per-test ChEMBL Stage 1 XGBoost
prediction CSVs. It only contains aggregate Stage 1 ChEMBL summaries. This
script does not substitute those aggregate summaries in place of per-test
prediction artifacts. Missing per-test artifacts are reported explicitly in the
tables, README files, and figure placeholders.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Optional

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from hergbench.analysis.paper_figures import (
        BLUE,
        CORAL,
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
    SIM_BIN_ORDER = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
    SIM_BIN_LABELS = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]


DATASET_ORDER = ["chembl", "tdc"]
PLOT_SPLIT_ORDER = ["cluster", "random", "scaffold"]
SUMMARY_SPLIT_ORDER = ["random", "scaffold", "cluster"]
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
MODEL_COLORS = {
    "chemprop_dmnn": BLUE,
    "xgboost": CORAL,
}
MODEL_FILLS = {
    "chemprop_dmnn": LIGHT_BLUE,
    "xgboost": LIGHT_CORAL,
}
NEGATIVE_COLOR = "#666666"
OUTPUT_ROOT_DEFAULT = REPO_ROOT / "reports" / "analysis" / "probability_compression"


@dataclass
class PredictionSource:
    dataset: str
    model: str
    split_type: str
    seed_label: str
    split_seed: Optional[str]
    run_dir: str
    source_file: str
    source_type: str
    selection_group: str
    selection_reason: str
    status: str
    manifest_path: Optional[str] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze probability compression from saved test predictions."
    )
    parser.add_argument(
        "--dataset",
        choices=["chembl", "tdc", "both"],
        default="both",
        help="Dataset subset to analyze.",
    )
    parser.add_argument(
        "--n-reliability-bins",
        type=int,
        default=10,
        help="Number of uniform probability bins for reliability diagrams.",
    )
    parser.add_argument(
        "--output-root",
        default=str(OUTPUT_ROOT_DEFAULT),
        help="Root output directory for analysis artifacts.",
    )
    return parser.parse_args()


def infer_dataset_from_path(dataset_path: str | None) -> str:
    dataset_path = dataset_path or ""
    return "chembl" if "data/chembl/" in dataset_path else "tdc"


def parse_seed_from_name(name: str) -> Optional[str]:
    match = re.search(r"_seed(\d+)", name)
    return match.group(1) if match else None


def parse_torch_seed(run_name: str) -> Optional[str]:
    match = re.search(r"_torch(\d+)", run_name)
    return match.group(1) if match else None


def canonical_test_pred_files(pred_dir: Path) -> list[Path]:
    files = []
    for path in sorted(pred_dir.glob("test_preds_*_with_sim.csv")):
        # Ignore macOS duplicate exports such as "file 2.csv".
        if re.search(r" \d+\.csv$", path.name):
            continue
        files.append(path)
    return files


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def derive_similarity_bin(sim_values: pd.Series) -> pd.Series:
    return pd.cut(
        sim_values.astype(float),
        bins=[-np.inf, 0.3, 0.5, 0.7, np.inf],
        labels=SIM_BIN_ORDER,
        right=False,
        include_lowest=True,
    ).astype(str)


def choose_stage1_xgboost_runset(repo_root: Path) -> tuple[Optional[Path], list[PredictionSource], str]:
    runs_root = repo_root / "reports" / "runs"
    candidates: list[tuple[int, int, str, Path, list[Path]]] = []
    for run_dir in sorted(runs_root.glob("*stage1*")):
        pred_dir = run_dir / "predictions"
        meta_path = run_dir / "metadata.json"
        if not pred_dir.exists() or not meta_path.exists():
            continue
        files = canonical_test_pred_files(pred_dir)
        if not files:
            continue
        style_priority = 2 if "signoff" in run_dir.name else 1 if "mvp" in run_dir.name else 0
        candidates.append((len(files), style_priority, run_dir.name, run_dir, files))

    if not candidates:
        return None, [], "No Stage 1 XGBoost run set with canonical test prediction CSVs was found."

    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    _, _, _, chosen_run_dir, chosen_files = candidates[0]

    reason = (
        "Selected the highest-coverage canonical Stage 1 XGBoost run set "
        f"({len(chosen_files)} prediction files) from {chosen_run_dir.name}. "
        "Coverage was prioritized ahead of run label because the checked-in "
        "signoff runs only contain seed11 predictions, whereas the selected "
        "MVP run provides all 3 splits x 5 split seeds."
    )

    sources = []
    for pred_file in chosen_files:
        split_match = re.match(r"test_preds_(random|scaffold|cluster)_seed(\d+)_with_sim\.csv", pred_file.name)
        if not split_match:
            continue
        split_type, split_seed = split_match.groups()
        sources.append(
            PredictionSource(
                dataset="tdc",
                model="xgboost",
                split_type=split_type,
                seed_label=split_seed,
                split_seed=split_seed,
                run_dir=str(chosen_run_dir),
                source_file=str(pred_file),
                source_type="stage1_runset",
                selection_group=chosen_run_dir.name,
                selection_reason=reason,
                status="available",
            )
        )
    return chosen_run_dir, sources, reason


def discover_stage2_manifest_sources(repo_root: Path, dataset: str) -> tuple[list[PredictionSource], str]:
    manifest_map = {
        "chembl": repo_root / "reports" / "chembl_stage2_multiseed_analysis" / "stage2_run_manifest.csv",
        "tdc": repo_root / "reports" / "stage2_multiseed_analysis" / "stage2_run_manifest.csv",
    }
    manifest_path = manifest_map[dataset]
    if not manifest_path.exists():
        return [], f"Manifest not found: {manifest_path}"

    manifest_df = pd.read_csv(manifest_path)
    sources: list[PredictionSource] = []
    for row in manifest_df.itertuples(index=False):
        run_dir = repo_root / str(row.run_dir)
        meta_path = run_dir / "run_metadata.json"
        if not meta_path.exists():
            continue
        meta = read_json(meta_path)
        split_type = str(meta.get("split_type", ""))
        pred_files = canonical_test_pred_files(run_dir / "predictions")
        pred_file = next((p for p in pred_files if f"test_preds_{split_type}_" in p.name), None)
        if pred_file is None:
            continue
        split_seed = parse_seed_from_name(pred_file.name)
        if dataset == "tdc":
            seed_label = (
                str(meta.get("train_config", {}).get("pytorch_seed"))
                if meta.get("train_config", {}).get("pytorch_seed") is not None
                else parse_torch_seed(run_dir.name) or "unknown"
            )
        else:
            seed_label = split_seed or "unknown"

        reason = (
            "Selected from the canonical Stage 2 manifest "
            f"{manifest_path.relative_to(repo_root)}."
        )
        sources.append(
            PredictionSource(
                dataset=infer_dataset_from_path(meta.get("dataset_path")),
                model="chemprop_dmnn",
                split_type=split_type,
                seed_label=str(seed_label),
                split_seed=split_seed,
                run_dir=str(run_dir),
                source_file=str(pred_file),
                source_type="stage2_manifest",
                selection_group=manifest_path.name,
                selection_reason=reason,
                status="available",
                manifest_path=str(manifest_path),
            )
        )

    return sources, f"Loaded {len(sources)} Stage 2 sources from {manifest_path.relative_to(repo_root)}."


def discover_sources(repo_root: Path, dataset_arg: str) -> tuple[list[PredictionSource], list[str]]:
    datasets = DATASET_ORDER if dataset_arg == "both" else [dataset_arg]
    sources: list[PredictionSource] = []
    notes: list[str] = []

    if "chembl" in datasets:
        chembl_sources, note = discover_stage2_manifest_sources(repo_root, "chembl")
        sources.extend(chembl_sources)
        notes.append(note)

    if "tdc" in datasets:
        tdc_stage2_sources, note = discover_stage2_manifest_sources(repo_root, "tdc")
        sources.extend(tdc_stage2_sources)
        notes.append(note)

        chosen_run_dir, xgb_sources, xgb_note = choose_stage1_xgboost_runset(repo_root)
        if xgb_sources:
            sources.extend(xgb_sources)
        notes.append(xgb_note)

    return sources, notes


def select_probability_column(df: pd.DataFrame) -> str:
    candidates = ["p_cal", "probability", "pred_prob", "prediction", "pred", "p", "y_score"]
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(f"Could not find a probability column in {list(df.columns)}")


def select_label_column(df: pd.DataFrame) -> str:
    candidates = ["y", "label", "target", "is_active"]
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(f"Could not find a label column in {list(df.columns)}")


def load_prediction_sources(sources: Iterable[PredictionSource]) -> pd.DataFrame:
    frames = []
    for source in sources:
        path = Path(source.source_file)
        if source.status != "available" or not path.exists():
            continue
        df = pd.read_csv(path)
        prob_col = select_probability_column(df)
        label_col = select_label_column(df)
        df = df.copy()
        df["pred_prob"] = pd.to_numeric(df[prob_col], errors="coerce")
        df["y_true"] = pd.to_numeric(df[label_col], errors="coerce")
        if "sim_bin" not in df.columns and "max_sim_to_train" in df.columns:
            df["sim_bin"] = derive_similarity_bin(df["max_sim_to_train"])
        elif "sim_bin" in df.columns:
            df["sim_bin"] = df["sim_bin"].astype(str)
        else:
            df["sim_bin"] = pd.NA

        df["dataset"] = source.dataset
        df["model"] = source.model
        df["split_type"] = source.split_type
        df["seed_label"] = source.seed_label
        df["split_seed"] = source.split_seed
        df["run_dir"] = source.run_dir
        df["source_file"] = source.source_file
        df["source_type"] = source.source_type
        df["selection_group"] = source.selection_group
        df["selection_reason"] = source.selection_reason
        df = df[df["pred_prob"].notna() & df["y_true"].notna()].copy()
        df["y_true"] = df["y_true"].astype(int)
        df["pred_prob"] = df["pred_prob"].clip(0.0, 1.0)
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined["split_type"] = pd.Categorical(combined["split_type"], categories=PLOT_SPLIT_ORDER, ordered=True)
    combined["model"] = pd.Categorical(combined["model"], categories=MODEL_ORDER, ordered=True)
    return combined


def calibration_intercept_slope(y_true: pd.Series, pred_prob: pd.Series) -> tuple[float, float]:
    if y_true.nunique() < 2 or len(y_true) < 10:
        return float("nan"), float("nan")

    clipped = np.clip(pred_prob.to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    x = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    y = y_true.to_numpy(dtype=int)

    try:
        from sklearn.linear_model import LogisticRegression
    except Exception:
        return float("nan"), float("nan")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            warnings.simplefilter("ignore", UserWarning)
            # Use an effectively unregularized fit while staying compatible
            # with the sklearn build in this environment.
            model = LogisticRegression(penalty="l2", C=1e12, solver="lbfgs", max_iter=1000)
            model.fit(x, y)
    except Exception:
        return float("nan"), float("nan")
    return float(model.intercept_[0]), float(model.coef_[0][0])


def compute_compression_stats(df: pd.DataFrame) -> dict[str, float | int | str]:
    if df.empty:
        return {
            "status": "missing_test_predictions",
            "n": 0,
            "prevalence": float("nan"),
            "mean_pred": float("nan"),
            "std_pred": float("nan"),
            "min_pred": float("nan"),
            "max_pred": float("nan"),
            "p05": float("nan"),
            "p25": float("nan"),
            "p50": float("nan"),
            "p75": float("nan"),
            "p95": float("nan"),
            "dynamic_range": float("nan"),
            "iqr": float("nan"),
            "label0_mean_pred": float("nan"),
            "label1_mean_pred": float("nan"),
            "label_gap": float("nan"),
            "calibration_intercept": float("nan"),
            "calibration_slope": float("nan"),
        }

    probs = df["pred_prob"].astype(float)
    y_true = df["y_true"].astype(int)
    label0 = probs[y_true == 0]
    label1 = probs[y_true == 1]
    p05, p25, p50, p75, p95 = np.quantile(probs, [0.05, 0.25, 0.50, 0.75, 0.95])
    intercept, slope = calibration_intercept_slope(y_true, probs)
    return {
        "status": "available",
        "n": int(len(df)),
        "prevalence": float(y_true.mean()),
        "mean_pred": float(probs.mean()),
        "std_pred": float(probs.std(ddof=1)) if len(probs) > 1 else float("nan"),
        "min_pred": float(probs.min()),
        "max_pred": float(probs.max()),
        "p05": float(p05),
        "p25": float(p25),
        "p50": float(p50),
        "p75": float(p75),
        "p95": float(p95),
        "dynamic_range": float(p95 - p05),
        "iqr": float(p75 - p25),
        "label0_mean_pred": float(label0.mean()) if len(label0) else float("nan"),
        "label1_mean_pred": float(label1.mean()) if len(label1) else float("nan"),
        "label_gap": float(label1.mean() - label0.mean()) if len(label0) and len(label1) else float("nan"),
        "calibration_intercept": intercept,
        "calibration_slope": slope,
    }


def build_master_summary(pred_df: pd.DataFrame, selected_sources: list[PredictionSource], datasets: list[str]) -> pd.DataFrame:
    selected_df = pd.DataFrame([asdict(s) for s in selected_sources])
    rows = []
    for dataset in datasets:
        for split_type in PLOT_SPLIT_ORDER:
            for model in MODEL_ORDER:
                subset = pred_df[
                    (pred_df["dataset"] == dataset)
                    & (pred_df["split_type"] == split_type)
                    & (pred_df["model"] == model)
                ].copy()
                source_subset = selected_df[
                    (selected_df["dataset"] == dataset)
                    & (selected_df["split_type"] == split_type)
                    & (selected_df["model"] == model)
                ].copy()
                row = {
                    "dataset": dataset,
                    "split_type": split_type,
                    "model": model,
                    "model_label": MODEL_LABELS[model],
                    "source_file_count": int(source_subset["source_file"].nunique()) if not source_subset.empty else 0,
                    "selected_seed_count": int(source_subset["seed_label"].nunique()) if not source_subset.empty else 0,
                    "selection_group": "|".join(sorted(source_subset["selection_group"].dropna().astype(str).unique()))
                    if not source_subset.empty else "",
                    "selection_reason": "|".join(sorted(source_subset["selection_reason"].dropna().astype(str).unique()))
                    if not source_subset.empty else "No saved test prediction files found.",
                }
                row.update(compute_compression_stats(subset))
                rows.append(row)
    summary = pd.DataFrame(rows)
    summary["dataset"] = pd.Categorical(summary["dataset"], categories=DATASET_ORDER, ordered=True)
    summary["split_type"] = pd.Categorical(summary["split_type"], categories=PLOT_SPLIT_ORDER, ordered=True)
    summary["model"] = pd.Categorical(summary["model"], categories=MODEL_ORDER, ordered=True)
    return summary.sort_values(["dataset", "split_type", "model"]).reset_index(drop=True)


def build_per_seed_summary(pred_df: pd.DataFrame) -> pd.DataFrame:
    if pred_df.empty:
        return pd.DataFrame()

    rows = []
    group_cols = ["dataset", "split_type", "model", "seed_label"]
    for key, subset in pred_df.groupby(group_cols, observed=True):
        dataset, split_type, model, seed_label = key
        row = {
            "dataset": dataset,
            "split_type": split_type,
            "model": model,
            "model_label": MODEL_LABELS[str(model)],
            "seed_label": seed_label,
            "source_file_count": int(subset["source_file"].nunique()),
        }
        row.update(compute_compression_stats(subset))
        rows.append(row)
    out = pd.DataFrame(rows)
    out["dataset"] = pd.Categorical(out["dataset"], categories=DATASET_ORDER, ordered=True)
    out["split_type"] = pd.Categorical(out["split_type"], categories=PLOT_SPLIT_ORDER, ordered=True)
    out["model"] = pd.Categorical(out["model"], categories=MODEL_ORDER, ordered=True)
    return out.sort_values(["dataset", "split_type", "model", "seed_label"]).reset_index(drop=True)


def build_cluster_similarity_summary(pred_df: pd.DataFrame) -> pd.DataFrame:
    cluster_df = pred_df[
        (pred_df["split_type"] == "cluster")
        & pred_df["sim_bin"].notna()
        & pred_df["sim_bin"].isin(SIM_BIN_ORDER)
    ].copy()
    if cluster_df.empty:
        return pd.DataFrame()

    rows = []
    for key, subset in cluster_df.groupby(["dataset", "model", "sim_bin"], observed=True):
        dataset, model, sim_bin = key
        row = {
            "dataset": dataset,
            "split_type": "cluster",
            "model": model,
            "model_label": MODEL_LABELS[str(model)],
            "sim_bin": sim_bin,
            "source_file_count": int(subset["source_file"].nunique()),
        }
        row.update(compute_compression_stats(subset))
        rows.append(row)
    out = pd.DataFrame(rows)
    out["dataset"] = pd.Categorical(out["dataset"], categories=DATASET_ORDER, ordered=True)
    out["model"] = pd.Categorical(out["model"], categories=MODEL_ORDER, ordered=True)
    out["sim_bin"] = pd.Categorical(out["sim_bin"], categories=SIM_BIN_ORDER, ordered=True)
    return out.sort_values(["dataset", "model", "sim_bin"]).reset_index(drop=True)


def reliability_curve_points(df: pd.DataFrame, n_bins: int) -> pd.DataFrame:
    rows = []
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    if df.empty:
        return pd.DataFrame(columns=["bin_left", "bin_right", "bin_mid", "n", "mean_pred", "frac_pos"])

    probs = df["pred_prob"].astype(float).to_numpy()
    y = df["y_true"].astype(int).to_numpy()
    for idx in range(n_bins):
        left = float(bin_edges[idx])
        right = float(bin_edges[idx + 1])
        if idx == n_bins - 1:
            mask = (probs >= left) & (probs <= right)
        else:
            mask = (probs >= left) & (probs < right)
        if not mask.any():
            rows.append({
                "bin_left": left,
                "bin_right": right,
                "bin_mid": (left + right) / 2.0,
                "n": 0,
                "mean_pred": float("nan"),
                "frac_pos": float("nan"),
            })
            continue
        rows.append({
            "bin_left": left,
            "bin_right": right,
            "bin_mid": (left + right) / 2.0,
            "n": int(mask.sum()),
            "mean_pred": float(probs[mask].mean()),
            "frac_pos": float(y[mask].mean()),
        })
    return pd.DataFrame(rows)


def build_reliability_data(pred_df: pd.DataFrame, n_bins: int) -> pd.DataFrame:
    rows = []
    if pred_df.empty:
        return pd.DataFrame()
    for key, subset in pred_df.groupby(["dataset", "split_type", "model"], observed=True):
        dataset, split_type, model = key
        rel_df = reliability_curve_points(subset, n_bins)
        rel_df["dataset"] = dataset
        rel_df["split_type"] = split_type
        rel_df["model"] = model
        rows.append(rel_df)
    out = pd.concat(rows, ignore_index=True)
    out["dataset"] = pd.Categorical(out["dataset"], categories=DATASET_ORDER, ordered=True)
    out["split_type"] = pd.Categorical(out["split_type"], categories=PLOT_SPLIT_ORDER, ordered=True)
    out["model"] = pd.Categorical(out["model"], categories=MODEL_ORDER, ordered=True)
    return out.sort_values(["dataset", "split_type", "model", "bin_left"]).reset_index(drop=True)


def dataset_output_dirs(output_root: Path, dataset: str) -> dict[str, Path]:
    base = output_root / dataset
    dirs = {
        "base": base,
        "figures": base / "figures",
        "tables": base / "tables",
        "data": base / "data",
    }
    for path in dirs.values():
        ensure_dir(path)
    return dirs


def available_panel_data(pred_df: pd.DataFrame, dataset: str, split_type: str, model: str) -> pd.DataFrame:
    return pred_df[
        (pred_df["dataset"] == dataset)
        & (pred_df["split_type"] == split_type)
        & (pred_df["model"] == model)
    ].copy()


def annotate_missing(ax: plt.Axes, title: str, message: str) -> None:
    ax.set_title(title, fontsize=9, fontweight="bold")
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=8, color="#555555", wrap=True)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(True)


def save_reliability_grid(dataset: str, pred_df: pd.DataFrame, n_bins: int, out_png: Path, out_pdf: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(9.0, 5.0), sharex=True, sharey=True)
    for row_idx, model in enumerate(MODEL_ORDER):
        for col_idx, split_type in enumerate(PLOT_SPLIT_ORDER):
            ax = axes[row_idx, col_idx]
            subset = available_panel_data(pred_df, dataset, split_type, model)
            title = f"{SPLIT_LABELS[split_type]}\n{MODEL_LABELS[model]}"
            if subset.empty:
                annotate_missing(ax, title, "Saved test predictions not found.")
                continue

            rel_df = reliability_curve_points(subset, n_bins)
            rel_df = rel_df[rel_df["n"] > 0].copy()
            ax.plot([0, 1], [0, 1], linestyle="--", linewidth=0.8, color="#999999")
            ax.plot(
                rel_df["mean_pred"],
                rel_df["frac_pos"],
                color=MODEL_COLORS[model],
                marker="o",
                linewidth=1.8,
                markersize=4.5,
            )
            ax.set_title(title, fontsize=9, fontweight="bold")
            ax.set_xlim(0.0, 1.0)
            ax.set_ylim(0.0, 1.0)
            ax.text(
                0.03,
                0.95,
                f"n={len(subset)}\nfiles={subset['source_file'].nunique()}",
                ha="left",
                va="top",
                fontsize=7,
                transform=ax.transAxes,
                bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=2.0),
            )
            if row_idx == 1:
                ax.set_xlabel("Mean predicted probability", fontsize=8)
            if col_idx == 0:
                ax.set_ylabel("Observed fraction positive", fontsize=8)
            ax.tick_params(labelsize=8)
    fig.suptitle(f"{dataset.upper()} reliability diagnostics", fontsize=11, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)


def save_cluster_reliability_focus(dataset: str, pred_df: pd.DataFrame, n_bins: int, out_png: Path, out_pdf: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=0.8, color="#999999", label="Perfect calibration")

    available_models = 0
    missing_labels = []
    for model in MODEL_ORDER:
        subset = available_panel_data(pred_df, dataset, "cluster", model)
        if subset.empty:
            missing_labels.append(MODEL_LABELS[model])
            continue
        available_models += 1
        rel_df = reliability_curve_points(subset, n_bins)
        rel_df = rel_df[rel_df["n"] > 0].copy()
        ax.plot(
            rel_df["mean_pred"],
            rel_df["frac_pos"],
            color=MODEL_COLORS[model],
            marker="o",
            linewidth=1.8,
            markersize=5,
            label=f"{MODEL_LABELS[model]} (n={len(subset)})",
        )

    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xlabel("Mean predicted probability", fontsize=9)
    ax.set_ylabel("Observed fraction positive", fontsize=9)
    ax.set_title(f"{dataset.upper()} cluster reliability comparison", fontsize=11, fontweight="bold")
    ax.tick_params(labelsize=8)
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    if missing_labels:
        ax.text(
            0.03,
            0.05,
            "Missing: " + ", ".join(missing_labels),
            transform=ax.transAxes,
            fontsize=8,
            color="#555555",
            ha="left",
            va="bottom",
        )
    fig.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)


def histogram_panel(ax: plt.Axes, subset: pd.DataFrame, model: str, title: str, show_ylabel: bool) -> None:
    if subset.empty:
        annotate_missing(ax, title, "Saved test predictions not found.")
        return

    bins = np.linspace(0.0, 1.0, 31)
    neg = subset.loc[subset["y_true"] == 0, "pred_prob"].astype(float)
    pos = subset.loc[subset["y_true"] == 1, "pred_prob"].astype(float)

    ax.hist(
        neg,
        bins=bins,
        density=True,
        histtype="step",
        linewidth=1.5,
        color=NEGATIVE_COLOR,
        label="y=0",
    )
    ax.hist(
        pos,
        bins=bins,
        density=True,
        alpha=0.45,
        color=MODEL_COLORS[model],
        edgecolor=MODEL_COLORS[model],
        label="y=1",
    )
    stats = compute_compression_stats(subset)
    ax.set_title(title, fontsize=9, fontweight="bold")
    ax.set_xlim(0.0, 1.0)
    ax.tick_params(labelsize=8)
    if show_ylabel:
        ax.set_ylabel("Density", fontsize=8)
    ax.text(
        0.03,
        0.95,
        f"n={stats['n']}\np95-p05={stats['dynamic_range']:.3f}\nlabel gap={stats['label_gap']:.3f}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=7,
        bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=2.0),
    )


def save_probability_grid(dataset: str, pred_df: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(9.0, 5.0), sharex=True)
    for row_idx, model in enumerate(MODEL_ORDER):
        for col_idx, split_type in enumerate(PLOT_SPLIT_ORDER):
            ax = axes[row_idx, col_idx]
            subset = available_panel_data(pred_df, dataset, split_type, model)
            title = f"{SPLIT_LABELS[split_type]}\n{MODEL_LABELS[model]}"
            histogram_panel(ax, subset, model, title, show_ylabel=(col_idx == 0))
            if row_idx == 1:
                ax.set_xlabel("Predicted probability", fontsize=8)
    handles = [
        plt.Line2D([0], [0], color=NEGATIVE_COLOR, linewidth=1.6, label="y=0"),
        plt.Rectangle((0, 0), 1, 1, facecolor=BLUE, alpha=0.45, edgecolor=BLUE, label="y=1"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=8, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(f"{dataset.upper()} predicted-probability distributions", fontsize=11, y=0.99)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)


def save_cluster_distribution_focus(dataset: str, pred_df: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.8), sharey=True)
    for idx, model in enumerate(MODEL_ORDER):
        ax = axes[idx]
        subset = available_panel_data(pred_df, dataset, "cluster", model)
        title = f"{MODEL_LABELS[model]} | CLUSTER"
        histogram_panel(ax, subset, model, title, show_ylabel=(idx == 0))
        if subset.empty:
            continue
        stats = compute_compression_stats(subset)
        ax.axvline(stats["p05"], color=MODEL_COLORS[model], linestyle="--", linewidth=1.0, alpha=0.9)
        ax.axvline(stats["p95"], color=MODEL_COLORS[model], linestyle="--", linewidth=1.0, alpha=0.9)
        ax.axvline(stats["p50"], color=MODEL_COLORS[model], linestyle=":", linewidth=1.0, alpha=0.9)
        ax.set_xlabel("Predicted probability", fontsize=8)
    fig.suptitle(f"{dataset.upper()} cluster probability comparison", fontsize=11, y=1.02)
    fig.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)


def save_cluster_similarity_grid(dataset: str, pred_df: pd.DataFrame, out_png: Path, out_pdf: Path) -> bool:
    cluster_df = pred_df[
        (pred_df["dataset"] == dataset)
        & (pred_df["split_type"] == "cluster")
        & pred_df["sim_bin"].notna()
        & pred_df["sim_bin"].isin(SIM_BIN_ORDER)
    ].copy()
    if cluster_df.empty:
        return False

    fig, axes = plt.subplots(2, 4, figsize=(11.0, 5.0), sharex=True)
    for row_idx, model in enumerate(MODEL_ORDER):
        for col_idx, sim_bin in enumerate(SIM_BIN_ORDER):
            ax = axes[row_idx, col_idx]
            subset = cluster_df[
                (cluster_df["model"] == model)
                & (cluster_df["sim_bin"] == sim_bin)
            ].copy()
            title = f"{MODEL_LABELS[model]}\n{SIM_BIN_LABELS[col_idx]}"
            histogram_panel(ax, subset, model, title, show_ylabel=(col_idx == 0))
            if row_idx == 1:
                ax.set_xlabel("Predicted probability", fontsize=8)
    fig.suptitle(f"{dataset.upper()} cluster distributions by similarity bin", fontsize=11, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)
    return True


def classify_signal(dataset: str, master_df: pd.DataFrame) -> str:
    ds = master_df[master_df["dataset"] == dataset].copy()
    xgb_cluster = ds[(ds["split_type"] == "cluster") & (ds["model"] == "xgboost")]
    dmpnn_cluster = ds[(ds["split_type"] == "cluster") & (ds["model"] == "chemprop_dmnn")]

    if xgb_cluster.empty or str(xgb_cluster.iloc[0]["status"]) != "available":
        if not dmpnn_cluster.empty and str(dmpnn_cluster.iloc[0]["status"]) == "available":
            return (
                "No clear compression signal can be established for ChEMBL XGBoost from the checked-in repo, "
                "because per-test ChEMBL XGBoost prediction files were not found. "
                "Within the available ChEMBL D-MPNN predictions, there is no direct evidence of severe probability collapse."
            )
        return "No saved per-test predictions were available to assess probability compression."

    xgb_cluster_row = xgb_cluster.iloc[0]
    dmpnn_cluster_row = dmpnn_cluster.iloc[0] if not dmpnn_cluster.empty else None
    xgb_other = ds[(ds["model"] == "xgboost") & (ds["split_type"].isin(["random", "scaffold"])) & (ds["status"] == "available")]

    cluster_dr = float(xgb_cluster_row["dynamic_range"])
    cluster_gap = float(xgb_cluster_row["label_gap"])
    other_dr = float(xgb_other["dynamic_range"].min()) if not xgb_other.empty else float("nan")
    dmpnn_dr = float(dmpnn_cluster_row["dynamic_range"]) if dmpnn_cluster_row is not None and str(dmpnn_cluster_row["status"]) == "available" else float("nan")

    severe_overlap = not math.isnan(cluster_gap) and cluster_gap < 0.08
    very_narrow = not math.isnan(cluster_dr) and cluster_dr < 0.10
    narrower_than_dmpnn = not math.isnan(dmpnn_dr) and cluster_dr < 0.60 * dmpnn_dr
    narrower_than_other_xgb = not math.isnan(other_dr) and cluster_dr < 0.70 * other_dr

    if very_narrow and severe_overlap:
        return "Probability collapse supported: XGBoost cluster predictions occupy a very narrow range with limited positive/negative separation."
    if narrower_than_dmpnn and narrower_than_other_xgb:
        return "Probability compression supported: XGBoost cluster predictions are materially narrower than both D-MPNN cluster predictions and XGBoost random/scaffold predictions."
    return "No clear compression signal."


def write_dataset_readme(
    dataset: str,
    output_dir: Path,
    selected_sources: pd.DataFrame,
    dataset_master: pd.DataFrame,
    dataset_per_seed: pd.DataFrame,
    similarity_available: bool,
) -> None:
    ds_sources = selected_sources[selected_sources["dataset"] == dataset].copy()
    ds_master = dataset_master[dataset_master["dataset"] == dataset].copy()
    signal_text = classify_signal(dataset, dataset_master)

    source_lines = []
    if ds_sources.empty:
        source_lines.append("- No saved per-test prediction sources were selected.")
    else:
        for _, row in ds_sources.sort_values(["model", "split_type", "seed_label"]).iterrows():
            source_lines.append(
                f"- `{row['model']}` / `{row['split_type']}` / seed `{row['seed_label']}`: "
                f"`{row['source_file']}`"
            )

    assumption_lines = [
        "- Expected prediction probability column: `p_cal` (fallbacks supported for other common names).",
        "- Expected label column: `y` (fallbacks supported for other common names).",
        "- If `sim_bin` was absent but `max_sim_to_train` was present, similarity bins were re-derived using thresholds 0.3 / 0.5 / 0.7.",
        "- Pooled summaries combine all selected seed-level prediction files for a given dataset x split x model combination.",
    ]
    if dataset == "chembl":
        assumption_lines.append(
            "- No per-test ChEMBL Stage 1 XGBoost prediction CSVs were found in the checked-in repo; ChEMBL XGBoost rows are therefore marked missing rather than back-filled from aggregate summaries."
        )

    key_rows = ds_master[["split_type", "model_label", "status", "n", "dynamic_range", "iqr", "label_gap"]].copy()
    key_rows["split_type"] = key_rows["split_type"].astype(str).map(SPLIT_LABELS)
    try:
        key_table = key_rows.to_markdown(index=False)
    except Exception:
        key_table = key_rows.to_string(index=False)

    source_text = "\n".join(source_lines)
    assumption_text = "\n".join(assumption_lines)

    per_seed_note = (
        f"Per-seed summary rows written: {len(dataset_per_seed)}."
        if not dataset_per_seed.empty else
        "No per-seed summary rows were available."
    )
    sim_note = (
        "Cluster similarity-bin plots/tables were generated from saved `sim_bin` values."
        if similarity_available else
        "Cluster similarity-bin plots/tables were skipped because similarity-bin data were unavailable."
    )

    readme = dedent(
        f"""# Probability Compression Analysis: {dataset.upper()}

## Files Found And Selected
{source_text}

## Column / Schema Assumptions
{assumption_text}

## Key Compression Summary
{key_table}

## Interpretation
{signal_text}

## Notes
- {per_seed_note}
- {sim_note}
"""
    ).strip() + "\n"
    (output_dir / "README.md").write_text(readme)


def save_dataset_artifacts(
    dataset: str,
    output_root: Path,
    pred_df: pd.DataFrame,
    source_df: pd.DataFrame,
    master_df: pd.DataFrame,
    per_seed_df: pd.DataFrame,
    cluster_bin_df: pd.DataFrame,
    reliability_df: pd.DataFrame,
    n_bins: int,
) -> None:
    dirs = dataset_output_dirs(output_root, dataset)
    ds_pred = pred_df[pred_df["dataset"] == dataset].copy()
    ds_source = source_df[source_df["dataset"] == dataset].copy()
    ds_master = master_df[master_df["dataset"] == dataset].copy()
    ds_per_seed = per_seed_df[per_seed_df["dataset"] == dataset].copy()
    ds_cluster_bin = cluster_bin_df[cluster_bin_df["dataset"] == dataset].copy()
    ds_reliability = reliability_df[reliability_df["dataset"] == dataset].copy()

    ds_pred.to_csv(dirs["data"] / "predictions_used.csv.gz", index=False, compression="gzip")
    ds_source.to_csv(dirs["data"] / "selected_prediction_sources.csv", index=False)
    ds_reliability.to_csv(dirs["data"] / "reliability_curve_points.csv", index=False)
    ds_master.to_csv(dirs["tables"] / "compression_summary.csv", index=False)
    ds_per_seed.to_csv(dirs["tables"] / "compression_summary_per_seed.csv", index=False)
    ds_master[ds_master["split_type"] == "cluster"].to_csv(dirs["tables"] / "cluster_only_compression_summary.csv", index=False)
    if not ds_cluster_bin.empty:
        ds_cluster_bin.to_csv(dirs["tables"] / "cluster_similarity_bin_compression_summary.csv", index=False)

    save_reliability_grid(
        dataset,
        pred_df,
        n_bins,
        dirs["figures"] / "reliability_grid.png",
        dirs["figures"] / "reliability_grid.pdf",
    )
    save_cluster_reliability_focus(
        dataset,
        pred_df,
        n_bins,
        dirs["figures"] / "reliability_cluster_focus.png",
        dirs["figures"] / "reliability_cluster_focus.pdf",
    )
    save_probability_grid(
        dataset,
        pred_df,
        dirs["figures"] / "probability_distribution_grid.png",
        dirs["figures"] / "probability_distribution_grid.pdf",
    )
    save_cluster_distribution_focus(
        dataset,
        pred_df,
        dirs["figures"] / "probability_distribution_cluster_focus.png",
        dirs["figures"] / "probability_distribution_cluster_focus.pdf",
    )
    similarity_available = save_cluster_similarity_grid(
        dataset,
        pred_df,
        dirs["figures"] / "probability_distribution_cluster_by_similarity.png",
        dirs["figures"] / "probability_distribution_cluster_by_similarity.pdf",
    )
    write_dataset_readme(
        dataset=dataset,
        output_dir=dirs["base"],
        selected_sources=source_df,
        dataset_master=master_df,
        dataset_per_seed=ds_per_seed,
        similarity_available=similarity_available,
    )


def print_dynamic_range_summary(master_df: pd.DataFrame) -> None:
    chembl = master_df[master_df["dataset"] == "chembl"].copy()
    print("\nChEMBL dynamic-range summary (p95 - p05):")
    for model in MODEL_ORDER:
        label = MODEL_LABELS[model]
        parts = []
        for split_type in SUMMARY_SPLIT_ORDER:
            row = chembl[(chembl["model"] == model) & (chembl["split_type"] == split_type)]
            if row.empty or str(row.iloc[0]["status"]) != "available":
                parts.append(f"{split_type}=N/A")
            else:
                parts.append(f"{split_type}={float(row.iloc[0]['dynamic_range']):.3f}")
        print(f"  {label}: " + ", ".join(parts))


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).expanduser().resolve()
    ensure_dir(output_root)
    datasets = DATASET_ORDER if args.dataset == "both" else [args.dataset]

    selected_sources, discovery_notes = discover_sources(REPO_ROOT, args.dataset)
    source_df = pd.DataFrame([asdict(s) for s in selected_sources])
    pred_df = load_prediction_sources(selected_sources)
    master_df = build_master_summary(pred_df, selected_sources, datasets)
    per_seed_df = build_per_seed_summary(pred_df)
    cluster_bin_df = build_cluster_similarity_summary(pred_df)
    reliability_df = build_reliability_data(pred_df, args.n_reliability_bins)

    source_df.to_csv(output_root / "selected_prediction_sources.csv", index=False)
    master_df.to_csv(output_root / "master_compression_summary.csv", index=False)
    per_seed_df.to_csv(output_root / "per_seed_compression_summary.csv", index=False)
    master_df[master_df["split_type"] == "cluster"].to_csv(output_root / "cluster_only_compression_summary.csv", index=False)
    if not cluster_bin_df.empty:
        cluster_bin_df.to_csv(output_root / "cluster_similarity_bin_compression_summary.csv", index=False)
    reliability_df.to_csv(output_root / "reliability_curve_points.csv", index=False)

    for dataset in datasets:
        save_dataset_artifacts(
            dataset=dataset,
            output_root=output_root,
            pred_df=pred_df,
            source_df=source_df,
            master_df=master_df,
            per_seed_df=per_seed_df,
            cluster_bin_df=cluster_bin_df,
            reliability_df=reliability_df,
            n_bins=args.n_reliability_bins,
        )

    print("Probability compression analysis completed.")
    print(f"Output root: {output_root}")
    print("Discovery notes:")
    for note in discovery_notes:
        print(f"  - {note}")
    print("\nMaster summary:")
    print(master_df[["dataset", "split_type", "model_label", "status", "n", "dynamic_range", "iqr", "label_gap"]].to_string(index=False))
    print_dynamic_range_summary(master_df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
