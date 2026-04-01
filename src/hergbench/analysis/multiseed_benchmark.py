"""
Multi-seed Stage 1 benchmark runner and aggregator.

Runs (or loads) XGBoost benchmarks for all 5 seeds × 3 split types, then
aggregates AD-binned metrics with mean/std across seeds.

Supports two datasets:
  - "tdc"    : data/processed/herg_clean.csv + data/splits/
  - "chembl" : data/chembl/processed/chembl_herg_clean.csv + data/chembl/splits/
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SEEDS = [11, 22, 33, 44, 55]
SPLIT_TYPES = ["random", "scaffold", "cluster"]
AD_BINS = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]

_AD_BIN_EDGES = [0.3, 0.5, 0.7]

# Per-dataset defaults: (data_path, splits_dir, output_dir)
_DATASET_PATHS: dict[str, Tuple[str, str, str]] = {
    "tdc": (
        "data/processed/herg_clean.csv",
        "data/splits",
        "reports/multiseed_analysis",
    ),
    "chembl": (
        "data/chembl/processed/chembl_herg_clean.csv",
        "data/chembl/splits",
        "reports/chembl_multiseed_analysis",
    ),
}

_DEFAULT_XGB_CFG = {
    "objective": "aucpr",
    "optuna_trials": 75,
    "max_estimators": 4000,
    "early_stopping_rounds": 50,
}
_DEFAULT_CAL_CFG = {
    "method": "isotonic",
    "threshold_metric": "youden",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def assign_ad_bin(sim: float) -> str:
    """Assign a Tanimoto similarity value to its AD bin label."""
    if sim < 0.3:
        return "<0.3"
    if sim < 0.5:
        return "0.3-0.5"
    if sim < 0.7:
        return "0.5-0.7"
    return ">0.7"


def compute_max_sim_to_train(
    test_smiles: List[str],
    train_fps: list,
    fp_cfg,
) -> List[float]:
    """For each test molecule, compute max Tanimoto to any training molecule."""
    from rdkit import Chem, DataStructs
    from hergbench.features.fingerprints import mol_to_ecfp_bits

    results = []
    for smi in test_smiles:
        mol = Chem.MolFromSmiles(str(smi))
        if mol is None:
            results.append(0.0)
            continue
        fp = mol_to_ecfp_bits(mol, fp_cfg)
        sims = DataStructs.BulkTanimotoSimilarity(fp, train_fps)
        results.append(float(max(sims)) if sims else 0.0)
    return results


def _raw_results_path(output_dir: Path) -> Path:
    return output_dir / "multiseed_ad_bins_raw.csv"


def _run_one(
    split_type: str,
    seed: int,
    df: pd.DataFrame,
    fps_all: list,
    idx_map: dict,
    fp_cfg,
    xgb_cfg_dict: dict,
    cal_cfg_dict: dict,
    random_state: int,
    splits_dir: Path = Path("data/splits"),
) -> List[dict]:
    """Train + evaluate for one (split_type, seed). Returns list of per-bin dicts."""
    from hergbench.data.splits import split_df
    from hergbench.features.fingerprints import fps_to_numpy, bulk_max_tanimoto
    from hergbench.models.xgb_optuna import XGBConfig, tune_xgb, fit_xgb
    from hergbench.evaluation.eval import (
        CalibrationConfig, calibrate_prefit, select_threshold, compute_metrics,
    )

    split_csv = Path(splits_dir) / f"{split_type}_seed{seed}.csv"
    if not split_csv.exists():
        logger.warning("Split file not found: %s — skipping.", split_csv)
        return []

    train_df, val_df, test_df = split_df(df, split_csv)

    def _idx_arr(sub: pd.DataFrame) -> np.ndarray:
        return np.array(
            [idx_map[m] for m in sub["mol_id"].astype(str) if m in idx_map],
            dtype=int,
        )

    tr_idx = _idx_arr(train_df)
    va_idx = _idx_arr(val_df)
    te_idx = _idx_arr(test_df)

    if len(tr_idx) == 0 or len(va_idx) == 0 or len(te_idx) == 0:
        logger.warning(
            "Empty split partition for %s seed%d — skipping.", split_type, seed
        )
        return []

    X_all = fps_to_numpy(fps_all)
    X_train, y_train = X_all[tr_idx], train_df.loc[
        train_df["mol_id"].isin(idx_map), "y"
    ].values
    X_val, y_val = X_all[va_idx], val_df.loc[
        val_df["mol_id"].isin(idx_map), "y"
    ].values
    X_test, y_test = X_all[te_idx], test_df.loc[
        test_df["mol_id"].isin(idx_map), "y"
    ].values

    # Rebuild arrays aligned to idx ordering (split_df preserves row order)
    y_train = train_df["y"].values[np.argsort(tr_idx)[np.argsort(np.argsort(tr_idx))]]
    y_val   = val_df["y"].values[np.argsort(va_idx)[np.argsort(np.argsort(va_idx))]]
    y_test  = test_df["y"].values[np.argsort(te_idx)[np.argsort(np.argsort(te_idx))]]
    # Simpler: just use df.iloc order which matches tr_idx
    y_train = df.iloc[tr_idx]["y"].values
    y_val   = df.iloc[va_idx]["y"].values
    y_test  = df.iloc[te_idx]["y"].values

    pos = float((y_train == 1).sum())
    neg = float((y_train == 0).sum())
    scale_pos_weight = (neg / pos) if pos > 0 else 1.0

    xgb_cfg = XGBConfig(
        objective=xgb_cfg_dict.get("objective", "aucpr"),
        optuna_trials=xgb_cfg_dict.get("optuna_trials", 75),
        max_estimators=xgb_cfg_dict.get("max_estimators", 4000),
        early_stopping_rounds=xgb_cfg_dict.get("early_stopping_rounds", 50),
        random_state=random_state,
    )
    cal_cfg = CalibrationConfig(
        method=cal_cfg_dict.get("method", "isotonic"),
        threshold_metric=cal_cfg_dict.get("threshold_metric", "youden"),
    )

    logger.info("Tuning XGBoost for %s seed%d...", split_type, seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        best_params, _ = tune_xgb(X_train, y_train, X_val, y_val,
                                   xgb_cfg, scale_pos_weight)
        model = fit_xgb(X_train, y_train, X_val, y_val,
                        best_params, xgb_cfg, scale_pos_weight)

    cal_model = calibrate_prefit(model, X_val, y_val, cal_cfg.method)
    p_val = cal_model.predict_proba(X_val)[:, 1]
    threshold = select_threshold(y_val, p_val, cal_cfg.threshold_metric)

    p_test = cal_model.predict_proba(X_test)[:, 1]

    # AD binning
    train_fps = [fps_all[i] for i in tr_idx]
    test_fps_list = [fps_all[i] for i in te_idx]
    max_sims = bulk_max_tanimoto(test_fps_list, train_fps)
    sim_bins = [assign_ad_bin(s) for s in max_sims]

    rows = []
    for b in AD_BINS:
        mask = np.array([sb == b for sb in sim_bins], dtype=bool)
        n_bin = int(mask.sum())
        if n_bin == 0:
            continue
        try:
            m = compute_metrics(y_test[mask], p_test[mask], threshold)
        except Exception as exc:
            logger.warning(
                "Metrics failed for %s seed%d bin %s: %s", split_type, seed, b, exc
            )
            m = {"auroc": float("nan"), "auprc": float("nan"),
                 "brier": float("nan"), "f1": float("nan"),
                 "balanced_acc": float("nan")}
        rows.append({
            "split_type": split_type,
            "seed": seed,
            "sim_bin": b,
            "n": n_bin,
            **m,
        })

    logger.info(
        "Done %s seed%d — threshold=%.3f, %d test compounds, %d non-empty bins.",
        split_type, seed, threshold, len(y_test), len(rows),
    )
    return rows


# ── Public API ────────────────────────────────────────────────────────────────

def run_multiseed_benchmark(
    dataset: str = "tdc",
    config_base: str = "configs/base.yaml",
    data_path: Optional[str] = None,
    splits_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    skip_existing: bool = True,
    xgb_cfg_overrides: Optional[dict] = None,
    cal_cfg_overrides: Optional[dict] = None,
    random_state: int = 42,
) -> pd.DataFrame:
    """Run Stage 1 XGBoost benchmarks for all seeds × split types.

    For each (split_type, seed):
    1. Load the pre-computed split CSV
    2. Train + calibrate an XGBoost model
    3. Compute per-molecule max_sim_to_train and AD bins on the test set
    4. Compute per-bin metrics: AUROC, AUPRC, Brier, F1, balanced accuracy

    Parameters
    ----------
    dataset : "tdc" or "chembl". Controls default data_path/splits_dir/output_dir.
    config_base : unused (reserved for future YAML config loading)
    data_path : path to the cleaned hERG dataset CSV. Auto-resolved from dataset if None.
    splits_dir : directory containing {split_type}_seed{N}.csv files. Auto-resolved if None.
    output_dir : where to write intermediate and final CSVs. Auto-resolved if None.
    skip_existing : if True and raw results CSV exists, load and return it
    xgb_cfg_overrides : override defaults for XGBConfig fields
    cal_cfg_overrides : override defaults for CalibrationConfig fields
    random_state : master random seed passed to XGBoost

    Returns
    -------
    DataFrame with columns:
        dataset, split_type, seed, sim_bin, n, auroc, auprc, brier, f1, balanced_acc
    """
    if dataset not in _DATASET_PATHS:
        raise ValueError(f"Unknown dataset '{dataset}'. Choose from: {list(_DATASET_PATHS)}")

    _default_data, _default_splits, _default_output = _DATASET_PATHS[dataset]
    data_path = data_path or _default_data
    splits_dir = splits_dir or _default_splits
    output_dir = output_dir or _default_output

    from hergbench.features.fingerprints import FingerprintConfig
    from hergbench.features.fingerprints import mol_to_ecfp_bits
    from rdkit import Chem

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = _raw_results_path(out_dir)
    if skip_existing and raw_path.exists():
        logger.info("Loading existing raw results from %s", raw_path)
        return pd.read_csv(raw_path)

    xgb_cfg_dict = {**_DEFAULT_XGB_CFG, **(xgb_cfg_overrides or {})}
    cal_cfg_dict = {**_DEFAULT_CAL_CFG, **(cal_cfg_overrides or {})}

    fp_cfg = FingerprintConfig(radius=2, n_bits=2048)

    logger.info("Loading dataset from %s", data_path)
    df = pd.read_csv(data_path)
    df = df.sort_values("mol_id").reset_index(drop=True)

    logger.info("Computing fingerprints for %d molecules...", len(df))
    fps_all = []
    for smi in df["smiles"].astype(str):
        mol = Chem.MolFromSmiles(smi)
        fps_all.append(mol_to_ecfp_bits(mol, fp_cfg) if mol is not None else None)

    idx_map = {mol_id: i for i, mol_id in enumerate(df["mol_id"].astype(str))}

    splits_dir_path = Path(splits_dir)
    all_rows: list[dict] = []
    for split_type in SPLIT_TYPES:
        for seed in SEEDS:
            logger.info("=== %s seed%d ===", split_type, seed)
            try:
                rows = _run_one(
                    split_type=split_type,
                    seed=seed,
                    df=df,
                    fps_all=fps_all,
                    idx_map=idx_map,
                    fp_cfg=fp_cfg,
                    xgb_cfg_dict=xgb_cfg_dict,
                    cal_cfg_dict=cal_cfg_dict,
                    random_state=random_state,
                    splits_dir=splits_dir_path,
                )
                for r in rows:
                    r["dataset"] = dataset
                all_rows.extend(rows)
            except Exception as exc:
                logger.error(
                    "Failed %s seed%d: %s", split_type, seed, exc, exc_info=True
                )

    raw_df = pd.DataFrame(all_rows)
    # Reorder so dataset is the first column
    if "dataset" in raw_df.columns:
        cols = ["dataset"] + [c for c in raw_df.columns if c != "dataset"]
        raw_df = raw_df[cols]
    raw_df.to_csv(raw_path, index=False)
    logger.info("Saved raw results to %s (%d rows)", raw_path, len(raw_df))
    return raw_df


def aggregate_multiseed_results(
    results_df: pd.DataFrame,
    output_dir: str = "reports/multiseed_analysis",
) -> pd.DataFrame:
    """Aggregate per-seed AD-bin metrics into mean ± std across seeds.

    Parameters
    ----------
    results_df:
        DataFrame returned by ``run_multiseed_benchmark``.  May contain a
        ``dataset`` column when multiple datasets are combined.
    output_dir:
        Where to write the three output CSVs.

    Returns
    -------
    DataFrame with columns:
        [dataset,] split_type, sim_bin, n_mean, n_total, n_seeds,
        auroc_mean, auroc_std, auprc_mean, auprc_std,
        brier_mean, brier_std, low_power
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metric_cols = ["auroc", "auprc", "brier", "f1", "balanced_acc"]
    has_dataset = "dataset" in results_df.columns

    group_keys = (["dataset", "split_type", "sim_bin"] if has_dataset
                  else ["split_type", "sim_bin"])
    summary_keys = (["dataset", "split_type"] if has_dataset else ["split_type"])

    rows = []
    for key, grp in results_df.groupby(group_keys):
        n_seeds = int(grp["seed"].nunique())
        if has_dataset:
            dataset_val, split_type, sim_bin = key
            row: dict = {"dataset": dataset_val, "split_type": split_type, "sim_bin": sim_bin}
        else:
            split_type, sim_bin = key
            row = {"split_type": split_type, "sim_bin": sim_bin}
        row.update({
            "n_mean": float(grp["n"].mean()),
            "n_total": int(grp["n"].sum()),
            "n_seeds": n_seeds,
            "low_power": n_seeds < 3,
        })
        for m in metric_cols:
            vals = grp[m].dropna()
            row[f"{m}_mean"] = float(vals.mean()) if len(vals) > 0 else float("nan")
            row[f"{m}_std"] = float(vals.std()) if len(vals) > 1 else float("nan")
        rows.append(row)

    agg_df = pd.DataFrame(rows)

    # Per (dataset,) split_type summary across all bins
    summary_rows = []
    for key, grp in results_df.groupby(summary_keys):
        if has_dataset:
            dataset_val, split_type = key
            s_row: dict = {"dataset": dataset_val, "split_type": split_type}
        else:
            split_type = key
            s_row = {"split_type": split_type}
        for m in metric_cols:
            vals = grp[m].dropna()
            s_row[f"{m}_mean"] = float(vals.mean()) if len(vals) > 0 else float("nan")
            s_row[f"{m}_std"] = float(vals.std()) if len(vals) > 1 else float("nan")
        summary_rows.append(s_row)
    summary_df = pd.DataFrame(summary_rows)

    # Save all three outputs
    results_df.to_csv(out_dir / "multiseed_ad_bins_raw.csv", index=False)
    agg_df.to_csv(out_dir / "multiseed_ad_bins_aggregated.csv", index=False)
    summary_df.to_csv(out_dir / "multiseed_benchmark_summary.csv", index=False)

    low_power = agg_df[agg_df["low_power"]]
    if not low_power.empty:
        for _, r in low_power.iterrows():
            prefix = f"{r['dataset']} / " if has_dataset else ""
            logger.warning(
                "LOW POWER: %s%s / %s has data from only %d seeds.",
                prefix, r["split_type"], r["sim_bin"], r["n_seeds"],
            )

    logger.info(
        "Saved aggregated results to %s (raw=%d rows, agg=%d rows)",
        out_dir, len(results_df), len(agg_df),
    )
    return agg_df
