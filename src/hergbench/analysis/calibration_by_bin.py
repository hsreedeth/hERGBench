"""
Tanimoto-binned calibration vs discrimination analysis.

Central figure generator for the calibration-thesis paper.
Compares XGBoost (Stage 1) and D-MPNN (Stage 2) under cluster split.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def build_cross_model_comparison(
    stage1_raw: pd.DataFrame,
    stage2_raw: pd.DataFrame,
    output_dir: str = "reports/cross_model_comparison",
) -> pd.DataFrame:
    """Merge Stage 1 (XGBoost) and Stage 2 (D-MPNN) AD-binned metrics.

    Both input DataFrames must have columns:
        [dataset,] split_type, seed, sim_bin, n, auroc, auprc, brier, f1, balanced_acc

    Each is labelled with a ``model`` column, then aggregated (mean ± std) across
    seeds within each (dataset, split_type, sim_bin, model) group.

    Parameters
    ----------
    stage1_raw :
        Raw per-seed rows from ``multiseed_benchmark.run_multiseed_benchmark()``.
    stage2_raw :
        Raw per-seed rows from ``stage2_multiseed_runner.run_stage2_multiseed()``.
    output_dir :
        Where to write the two output CSVs.

    Returns
    -------
    DataFrame with columns:
        [dataset,] split_type, sim_bin, model,
        auroc_mean, auroc_std, auprc_mean, auprc_std,
        brier_mean, brier_std, f1_mean, f1_std,
        balanced_acc_mean, balanced_acc_std, n_mean, n_seeds

    This is the table that becomes the paper's main result table.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metric_cols = ["auroc", "auprc", "brier", "f1", "balanced_acc"]

    s1 = stage1_raw.copy()
    s2 = stage2_raw.copy()
    s1["model"] = "xgboost"
    s2["model"] = "chemprop_dmnn"

    combined = pd.concat([s1, s2], ignore_index=True)

    has_dataset = "dataset" in combined.columns
    group_keys = (["dataset", "split_type", "sim_bin", "model"] if has_dataset
                  else ["split_type", "sim_bin", "model"])

    rows = []
    for key, grp in combined.groupby(group_keys, observed=True):
        n_seeds = int(grp["seed"].nunique())
        if has_dataset:
            dataset_val, split_type, sim_bin, model = key
            row: dict = {
                "dataset": dataset_val,
                "split_type": split_type,
                "sim_bin": sim_bin,
                "model": model,
            }
        else:
            split_type, sim_bin, model = key
            row = {"split_type": split_type, "sim_bin": sim_bin, "model": model}

        row.update({
            "n_mean": float(grp["n"].mean()),
            "n_seeds": n_seeds,
        })
        for m in metric_cols:
            vals = grp[m].dropna()
            row[f"{m}_mean"] = float(vals.mean()) if len(vals) > 0 else float("nan")
            row[f"{m}_std"] = float(vals.std()) if len(vals) > 1 else float("nan")
        rows.append(row)

    agg_df = pd.DataFrame(rows)

    # Summary collapsed across AD bins (macro-average per model × split_type)
    summary_keys = (["dataset", "split_type", "model"] if has_dataset
                    else ["split_type", "model"])
    summary_rows = []
    for key, grp in combined.groupby(summary_keys, observed=True):
        if has_dataset:
            dataset_val, split_type, model = key
            s_row: dict = {"dataset": dataset_val, "split_type": split_type, "model": model}
        else:
            split_type, model = key
            s_row = {"split_type": split_type, "model": model}
        for m in metric_cols:
            vals = grp[m].dropna()
            s_row[f"{m}_mean"] = float(vals.mean()) if len(vals) > 0 else float("nan")
            s_row[f"{m}_std"] = float(vals.std()) if len(vals) > 1 else float("nan")
        summary_rows.append(s_row)
    summary_df = pd.DataFrame(summary_rows)

    agg_df.to_csv(out_dir / "cross_model_ad_bins.csv", index=False)
    summary_df.to_csv(out_dir / "cross_model_summary.csv", index=False)

    return agg_df
