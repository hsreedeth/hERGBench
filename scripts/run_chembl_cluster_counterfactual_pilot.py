#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import yaml
from rdkit import Chem, DataStructs
from rdkit.Chem.Scaffolds import MurckoScaffold


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hergbench.data.splits import split_df
from hergbench.data.standardize import StandardizeConfig, canonical_smiles, smiles_to_mol, standardize_mol
from hergbench.features.fingerprints import FingerprintConfig, fps_to_numpy, mol_to_ecfp_bits
from hergbench.reporting.lead_opt import (
    CFConstraints,
    dataset_analogues,
    generate_counterfactuals_exmol,
    has_structural_alerts,
    mol_props,
    write_lead_report,
)
from hergbench.stage1_pipeline import _bin_similarity, _prepare_fps, reconcile_tier_std


SIM_BIN_ORDER = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
SIM_BIN_CENTER = {"<0.3": 0.15, "0.3-0.5": 0.4, "0.5-0.7": 0.6, ">0.7": 0.85}


@dataclass(frozen=True)
class SourceRun:
    run_dir: Path
    metadata_path: Path
    config_path: Path
    pred_with_sim_path: Path
    pred_path: Path
    split_csv_path: Path
    bundle_path: Path
    model_meta_path: Path
    dataset: str
    split_type: str
    seed: int
    threshold: float


def _default_source_run_candidates() -> List[Path]:
    pattern = REPO_ROOT / "reports"
    return sorted(pattern.rglob("metadata.json"))


def _discover_source_run(seed: int, logger: logging.Logger) -> SourceRun:
    candidates: List[SourceRun] = []
    for meta_path in _default_source_run_candidates():
        run_dir = meta_path.parent
        if "runs" not in run_dir.parts:
            continue
        config_path = run_dir / "config.resolved.yaml"
        pred_with_sim_path = run_dir / "predictions" / f"test_preds_cluster_seed{seed}_with_sim.csv"
        pred_path = run_dir / "predictions" / f"test_preds_cluster_seed{seed}.csv"
        bundle_path = run_dir / "models" / f"model_cluster_seed{seed}.joblib"
        model_meta_path = run_dir / "models" / f"model_meta_cluster_seed{seed}.json"
        if not all(
            path.exists()
            for path in [config_path, pred_with_sim_path, pred_path, bundle_path, model_meta_path]
        ):
            continue
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        cfg = metadata.get("config", {})
        data_processed = str(cfg.get("paths", {}).get("data_processed", ""))
        if "chembl" not in data_processed.lower():
            continue
        split_csv_path = REPO_ROOT / str(cfg.get("paths", {}).get("data_splits", "data/chembl/splits")) / f"cluster_seed{seed}.csv"
        if not split_csv_path.exists():
            continue
        model_meta = json.loads(model_meta_path.read_text(encoding="utf-8"))
        threshold = float(model_meta["calibration"]["threshold"])
        candidates.append(
            SourceRun(
                run_dir=run_dir,
                metadata_path=meta_path,
                config_path=config_path,
                pred_with_sim_path=pred_with_sim_path,
                pred_path=pred_path,
                split_csv_path=split_csv_path,
                bundle_path=bundle_path,
                model_meta_path=model_meta_path,
                dataset="chembl",
                split_type="cluster",
                seed=seed,
                threshold=threshold,
            )
        )

    if not candidates:
        raise FileNotFoundError(
            "No valid ChEMBL Stage 1 Cluster source run was found with predictions, model bundle, and split CSV."
        )

    chosen = sorted(candidates, key=lambda s: s.run_dir.name)[-1]
    logger.info("Selected ChEMBL source run: %s", chosen.run_dir)
    if len(candidates) > 1:
        logger.info(
            "Multiple valid ChEMBL source runs found; selected the most recent run directory by timestamped name."
        )
    return chosen


def _scaffold_smiles(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return ""
    try:
        return MurckoScaffold.MurckoScaffoldSmiles(mol=mol)
    except Exception:
        return ""


def _select_diverse(df_bin: pd.DataFrame, target: int) -> Tuple[List[int], Dict[int, str]]:
    df_sorted = df_bin.sort_values(
        ["margin_above_threshold", "p_cal", "mol_id"], ascending=[True, True, True], kind="mergesort"
    )
    chosen: List[int] = []
    reasons: Dict[int, str] = {}
    seen_scaffolds: set[str] = set()

    for idx, row in df_sorted.iterrows():
        scaffold = str(row.get("scaffold", "")) or "<no_scaffold>"
        if scaffold not in seen_scaffolds:
            chosen.append(idx)
            reasons[idx] = "primary_bin_scaffold_diverse"
            seen_scaffolds.add(scaffold)
        if len(chosen) == target:
            return chosen, reasons

    for idx, _row in df_sorted.iterrows():
        if idx in reasons:
            continue
        chosen.append(idx)
        reasons[idx] = "primary_bin_margin_fill"
        if len(chosen) == target:
            break
    return chosen, reasons


def _backfill_candidates(
    target_bin: str,
    unused: pd.DataFrame,
) -> pd.DataFrame:
    tmp = unused.copy()
    tmp["bin_distance"] = tmp["parent_similarity_bin"].map(
        lambda b: abs(SIM_BIN_CENTER[str(b)] - SIM_BIN_CENTER[target_bin])
    )
    return tmp.sort_values(
        ["bin_distance", "margin_above_threshold", "p_cal", "mol_id"],
        ascending=[True, True, True, True],
        kind="mergesort",
    )


def build_panel(
    source: SourceRun,
    panel_csv: Path,
    panel_summary_md: Path,
    target_total: int,
    per_bin: int,
    logger: logging.Logger,
) -> pd.DataFrame:
    df = pd.read_csv(source.pred_with_sim_path)
    required_cols = {"mol_id", "smiles", "y", "p_cal", "max_sim_to_train", "sim_bin"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Prediction file missing required columns: {sorted(missing)}")

    df["smiles"] = df["smiles"].astype(str)
    df["mol_id"] = df["mol_id"].astype(str)
    df["parent_similarity_bin"] = df["sim_bin"].astype(str)
    df["margin_above_threshold"] = df["p_cal"].astype(float) - float(source.threshold)
    df["valid_parent"] = df["smiles"].map(lambda s: Chem.MolFromSmiles(s) is not None)
    df["scaffold"] = df["smiles"].map(_scaffold_smiles)

    eligible = df[
        (df["y"].astype(int) == 1)
        & (df["p_cal"].astype(float) >= float(source.threshold))
        & (df["valid_parent"])
        & (df["parent_similarity_bin"].isin(SIM_BIN_ORDER))
    ].copy()
    if eligible.empty:
        raise ValueError("No eligible ChEMBL Cluster blocker parents were found for the pilot panel.")

    selected_rows: List[pd.DataFrame] = []
    selected_ids: set[str] = set()
    shortages: Dict[str, int] = {}

    for sim_bin in SIM_BIN_ORDER:
        df_bin = eligible[eligible["parent_similarity_bin"] == sim_bin].copy()
        chosen_idx, reasons = _select_diverse(df_bin, per_bin)
        df_sel = df_bin.loc[chosen_idx].copy()
        df_sel["selection_reason"] = [reasons[idx] for idx in df_sel.index]
        selected_rows.append(df_sel)
        selected_ids.update(df_sel["mol_id"].tolist())
        shortages[sim_bin] = max(0, per_bin - len(df_sel))

    for sim_bin in SIM_BIN_ORDER:
        shortage = shortages[sim_bin]
        if shortage <= 0:
            continue
        unused = eligible[~eligible["mol_id"].isin(selected_ids)].copy()
        ordered = _backfill_candidates(sim_bin, unused)
        take = ordered.head(shortage).copy()
        if len(take) < shortage:
            raise ValueError(
                f"Could not backfill pilot panel for {sim_bin}: requested {shortage}, found {len(take)}"
            )
        take["selection_reason"] = take["parent_similarity_bin"].map(
            lambda donor: f"backfill_from_{donor}_for_{sim_bin}"
        )
        selected_rows.append(take)
        selected_ids.update(take["mol_id"].tolist())

    panel = pd.concat(selected_rows, ignore_index=True)
    panel = panel.sort_values(
        ["parent_similarity_bin", "margin_above_threshold", "p_cal", "mol_id"],
        key=lambda col: col.map({b: i for i, b in enumerate(SIM_BIN_ORDER)}) if col.name == "parent_similarity_bin" else col,
        kind="mergesort",
    ).reset_index(drop=True)
    panel = panel.head(target_total).copy()
    panel["parent_id"] = panel["mol_id"]
    panel["true_label"] = panel["y"].astype(int)
    panel["calibrated_prob"] = panel["p_cal"].astype(float)
    panel["threshold"] = float(source.threshold)
    panel["split_type"] = source.split_type
    panel["seed"] = int(source.seed)
    panel["dataset"] = source.dataset
    panel["selection_rank"] = np.arange(1, len(panel) + 1)
    panel["selection_rank_within_bin"] = (
        panel.groupby("parent_similarity_bin").cumcount() + 1
    )

    out_cols = [
        "parent_id",
        "mol_id",
        "smiles",
        "true_label",
        "calibrated_prob",
        "threshold",
        "margin_above_threshold",
        "max_sim_to_train",
        "parent_similarity_bin",
        "split_type",
        "seed",
        "dataset",
        "scaffold",
        "selection_rank",
        "selection_rank_within_bin",
        "selection_reason",
    ]
    panel[out_cols].to_csv(panel_csv, index=False)

    counts = panel.groupby("parent_similarity_bin").size().reindex(SIM_BIN_ORDER, fill_value=0)
    shortage_lines = []
    for sim_bin in SIM_BIN_ORDER:
        shortage = shortages[sim_bin]
        if shortage > 0:
            shortage_lines.append(f"- `{sim_bin}` short by {shortage}; deterministically backfilled from nearest bins.")
    if not shortage_lines:
        shortage_lines.append("- No novelty-bin shortages; no backfill was needed.")

    lines = [
        "# ChEMBL Cluster Pilot Parent Panel",
        "",
        f"- Source run: `{source.run_dir}`",
        f"- Dataset: `{source.dataset}`",
        f"- Split: `{source.split_type}`",
        f"- Seed: `{source.seed}`",
        f"- Threshold: `{source.threshold:.3f}`",
        f"- Requested panel: `{target_total}` parents total, `{per_bin}` per novelty bin",
        "",
        "## Cohort rules",
        "",
        "- True blockers only (`y == 1`)",
        "- Predicted blocker / above threshold only (`p_cal >= threshold`)",
        "- Cluster split test set only",
        "- Valid parent novelty bin required",
        "- Invalid parent molecules excluded",
        "- Within each bin, selected by smallest positive margin above threshold with Murcko-scaffold diversity preference",
        "",
        "## Final counts by novelty bin",
        "",
    ]
    for sim_bin, count in counts.items():
        lines.append(f"- `{sim_bin}`: {int(count)} parents")
    lines.extend(["", "## Shortages / backfill", ""])
    lines.extend(shortage_lines)
    panel_summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote pilot panel: %s", panel_csv)
    return panel[out_cols].copy()


def _ensure_dirs(root: Path) -> Dict[str, Path]:
    dirs = {
        "root": root,
        "inputs_snapshot": root / "inputs_snapshot",
        "generation": root / "generation",
        "generation_run": root / "generation" / "run",
        "generation_lead_reports": root / "generation" / "run" / "lead_reports",
        "audit": root / "audit",
        "figures": root / "figures",
        "tables": root / "tables",
        "summaries": root / "summaries",
        "logs": root / "logs",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _setup_logger(log_path: Path, verbose: bool) -> logging.Logger:
    logger = logging.getLogger("chembl_cluster_counterfactual_pilot")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    return logger


def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _snapshot_inputs(source: SourceRun, cfg_path: Path, panel_csv: Path, dirs: Dict[str, Path]) -> None:
    files_to_copy = {
        source.metadata_path: dirs["inputs_snapshot"] / "source_metadata.json",
        source.config_path: dirs["inputs_snapshot"] / "source_config.resolved.yaml",
        source.model_meta_path: dirs["inputs_snapshot"] / f"model_meta_{source.split_type}_seed{source.seed}.json",
        cfg_path: dirs["inputs_snapshot"] / "pilot_config.yaml",
        source.pred_with_sim_path: dirs["inputs_snapshot"] / f"source_{source.pred_with_sim_path.name}",
        panel_csv: dirs["inputs_snapshot"] / panel_csv.name,
    }
    for src, dst in files_to_copy.items():
        if src.resolve() == dst.resolve():
            continue
        shutil.copy2(src, dst)

    selection = {
        "source_run": str(source.run_dir.resolve()),
        "metadata_path": str(source.metadata_path.resolve()),
        "config_path": str(source.config_path.resolve()),
        "pred_with_sim_path": str(source.pred_with_sim_path.resolve()),
        "pred_path": str(source.pred_path.resolve()),
        "bundle_path": str(source.bundle_path.resolve()),
        "model_meta_path": str(source.model_meta_path.resolve()),
        "split_csv_path": str(source.split_csv_path.resolve()),
        "dataset": source.dataset,
        "split_type": source.split_type,
        "seed": source.seed,
        "threshold": source.threshold,
    }
    (dirs["inputs_snapshot"] / "source_run_selection.json").write_text(
        json.dumps(selection, indent=2, sort_keys=True), encoding="utf-8"
    )


def _std_for_scoring(smiles: str, cfg: StandardizeConfig) -> Tuple[Optional[str], Optional[Chem.Mol]]:
    mol_sc = smiles_to_mol(smiles)
    mol_sc = standardize_mol(mol_sc, cfg)
    if mol_sc is None:
        return None, None
    return canonical_smiles(mol_sc), mol_sc


def _generation_constraints(cfg: Dict[str, Any]) -> Tuple[CFConstraints, Dict[str, Any]]:
    cf_cfg = cfg["stage1"]["counterfactuals"]
    cons_cfg = cf_cfg.get("constraints", {})
    constraints = CFConstraints(
        min_tanimoto=float(cons_cfg.get("min_tanimoto", 0.7)),
        min_tanimoto_flip=cons_cfg.get("min_tanimoto_flip"),
        min_tanimoto_improve=cons_cfg.get("min_tanimoto_improve"),
        sa_max=float(cons_cfg.get("sa_max", 4.5)),
        logp_delta_max=float(cons_cfg.get("logp_delta_max", 1.5)),
        qed_min=float(cons_cfg.get("qed_min", 0.0)),
        pains=bool(cons_cfg.get("pains", True)),
    )
    return constraints, cf_cfg


def _load_generation_context(source: SourceRun, pilot_cfg: Dict[str, Any], logger: logging.Logger) -> Dict[str, Any]:
    cfg = pilot_cfg.copy()
    processed_dir = REPO_ROOT / str(cfg["paths"]["data_processed"])
    chembl_candidates = [
        processed_dir / "chembl_herg_clean.csv",
        processed_dir / "herg_clean.csv",
    ]
    dataset_path = next((path for path in chembl_candidates if path.exists()), None)
    if dataset_path is None:
        raise FileNotFoundError(
            f"Could not find a processed ChEMBL dataset under {processed_dir}. "
            "Expected chembl_herg_clean.csv or herg_clean.csv."
        )

    df = pd.read_csv(dataset_path)
    required_cols = {"mol_id", "smiles", "y"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(
            f"Processed ChEMBL dataset {dataset_path} is missing required columns: {sorted(missing)}"
        )
    df = df.sort_values("mol_id").reset_index(drop=True)
    logger.info("Loaded processed ChEMBL dataset from %s (%d rows)", dataset_path, len(df))

    fp_cfg = FingerprintConfig(
        radius=int(cfg["stage1"]["features"]["radius"]),
        n_bits=int(cfg["stage1"]["features"]["n_bits"]),
    )
    fps_all, X_all = _prepare_fps(df, fp_cfg)
    idx_map = {mol_id: i for i, mol_id in enumerate(df["mol_id"].astype(str).tolist())}

    bundle = joblib.load(source.bundle_path)
    cal_model = bundle["cal_model"]
    threshold = float(bundle["threshold"])
    if abs(threshold - float(source.threshold)) > 1e-9:
        raise ValueError(
            f"Threshold mismatch between bundle ({threshold}) and model meta ({source.threshold})."
        )

    train_df, _, _ = split_df(df, source.split_csv_path)
    tr_idx = [idx_map[i] for i in train_df["mol_id"].astype(str).tolist()]
    train_fps = [fps_all[i] for i in tr_idx]
    dataset_smiles = df["smiles"].astype(str).tolist()
    p_all_cal = cal_model.predict_proba(X_all)[:, 1]
    return {
        "cfg": cfg,
        "dataset_path": str(dataset_path.resolve()),
        "df": df,
        "fp_cfg": fp_cfg,
        "fps_all": fps_all,
        "X_all": X_all,
        "idx_map": idx_map,
        "cal_model": cal_model,
        "threshold": threshold,
        "train_fps": train_fps,
        "dataset_smiles": dataset_smiles,
        "dataset_probs": p_all_cal,
    }


def _prob_and_class_fns(cal_model, fp_cfg: FingerprintConfig):
    def prob_fn(smiles: str) -> float:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return 0.0
        fp = mol_to_ecfp_bits(mol, fp_cfg)
        X = fps_to_numpy([fp])
        return float(cal_model.predict_proba(X)[:, 1][0])

    def class_fn(smiles: str, threshold: float) -> int:
        return int(prob_fn(smiles) >= threshold)

    return prob_fn, class_fn


def run_generation(
    source: SourceRun,
    pilot_cfg_path: Path,
    output_root: Path,
    panel_csv: Path,
    resume: bool,
    max_parents: Optional[int],
    verbose: bool,
) -> Dict[str, Any]:
    dirs = _ensure_dirs(output_root)
    logger = _setup_logger(dirs["logs"] / "generation.log", verbose=verbose)
    pilot_cfg = _load_yaml(pilot_cfg_path)
    logger.info("Using pilot config: %s", pilot_cfg_path)
    logger.info("Using source run: %s", source.run_dir)

    panel_df = pd.read_csv(panel_csv)
    if max_parents is not None:
        panel_df = panel_df.head(max_parents).copy()
    if panel_df.empty:
        raise ValueError("Pilot panel is empty; generation cannot proceed.")

    _snapshot_inputs(source, pilot_cfg_path, panel_csv, dirs)
    context = _load_generation_context(source, pilot_cfg, logger)
    constraints, cf_cfg = _generation_constraints(pilot_cfg)

    prob_fn, class_fn_factory = _prob_and_class_fns(context["cal_model"], context["fp_cfg"])
    threshold = float(context["threshold"])
    std_cfg = StandardizeConfig(tautomer_canonicalize=True, strip_salts=True)

    copied_preds = dirs["generation_run"] / "predictions"
    copied_models = dirs["generation_run"] / "models"
    copied_preds.mkdir(parents=True, exist_ok=True)
    copied_models.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.pred_with_sim_path, copied_preds / source.pred_with_sim_path.name)
    shutil.copy2(source.pred_path, copied_preds / source.pred_path.name)
    shutil.copy2(source.bundle_path, copied_models / source.bundle_path.name)
    shutil.copy2(source.model_meta_path, copied_models / source.model_meta_path.name)

    run_meta = {
        "source_run": str(source.run_dir.resolve()),
        "pilot_config": str(pilot_cfg_path.resolve()),
        "panel_csv": str(panel_csv.resolve()),
        "dataset_path": context["dataset_path"],
        "dataset": source.dataset,
        "split_type": source.split_type,
        "seed": source.seed,
        "threshold": threshold,
        "counterfactuals": cf_cfg,
    }
    (dirs["generation_run"] / "metadata.json").write_text(
        json.dumps(run_meta, indent=2, sort_keys=True), encoding="utf-8"
    )

    lead_candidates = panel_df.to_dict(orient="records")
    logger.info("Pilot generation parents to attempt: %d", len(lead_candidates))
    logger.info("Threshold used: %.3f", threshold)
    logger.info("Source prediction file: %s", source.pred_with_sim_path)

    for i, cand in enumerate(lead_candidates, start=1):
        mol_id = str(cand["mol_id"])
        smi = str(cand["smiles"])
        y_true = int(cand["true_label"])
        report_dir = dirs["generation_lead_reports"] / mol_id
        report_json = report_dir / "report.json"
        if resume and report_json.exists():
            logger.info("Resume skip %d/%d: %s already has report.json", i, len(lead_candidates), mol_id)
            continue

        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            logger.warning("Skipping invalid pilot parent %s", mol_id)
            continue

        fp = mol_to_ecfp_bits(mol, context["fp_cfg"])
        max_sim = (
            float(max(DataStructs.BulkTanimotoSimilarity(fp, context["train_fps"])))
            if context["train_fps"]
            else 0.0
        )
        sim_bin = _bin_similarity(max_sim, [0.3, 0.5, 0.7])
        p_cal = float(prob_fn(smi))

        try:
            flip_prob_max = max(0.0, threshold - 1e-6)
            cfs, cf_diag = generate_counterfactuals_exmol(
                base_smiles=smi,
                model_class=lambda smiles: class_fn_factory(smiles, threshold),
                model_prob=prob_fn,
                fp_cfg=context["fp_cfg"],
                constraints=constraints,
                safe_prob_max=flip_prob_max,
                exmol_preset=str(cf_cfg.get("exmol_preset", "medium")),
                nmols=int(cf_cfg.get("nmols", 5)),
                exmol_n_samples=int(cf_cfg.get("exmol_n_samples", 1800)),
                search_nmols=int(cf_cfg["search_nmols"]) if cf_cfg.get("search_nmols") is not None else None,
                delta_min=float(cf_cfg.get("delta_min", 0.10)),
                delta_min_tier3=float(cf_cfg.get("delta_min_tier3", 0.05)),
                relaxation_plan=cf_cfg.get("relaxations", []),
                logger=logger,
            )
        except Exception as exc:
            logger.exception("Counterfactual generation failed for %s", mol_id)
            cfs = []
            cf_diag = {
                "error": str(exc),
                "sampled": 0,
                "scarcity": True,
                "final_tier": "error",
                "final_count": 0,
            }

        cf_diag = dict(cf_diag or {})
        base_std_smi, base_std_mol = _std_for_scoring(smi, std_cfg)
        if base_std_smi is None:
            base_std_smi = smi
        base_std_p = float(prob_fn(base_std_smi))
        base_props = mol_props(base_std_mol) if base_std_mol is not None else None

        seen_std: set[str] = set()
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

            std_fp = mol_to_ecfp_bits(std_mol, context["fp_cfg"])
            sim_to_train = (
                float(max(DataStructs.BulkTanimotoSimilarity(std_fp, context["train_fps"])))
                if context["train_fps"]
                else 0.0
            )
            p_std = float(prob_fn(std_smi))
            delta_std = base_std_p - p_std
            props_std = mol_props(std_mol)
            alert_std = has_structural_alerts(std_mol) if constraints.pains else False
            logp_delta = None
            if base_props is not None and "logp" in props_std and "logp" in base_props:
                logp_delta = abs(float(props_std["logp"]) - float(base_props["logp"]))

            tier_num, tier_label_std = reconcile_tier_std(
                p_cf=p_std,
                base_p=base_std_p,
                threshold=threshold,
                delta_min=float(cf_cfg.get("delta_min", 0.10)),
                delta_min_tier3=float(cf_cfg.get("delta_min_tier3", 0.05)),
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
            cf["tier_raw"] = cf.get("tier")
            cf["tier_num_std"] = tier_num
            cf["tier_label_std"] = tier_label_std
            cf["tier"] = tier_label_std
            cf["logp"] = props_std["logp"]
            cf["qed"] = props_std["qed"]
            cf["sascore"] = props_std["sascore"]
            cf["alert"] = alert_std
            normalized.append(cf)

        cfs = normalized
        has_actionable = any(cf.get("tier_num_std", 4) in (1, 2, 3) for cf in cfs)
        dataset_fallback: List[Dict[str, Any]] = []
        fallback_used = False
        if (not cfs) or (not has_actionable):
            dataset_fallback = dataset_analogues(
                base_smiles=smi,
                base_fp=fp,
                base_p=p_cal,
                dataset_smiles=context["dataset_smiles"],
                dataset_fps=context["fps_all"],
                dataset_probs=context["dataset_probs"],
                fp_cfg=context["fp_cfg"],
                top_k=int(cf_cfg.get("nmols", 5)),
                constraints=constraints,
            )
            fallback_used = True

        cf_diag["dataset_fallback_used"] = fallback_used
        cf_diag["dataset_fallback_count"] = len(dataset_fallback)
        if fallback_used and (not cfs):
            cf_diag["final_tier"] = "dataset_fallback" if dataset_fallback else cf_diag.get("final_tier", "none")
            cf_diag["final_tier_label"] = (
                "Dataset analogue (fallback)"
                if dataset_fallback
                else cf_diag.get("final_tier_label", cf_diag.get("final_tier", "none"))
            )
            cf_diag["final_relaxation"] = "none"
            cf_diag["final_relaxation_desc"] = "dataset fallback"
            cf_diag["final_count"] = len(dataset_fallback)
            cf_diag["scarcity"] = False if dataset_fallback else True

        final_count_total = len(cfs)
        final_count_tier123 = len([cf for cf in cfs if cf.get("tier_num_std", 4) in (1, 2, 3)])
        best_tier_num = min([cf.get("tier_num_std", 4) for cf in cfs], default=4)
        cf_diag["final_count_total"] = final_count_total
        cf_diag["final_count_tier123"] = final_count_tier123
        cf_diag["final_best_tier_num"] = best_tier_num
        cf_diag["final_tier"] = tier_label_map.get(best_tier_num, cf_diag.get("final_tier"))
        cf_diag["final_tier_label"] = tier_label_map.get(best_tier_num, cf_diag.get("final_tier_label"))
        cf_diag["scarcity"] = final_count_total == 0

        write_lead_report(
            out_dir=report_dir,
            mol_id=mol_id,
            base_smiles=smi,
            base_smiles_std=base_std_smi,
            y_true=y_true,
            p_cal=p_cal,
            p_base_std=base_std_p,
            threshold=threshold,
            max_sim=max_sim,
            sim_bin=sim_bin,
            counterfactuals=cfs,
            dataset_analogues=dataset_fallback,
            cf_summary=cf_diag,
        )
        logger.info(
            "Lead report %d/%d written: %s | final_tier=%s | generated=%d | fallback=%d",
            i,
            len(lead_candidates),
            report_dir,
            cf_diag.get("final_tier"),
            len(cfs),
            len(dataset_fallback),
        )

    summary = summarize_generation(output_root, source, panel_csv, logger, write_md=True)
    return summary


def summarize_generation(
    output_root: Path,
    source: SourceRun,
    panel_csv: Path,
    logger: logging.Logger,
    write_md: bool = True,
) -> Dict[str, Any]:
    dirs = _ensure_dirs(output_root)
    report_paths = sorted(dirs["generation_lead_reports"].rglob("report.json"))
    summary: Dict[str, Any] = {
        "source_run": str(source.run_dir.resolve()),
        "panel_csv": str(panel_csv.resolve()),
        "parents_attempted": 0,
        "parents_completed": len(report_paths),
        "run_incomplete": False,
        "tier_counts": {"tier1": 0, "tier2": 0, "tier3": 0, "tier4": 0, "none": 0},
        "no_surviving_candidates": 0,
        "dataset_fallback_used": 0,
    }

    panel_df = pd.read_csv(panel_csv)
    summary["parents_attempted"] = len(panel_df)
    summary["run_incomplete"] = len(report_paths) < len(panel_df)
    best_tiers: List[int] = []
    for report_path in report_paths:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        cf_summary = report.get("cf_summary", {})
        best_tier = int(cf_summary.get("final_best_tier_num", 4))
        if best_tier == 1:
            summary["tier_counts"]["tier1"] += 1
        elif best_tier == 2:
            summary["tier_counts"]["tier2"] += 1
        elif best_tier == 3:
            summary["tier_counts"]["tier3"] += 1
        elif report.get("counterfactuals"):
            summary["tier_counts"]["tier4"] += 1
        else:
            summary["tier_counts"]["none"] += 1

        if int(cf_summary.get("final_count_total", 0)) == 0:
            summary["no_surviving_candidates"] += 1
        if bool(cf_summary.get("dataset_fallback_used", False)):
            summary["dataset_fallback_used"] += 1
        best_tiers.append(best_tier)

    summary_path = dirs["generation"] / "generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    if write_md:
        lines = [
            "# ChEMBL Cluster Counterfactual Pilot Generation Summary",
            "",
            f"- Source run: `{source.run_dir}`",
            f"- Panel: `{panel_csv}`",
            f"- Threshold: `{source.threshold:.3f}`",
            f"- Parents attempted: `{summary['parents_attempted']}`",
            f"- Parents completed successfully: `{summary['parents_completed']}`",
            f"- Generation incomplete: `{summary['run_incomplete']}`",
            f"- Tier 1 parents: `{summary['tier_counts']['tier1']}`",
            f"- Tier 2 parents: `{summary['tier_counts']['tier2']}`",
            f"- Tier 3 parents: `{summary['tier_counts']['tier3']}`",
            f"- Tier 4-only parents: `{summary['tier_counts']['tier4']}`",
            f"- No surviving generated candidates: `{summary['no_surviving_candidates']}`",
            f"- Dataset fallback used: `{summary['dataset_fallback_used']}`",
        ]
        (dirs["summaries"] / "generation_summary.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    logger.info("Wrote generation summary: %s", summary_path)
    return summary


def write_pilot_summary(output_root: Path, source: SourceRun, panel_csv: Path, logger: logging.Logger) -> Path:
    dirs = _ensure_dirs(output_root)
    panel_df = pd.read_csv(panel_csv)
    generation_summary = json.loads((dirs["generation"] / "generation_summary.json").read_text(encoding="utf-8"))

    candidate_table_path = dirs["tables"] / "counterfactual_literature_audit_candidates.csv"
    similarity_summary_path = dirs["tables"] / "concordance_by_similarity_bin.csv"
    tier_summary_path = dirs["tables"] / "concordance_by_tier.csv"

    lines = [
        "# ChEMBL Cluster Pilot Summary",
        "",
        f"- Source ChEMBL Cluster run: `{source.run_dir}`",
        f"- Source prediction file: `{source.pred_with_sim_path}`",
        f"- Source model bundle: `{source.bundle_path}`",
        f"- Dataset: `{source.dataset}`",
        f"- Split: `{source.split_type}`",
        f"- Seed: `{source.seed}`",
        f"- Threshold used: `{source.threshold:.3f}`",
        "",
        "## Panel design",
        "",
        "- True blockers only (`y == 1`)",
        "- Predicted blockers only (`p_cal >= threshold`)",
        "- Cluster test-set parents only",
        "- Deterministic selection by smallest positive margin above threshold with scaffold diversity preference",
        "",
    ]
    counts = panel_df.groupby("parent_similarity_bin").size().reindex(SIM_BIN_ORDER, fill_value=0)
    for sim_bin, count in counts.items():
        lines.append(f"- `{sim_bin}`: {int(count)} parents")

    lines.extend(
        [
            "",
            "## Generation outcome",
            "",
            f"- Parents attempted: `{generation_summary['parents_attempted']}`",
            f"- Parents completed successfully: `{generation_summary['parents_completed']}`",
            f"- Generation incomplete: `{generation_summary.get('run_incomplete', False)}`",
            f"- Tier 1 parents: `{generation_summary['tier_counts']['tier1']}`",
            f"- Tier 2 parents: `{generation_summary['tier_counts']['tier2']}`",
            f"- Tier 3 parents: `{generation_summary['tier_counts']['tier3']}`",
            f"- Tier 4-only parents: `{generation_summary['tier_counts']['tier4']}`",
            f"- No surviving generated candidates: `{generation_summary['no_surviving_candidates']}`",
            "",
        ]
    )

    recommendation = "modify panel design first"
    if candidate_table_path.exists():
        cand_df = pd.read_csv(candidate_table_path)
        lines.extend(["## Literature-concordance audit", ""])
        lines.append(f"- Audited candidate rows: `{len(cand_df)}`")
        if not cand_df.empty:
            scaffold_fraction = float(cand_df["scaffold_preserved"].fillna(False).astype(bool).mean())
            concordance_fraction = float(
                cand_df["literature_concordant_overall"].fillna(False).astype(bool).mean()
            )
            mean_score = float(cand_df["total_concordance_score"].mean())
            bins_hit = int(cand_df["parent_similarity_bin"].nunique())
            lines.append(f"- Fraction scaffold-preserving: `{scaffold_fraction:.1%}`")
            lines.append(f"- Fraction literature-concordant overall: `{concordance_fraction:.1%}`")
            lines.append(f"- Mean concordance score: `{mean_score:.2f}`")
            lines.append(f"- Novelty bins represented in audited cohort: `{bins_hit}`")

            if similarity_summary_path.exists():
                sim_df = pd.read_csv(similarity_summary_path)
                if not sim_df.empty:
                    lines.append("")
                    lines.append("### Concordance by novelty bin")
                    lines.append("")
                    for _, row in sim_df.iterrows():
                        lines.append(
                            f"- `{row['parent_similarity_bin']}`: n_candidates={int(row['n_candidates'])}, "
                            f"mean_score={float(row['mean_concordance_score']):.2f}, "
                            f"lit_concordant={float(row['fraction_literature_concordant_overall']):.1%}"
                        )

            failure_modes: List[str] = []
            if generation_summary["tier_counts"]["tier1"] + generation_summary["tier_counts"]["tier2"] + generation_summary["tier_counts"]["tier3"] == 0:
                failure_modes.append("No Tier 1-3 generated hits were produced in the pilot.")
            if scaffold_fraction < 0.5:
                failure_modes.append("Scaffold-preserving suggestions were uncommon in the retained audit cohort.")
            if bins_hit < 2:
                failure_modes.append("The retained audit cohort populated fewer than two novelty bins meaningfully.")
            if concordance_fraction < 0.25:
                failure_modes.append("Most retained candidates did not satisfy the heuristic literature-concordance threshold.")

            lines.extend(["", "## Obvious failure modes", ""])
            if failure_modes:
                lines.extend(f"- {item}" for item in failure_modes)
            else:
                lines.append("- No dominant operational failure mode stood out in the pilot cohort.")

            if generation_summary.get("run_incomplete", False):
                lines.append(
                    "- The full 20-parent pilot did not complete in one clean pass; the current audit reflects only the completed subset."
                )

            tier123_total = (
                generation_summary["tier_counts"]["tier1"]
                + generation_summary["tier_counts"]["tier2"]
                + generation_summary["tier_counts"]["tier3"]
            )
            if tier123_total >= 6 and bins_hit >= 2 and scaffold_fraction >= 0.5:
                recommendation = "scale"
            elif tier123_total == 0 or bins_hit < 2:
                recommendation = "modify panel design first"
            else:
                recommendation = "increase parent count cautiously"
        else:
            lines.append("- The audit completed, but no Tier 1-3 candidate rows were retained.")
            lines.extend(["", "## Obvious failure modes", "", "- The strict Tier 1-3 best-per-parent cohort was empty."])
            recommendation = "modify panel design first"
    else:
        lines.extend(
            [
                "## Literature-concordance audit",
                "",
                "- Audit outputs were not found yet; run the audit before writing the final pilot recommendation.",
            ]
        )

    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- Pilot recommendation: **{recommendation}**",
            "- This pilot is decision-oriented only; it does not constitute final manuscript evidence.",
        ]
    )

    out_path = dirs["summaries"] / "pilot_summary.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote pilot summary: %s", out_path)
    return out_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a ChEMBL Cluster pilot parent panel and run counterfactual generation "
            "against an existing calibrated Stage 1 ChEMBL Cluster source run."
        )
    )
    parser.add_argument(
        "--source-run",
        type=Path,
        default=None,
        help="Optional explicit ChEMBL Stage 1 run directory. If omitted, a valid source run is auto-selected.",
    )
    parser.add_argument(
        "--pilot-config",
        type=Path,
        default=Path("configs/chembl_cluster_counterfactual_pilot.yaml"),
        help="Pilot counterfactual config used for generation policy and provenance.",
    )
    parser.add_argument(
        "--panel-file",
        type=Path,
        default=None,
        help=(
            "Optional existing parent panel CSV to use instead of rebuilding the default "
            "20-parent Cluster pilot panel."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports/lead_opt_literature_audit_chembl/cluster_pilot"),
        help="Pilot output root.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=11,
        help="Cluster seed to anchor the pilot to. Default: 11",
    )
    parser.add_argument(
        "--panel-size",
        type=int,
        default=20,
        help="Total pilot parent count. Default: 20",
    )
    parser.add_argument(
        "--per-bin",
        type=int,
        default=5,
        help="Target number of parents per novelty bin. Default: 5",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip parents that already have a completed report.json under the pilot generation directory.",
    )
    parser.add_argument(
        "--build-panel-only",
        action="store_true",
        help="Build and snapshot the pilot parent panel, then exit without generation.",
    )
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="Write the final pilot summary from existing generation and audit outputs, then exit.",
    )
    parser.add_argument(
        "--max-parents",
        type=int,
        default=None,
        help="Optional deterministic cap on the number of panel parents to generate in this invocation.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable more detailed logging.",
    )
    return parser


def _resolve_source(args, logger: logging.Logger) -> SourceRun:
    if args.source_run is None:
        return _discover_source_run(seed=args.seed, logger=logger)

    run_dir = (REPO_ROOT / args.source_run).resolve() if not args.source_run.is_absolute() else args.source_run.resolve()
    metadata_path = run_dir / "metadata.json"
    config_path = run_dir / "config.resolved.yaml"
    pred_with_sim_path = run_dir / "predictions" / f"test_preds_cluster_seed{args.seed}_with_sim.csv"
    pred_path = run_dir / "predictions" / f"test_preds_cluster_seed{args.seed}.csv"
    bundle_path = run_dir / "models" / f"model_cluster_seed{args.seed}.joblib"
    model_meta_path = run_dir / "models" / f"model_meta_cluster_seed{args.seed}.json"
    for path in [metadata_path, config_path, pred_with_sim_path, pred_path, bundle_path, model_meta_path]:
        if not path.exists():
            raise FileNotFoundError(f"Missing required source-run file: {path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    cfg = metadata.get("config", {})
    split_csv_path = REPO_ROOT / str(cfg.get("paths", {}).get("data_splits", "data/chembl/splits")) / f"cluster_seed{args.seed}.csv"
    model_meta = json.loads(model_meta_path.read_text(encoding="utf-8"))
    return SourceRun(
        run_dir=run_dir,
        metadata_path=metadata_path,
        config_path=config_path,
        pred_with_sim_path=pred_with_sim_path,
        pred_path=pred_path,
        split_csv_path=split_csv_path,
        bundle_path=bundle_path,
        model_meta_path=model_meta_path,
        dataset="chembl",
        split_type="cluster",
        seed=args.seed,
        threshold=float(model_meta["calibration"]["threshold"]),
    )


def main() -> int:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

    parser = _build_parser()
    args = parser.parse_args()
    output_root = (REPO_ROOT / args.output_root).resolve() if not args.output_root.is_absolute() else args.output_root.resolve()
    dirs = _ensure_dirs(output_root)
    logger = _setup_logger(dirs["logs"] / "pilot_driver.log", verbose=args.verbose)
    source = _resolve_source(args, logger)

    logger.info("Chosen source run directory: %s", source.run_dir)
    logger.info("Source files for panel construction:")
    logger.info("  predictions with similarity: %s", source.pred_with_sim_path)
    logger.info("  raw test predictions: %s", source.pred_path)
    logger.info("  model metadata: %s", source.model_meta_path)
    logger.info("  model bundle: %s", source.bundle_path)
    logger.info("  split CSV: %s", source.split_csv_path)
    logger.info("Metadata: dataset=%s split=%s seed=%d threshold=%.3f", source.dataset, source.split_type, source.seed, source.threshold)

    if args.panel_file is not None:
        panel_csv = (REPO_ROOT / args.panel_file).resolve() if not args.panel_file.is_absolute() else args.panel_file.resolve()
        if not panel_csv.exists():
            raise FileNotFoundError(f"Explicit panel file not found: {panel_csv}")
        panel_df = pd.read_csv(panel_csv)
        panel_summary_md = dirs["summaries"] / "panel_design.md"
        lines = [
            "# ChEMBL Cluster Pilot Parent Panel",
            "",
            f"- Source run: `{source.run_dir}`",
            f"- External panel file: `{panel_csv}`",
            f"- Dataset: `{source.dataset}`",
            f"- Split: `{source.split_type}`",
            f"- Seed: `{source.seed}`",
            f"- Threshold: `{source.threshold:.3f}`",
            "",
            "- This shard reused an explicit prebuilt pilot panel subset rather than rebuilding the default full panel.",
        ]
        panel_summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        panel_csv = dirs["inputs_snapshot"] / "chembl_cluster_pilot_parent_panel.csv"
        panel_summary_md = dirs["summaries"] / "panel_design.md"
        panel_df = build_panel(
            source=source,
            panel_csv=panel_csv,
            panel_summary_md=panel_summary_md,
            target_total=args.panel_size,
            per_bin=args.per_bin,
            logger=logger,
        )

    if args.build_panel_only and not args.summarize_only:
        return 0

    pilot_cfg_path = (REPO_ROOT / args.pilot_config).resolve() if not args.pilot_config.is_absolute() else args.pilot_config.resolve()
    if not args.summarize_only:
        run_generation(
            source=source,
            pilot_cfg_path=pilot_cfg_path,
            output_root=output_root,
            panel_csv=panel_csv,
            resume=args.resume,
            max_parents=args.max_parents,
            verbose=args.verbose,
        )

    write_pilot_summary(output_root=output_root, source=source, panel_csv=panel_csv, logger=logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
