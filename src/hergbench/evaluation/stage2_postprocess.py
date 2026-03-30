# src/hergbench/evaluation/stage2_postprocess.py

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from hergbench.evaluation.eval import (
    bootstrap_ci,
    compute_metrics,
    plot_reliability,
    select_threshold,
)
# using the same fingerprint helpers Stage 1 uses.
from hergbench.features.fingerprints import (
    FingerprintConfig,
    bulk_max_tanimoto,
    mol_to_ecfp_bits,
)
from rdkit import Chem


def _normalize_calibration_method(method: str) -> str:
    method = str(method).strip().lower()
    if method in {"none", "identity", "raw"}:
        return "none"
    if method in {"platt", "sigmoid", "logistic"}:
        return "sigmoid"
    if method == "isotonic":
        return "isotonic"
    raise ValueError(f"Unsupported calibration method: {method}")


class RawProbCalibrator:
    def __init__(self, method: str, fitted):
        self.method = method
        self.fitted = fitted

    def predict(self, p_raw: np.ndarray) -> np.ndarray:
        p_raw = np.asarray(p_raw, dtype=float)

        if self.method == "none":
            out = p_raw
        elif self.method == "isotonic":
            out = self.fitted.transform(p_raw)
        elif self.method == "sigmoid":
            out = self.fitted.predict_proba(p_raw.reshape(-1, 1))[:, 1]
        else:
            raise ValueError(f"Unknown calibration method: {self.method}")

        return np.clip(out, 0.0, 1.0)


def fit_calibrator(y_val: np.ndarray, p_val_raw: np.ndarray, method: str) -> RawProbCalibrator:
    method = _normalize_calibration_method(method)
    y_val = np.asarray(y_val).astype(int)
    p_val_raw = np.asarray(p_val_raw, dtype=float)

    if method == "none":
        return RawProbCalibrator(method = "none", fitted=None)
    if method == "isotonic":
        model = IsotonicRegression(out_of_bounds="clip")
        model.fit(p_val_raw, y_val)
    else:
        model = LogisticRegression(max_iter=1000, solver="lbfgs")
        model.fit(p_val_raw.reshape(-1, 1), y_val)

    return RawProbCalibrator(method, model)


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


def add_ad_columns(test_df: pd.DataFrame, train_df: pd.DataFrame, bins: list[float], fp_radius=2, fp_n_bits=2048):
    fp_cfg = FingerprintConfig(radius=fp_radius, n_bits=fp_n_bits)

    train_mols = [Chem.MolFromSmiles(s) for s in train_df["smiles"].astype(str)]
    test_mols = [Chem.MolFromSmiles(s) for s in test_df["smiles"].astype(str)]

    train_fps = [mol_to_ecfp_bits(m, fp_cfg) for m in train_mols if m is not None]
    test_fps = [mol_to_ecfp_bits(m, fp_cfg) if m is not None else None for m in test_mols]

    max_sims = []
    sim_bins = []

    for fp in test_fps:
        if fp is None or len(train_fps) == 0:
            sim = np.nan
        else:
            sim = float(max(bulk_max_tanimoto([fp], train_fps)))
        max_sims.append(sim)
        sim_bins.append(_bin_similarity(sim, bins))

    out = test_df.copy()
    out["max_sim_to_train"] = max_sims
    out["sim_bin"] = sim_bins
    return out


def summarize_ad_bins(df_pred: pd.DataFrame, threshold: float) -> pd.DataFrame:
    rows = []
    for sim_bin, g in df_pred.groupby("sim_bin", dropna=False):
        y_true = g["y"].astype(int).to_numpy()
        p = g["p_cal"].astype(float).to_numpy()
        m = compute_metrics(y_true, p, threshold)
        rows.append(
            {
                "sim_bin": sim_bin,
                "n": int(len(g)),
                **m,
            }
        )
    return pd.DataFrame(rows)


def postprocess_stage2_run(
    run_dir: Path,
    split_type: str,
    seed: int,
    calibration_method: str,
    threshold_metric: str = "youden",
    ad_bins: list[float] | None = None,
    fp_radius: int = 2,
    fp_n_bits: int = 2048,
    bootstrap_B: int = 2000,
    reliability_bins: int = 10,
):
    if ad_bins is None:
        ad_bins = [0.3, 0.5, 0.7]

    full_input_path = run_dir / "chemprop_input_full.csv"
    pred_path = run_dir / "predictions" / "preds.csv"

    full_df = pd.read_csv(full_input_path)
    pred_df = pd.read_csv(pred_path)

    assert len(full_df) == len(pred_df), "Row mismatch between input and predictions"
    if "smiles" in pred_df.columns:
        assert (full_df["smiles"].astype(str).values == pred_df["smiles"].astype(str).values).all(), \
            "SMILES row order mismatch"

    # exact from sample preds.csv . prediction column is y
    full_df = full_df.copy()
    full_df["p_raw"] = pred_df["y"].astype(float).values

    train_df = full_df[full_df["split"] == "train"].copy()
    val_df = full_df[full_df["split"] == "val"].copy()
    test_df = full_df[full_df["split"] == "test"].copy()

    y_val = val_df["y"].astype(int).to_numpy()
    p_val_raw = val_df["p_raw"].astype(float).to_numpy()

    calibrator = fit_calibrator(y_val=y_val, p_val_raw=p_val_raw, method=calibration_method)

    val_df["p_cal"] = calibrator.predict(val_df["p_raw"].to_numpy())
    threshold = select_threshold(
        y_true=val_df["y"].astype(int).to_numpy(),
        p=val_df["p_cal"].astype(float).to_numpy(),
        metric=threshold_metric,
    )

    test_df["p_cal"] = calibrator.predict(test_df["p_raw"].to_numpy())
    test_df["y_pred"] = (test_df["p_cal"] >= threshold).astype(int)

    metrics = compute_metrics(
        y_true=test_df["y"].astype(int).to_numpy(),
        p=test_df["p_cal"].astype(float).to_numpy(),
        threshold=threshold,
    )
    ci = bootstrap_ci(
        y_true=test_df["y"].astype(int).to_numpy(),
        p=test_df["p_cal"].astype(float).to_numpy(),
        threshold=threshold,
        B=bootstrap_B,
        seed=seed,
    )

    benchmark_row = {
        "model": "chemprop_dmnn",
        "split_type": split_type,
        "seed": int(seed),
        "threshold": float(threshold),
        **metrics,
        "auroc_ci_lo": ci["auroc"][1],
        "auroc_ci_hi": ci["auroc"][2],
        "auprc_ci_lo": ci["auprc"][1],
        "auprc_ci_hi": ci["auprc"][2],
        "f1_ci_lo": ci["f1"][1],
        "f1_ci_hi": ci["f1"][2],
        "balanced_acc_ci_lo": ci["balanced_acc"][1],
        "balanced_acc_ci_hi": ci["balanced_acc"][2],
        "brier_ci_lo": ci["brier"][1],
        "brier_ci_hi": ci["brier"][2],
    }
    benchmark_df = pd.DataFrame([benchmark_row])

    test_with_sim = add_ad_columns(
        test_df=test_df,
        train_df=train_df,
        bins=ad_bins,
        fp_radius=fp_radius,
        fp_n_bits=fp_n_bits,
    )
    ad_df = summarize_ad_bins(test_with_sim, threshold=threshold)

    tables_dir = run_dir / "tables"
    preds_dir = run_dir / "predictions"
    figs_dir = run_dir / "figures"
    models_dir = run_dir / "models"
    for d in [tables_dir, preds_dir, figs_dir, models_dir]:
        d.mkdir(parents=True, exist_ok=True)

    benchmark_df.to_csv(tables_dir / "benchmark_results.csv", index=False)
    ad_df.to_csv(tables_dir / "applicability_domain_bins.csv", index=False)

    test_df[["mol_id", "smiles", "y", "p_cal", "y_pred"]].to_csv(
        preds_dir / f"test_preds_{split_type}_seed{seed}.csv",
        index=False,
    )
    test_with_sim[["mol_id", "smiles", "y", "p_cal", "y_pred", "max_sim_to_train", "sim_bin"]].to_csv(
        preds_dir / f"test_preds_{split_type}_seed{seed}_with_sim.csv",
        index=False,
    )

    plot_reliability(
        y_true=test_df["y"].astype(int).to_numpy(),
        p=test_df["p_cal"].astype(float).to_numpy(),
        n_bins=reliability_bins,
        out_path=figs_dir / f"reliability_{split_type}.png",
        title=f"Reliability — {split_type}",
    )

    joblib.dump(calibrator, models_dir / f"calibrator_{split_type}_seed{seed}.joblib")
    (models_dir / f"threshold_{split_type}_seed{seed}.json").write_text(
        json.dumps(
            {
                "threshold": float(threshold),
                "calibration_method": _normalize_calibration_method(calibration_method),
                "threshold_metric": threshold_metric,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return benchmark_df, ad_df