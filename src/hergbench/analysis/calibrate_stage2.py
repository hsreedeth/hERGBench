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
from datetime import datetime, timezone
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

def _replace_or_write_csv(df: pd.DataFrame, path: Path) -> None:
    action = "Replacing" if path.exists() else "Writing"
    logger.info("%s %s", action, path)
    df.to_csv(path, index=False)


def _assert_required_columns(df: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise KeyError(f"{label} missing required columns: {missing}")


def _resolve_run_file(preferred: Path, fallback_pattern: Optional[str] = None) -> Path:
    if preferred.exists():
        return preferred
    if fallback_pattern is None:
        raise FileNotFoundError(f"Required file not found: {preferred}")

    matches = sorted(preferred.parent.glob(fallback_pattern))
    if len(matches) == 1:
        logger.warning("Using fallback file for %s -> %s", preferred.name, matches[0].name)
        return matches[0]
    if len(matches) > 1:
        raise FileNotFoundError(
            f"Ambiguous fallback for {preferred}: {[str(m) for m in matches]}"
        )
    raise FileNotFoundError(f"Required file not found: {preferred}")

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


def _load_stage2_run_inputs(
    run_dir: Path,
    split_type: str,
    data_seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    full_input_path = _resolve_run_file(run_dir / "chemprop_input_full.csv")
    pred_path = _resolve_run_file(
        run_dir / "predictions" / "preds.csv",
        fallback_pattern="preds*.csv",
    )
    with_sim_path = _resolve_run_file(
        run_dir / "predictions" / f"test_preds_{split_type}_seed{data_seed}_with_sim.csv",
        fallback_pattern=f"test_preds_{split_type}_seed{data_seed}_with_sim*.csv",
    )

    full_df = pd.read_csv(full_input_path)
    pred_df = pd.read_csv(pred_path)
    with_sim_df = pd.read_csv(with_sim_path)

    _assert_required_columns(full_df, {"y", "split", "smiles"}, str(full_input_path))
    _assert_required_columns(pred_df, {"y"}, str(pred_path))
    _assert_required_columns(with_sim_df, {"sim_bin", "max_sim_to_train", "smiles"}, str(with_sim_path))

    if len(full_df) != len(pred_df):
        raise ValueError(
            f"Row mismatch in {run_dir.name}: chemprop_input_full.csv={len(full_df)} preds.csv={len(pred_df)}"
        )

    if "smiles" in pred_df.columns:
        full_smiles = full_df["smiles"].astype(str).reset_index(drop=True)
        pred_smiles = pred_df["smiles"].astype(str).reset_index(drop=True)
        if not full_smiles.equals(pred_smiles):
            raise ValueError(f"SMILES row-order mismatch between full input and preds.csv in {run_dir.name}")

    if "split" in pred_df.columns:
        full_split = full_df["split"].astype(str).reset_index(drop=True)
        pred_split = pred_df["split"].astype(str).reset_index(drop=True)
        if not full_split.equals(pred_split):
            raise ValueError(f"Split row-order mismatch between full input and preds.csv in {run_dir.name}")

    return full_df, pred_df, with_sim_df


def _attach_similarity_bins(test_df: pd.DataFrame, with_sim_df: pd.DataFrame, run_dir: Path) -> pd.DataFrame:
    test_df = test_df.reset_index(drop=True).copy()

    if len(with_sim_df) != len(test_df):
        raise ValueError(
            f"Row mismatch in {run_dir.name}: test rows={len(test_df)} _with_sim rows={len(with_sim_df)}"
        )

    if "mol_id" in test_df.columns and "mol_id" in with_sim_df.columns:
        if test_df["mol_id"].astype(str).is_unique and with_sim_df["mol_id"].astype(str).is_unique:
            merged = test_df.merge(
                with_sim_df[["mol_id", "smiles", "sim_bin", "max_sim_to_train"]],
                on="mol_id",
                how="left",
                validate="one_to_one",
                suffixes=("", "_with_sim"),
            )
            if merged["sim_bin"].isna().any():
                raise ValueError(f"Unmatched mol_id rows while joining _with_sim.csv in {run_dir.name}")
            if "smiles_with_sim" in merged.columns:
                left = merged["smiles"].astype(str)
                right = merged["smiles_with_sim"].astype(str)
                if not left.equals(right):
                    raise ValueError(f"SMILES mismatch after mol_id join in {run_dir.name}")
                merged = merged.drop(columns=["smiles_with_sim"])
            return merged

    test_smiles = test_df["smiles"].astype(str)
    sim_smiles = with_sim_df["smiles"].astype(str).reset_index(drop=True)
    if not test_smiles.reset_index(drop=True).equals(sim_smiles):
        raise ValueError(f"SMILES row-order mismatch between test set and _with_sim.csv in {run_dir.name}")

    test_df["sim_bin"] = with_sim_df["sim_bin"].values
    test_df["max_sim_to_train"] = with_sim_df["max_sim_to_train"].values
    return test_df


def _safe_compute_metrics(y_true: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, float]:
    try:
        return compute_metrics(y_true, p, threshold)
    except Exception as exc:
        logger.warning("Metric computation failed; returning NaNs: %s", exc)
        return {
            "auroc": float("nan"),
            "auprc": float("nan"),
            "brier": float("nan"),
            "f1": float("nan"),
            "balanced_acc": float("nan"),
        }


# ── Per-run calibration ───────────────────────────────────────────────────────

def calibrate_stage2_run(
    run_dir: Path,
    split_type: str,
    seed: int,
    data_seed: Optional[int],
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
    data_seed : split seed used in the ``test_preds_*_with_sim.csv`` filename.
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
    split_seed = data_seed if data_seed is not None else seed

    full_df, pred_df, with_sim_df = _load_stage2_run_inputs(
        run_dir=run_dir,
        split_type=split_type,
        data_seed=split_seed,
    )

    full_df = full_df.copy()
    full_df["p_raw"] = pred_df["y"].astype(float).values

    val_df = full_df[full_df["split"] == "val"].copy()
    test_df = full_df[full_df["split"] == "test"].copy()

    if len(val_df) == 0 or val_df["y"].nunique() < 2:
        raise ValueError(f"Insufficient validation data for calibration in {run_dir.name}")

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
    test_df = _attach_similarity_bins(test_df, with_sim_df, run_dir)

    rows = []
    for sim_bin, grp in test_df.groupby("sim_bin", dropna=False, sort=True):
        y_true = grp["y"].astype(int).to_numpy()
        p = grp["p_cal"].astype(float).to_numpy()
        if len(y_true) == 0:
            continue
        m = _safe_compute_metrics(y_true, p, threshold)
        rows.append({
            "split_type": split_type,
            "seed": seed,
            "sim_bin": sim_bin,
            "n": int(len(grp)),
            "calibration_method": resolved_method,
            **m,
        })

    expected_test_rows = int(len(test_df))
    observed_test_rows = int(sum(r["n"] for r in rows))
    if observed_test_rows != expected_test_rows:
        raise ValueError(
            f"AD-bin row count mismatch in {run_dir.name}: expected {expected_test_rows}, got {observed_test_rows}"
        )

    logger.info(
        "  calibrate_stage2_run: %s  method=%s  bins=%d  n_test=%d",
        run_dir.name, resolved_method, len(rows), expected_test_rows,
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
            data_seed=meta["data_seed"],
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
    _replace_or_write_csv(raw_df, calibrated_raw_path)
    logger.info("Saved calibrated raw results: %s  (%d rows)", calibrated_raw_path, len(raw_df))

    return _aggregate_calibrated(raw_df, dataset, output_dir)


def _build_audit_row(
    dataset: str,
    split_type: str,
    seed: int,
    run_dir: Path,
    run_dir_raw: str,
    source_manifest: str,
    regenerated_at: str,
    calibration_method: str,
    full_df: pd.DataFrame,
    pred_df: pd.DataFrame,
    with_sim_df: pd.DataFrame,
    threshold_metric: str,
) -> tuple[list[dict], dict]:
    full_df = full_df.copy()
    full_df["p_raw"] = pred_df["y"].astype(float).values

    val_df = full_df[full_df["split"] == "val"].copy()
    test_df = full_df[full_df["split"] == "test"].copy()

    if len(val_df) == 0 or val_df["y"].nunique() < 2:
        raise ValueError(f"Insufficient validation data for calibration in {run_dir.name}")
    if len(test_df) == 0:
        raise ValueError(f"Empty test split in {run_dir.name}")

    y_val = val_df["y"].astype(int).to_numpy()
    p_val_raw = val_df["p_raw"].astype(float).to_numpy()
    y_test = test_df["y"].astype(int).to_numpy()
    p_test_raw = test_df["p_raw"].astype(float).to_numpy()

    raw_threshold = select_threshold(y_true=y_val, p=p_val_raw, metric=threshold_metric)
    raw_metrics = _safe_compute_metrics(y_test, p_test_raw, raw_threshold)

    calibrator = fit_calibrator(y_val=y_val, p_val_raw=p_val_raw, method=calibration_method)
    val_p_cal = calibrator.predict(p_val_raw)
    cal_threshold = select_threshold(y_true=y_val, p=val_p_cal, metric=threshold_metric)

    test_df = test_df.copy()
    test_df["p_cal"] = calibrator.predict(test_df["p_raw"].to_numpy())
    cal_metrics = _safe_compute_metrics(y_test, test_df["p_cal"].astype(float).to_numpy(), cal_threshold)

    test_with_bins = _attach_similarity_bins(test_df, with_sim_df, run_dir)

    bin_rows: list[dict] = []
    for sim_bin, grp in test_with_bins.groupby("sim_bin", dropna=False, sort=True):
        if len(grp) == 0:
            continue
        metrics = _safe_compute_metrics(
            grp["y"].astype(int).to_numpy(),
            grp["p_cal"].astype(float).to_numpy(),
            cal_threshold,
        )
        bin_rows.append(
            {
                "dataset": dataset,
                "split_type": split_type,
                "seed": seed,
                "sim_bin": sim_bin,
                "n": int(len(grp)),
                "auroc": metrics["auroc"],
                "auprc": metrics["auprc"],
                "brier": metrics["brier"],
                "f1": metrics["f1"],
                "balanced_acc": metrics["balanced_acc"],
                "calibration_method": calibration_method,
            }
        )

    expected_test_rows = int(len(test_df))
    binned_test_rows = int(sum(r["n"] for r in bin_rows))
    if binned_test_rows != expected_test_rows:
        raise ValueError(
            f"AD-bin row count mismatch in {run_dir.name}: expected {expected_test_rows}, got {binned_test_rows}"
        )

    auroc_delta = float(cal_metrics["auroc"] - raw_metrics["auroc"])
    brier_delta = float(cal_metrics["brier"] - raw_metrics["brier"])
    audit_row = {
        "dataset": dataset,
        "split_type": split_type,
        "seed": int(seed),
        "run_dir": run_dir_raw,
        "calibration_method": calibration_method,
        "n_test": expected_test_rows,
        "auroc_before": float(raw_metrics["auroc"]),
        "auroc_after": float(cal_metrics["auroc"]),
        "auroc_delta": auroc_delta,
        "auprc_before": float(raw_metrics["auprc"]),
        "auprc_after": float(cal_metrics["auprc"]),
        "auprc_delta": float(cal_metrics["auprc"] - raw_metrics["auprc"]),
        "brier_before": float(raw_metrics["brier"]),
        "brier_after": float(cal_metrics["brier"]),
        "brier_delta": brier_delta,
        "source_manifest": source_manifest,
        "regenerated_at": regenerated_at,
        "raw_threshold": float(raw_threshold),
        "calibrated_threshold": float(cal_threshold),
        "brier_direction": "improved" if brier_delta < 0 else ("worsened" if brier_delta > 0 else "unchanged"),
        "bin_row_count": len(bin_rows),
        "binned_test_rows": binned_test_rows,
        "row_count_match": binned_test_rows == expected_test_rows,
        "cluster_auroc_invariance_pass": (
            split_type != "cluster" or abs(auroc_delta) <= 1e-8
        ),
    }
    return bin_rows, audit_row


def _aggregate_audit_summary(audit_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dataset, split_type), grp in audit_df.groupby(["dataset", "split_type"], sort=True):
        rows.append(
            {
                "dataset": dataset,
                "split_type": split_type,
                "n_runs": int(len(grp)),
                "mean_auroc_before": float(grp["auroc_before"].mean()),
                "std_auroc_before": float(grp["auroc_before"].std(ddof=1)) if len(grp) > 1 else float("nan"),
                "mean_auroc_after": float(grp["auroc_after"].mean()),
                "std_auroc_after": float(grp["auroc_after"].std(ddof=1)) if len(grp) > 1 else float("nan"),
                "mean_auroc_delta": float(grp["auroc_delta"].mean()),
                "std_auroc_delta": float(grp["auroc_delta"].std(ddof=1)) if len(grp) > 1 else float("nan"),
                "mean_brier_before": float(grp["brier_before"].mean()),
                "std_brier_before": float(grp["brier_before"].std(ddof=1)) if len(grp) > 1 else float("nan"),
                "mean_brier_after": float(grp["brier_after"].mean()),
                "std_brier_after": float(grp["brier_after"].std(ddof=1)) if len(grp) > 1 else float("nan"),
                "mean_brier_delta": float(grp["brier_delta"].mean()),
                "std_brier_delta": float(grp["brier_delta"].std(ddof=1)) if len(grp) > 1 else float("nan"),
                "brier_improved_runs": int((grp["brier_delta"] < 0).sum()),
                "brier_worsened_runs": int((grp["brier_delta"] > 0).sum()),
                "cluster_auroc_invariance_all_pass": bool(grp["cluster_auroc_invariance_pass"].all()),
                "source_manifest": str(grp["source_manifest"].iloc[0]),
                "regenerated_at": str(grp["regenerated_at"].iloc[0]),
            }
        )
    return pd.DataFrame(rows)


def regenerate_stage2_calibration_audit(
    dataset: str,
    manifest_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    summary_dir: Optional[Path] = None,
    run_date_prefix: Optional[str] = None,
    threshold_metric: str = "youden",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if dataset not in _DATASET_DEFAULTS:
        raise ValueError(f"Unknown dataset '{dataset}'. Choose from: {list(_DATASET_DEFAULTS)}")

    default_analysis_dir, default_out_dir = _DATASET_DEFAULTS[dataset]
    if manifest_path is None:
        manifest_path = Path(default_analysis_dir) / "stage2_run_manifest.csv"
    if repo_root is None:
        repo_root = Path.cwd()
    if output_dir is None:
        output_dir = Path(default_out_dir)
    if summary_dir is None:
        summary_dir = Path("reports/summary")

    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    summary_dir = Path(summary_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest_df = pd.read_csv(manifest_path)
    if run_date_prefix:
        manifest_df = manifest_df[
            manifest_df["run_dir"].astype(str).map(lambda p: Path(p).name.startswith(run_date_prefix))
        ].copy()
    if manifest_df.empty:
        raise ValueError(
            f"No runs selected for dataset={dataset} from {manifest_path} with run_date_prefix={run_date_prefix!r}"
        )

    logger.info("Using manifest: %s", manifest_path)
    logger.info("Resolved %d run(s) for dataset=%s", len(manifest_df), dataset)
    for _, row in manifest_df.iterrows():
        logger.info("  %s", row["run_dir"])

    regenerated_at = datetime.now(timezone.utc).isoformat()
    all_bin_rows: list[dict] = []
    audit_rows: list[dict] = []

    for _, row in manifest_df.iterrows():
        run_dir_raw = str(row["run_dir"])
        run_dir = Path(run_dir_raw) if Path(run_dir_raw).is_absolute() else repo_root / run_dir_raw
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")

        meta = _parse_run_dir_meta(run_dir)
        split_type = meta["split_type"]
        data_seed = meta["data_seed"]
        seed = _seed_label(dataset, data_seed, meta["pytorch_seed"])
        calibration_method = _cal_method_for_split(split_type, "auto")

        logger.info(
            "Processing %s split=%s seed=%s data_seed=%s calibration=%s",
            run_dir.name,
            split_type,
            seed,
            data_seed,
            calibration_method,
        )

        full_df, pred_df, with_sim_df = _load_stage2_run_inputs(
            run_dir=run_dir,
            split_type=split_type,
            data_seed=data_seed,
        )
        bin_rows, audit_row = _build_audit_row(
            dataset=dataset,
            split_type=split_type,
            seed=seed,
            run_dir=run_dir,
            run_dir_raw=run_dir_raw,
            source_manifest=str(manifest_path),
            regenerated_at=regenerated_at,
            calibration_method=calibration_method,
            full_df=full_df,
            pred_df=pred_df,
            with_sim_df=with_sim_df,
            threshold_metric=threshold_metric,
        )
        all_bin_rows.extend(bin_rows)
        audit_rows.append(audit_row)

    raw_df = pd.DataFrame(all_bin_rows)
    raw_columns = [
        "dataset",
        "split_type",
        "seed",
        "sim_bin",
        "n",
        "auroc",
        "auprc",
        "brier",
        "f1",
        "balanced_acc",
        "calibration_method",
    ]
    raw_df = raw_df[raw_columns]
    raw_output_path = output_dir / "stage2_ad_bins_calibrated_raw.csv"
    _replace_or_write_csv(raw_df, raw_output_path)

    agg_df = _aggregate_calibrated(raw_df, dataset, output_dir)

    audit_df = pd.DataFrame(audit_rows)
    audit_output_path = summary_dir / "calibration_check.csv"
    _replace_or_write_csv(audit_df, audit_output_path)

    audit_agg_df = _aggregate_audit_summary(audit_df)
    audit_agg_output_path = summary_dir / "calibration_check_aggregate.csv"
    _replace_or_write_csv(audit_agg_df, audit_agg_output_path)

    cluster_failures = audit_df[
        audit_df["split_type"].eq("cluster") & ~audit_df["cluster_auroc_invariance_pass"]
    ]
    if not cluster_failures.empty:
        raise ValueError(
            "Cluster AUROC invariance check failed:\n"
            f"{cluster_failures[['seed', 'auroc_before', 'auroc_after', 'auroc_delta']].to_string(index=False)}"
        )

    logger.info("Wrote calibrated raw CSV: %s", raw_output_path)
    logger.info("Wrote calibrated aggregated CSV: %s", output_dir / "stage2_ad_bins_calibrated_aggregated.csv")
    logger.info("Wrote audit summary: %s", audit_output_path)
    logger.info("Wrote audit aggregate summary: %s", audit_agg_output_path)
    return raw_df, audit_df, audit_agg_df


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
    _replace_or_write_csv(raw_df, calibrated_raw_path)
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
    _replace_or_write_csv(agg_df, agg_path)
    logger.info("Saved calibrated aggregated results: %s  (%d rows)", agg_path, len(agg_df))
    return agg_df
