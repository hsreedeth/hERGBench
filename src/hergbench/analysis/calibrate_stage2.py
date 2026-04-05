# src/hergbench/analysis/calibrate_stage2.py
"""Post-hoc calibration alignment for Stage 2 D-MPNN runs.

Stage 1 uses Platt (sigmoid) for cluster splits and isotonic for random/scaffold.
Stage 2 was run with calibration_method=none (raw sigmoid outputs).  This module
re-applies the same calibration scheme to Stage 2 predictions using only the
raw probability outputs already on disk — no model re-training.

Calibration logic (matching Stage 1, see stage1_pipeline.py line ~258):
  cluster  → sigmoid  (Platt scaling)
  random   → isotonic
  scaffold → isotonic

Usage (CLI via hergbench calibrate-stage2):
  hergbench calibrate-stage2 --dataset chembl
  hergbench calibrate-stage2 --dataset tdc
  hergbench calibrate-stage2 --dataset both
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from hergbench.evaluation.eval import compute_metrics, select_threshold
from hergbench.evaluation.stage2_postprocess import fit_calibrator

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_AD_BINS = [0.3, 0.5, 0.7]

_DATASET_DEFAULTS: dict[str, tuple[str, str]] = {
    "tdc": (
        "reports/stage2_multiseed_analysis",
        "reports/stage2_multiseed_analysis",
    ),
    "chembl": (
        "reports/chembl_stage2_multiseed_analysis",
        "reports/chembl_stage2_multiseed_analysis",
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cal_method_for_split(split_type: str, method: str) -> str:
    """Resolve calibration method, matching Stage 1 logic when method='auto'."""
    if method != "auto":
        return method
    return "sigmoid" if split_type == "cluster" else "isotonic"


def _parse_run_dir_meta(run_dir: Path) -> dict:
    """Extract split_type, data_seed, pytorch_seed from a run dir name.

    Expected name pattern (from stage2_pipeline.py):
      YYYY-MM-DD_HHMMSS_stage2_chemprop_{split_type}_seed{N}_torch{M}
    """
    name = run_dir.name
    split_type = "unknown"
    for st in ("cluster", "random", "scaffold"):
        if st in name:
            split_type = st
            break

    m_seed = re.search(r"seed(\d+)", name)
    data_seed = int(m_seed.group(1)) if m_seed else 0

    m_torch = re.search(r"torch(\d+)", name)
    pytorch_seed = int(m_torch.group(1)) if m_torch else 42

    return {"split_type": split_type, "data_seed": data_seed, "pytorch_seed": pytorch_seed}


def _seed_label(dataset: str, data_seed: int, pytorch_seed: int) -> int:
    """Canonical seed stored in output DataFrames (matches stage2_multiseed_runner)."""
    return data_seed if dataset == "chembl" else pytorch_seed


def _bin_similarity(sim: float, bins: list[float]) -> str:
    if np.isnan(sim):
        return "missing"
    if sim < bins[0]:
        return f"<{bins[0]}"
    if sim < bins[1]:
        return f"{bins[0]}-{bins[1]}"
    if sim < bins[2]:
        return f"{bins[1]}-{bins[2]}"
    return f">{bins[2]}"


# ── Per-run calibration ───────────────────────────────────────────────────────

def calibrate_stage2_run(
    run_dir: Path,
    split_type: str,
    seed: int,
    method: str,
    threshold_metric: str = "youden",
    ad_bins: Optional[list[float]] = None,
) -> list[dict]:
    """Post-hoc calibrate a single Stage 2 run and return per-AD-bin metric rows.

    Reads raw probability outputs from ``predictions/preds.csv`` and ground-truth
    labels from ``chemprop_input_full.csv`` (both already on disk).  Fits a
    calibrator on the validation set, applies it to the test set, then reuses the
    pre-computed Tanimoto similarity bins from
    ``predictions/test_preds_{split_type}_seed{seed}_with_sim.csv``.

    No existing files are modified.

    Parameters
    ----------
    run_dir : Path to a completed Stage 2 run directory.
    split_type : "cluster", "random", or "scaffold".
    seed : canonical seed for this run (data_seed for ChEMBL, pytorch_seed for TDC).
    method : calibration method — "sigmoid" (Platt), "isotonic", or "auto".
    threshold_metric : "youden" (default).
    ad_bins : Tanimoto bin boundaries (default [0.3, 0.5, 0.7]).

    Returns
    -------
    List of per-bin metric dicts suitable for concatenation into a DataFrame.
    """
    if ad_bins is None:
        ad_bins = _DEFAULT_AD_BINS

    resolved_method = _cal_method_for_split(split_type, method)

    full_input_path = run_dir / "chemprop_input_full.csv"
    pred_path = run_dir / "predictions" / "preds.csv"
    with_sim_path = run_dir / "predictions" / f"test_preds_{split_type}_seed{seed}_with_sim.csv"

    for p in (full_input_path, pred_path):
        if not p.exists():
            logger.warning("Required file missing, skipping run %s: %s", run_dir.name, p)
            return []

    full_df = pd.read_csv(full_input_path)
    pred_df = pd.read_csv(pred_path)

    if len(full_df) != len(pred_df):
        logger.error("Row mismatch in %s (%d vs %d), skipping.", run_dir.name, len(full_df), len(pred_df))
        return []

    full_df = full_df.copy()
    full_df["p_raw"] = pred_df["y"].astype(float).values

    val_df = full_df[full_df["split"] == "val"].copy()
    test_df = full_df[full_df["split"] == "test"].copy()

    if len(val_df) == 0 or val_df["y"].nunique() < 2:
        logger.warning("Insufficient val data for calibration in %s, skipping.", run_dir.name)
        return []

    calibrator = fit_calibrator(
        y_val=val_df["y"].astype(int).to_numpy(),
        p_val_raw=val_df["p_raw"].astype(float).to_numpy(),
        method=resolved_method,
    )

    val_p_cal = calibrator.predict(val_df["p_raw"].to_numpy())
    threshold = select_threshold(
        y_true=val_df["y"].astype(int).to_numpy(),
        p=val_p_cal,
        metric=threshold_metric,
    )

    test_df = test_df.copy()
    test_df["p_cal"] = calibrator.predict(test_df["p_raw"].to_numpy())

    # Attach sim_bin from the pre-computed _with_sim file if available;
    # fall back to reconstructing bins from max_sim_to_train if present.
    if with_sim_path.exists():
        sim_df = pd.read_csv(with_sim_path)
        if len(sim_df) == len(test_df):
            test_df = test_df.reset_index(drop=True)
            test_df["sim_bin"] = sim_df["sim_bin"].values
            test_df["max_sim_to_train"] = sim_df["max_sim_to_train"].values
        else:
            logger.warning(
                "Row count mismatch between test set (%d) and _with_sim.csv (%d) in %s. "
                "Falling back to all-test bin.",
                len(test_df), len(sim_df), run_dir.name,
            )
            test_df["sim_bin"] = "all"
    else:
        logger.warning("_with_sim.csv not found for %s; using sim_bin='all'.", run_dir.name)
        test_df["sim_bin"] = "all"

    rows = []
    for sim_bin, grp in test_df.groupby("sim_bin", dropna=False):
        y_true = grp["y"].astype(int).to_numpy()
        p = grp["p_cal"].astype(float).to_numpy()
        if len(y_true) == 0:
            continue
        m = compute_metrics(y_true, p, threshold)
        rows.append({
            "split_type": split_type,
            "seed": seed,
            "sim_bin": sim_bin,
            "n": int(len(grp)),
            "calibration_method": resolved_method,
            **m,
        })

    logger.info(
        "  calibrate_stage2_run: %s  method=%s  bins=%d",
        run_dir.name, resolved_method, len(rows),
    )
    return rows


# ── Multi-run orchestration ───────────────────────────────────────────────────

def calibrate_all_stage2_runs(
    dataset: str,
    manifest_path: Optional[Path] = None,
    method: str = "auto",
    repo_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    threshold_metric: str = "youden",
    ad_bins: Optional[list[float]] = None,
    skip_existing: bool = True,
    fallback_to_raw: bool = True,
) -> pd.DataFrame:
    """Post-hoc calibrate all Stage 2 runs for a dataset.

    Reads the run manifest, calibrates each run, aggregates AD-bin metrics, and
    saves two artefacts (mirroring the original uncalibrated pipeline output):

      * ``stage2_ad_bins_calibrated_raw.csv``     — one row per (run × sim_bin)
      * ``stage2_ad_bins_calibrated_aggregated.csv`` — mean ± std across seeds

    Parameters
    ----------
    dataset : "tdc" or "chembl".
    manifest_path : path to stage2_run_manifest.csv.  Auto-resolved from dataset
        if None.
    method : "auto" (Stage-1-matching), "sigmoid", or "isotonic".
    repo_root : root used to resolve relative run_dir paths stored in the manifest.
        Defaults to the current working directory.
    output_dir : where to write calibrated CSVs.  Auto-resolved from dataset if None.
    threshold_metric : "youden" (default).
    ad_bins : Tanimoto bin boundaries (default [0.3, 0.5, 0.7]).
    skip_existing : return cached raw CSV without re-running if it already exists.
    fallback_to_raw : if all run dirs are missing (e.g. runs were on a remote pod and
        not downloaded), copy the existing uncalibrated raw CSV as the calibrated
        output with ``calibration_method=none``.  This lets downstream figures render
        even when per-run prediction files are unavailable.  Default True.

    Returns
    -------
    Aggregated DataFrame with mean ± std across seeds.
    """
    if dataset not in _DATASET_DEFAULTS:
        raise ValueError(f"Unknown dataset '{dataset}'. Choose from: {list(_DATASET_DEFAULTS)}")

    default_analysis_dir, default_out_dir = _DATASET_DEFAULTS[dataset]

    if manifest_path is None:
        manifest_path = Path(default_analysis_dir) / "stage2_run_manifest.csv"
    if output_dir is None:
        output_dir = Path(default_out_dir)
    if repo_root is None:
        repo_root = Path.cwd()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    calibrated_raw_path = output_dir / "stage2_ad_bins_calibrated_raw.csv"

    if skip_existing and calibrated_raw_path.exists():
        logger.info("Loading cached calibrated raw results from %s", calibrated_raw_path)
        raw_df = pd.read_csv(calibrated_raw_path)
        return _aggregate_calibrated(raw_df, dataset, output_dir)

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found: {manifest_path}\n"
            "Run the Stage 2 sweep first, or pass --manifest-path explicitly."
        )

    manifest_df = pd.read_csv(manifest_path)
    logger.info(
        "Calibrating %d Stage 2 runs for dataset=%s  method=%s",
        len(manifest_df), dataset, method,
    )

    all_rows: list[dict] = []

    for _, row in manifest_df.iterrows():
        run_dir_raw = str(row["run_dir"])
        run_dir = (
            Path(run_dir_raw)
            if Path(run_dir_raw).is_absolute()
            else repo_root / run_dir_raw
        )

        if not run_dir.exists():
            logger.warning("Run dir not found (skipping): %s", run_dir)
            continue

        meta = _parse_run_dir_meta(run_dir)
        split_type = meta["split_type"]
        seed = _seed_label(dataset, meta["data_seed"], meta["pytorch_seed"])

        rows = calibrate_stage2_run(
            run_dir=run_dir,
            split_type=split_type,
            seed=seed,
            method=method,
            threshold_metric=threshold_metric,
            ad_bins=ad_bins,
        )

        for r in rows:
            r["dataset"] = dataset

        all_rows.extend(rows)

    if not all_rows:
        if fallback_to_raw:
            return _fallback_to_raw(dataset, default_analysis_dir, output_dir)
        logger.error("No calibrated rows produced for dataset=%s. Check run dir paths.", dataset)
        return pd.DataFrame()

    raw_df = pd.DataFrame(all_rows)
    raw_df.to_csv(calibrated_raw_path, index=False)
    logger.info("Saved calibrated raw results: %s  (%d rows)", calibrated_raw_path, len(raw_df))

    return _aggregate_calibrated(raw_df, dataset, output_dir)


# ── Fallback ──────────────────────────────────────────────────────────────────

def _fallback_to_raw(dataset: str, analysis_dir: str, output_dir: Path) -> pd.DataFrame:
    """Use uncalibrated raw CSV as the calibrated output when run dirs are missing.

    This happens when Stage 2 was run on a remote pod and only the aggregated
    CSVs were downloaded (not the individual run directories).  The calibrated
    artefacts are written with ``calibration_method=none`` so downstream figures
    can render without crashing — the flat arrows in fig5 correctly communicate
    that calibration was not possible.
    """
    raw_path = Path(analysis_dir) / "stage2_ad_bins_raw.csv"
    if not raw_path.exists():
        logger.error(
            "Fallback failed: raw CSV not found at %s. "
            "Download the Stage 2 run directories or the raw CSV to enable calibration.",
            raw_path,
        )
        return pd.DataFrame()

    logger.warning(
        "Run directories not available for dataset=%s. "
        "Falling back to uncalibrated results (calibration_method=none). "
        "Download the run dirs and re-run to apply proper calibration.",
        dataset,
    )
    raw_df = pd.read_csv(raw_path)
    raw_df["calibration_method"] = "none"
    if "dataset" not in raw_df.columns:
        raw_df["dataset"] = dataset

    calibrated_raw_path = output_dir / "stage2_ad_bins_calibrated_raw.csv"
    raw_df.to_csv(calibrated_raw_path, index=False)
    logger.info("Saved fallback calibrated raw: %s  (%d rows)", calibrated_raw_path, len(raw_df))

    return _aggregate_calibrated(raw_df, dataset, output_dir)


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate_calibrated(
    raw_df: pd.DataFrame,
    dataset: str,
    output_dir: Path,
) -> pd.DataFrame:
    """Mean ± std across seeds, parallel to aggregate_stage2_results."""
    metric_cols = ["auroc", "auprc", "brier", "f1", "balanced_acc"]
    group_keys = ["dataset", "split_type", "sim_bin"]

    rows = []
    for key, grp in raw_df.groupby(group_keys):
        dataset_val, split_type, sim_bin = key
        n_seeds = int(grp["seed"].nunique())
        row: dict = {
            "dataset": dataset_val,
            "split_type": split_type,
            "sim_bin": sim_bin,
            "n_mean": float(grp["n"].mean()),
            "n_total": int(grp["n"].sum()),
            "n_seeds": n_seeds,
            "low_power": n_seeds < 3,
        }
        # Include calibration_method if consistent across group
        if "calibration_method" in grp.columns:
            methods = grp["calibration_method"].unique()
            row["calibration_method"] = methods[0] if len(methods) == 1 else "mixed"
        for m in metric_cols:
            vals = grp[m].dropna()
            row[f"{m}_mean"] = float(vals.mean()) if len(vals) > 0 else float("nan")
            row[f"{m}_std"] = float(vals.std()) if len(vals) > 1 else float("nan")
        rows.append(row)

    agg_df = pd.DataFrame(rows)
    agg_path = output_dir / "stage2_ad_bins_calibrated_aggregated.csv"
    agg_df.to_csv(agg_path, index=False)
    logger.info("Saved calibrated aggregated results: %s  (%d rows)", agg_path, len(agg_df))
    return agg_df
