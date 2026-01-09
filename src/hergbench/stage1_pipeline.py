
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import joblib
from rdkit import DataStructs
from sklearn.metrics import average_precision_score

from hergbench.data.herg_dataset import load_or_prepare_dataset
from hergbench.data.standardize import StandardizeConfig, canonical_smiles, smiles_to_mol, standardize_mol
from hergbench.data.splits import SplitConfig, get_or_create_split, split_df
from hergbench.evaluation.eval import (
    CalibrationConfig,
    bootstrap_ci,
    calibrate_prefit,
    compute_metrics,
    plot_generalization_gap,
    plot_reliability,
    select_threshold,
)
from hergbench.features.fingerprints import FingerprintConfig, bulk_max_tanimoto, fps_to_numpy, mol_to_ecfp_bits
from hergbench.models.xgb_optuna import XGBConfig, fit_xgb, tune_xgb
from hergbench.reporting.lead_opt import (
    CFConstraints,
    dataset_analogues,
    generate_counterfactuals_exmol,
    has_structural_alerts,
    mol_props,
    write_lead_report,
)


@dataclass(frozen=True)
class Stage1Config:
    split_types: List[str]
    seeds: List[int]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _bin_similarity(max_sim: float, bins: List[float]) -> str:
    # bins like [0.3,0.5,0.7]
    if max_sim < bins[0]:
        return f"<{bins[0]}"
    if max_sim < bins[1]:
        return f"{bins[0]}-{bins[1]}"
    if max_sim < bins[2]:
        return f"{bins[1]}-{bins[2]}"
    return f">{bins[2]}"


def _prepare_fps(df: pd.DataFrame, fp_cfg: FingerprintConfig):
    """Compute RDKit fingerprints + numpy matrix once."""
    from rdkit import Chem

    mols = [Chem.MolFromSmiles(s) for s in df["smiles"].astype(str).tolist()]
    fps = [mol_to_ecfp_bits(m, fp_cfg) for m in mols]  # preprocessing ensures mols are valid
    X = fps_to_numpy(fps)
    return fps, X


def _scale_pos_weight(y: np.ndarray) -> float:
    pos = float((y == 1).sum())
    neg = float((y == 0).sum())
    return (neg / pos) if pos > 0 else 1.0


def reconcile_tier_std(
    p_cf: float,
    base_p: float,
    threshold: float,
    delta_min: float,
    delta_min_tier3: float,
    sim_to_train: float,
    constraints: CFConstraints,
    alert: bool,
    sascore: Optional[float],
    logp_delta: Optional[float] = None,
    qed: Optional[float] = None,
) -> Tuple[int, str]:
    """
    Recompute tier using standardized scoring + constraints.
    Tier 1: p_std < threshold AND sim >= min_tanimoto_flip (or min_tanimoto)
    Tier 2: Δp >= delta_min AND sim >= min_tanimoto_improve (or min_tanimoto)
    Tier 3: Δp >= delta_min_tier3 AND sim >= min_tanimoto_improve (or min_tanimoto)
    Tier 4: otherwise, or if hard constraints fail (similarity/PAINS/SA/logP/QED)
    """

    def _min_sim_required_for_tier(tier_num: int, cons: CFConstraints) -> float:
        base = float(cons.min_tanimoto) if cons.min_tanimoto is not None else 0.0
        if tier_num == 1:
            return float(cons.min_tanimoto_flip) if cons.min_tanimoto_flip is not None else base
        if tier_num in (2, 3):
            return float(cons.min_tanimoto_improve) if cons.min_tanimoto_improve is not None else base
        return base

    # Score-based proposal
    if p_cf < (threshold - 1e-6):
        tier = 1
    elif (base_p - p_cf) >= delta_min:
        tier = 2
    elif (base_p - p_cf) >= delta_min_tier3:
        tier = 3
    else:
        tier = 4

    # Medicinal constraints / similarity floors
    min_sim_req = _min_sim_required_for_tier(tier, constraints)
    if sim_to_train < min_sim_req:
        return 4, "diagnostic_close_edits"
    if constraints.pains and alert:
        return 4, "diagnostic_close_edits"
    if sascore is not None and float(sascore) > float(constraints.sa_max):
        return 4, "diagnostic_close_edits"
    if logp_delta is not None and float(logp_delta) > float(constraints.logp_delta_max):
        return 4, "diagnostic_close_edits"
    if qed is not None and float(qed) < float(constraints.qed_min):
        return 4, "diagnostic_close_edits"

    label = {1: "flip", 2: "risk_reduction", 3: "weak_improvement", 4: "diagnostic_close_edits"}[tier]
    return tier, label


def _apply_split(
    df: pd.DataFrame,
    idx_map: Dict[str, int],
    X_all: np.ndarray,
    split_csv: Path,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    train_df, val_df, test_df = split_df(df, split_csv)
    tr_idx = np.array([idx_map[i] for i in train_df["mol_id"].astype(str).tolist()], dtype=int)
    va_idx = np.array([idx_map[i] for i in val_df["mol_id"].astype(str).tolist()], dtype=int)
    te_idx = np.array([idx_map[i] for i in test_df["mol_id"].astype(str).tolist()], dtype=int)
    return train_df, val_df, test_df, X_all[tr_idx], X_all[va_idx], X_all[te_idx]


def _applicability_bins(
    test_df: pd.DataFrame,
    test_fps,
    train_fps,
    bins: List[float],
    y_true: np.ndarray,
    p: np.ndarray,
    threshold: float,
) -> pd.DataFrame:
    max_sims = bulk_max_tanimoto(test_fps, train_fps)
    sim_bins = [_bin_similarity(s, bins) for s in max_sims]

    out_rows = []
    for b in sorted(set(sim_bins), key=lambda x: ("<" not in x, x)):
        mask = np.array([sb == b for sb in sim_bins], dtype=bool)
        if mask.sum() == 0:
            continue
        m = compute_metrics(y_true[mask], p[mask], threshold)
        out_rows.append({"sim_bin": b, "n": int(mask.sum()), **m})

    dfb = pd.DataFrame(out_rows)
    dfb["max_sim"] = max_sims
    dfb["mol_id"] = test_df["mol_id"].astype(str).tolist()
    dfb["sim_bin_per_mol"] = sim_bins
    return dfb


def run_stage1(cfg: Dict[str, Any], run_dir: Path, logger) -> None:
    """Stage 1: baseline-only benchmarking + lead optimization module."""
    s1 = cfg.get("stage1", {})
    split_cfg = SplitConfig(
        frac_train=float(s1["splits"]["frac_train"]),
        frac_val=float(s1["splits"]["frac_val"]),
        frac_test=float(s1["splits"]["frac_test"]),
        force_resplit=bool(s1["splits"].get("force_resplit", False)),
        butina_cutoff=float(s1["splits"].get("butina_cutoff", 0.6)),
    )
    split_types = s1["splits"].get("types", ["random", "scaffold", "cluster"])
    seeds = s1["splits"].get("seeds", [11, 22, 33, 44, 55])

    fp_cfg = FingerprintConfig(
        radius=int(s1["features"]["radius"]),
        n_bits=int(s1["features"]["n_bits"]),
    )

    xgb_cfg = XGBConfig(
        objective=str(s1["model"].get("objective", "aucpr")),
        optuna_trials=int(s1["model"].get("optuna_trials", 75)),
        max_estimators=int(s1["model"].get("max_estimators", 4000)),
        early_stopping_rounds=int(s1["model"].get("early_stopping_rounds", 50)),
        random_state=int(cfg["repro"].get("seed", 42)),
    )

    cal_cfg = CalibrationConfig(
        method=str(s1["calibration"].get("method", "isotonic")),
        threshold_metric=str(s1["calibration"].get("threshold_metric", "youden")),
        n_bins=int(s1["calibration"].get("n_bins", 10)),
    )

    eval_bins = [float(x) for x in s1["eval"].get("bins", [0.3, 0.5, 0.7])]
    B = int(s1["eval"].get("bootstrap_B", 2000))

    cf_cfg_raw = s1.get("counterfactuals", {})
    cf_enable = bool(cf_cfg_raw.get("enable", True))
    cf_nmols = int(cf_cfg_raw.get("nmols", 5))
    cf_max_targets = int(cf_cfg_raw.get("max_targets", 20))
    cf_selection = str(cf_cfg_raw.get("selection", "high_risk"))
    cf_panel_csv = cf_cfg_raw.get("panel_csv", None)
    cf_panel_csv = Path(cf_panel_csv) if cf_panel_csv else None
    high_risk_p = float(cf_cfg_raw.get("high_risk_p", 0.7))
    safe_p = float(cf_cfg_raw.get("safe_p", 0.3))
    exmol_preset = str(cf_cfg_raw.get("exmol_preset", "medium"))
    # Keep pipeline config simple; budget guardrails live inside generate_counterfactuals_exmol now.
    cf_exmol_n_samples = int(cf_cfg_raw.get("exmol_n_samples", 1800))
    cf_search_nmols = cf_cfg_raw.get("search_nmols", None)
    cf_search_nmols = int(cf_search_nmols) if cf_search_nmols is not None else None
    cf_delta_min = float(cf_cfg_raw.get("delta_min", 0.10))
    cf_delta_min_tier3 = float(cf_cfg_raw.get("delta_min_tier3", 0.05))
    cf_relax_plan = cf_cfg_raw.get("relaxations", [])

    constraints = CFConstraints(
        min_tanimoto=float(cf_cfg_raw.get("constraints", {}).get("min_tanimoto", 0.7)),
        min_tanimoto_flip=cf_cfg_raw.get("constraints", {}).get("min_tanimoto_flip"),
        min_tanimoto_improve=cf_cfg_raw.get("constraints", {}).get("min_tanimoto_improve"),
        sa_max=float(cf_cfg_raw.get("constraints", {}).get("sa_max", 4.5)),
        logp_delta_max=float(cf_cfg_raw.get("constraints", {}).get("logp_delta_max", 1.5)),
        qed_min=float(cf_cfg_raw.get("constraints", {}).get("qed_min", 0.0)),
        pains=bool(cf_cfg_raw.get("constraints", {}).get("pains", True)),
    )

    # Load dataset
    df, _paths = load_or_prepare_dataset(cfg, logger=logger)
    df = df.sort_values("mol_id").reset_index(drop=True)

    # Fingerprints once
    fps_all, X_all = _prepare_fps(df, fp_cfg)
    idx_map = {mol_id: i for i, mol_id in enumerate(df["mol_id"].astype(str).tolist())}

    # Output dirs
    tables_dir = run_dir / "tables"
    figs_dir = run_dir / "figures"
    preds_dir = run_dir / "predictions"
    lead_dir = run_dir / "lead_reports"
    models_dir = run_dir / "models"
    for p in [tables_dir, figs_dir, preds_dir, lead_dir, models_dir]:
        _ensure_dir(p)

    all_rows: List[Dict[str, Any]] = []
    pooled_reliability = {}  # split_type -> (y, p)

    for split_type in split_types:
        for seed in seeds:
            logger.info("Stage1: split=%s seed=%d", split_type, seed)
            cal_method = "sigmoid" if split_type == "cluster" else cal_cfg.method
            if split_type == "cluster" and cal_cfg.method != "sigmoid":
                logger.info("Using sigmoid calibration for cluster split to reduce overfitting risk.")

            split_csv = get_or_create_split(
                df=df,
                out_dir=Path(cfg["paths"]["data_splits"]),
                split_type=split_type,
                seed=int(seed),
                cfg=split_cfg,
                fp_radius=fp_cfg.radius,
                fp_bits=fp_cfg.n_bits,
            )

            train_df, val_df, test_df, X_tr, X_va, X_te = _apply_split(df, idx_map, X_all, split_csv)

            y_tr = train_df["y"].astype(int).values
            y_va = val_df["y"].astype(int).values
            y_te = test_df["y"].astype(int).values

            spw = _scale_pos_weight(y_tr)
            logger.info("scale_pos_weight=%.3f (train pos=%d neg=%d)", spw, int((y_tr==1).sum()), int((y_tr==0).sum()))

            # Optuna tuning
            best_params, best_val = tune_xgb(X_tr, y_tr, X_va, y_va, cfg=xgb_cfg, scale_pos_weight=spw)
            logger.info("Best val %s=%.4f with params=%s", xgb_cfg.objective, best_val, best_params)

            model = fit_xgb(X_tr, y_tr, X_va, y_va, params=best_params, cfg=xgb_cfg, scale_pos_weight=spw)

            # Calibrate + threshold on validation
            cal_model = calibrate_prefit(model, X_va, y_va, method=cal_method)
            p_va = cal_model.predict_proba(X_va)[:, 1]
            threshold = select_threshold(y_va, p_va, metric=cal_cfg.threshold_metric)

            # Test predictions
            p_te = cal_model.predict_proba(X_te)[:, 1]

            # Persist fitted artifacts (makes lead reports exactly reproducible)
            joblib.dump(
                {
                    "cal_model": cal_model,
                    "threshold": float(threshold),
                    "fp_cfg": {"radius": fp_cfg.radius, "n_bits": fp_cfg.n_bits},
                },
                models_dir / f"model_{split_type}_seed{seed}.joblib",
            )

            m = compute_metrics(y_te, p_te, threshold)
            ci = bootstrap_ci(y_te, p_te, threshold, B=B, seed=int(seed))

            row = {
                "model": "xgboost_ecfp",
                "split_type": split_type,
                "seed": int(seed),
                "threshold": float(threshold),
                **m,
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
            all_rows.append(row)

            # Save test predictions
            df_pred = test_df[["mol_id", "smiles", "y"]].copy()
            df_pred["p_cal"] = p_te
            df_pred["y_pred"] = (p_te >= threshold).astype(int)
            out_pred = preds_dir / f"test_preds_{split_type}_seed{seed}.csv"
            df_pred.to_csv(out_pred, index=False)

            # Pool for reliability plots per split_type
            pooled = pooled_reliability.setdefault(split_type, {"y": [], "p": []})
            pooled["y"].extend(y_te.tolist())
            pooled["p"].extend(p_te.tolist())

            # Persist model params for audit
            model_meta = {
                "split_type": split_type,
                "seed": int(seed),
                "best_val_score": float(best_val),
                "best_params": best_params,
                "scale_pos_weight": float(spw),
                "calibration": {
                    "method": cal_method,
                    "threshold_metric": cal_cfg.threshold_metric,
                    "threshold": float(threshold),
                },
            }
            (models_dir / f"model_meta_{split_type}_seed{seed}.json").write_text(json.dumps(model_meta, indent=2), encoding="utf-8")

    df_results = pd.DataFrame(all_rows)
    out_results = tables_dir / "benchmark_results.csv"
    df_results.to_csv(out_results, index=False)
    logger.info("Wrote %s", out_results)

    # Generalization plot (AUPRC as primary)
    plot_generalization_gap(
        df_results=df_results,
        metric="auprc",
        out_path=figs_dir / "generalization_gap_auprc.png",
        title="Generalization gap across splits (AUPRC)",
        split_order=["random", "scaffold", "cluster"],
    )

    # Reliability plots per split_type (pooled)
    for split_type, v in pooled_reliability.items():
        y = np.array(v["y"], dtype=int)
        p = np.array(v["p"], dtype=float)
        plot_reliability(y, p, n_bins=cal_cfg.n_bins, out_path=figs_dir / f"reliability_{split_type}.png", title=f"Reliability — {split_type}")

    # Applicability domain analysis for the cluster split (pooled across seeds, using per-file train set is complex).
    # MVP implementation: compute max similarity to *full* training pool for each seed independently and save per-seed.
    app_rows = []
    for split_type in split_types:
        for seed in seeds:
            split_csv = Path(cfg["paths"]["data_splits"]) / f"{split_type}_seed{seed}.csv"
            if not split_csv.exists():
                continue
            train_df, _, test_df = split_df(df, split_csv)
            # prepare fps subsets
            tr_idx = [idx_map[i] for i in train_df["mol_id"].astype(str).tolist()]
            te_idx = [idx_map[i] for i in test_df["mol_id"].astype(str).tolist()]
            train_fps = [fps_all[i] for i in tr_idx]
            test_fps = [fps_all[i] for i in te_idx]

            pred_path = preds_dir / f"test_preds_{split_type}_seed{seed}.csv"
            if not pred_path.exists():
                continue
            df_pred = pd.read_csv(pred_path)
            y_te = df_pred["y"].astype(int).values
            p_te = df_pred["p_cal"].astype(float).values
            # threshold used in that run:
            thr = float(df_results[(df_results["split_type"] == split_type) & (df_results["seed"] == int(seed))]["threshold"].iloc[0])

            max_sims = bulk_max_tanimoto(test_fps, train_fps)
            sim_bins = [_bin_similarity(s, eval_bins) for s in max_sims]
            df_pred["max_sim_to_train"] = max_sims
            df_pred["sim_bin"] = sim_bins

            # metrics by bin
            for b in sorted(set(sim_bins), key=lambda x: x):
                mask = df_pred["sim_bin"].values == b
                if mask.sum() == 0:
                    continue
                m = compute_metrics(y_te[mask], p_te[mask], thr)
                app_rows.append(
                    {"split_type": split_type, "seed": int(seed), "sim_bin": b, "n": int(mask.sum()), **m}
                )

            # save per-seed test preds with similarity
            df_pred.to_csv(preds_dir / f"test_preds_{split_type}_seed{seed}_with_sim.csv", index=False)

    df_app = pd.DataFrame(app_rows)
    out_app = tables_dir / "applicability_domain_bins.csv"
    df_app.to_csv(out_app, index=False)
    logger.info("Wrote %s", out_app)

    # Lead reports (cluster; consistent seed/model)
    if cf_enable:
        seed0 = int(seeds[0])

        pred_path0 = preds_dir / f"test_preds_cluster_seed{seed0}.csv"
        split_csv0 = Path(cfg["paths"]["data_splits"]) / f"cluster_seed{seed0}.csv"
        model_path0 = models_dir / f"model_cluster_seed{seed0}.joblib"

        if pred_path0.exists() and split_csv0.exists() and model_path0.exists():
            df_pred0 = pd.read_csv(pred_path0)

            # Optional panel-driven selection: only generate reports for molecules listed in panel.csv
            if cf_selection == "panel_csv":
                if cf_panel_csv is None or (not cf_panel_csv.exists()):
                    raise FileNotFoundError(f"counterfactuals.panel_csv not found: {cf_panel_csv}")

                panel_df = pd.read_csv(cf_panel_csv)
                if "smiles" not in panel_df.columns:
                    raise ValueError("panel_csv must include a 'smiles' column")

                panel_smiles = set(panel_df["smiles"].astype(str).tolist())
                before = len(df_pred0)
                df_pred0 = df_pred0[df_pred0["smiles"].astype(str).isin(panel_smiles)].copy()
                logger.info("Panel-driven CF selection: %d -> %d candidates from %s", before, len(df_pred0), str(cf_panel_csv))


            # Load calibrated model bundle
            bundle = joblib.load(model_path0)
            cal_model = bundle["cal_model"]
            threshold = float(bundle["threshold"])

            # Train fingerprints for similarity warnings (from the same split)
            train_df0, _, _ = split_df(df, split_csv0)
            tr_idx0 = [idx_map[i] for i in train_df0["mol_id"].astype(str).tolist()]
            train_fps0 = [fps_all[i] for i in tr_idx0]

            # Precompute dataset-wide predictions for deterministic analogue fallback.
            dataset_smiles = df["smiles"].astype(str).tolist()
            p_all_cal = cal_model.predict_proba(X_all)[:, 1]

            # Candidate selection
            lead_candidates: List[Dict[str, Any]] = []
            for mol_id, smi, y, p, y_pred in zip(
                df_pred0["mol_id"], df_pred0["smiles"], df_pred0["y"], df_pred0["p_cal"], df_pred0["y_pred"]
            ):
                y = int(y)
                p = float(p)
                y_pred = int(y_pred)

                if cf_selection == "high_risk" and p >= high_risk_p:
                    lead_candidates.append({"mol_id": str(mol_id), "smiles": str(smi), "y": y, "p": p})
                elif cf_selection == "false_positives" and (y == 0) and (y_pred == 1):
                    lead_candidates.append({"mol_id": str(mol_id), "smiles": str(smi), "y": y, "p": p})
                elif cf_selection == "panel_csv":
                    lead_candidates.append({"mol_id": str(mol_id), "smiles": str(smi), "y": y, "p": p})

            if not lead_candidates and cf_selection == "high_risk":
                # Fallback: take top cf_max_targets by predicted risk for lead optimization
                df_sorted = df_pred0.sort_values("p_cal", ascending=False).head(cf_max_targets)
                lead_candidates = [
                    {"mol_id": str(r["mol_id"]), "smiles": str(r["smiles"]), "y": int(r["y"]), "p": float(r["p_cal"])}
                    for _, r in df_sorted.iterrows()
                ]
                logger.info(
                    "No cluster candidates met high_risk_p=%.2f; falling back to top %d by p_cal (max=%.3f).",
                    high_risk_p,
                    cf_max_targets,
                    float(df_sorted["p_cal"].max()) if not df_sorted.empty else 0.0,
                )

            lead_candidates = lead_candidates[:cf_max_targets]

            def prob_fn(smiles: str) -> float:
                from rdkit import Chem
                m = Chem.MolFromSmiles(smiles)
                if m is None:
                    return 0.0
                fp = mol_to_ecfp_bits(m, fp_cfg)
                X = fps_to_numpy([fp])
                return float(cal_model.predict_proba(X)[:, 1][0])

            def class_fn(smiles: str) -> int:
                return int(prob_fn(smiles) >= threshold)

            for i, cand in enumerate(lead_candidates, start=1):
                mol_id = cand["mol_id"]
                smi = cand["smiles"]
                y = int(cand["y"])
                p_cal = float(prob_fn(smi))

                from rdkit import Chem
                mol = Chem.MolFromSmiles(smi)
                if mol is None:
                    continue
                fp = mol_to_ecfp_bits(mol, fp_cfg)
                max_sim = float(max(DataStructs.BulkTanimotoSimilarity(fp, train_fps0))) if train_fps0 else 0.0
                sim_bin = _bin_similarity(max_sim, eval_bins)

                try:
                    flip_prob_max = max(0.0, threshold - 1e-6)
                    cfs, cf_diag = generate_counterfactuals_exmol(
                        base_smiles=smi,
                        model_class=class_fn,
                        model_prob=prob_fn,
                        fp_cfg=fp_cfg,
                        constraints=constraints,
                        safe_prob_max=flip_prob_max,
                        exmol_preset=exmol_preset,
                        nmols=cf_nmols,
                        exmol_n_samples=cf_exmol_n_samples,
                        search_nmols=cf_search_nmols,
                        delta_min=cf_delta_min,
                        delta_min_tier3=cf_delta_min_tier3,
                        relaxation_plan=cf_relax_plan,
                        logger=logger,
                    )
                except Exception as exc:
                    logger.exception("Counterfactual generation failed for %s", mol_id)
                    cfs = []
                    cf_diag = {"error": str(exc), "sampled": 0, "scarcity": True, "final_tier": "error", "final_count": 0}

                if cf_diag is None:
                    cf_diag = {}

                # Normalize counterfactual identities to the Stage-1 canonical form for scoring/deduplication.
                std_cfg = StandardizeConfig(tautomer_canonicalize=True, strip_salts=True)

                def _std_for_scoring(smiles: str, cfg: StandardizeConfig):
                    mol_sc = smiles_to_mol(smiles)
                    mol_sc = standardize_mol(mol_sc, cfg)
                    if mol_sc is None:
                        return None, None
                    return canonical_smiles(mol_sc), mol_sc

                base_std_smi, base_std_mol = _std_for_scoring(smi, std_cfg)
                if base_std_smi is None:
                    base_std_smi = smi
                base_std_p = float(prob_fn(base_std_smi))
                base_props = mol_props(base_std_mol) if base_std_mol is not None else None

                seen_std = set()
                normalized: List[Dict[str, Any]] = []
                tier_label_map = {1: "flip", 2: "risk_reduction", 3: "weak_improvement", 4: "diagnostic_close_edits"}

                for cf in cfs:
                    raw = cf.get("smiles")
                    std_smi, std_mol = _std_for_scoring(raw, std_cfg)
                    if std_smi is None or std_mol is None:
                        continue
                    if std_smi == base_std_smi:
                        continue
                    if std_smi in seen_std:
                        continue
                    seen_std.add(std_smi)

                    std_fp = mol_to_ecfp_bits(std_mol, fp_cfg)
                    sim_to_train = float(max(DataStructs.BulkTanimotoSimilarity(std_fp, train_fps0))) if train_fps0 else 0.0
                    p_std = float(prob_fn(std_smi))
                    delta_std = base_std_p - p_std
                    props_std = mol_props(std_mol)
                    alert_std = has_structural_alerts(std_mol) if constraints.pains else False
                    logp_delta = None
                    if base_props is not None and "logp" in props_std and "logp" in base_props:
                        logp_delta = abs(float(props_std["logp"]) - float(base_props["logp"]))

                    tier_raw = cf.get("tier")
                    p_raw = cf.get("p")
                    delta_raw = cf.get("delta_p")

                    tier_num, tier_label_std = reconcile_tier_std(
                        p_cf=p_std,
                        base_p=base_std_p,
                        threshold=threshold,
                        delta_min=cf_delta_min,
                        delta_min_tier3=cf_delta_min_tier3,
                        sim_to_train=sim_to_train,
                        constraints=constraints,
                        alert=alert_std,
                        sascore=props_std["sascore"],
                        logp_delta=logp_delta,
                        qed=props_std["qed"],
                    )

                    cf["raw_smiles"] = raw
                    cf["smiles"] = std_smi
                    cf["_std_mol"] = std_mol
                    cf["similarity"] = sim_to_train
                    cf["p"] = p_std
                    cf["delta_p"] = delta_std
                    cf["p_raw"] = p_raw
                    cf["delta_p_raw"] = delta_raw
                    cf["tier_raw"] = tier_raw
                    cf["tier_num_std"] = tier_num
                    cf["tier_label_std"] = tier_label_std
                    # Overwrite canonical tier used downstream to reflect standardized scoring
                    cf["tier"] = tier_label_std
                    cf["logp"] = props_std["logp"]
                    cf["qed"] = props_std["qed"]
                    cf["sascore"] = props_std["sascore"]
                    cf["alert"] = alert_std

                    normalized.append(cf)

                cfs = normalized

                def _is_actionable(cf: Dict[str, Any]) -> bool:
                    return cf.get("tier_num_std", 4) in (1, 2, 3)

                has_actionable = any(_is_actionable(cf) for cf in cfs)

                dataset_fallback: List[Dict[str, Any]] = []
                fallback_used = False

                if (not cfs) or (not has_actionable):
                    dataset_fallback = dataset_analogues(
                        base_smiles=smi,
                        base_fp=fp,
                        base_p=p_cal,
                        dataset_smiles=dataset_smiles,
                        dataset_fps=fps_all,
                        dataset_probs=p_all_cal,
                        fp_cfg=fp_cfg,
                        top_k=cf_nmols,
                        constraints=constraints,              # IMPORTANT: align medicinal policy
                    )
                    fallback_used = True

                cf_diag["dataset_fallback_used"] = fallback_used
                cf_diag["dataset_fallback_count"] = len(dataset_fallback)

                # Only if we truly have *no* generated rows do we re-label the "final tier" as dataset fallback.
                if fallback_used and (not cfs):
                    cf_diag["final_tier"] = "dataset_fallback" if dataset_fallback else cf_diag.get("final_tier", "none")
                    cf_diag["final_tier_label"] = (
                        "Dataset analogue (fallback)" if dataset_fallback else cf_diag.get("final_tier_label", cf_diag.get("final_tier", "none"))
                    )
                    cf_diag["final_relaxation"] = "none"
                    cf_diag["final_relaxation_desc"] = "dataset fallback"
                    cf_diag["final_count"] = len(dataset_fallback)
                    cf_diag["scarcity"] = False if dataset_fallback else True

                # Reconcile final tier/label/count with standardized survivors if any
                final_count_total = len(cfs)
                final_tier123 = [cf for cf in cfs if cf.get("tier_num_std", 4) in (1, 2, 3)]
                final_count_tier123 = len(final_tier123)
                best_tier_num = min([cf.get("tier_num_std", 4) for cf in cfs]) if cfs else 4
                cf_diag["final_count_total"] = final_count_total
                cf_diag["final_count_tier123"] = final_count_tier123
                cf_diag["final_best_tier_num"] = best_tier_num
                cf_diag["final_tier"] = tier_label_map.get(best_tier_num, cf_diag.get("final_tier"))
                cf_diag["final_tier_label"] = tier_label_map.get(best_tier_num, cf_diag.get("final_tier_label"))
                cf_diag["scarcity"] = final_count_total == 0


                if cf_diag:
                    logger.info(
                        "CF outcome %s: sampled=%s final_tier=%s relaxation=%s kept=%s scarcity=%s fallback_used=%s",
                        mol_id,
                        cf_diag.get("sampled"),
                        cf_diag.get("final_tier"),
                        cf_diag.get("final_relaxation"),
                        cf_diag.get("final_count"),
                        cf_diag.get("scarcity"),
                        cf_diag.get("dataset_fallback_used"),
                    )
                    fallback_used = bool(cf_diag.get("dataset_fallback_used", False))
                    relaxation_used = cf_diag.get("final_relaxation") not in ("none", None, "")
                    logger.info(
                        "CF audit flags %s: fallback_tier=%s relaxation_used=%s scarcity=%s",
                        mol_id,
                        fallback_used,
                        relaxation_used,
                        bool(cf_diag.get("scarcity")),
                    )
                    if cf_diag.get("scarcity"):
                        logger.info(
                            "Counterfactual scarcity recorded for %s: sampled=%s, no survivors under medicinal constraints.",
                            mol_id,
                            cf_diag.get("sampled"),
                        )

                report_dir = lead_dir / mol_id
                write_lead_report(
                    out_dir=report_dir,
                    mol_id=mol_id,
                    base_smiles=smi,
                    base_smiles_std=base_std_smi,
                    y_true=y,
                    p_cal=p_cal,
                    p_base_std=base_std_p,
                    threshold=threshold,
                    max_sim=max_sim,
                    sim_bin=sim_bin,
                    counterfactuals=cfs,
                    dataset_analogues=dataset_fallback,
                    cf_summary=cf_diag,
                )
                logger.info("Lead report %d/%d written: %s", i, len(lead_candidates), report_dir)

    logger.info("Stage 1 completed.")
