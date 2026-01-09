import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


class DummyCalModel:
    """
    Picklable, deterministic. Produces probabilities from X density.
    """
    def predict_proba(self, X):
        X = np.asarray(X)
        p = np.clip((X.mean(axis=1) * 2.0), 0.0, 1.0)  # scale to get some >0.5
        return np.vstack([1.0 - p, p]).T


@pytest.fixture
def logger():
    log = logging.getLogger("stage1_smoke")
    if not log.handlers:
        log.addHandler(logging.NullHandler())
    return log


def test_stage1_signoff_smoke(tmp_path: Path, monkeypatch, logger):
    # Import here so monkeypatch targets module attributes correctly
    import hergbench.stage1_pipeline as s1

    # --- synthetic dataset (tiny) ---
    df = pd.DataFrame(
        {
            "mol_id": [f"m{i:02d}" for i in range(10)],
            "smiles": [
                "CCN", "CCCCN", "c1ccccc1", "CC(=O)N", "CCOC", "CCCl", "CCBr", "CCN(CC)CC", "O=C=O", "CC(C)N"
            ],
            "y": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        }
    )

    # Split: 6 train, 2 val, 2 test
    splits_dir = tmp_path / "splits"
    splits_dir.mkdir(parents=True, exist_ok=True)
    split_csv = splits_dir / "cluster_seed11.csv"
    split_df = pd.DataFrame(
        {
            "mol_id": df["mol_id"].tolist(),
            "split": ["train"] * 6 + ["val"] * 2 + ["test"] * 2,
        }
    )
    split_df.to_csv(split_csv, index=False)

    # Panel uses ONLY test smiles so selection=panel_csv generates reports for all panel rows.
    panel_dir = tmp_path / "panel"
    panel_dir.mkdir(parents=True, exist_ok=True)
    panel_csv = panel_dir / "panel.csv"
    panel = df.iloc[-2:][["smiles"]].copy()
    panel.to_csv(panel_csv, index=False)

    # --- monkeypatch expensive / external parts ---
    def fake_load_or_prepare_dataset(cfg, logger=None):
        return df.copy(), {"processed_csv": "dummy"}

    monkeypatch.setattr(s1, "load_or_prepare_dataset", fake_load_or_prepare_dataset)
    monkeypatch.setattr(s1, "get_or_create_split", lambda **kwargs: split_csv)

    monkeypatch.setattr(s1, "tune_xgb", lambda *a, **k: ({}, 0.5))
    monkeypatch.setattr(s1, "fit_xgb", lambda *a, **k: object())
    monkeypatch.setattr(s1, "calibrate_prefit", lambda *a, **k: DummyCalModel())
    monkeypatch.setattr(s1, "select_threshold", lambda *a, **k: 0.5)

    # metrics / bootstrap / plots should not dominate smoke test
    monkeypatch.setattr(
        s1,
        "compute_metrics",
        lambda y, p, thr: {
            "auroc": 0.5,
            "auprc": 0.5,
            "f1": 0.0,
            "balanced_acc": 0.5,
            "brier": float(np.mean((np.asarray(p) - np.asarray(y)) ** 2)),
        },
    )
    monkeypatch.setattr(
        s1,
        "bootstrap_ci",
        lambda y, p, thr, B, seed: {
            "auroc": (0.5, 0.4, 0.6),
            "auprc": (0.5, 0.4, 0.6),
            "f1": (0.0, 0.0, 0.1),
            "balanced_acc": (0.5, 0.4, 0.6),
            "brier": (0.2, 0.1, 0.3),
        },
    )
    monkeypatch.setattr(s1, "plot_generalization_gap", lambda *a, **k: None)
    monkeypatch.setattr(s1, "plot_reliability", lambda *a, **k: None)

    # CF generation stub: cheap list + diagnostic
    def fake_generate_counterfactuals_exmol(**kwargs):
        base = kwargs["base_smiles"]
        cfs = [
            {"smiles": base, "tier": "flip", "p": 0.1, "delta_p": 0.1},   # should be dropped as identical
            {"smiles": "CCN", "tier": "flip", "p": 0.2, "delta_p": 0.2},
            {"smiles": "CCCCN", "tier": "flip", "p": 0.2, "delta_p": 0.2},
        ]
        diag = {"sampled": 3, "final_tier": "flip", "final_count": 2, "final_relaxation": "none", "scarcity": False}
        return cfs, diag

    monkeypatch.setattr(s1, "generate_counterfactuals_exmol", fake_generate_counterfactuals_exmol)
    monkeypatch.setattr(s1, "dataset_analogues", lambda **kwargs: [])
    monkeypatch.setattr(s1, "mol_props", lambda mol: {"logp": 1.0, "qed": 0.5, "sascore": 2.0})
    monkeypatch.setattr(s1, "has_structural_alerts", lambda mol: False)

    # --- minimal config: cluster only, seed 11, selection=panel_csv ---
    run_dir = tmp_path / "run"
    cfg = {
        "repro": {"seed": 42},
        "paths": {"data_splits": str(splits_dir)},
        "stage1": {
            "splits": {
                "frac_train": 0.6,
                "frac_val": 0.2,
                "frac_test": 0.2,
                "force_resplit": False,
                "butina_cutoff": 0.6,
                "types": ["cluster"],
                "seeds": [11],
            },
            "features": {"radius": 2, "n_bits": 64},
            "model": {"objective": "aucpr", "optuna_trials": 1, "max_estimators": 10, "early_stopping_rounds": 5},
            "calibration": {"method": "sigmoid", "threshold_metric": "youden", "n_bins": 5},
            "eval": {"bins": [0.3, 0.5, 0.7], "bootstrap_B": 10},
            "counterfactuals": {
                "enable": True,
                "selection": "panel_csv",
                "panel_csv": str(panel_csv),
                "nmols": 2,
                "max_targets": 10,
                "high_risk_p": 0.7,
                "safe_p": 0.3,
                "exmol_preset": "tiny",
                "exmol_n_samples": 10,
                "delta_min": 0.10,
                "delta_min_tier3": 0.05,
                "constraints": {"min_tanimoto": 0.0, "sa_max": 4.5, "logp_delta_max": 1.5, "qed_min": 0.0, "pains": True},
                "relaxations": [],
            },
        },
    }

    # Run
    s1.run_stage1(cfg=cfg, run_dir=run_dir, logger=logger)

    # Assert key outputs exist
    assert (run_dir / "tables" / "benchmark_results.csv").exists()
    assert (run_dir / "predictions" / "test_preds_cluster_seed11.csv").exists()
    assert (run_dir / "models" / "model_cluster_seed11.joblib").exists()

    # Reports generated for all panel molecules (panel rows correspond to test split)
    preds = pd.read_csv(run_dir / "predictions" / "test_preds_cluster_seed11.csv")
    panel_smiles = set(pd.read_csv(panel_csv)["smiles"].astype(str))
    panel_rows = preds[preds["smiles"].astype(str).isin(panel_smiles)]
    assert len(panel_rows) == len(panel_smiles)

    for mol_id in panel_rows["mol_id"].astype(str).tolist():
        rep_dir = run_dir / "lead_reports" / mol_id
        assert (rep_dir / "report.md").exists()
        assert (rep_dir / "report.json").exists()

        rep = json.loads((rep_dir / "report.json").read_text(encoding="utf-8"))
        thr = float(rep["threshold"])
        for cf in rep.get("counterfactuals", []):
            tier = cf.get("tier_label_std")
            p = float(cf.get("p_std"))
            dp = float(cf.get("delta_p_std"))
            if tier == "flip":
                assert p < thr
            if tier in ("risk_reduction", "weak_improvement"):
                assert dp > 0.0
