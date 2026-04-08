from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor
from rdkit import Chem
from rdkit.Chem import Crippen, Lipinski, rdMolDescriptors
from rdkit.Chem.Scaffolds import MurckoScaffold


LOGGER = logging.getLogger(__name__)

SIMILARITY_BIN_ORDER = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
SIMILARITY_BIN_COLORS = {
    "<0.3": "#D95F5F",
    "0.3-0.5": "#F4A261",
    "0.5-0.7": "#7FB069",
    ">0.7": "#4C78A8",
}

TIER_NAME_TO_NUM = {
    "flip": 1,
    "risk_reduction": 2,
    "weak_reduction": 3,
    "weak_improvement": 3,
    "diagnostic_close_edits": 4,
    "dataset_analogue": 5,
}
TIER_NUM_TO_NAME = {v: k for k, v in TIER_NAME_TO_NUM.items()}
TIER_NUM_TO_LABEL = {
    1: "Tier 1 — Flip",
    2: "Tier 2 — Risk reduction",
    3: "Tier 3 — Weak improvement",
    4: "Tier 4 — Diagnostic fallback",
    5: "Dataset analogue fallback",
}

PREDICTION_FILENAME_RE = re.compile(
    r"test_preds_(?P<split_type>[a-z]+)_seed(?P<split_seed>\d+)_with_sim\.csv$"
)

TERTIARY_AMINE_SMARTS = Chem.MolFromSmarts(
    "[N;X3;H0;+0;!$(N-C=O);!$(N-C=S);!$(N=a);!$(N#*);!$(N=*)]([#6])[#6]"
)
BASIC_AMINE_SMARTS = Chem.MolFromSmarts(
    "[N;X3;H0,H1,H2;+0;!$(N-C=O);!$(N-C=S);!$(N=a);!$(N#*);!$(N=*)]"
)

CORE_RULES = [
    ("rule_lower_logp", "Lower logP"),
    ("rule_increase_tpsa", "Increase TPSA"),
    ("rule_reduce_aromatic_rings", "Reduce aromatic ring count"),
    ("rule_reduce_rotatable_bonds", "Reduce rotatable bonds"),
    ("rule_reduce_cationic_burden_proxy", "Reduce cationic burden proxy"),
]

ALL_RULES = CORE_RULES + [
    ("rule_increase_fraction_csp3", "Increase fraction Csp3"),
    ("rule_reduce_formal_charge", "Reduce formal charge"),
    ("rule_reduce_tertiary_amine_like", "Reduce tertiary amine-like motif"),
]

SIMILARITY_FIELD_NOTE = (
    "The current serialized field `similarity_to_train` in lead-opt report.json "
    "counterfactual records is interpreted here as candidate-to-parent similarity, "
    "not train-set similarity."
)


@dataclass
class RunContext:
    input_root: Path
    run_dir: Path
    lead_reports_dir: Path
    metadata_path: Optional[Path]
    prediction_files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class AuditArtifacts:
    candidate_table: Path
    best_table: Path
    summary_by_similarity: Path
    summary_by_tier: Path
    summary_by_split: Optional[Path]
    summary_txt: Path
    concordance_by_similarity_fig: Path
    rule_hit_rates_fig: Path
    scaffold_preservation_fig: Path
    delta_prob_vs_concordance_fig: Path
    input_manifest: Path
    report_manifest: Path
    rule_snapshot: Path
    run_parameters: Path
    filter_counts: Path
    log_path: Path


def setup_audit_logger(log_path: Path, verbose: bool = False) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("literature_concordance_audit")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def ensure_output_tree(output_root: Path) -> dict[str, Path]:
    paths = {
        "root": output_root,
        "inputs_snapshot": output_root / "inputs_snapshot",
        "tables": output_root / "tables",
        "figures": output_root / "figures",
        "summaries": output_root / "summaries",
        "logs": output_root / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def resolve_run_context(input_root: Path) -> RunContext:
    input_root = input_root.resolve()
    notes: list[str] = []

    if input_root.is_dir() and input_root.name == "lead_reports":
        run_dir = input_root.parent
        lead_reports_dir = input_root
    elif (input_root / "lead_reports").is_dir():
        run_dir = input_root
        lead_reports_dir = input_root / "lead_reports"
    else:
        candidates = sorted(
            [
                path
                for path in input_root.glob("*")
                if path.is_dir() and (path / "lead_reports").is_dir()
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(
                f"No lead_reports/ directory found under input root: {input_root}"
            )
        run_dir = candidates[0]
        lead_reports_dir = run_dir / "lead_reports"
        notes.append(
            f"Auto-selected latest run directory from {input_root}: {run_dir}"
        )

    metadata_path = run_dir / "metadata.json"
    prediction_dir = run_dir / "predictions"
    prediction_files = sorted(prediction_dir.glob("test_preds_*_with_sim.csv"))

    return RunContext(
        input_root=input_root,
        run_dir=run_dir,
        lead_reports_dir=lead_reports_dir,
        metadata_path=metadata_path if metadata_path.exists() else None,
        prediction_files=prediction_files,
        notes=notes,
    )


def _safe_json_load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Failed to parse JSON at {path}: {exc}") from exc


def infer_dataset(context: RunContext, dataset_override: Optional[str]) -> str:
    if dataset_override:
        return dataset_override.lower()

    if context.metadata_path and context.metadata_path.exists():
        meta = _safe_json_load(context.metadata_path)
        stage1_cfg = meta.get("config", {}).get("stage1", {})
        dataset_cfg = stage1_cfg.get("dataset", {})
        if "tdc_task" in dataset_cfg:
            return "tdc"
        dataset_name = str(dataset_cfg.get("name", "")).lower()
        if "chembl" in dataset_name:
            return "chembl"

    run_label = context.run_dir.name.lower()
    if "chembl" in run_label:
        return "chembl"
    return "tdc"


def load_prediction_context(prediction_files: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    required_cols = {"mol_id", "smiles", "p_cal", "max_sim_to_train", "sim_bin"}

    for pred_path in prediction_files:
        match = PREDICTION_FILENAME_RE.match(pred_path.name)
        if not match:
            continue
        df = pd.read_csv(pred_path)
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(
                f"Prediction file {pred_path} is missing required columns: {sorted(missing)}"
            )
        df = df.copy()
        df["split_type"] = match.group("split_type")
        df["split_seed"] = int(match.group("split_seed"))
        df["prediction_file"] = str(pred_path)
        frames.append(df)

    if not frames:
        return pd.DataFrame(
            columns=[
                "mol_id",
                "smiles",
                "p_cal",
                "max_sim_to_train",
                "sim_bin",
                "split_type",
                "split_seed",
                "prediction_file",
            ]
        )

    return pd.concat(frames, ignore_index=True)


def _normalize_similarity_bin(max_sim: Optional[float], sim_bin: Optional[str]) -> Optional[str]:
    if sim_bin in SIMILARITY_BIN_ORDER:
        return sim_bin
    if max_sim is None or math.isnan(max_sim):
        return None
    if max_sim < 0.3:
        return "<0.3"
    if max_sim < 0.5:
        return "0.3-0.5"
    if max_sim < 0.7:
        return "0.5-0.7"
    return ">0.7"


def _extract_match_row(
    prediction_df: pd.DataFrame,
    mol_id: str,
    base_smiles: str,
    p_base_std: Optional[float],
    max_sim_to_train: Optional[float],
    sim_bin: Optional[str],
) -> tuple[dict[str, Any], Optional[str]]:
    if prediction_df.empty:
        return {}, None

    sub = prediction_df[
        (prediction_df["mol_id"].astype(str) == str(mol_id))
        | (prediction_df["smiles"].astype(str) == str(base_smiles))
    ].copy()
    if sub.empty:
        return {}, None

    target_bin = _normalize_similarity_bin(max_sim_to_train, sim_bin)
    target_p = float(p_base_std) if p_base_std is not None else None
    target_sim = float(max_sim_to_train) if max_sim_to_train is not None else None

    sub["score_bin"] = (
        0
        if target_bin is None
        else (sub["sim_bin"].astype(str) != target_bin).astype(int)
    )
    sub["score_sim"] = 0.0 if target_sim is None else (
        sub["max_sim_to_train"].astype(float) - target_sim
    ).abs()
    sub["score_prob"] = 0.0 if target_p is None else (
        sub["p_cal"].astype(float) - target_p
    ).abs()
    sub = sub.sort_values(
        ["score_bin", "score_sim", "score_prob", "split_type", "split_seed"]
    ).reset_index(drop=True)

    if len(sub) > 1:
        first = sub.iloc[0]
        second = sub.iloc[1]
        tied = (
            int(first["score_bin"]) == int(second["score_bin"])
            and float(first["score_sim"]) == float(second["score_sim"])
            and float(first["score_prob"]) == float(second["score_prob"])
        )
        if tied:
            return {}, (
                f"Ambiguous prediction-context join for mol_id={mol_id}; "
                f"multiple rows tied across split regimes."
            )

    chosen = sub.iloc[0].to_dict()
    return chosen, None


def load_parent_novelty_join(join_path: Path) -> pd.DataFrame:
    join_path = join_path.resolve()
    df = pd.read_csv(join_path)
    cols = set(df.columns)

    id_col = None
    for candidate in ("mol_id", "parent_id"):
        if candidate in cols:
            id_col = candidate
            break
    smiles_col = None
    for candidate in ("smiles", "parent_smiles", "base_smiles_std", "base_smiles_raw"):
        if candidate in cols:
            smiles_col = candidate
            break

    if id_col is None and smiles_col is None:
        raise ValueError(
            f"Novelty join file {join_path} must contain at least one identifier column "
            "(mol_id/parent_id or smiles/parent_smiles)."
        )

    if "max_sim_to_train" not in cols and "sim_bin" not in cols:
        raise ValueError(
            f"Novelty join file {join_path} must contain max_sim_to_train and/or sim_bin."
        )

    join_df = df.copy()
    if id_col is not None:
        join_df["parent_id"] = join_df[id_col].astype(str)
    else:
        join_df["parent_id"] = None
    if smiles_col is not None:
        join_df["parent_smiles"] = join_df[smiles_col].astype(str)
    else:
        join_df["parent_smiles"] = None

    if "max_sim_to_train" in join_df.columns:
        join_df["parent_max_sim_to_train"] = pd.to_numeric(
            join_df["max_sim_to_train"], errors="coerce"
        )
    else:
        join_df["parent_max_sim_to_train"] = np.nan

    if "sim_bin" in join_df.columns:
        join_df["parent_similarity_bin"] = join_df["sim_bin"].astype(str)
    else:
        join_df["parent_similarity_bin"] = None

    if "split_type" in join_df.columns:
        join_df["split_type"] = join_df["split_type"].astype(str)
    if "seed" in join_df.columns:
        join_df["split_seed"] = pd.to_numeric(join_df["seed"], errors="coerce")
    elif "split_seed" in join_df.columns:
        join_df["split_seed"] = pd.to_numeric(join_df["split_seed"], errors="coerce")

    keep_cols = [
        "parent_id",
        "parent_smiles",
        "parent_max_sim_to_train",
        "parent_similarity_bin",
    ]
    if "split_type" in join_df.columns:
        keep_cols.append("split_type")
    if "split_seed" in join_df.columns:
        keep_cols.append("split_seed")
    return join_df[keep_cols].copy()


def _require_candidate_field(candidate: dict[str, Any], field_names: list[str], source: Path) -> Any:
    for field_name in field_names:
        if candidate.get(field_name) is not None:
            return candidate[field_name]
    raise ValueError(
        f"Candidate record in {source} is missing essential fields: {field_names}"
    )


def _normalize_tier(candidate: dict[str, Any], source_kind: str) -> tuple[int, str, str]:
    if source_kind == "dataset_analogue":
        return 5, "dataset_analogue", TIER_NUM_TO_LABEL[5]

    tier_num = candidate.get("tier_num_std")
    if tier_num is not None:
        tier_num = int(tier_num)
        return tier_num, TIER_NUM_TO_NAME.get(tier_num, "unknown"), TIER_NUM_TO_LABEL.get(
            tier_num, f"Tier {tier_num}"
        )

    raw_name = str(
        candidate.get("tier_raw")
        or candidate.get("tier")
        or candidate.get("tier_label_std")
        or ""
    ).strip()
    norm_name = raw_name.lower().replace(" ", "_")
    tier_num = TIER_NAME_TO_NUM.get(norm_name)
    if tier_num is None:
        raise ValueError(f"Unrecognized tier value {raw_name!r}")
    return tier_num, TIER_NUM_TO_NAME[tier_num], TIER_NUM_TO_LABEL[tier_num]


def _mol_from_smiles(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"RDKit failed to parse SMILES: {smiles}")
    return mol


def _generic_scaffold_smi(mol: Chem.Mol) -> Optional[str]:
    try:
        scaffold = MurckoScaffold.GetScaffoldForMol(mol)
        if scaffold is None:
            return None
        generic = MurckoScaffold.MakeScaffoldGeneric(scaffold)
        if generic is None:
            return None
        return Chem.MolToSmiles(generic, canonical=True)
    except Exception:
        return None


def _count_match_atoms(mol: Chem.Mol, pattern: Optional[Chem.Mol]) -> tuple[int, set[int]]:
    if pattern is None:
        return 0, set()
    matches = mol.GetSubstructMatches(pattern)
    atoms = {idx for match in matches for idx in match}
    return len(matches), atoms


def compute_descriptor_block(smiles: str) -> dict[str, float | int | bool | str]:
    mol = _mol_from_smiles(smiles)
    tertiary_count, tertiary_atoms = _count_match_atoms(mol, TERTIARY_AMINE_SMARTS)
    basic_count, basic_atoms = _count_match_atoms(mol, BASIC_AMINE_SMARTS)
    positive_n_atoms = {
        atom.GetIdx()
        for atom in mol.GetAtoms()
        if atom.GetAtomicNum() == 7 and atom.GetFormalCharge() > 0
    }

    formal_charge = int(sum(atom.GetFormalCharge() for atom in mol.GetAtoms()))
    heteroatom_count = int(
        sum(atom.GetAtomicNum() not in (1, 6) for atom in mol.GetAtoms())
    )

    return {
        "mol_logp": float(Crippen.MolLogP(mol)),
        "tpsa": float(rdMolDescriptors.CalcTPSA(mol)),
        "fraction_csp3": float(rdMolDescriptors.CalcFractionCSP3(mol)),
        "aromatic_ring_count": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        "total_ring_count": int(rdMolDescriptors.CalcNumRings(mol)),
        "rotatable_bonds": int(rdMolDescriptors.CalcNumRotatableBonds(mol)),
        "formal_charge": formal_charge,
        "heavy_atom_count": int(rdMolDescriptors.CalcNumHeavyAtoms(mol)),
        "heteroatom_count": heteroatom_count,
        "hbd_count": int(rdMolDescriptors.CalcNumHBD(mol)),
        "hba_count": int(rdMolDescriptors.CalcNumHBA(mol)),
        "tertiary_amine_like_count": int(tertiary_count),
        "basic_amine_proxy_count": int(basic_count),
        "formal_positive_n_count": int(len(positive_n_atoms)),
        "cationic_burden_proxy": int(len(basic_atoms | positive_n_atoms)),
        "smiles_rdkit": Chem.MolToSmiles(mol, canonical=True),
        "generic_scaffold_smiles": _generic_scaffold_smi(mol),
    }


def _is_concordant_decrease(delta: float) -> bool:
    return pd.notna(delta) and float(delta) < 0


def _is_concordant_increase(delta: float) -> bool:
    return pd.notna(delta) and float(delta) > 0


def _descriptor_worker(smiles: str) -> tuple[str, dict[str, float | int | bool | str]]:
    return smiles, compute_descriptor_block(smiles)


def _build_descriptor_map(
    smiles_list: list[str],
    *,
    workers: int,
    chunk_size: int,
    logger: Optional[logging.Logger] = None,
) -> dict[str, dict[str, float | int | bool | str]]:
    unique_smiles = sorted({str(smiles) for smiles in smiles_list})
    if logger:
        logger.info(
            "Descriptor scoring: %d candidate/parent rows collapsed to %d unique SMILES (workers=%d, chunk_size=%d)",
            len(smiles_list),
            len(unique_smiles),
            workers,
            chunk_size,
        )
    if not unique_smiles:
        return {}

    if workers <= 1:
        return {smiles: compute_descriptor_block(smiles) for smiles in unique_smiles}

    descriptor_map: dict[str, dict[str, float | int | bool | str]] = {}
    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            for smiles, descriptor_block in executor.map(
                _descriptor_worker,
                unique_smiles,
                chunksize=max(1, int(chunk_size)),
            ):
                descriptor_map[smiles] = descriptor_block
        return descriptor_map
    except (PermissionError, OSError) as exc:
        if logger:
            logger.warning(
                "Falling back to serial descriptor scoring because worker-process initialization failed: %s",
                exc,
            )
        return {smiles: compute_descriptor_block(smiles) for smiles in unique_smiles}


def compute_concordance_fields(
    df: pd.DataFrame,
    *,
    workers: int = 1,
    chunk_size: int = 64,
    logger: Optional[logging.Logger] = None,
) -> pd.DataFrame:
    all_smiles = df["parent_smiles"].astype(str).tolist() + df["candidate_smiles"].astype(str).tolist()
    descriptor_map = _build_descriptor_map(
        all_smiles,
        workers=max(1, int(workers)),
        chunk_size=max(1, int(chunk_size)),
        logger=logger,
    )

    rows = []
    for row in df.to_dict(orient="records"):
        parent_desc = descriptor_map[str(row["parent_smiles"])]
        candidate_desc = descriptor_map[str(row["candidate_smiles"])]
        base_scaffold = parent_desc.get("generic_scaffold_smiles")
        cand_scaffold = candidate_desc.get("generic_scaffold_smiles")
        scaffold_preserved = bool(base_scaffold is not None and cand_scaffold == base_scaffold)

        enriched = dict(row)
        for name, value in parent_desc.items():
            enriched[f"parent_{name}"] = value
        for name, value in candidate_desc.items():
            enriched[f"candidate_{name}"] = value

        for descriptor in (
            "mol_logp",
            "tpsa",
            "fraction_csp3",
            "aromatic_ring_count",
            "total_ring_count",
            "rotatable_bonds",
            "formal_charge",
            "heavy_atom_count",
            "heteroatom_count",
            "hbd_count",
            "hba_count",
            "tertiary_amine_like_count",
            "basic_amine_proxy_count",
            "formal_positive_n_count",
            "cationic_burden_proxy",
        ):
            enriched[f"delta_{descriptor}"] = (
                enriched[f"candidate_{descriptor}"] - enriched[f"parent_{descriptor}"]
            )

        enriched["scaffold_preserved"] = scaffold_preserved
        enriched["medicinal_locality_score"] = int(scaffold_preserved) + int(
            float(enriched["similarity_to_parent"]) >= 0.5
        ) + int(abs(float(enriched["delta_heavy_atom_count"])) <= 2)
        enriched["medicinal_locality_flag"] = bool(
            enriched["medicinal_locality_score"] >= 2
        )

        enriched["rule_lower_logp"] = _is_concordant_decrease(
            enriched["delta_mol_logp"]
        )
        enriched["rule_increase_tpsa"] = _is_concordant_increase(
            enriched["delta_tpsa"]
        )
        enriched["rule_reduce_aromatic_rings"] = _is_concordant_decrease(
            enriched["delta_aromatic_ring_count"]
        )
        enriched["rule_reduce_rotatable_bonds"] = _is_concordant_decrease(
            enriched["delta_rotatable_bonds"]
        )
        enriched["rule_reduce_cationic_burden_proxy"] = _is_concordant_decrease(
            enriched["delta_cationic_burden_proxy"]
        )
        enriched["rule_increase_fraction_csp3"] = _is_concordant_increase(
            enriched["delta_fraction_csp3"]
        )
        enriched["rule_reduce_formal_charge"] = _is_concordant_decrease(
            enriched["delta_formal_charge"]
        )
        enriched["rule_reduce_tertiary_amine_like"] = _is_concordant_decrease(
            enriched["delta_tertiary_amine_like_count"]
        )

        enriched["total_concordance_score"] = int(
            sum(bool(enriched[name]) for name, _ in CORE_RULES)
        )
        enriched["normalized_concordance_fraction"] = (
            enriched["total_concordance_score"] / len(CORE_RULES)
        )
        enriched["literature_concordant_overall"] = bool(
            enriched["total_concordance_score"] >= 3
        )
        rows.append(enriched)

    out = pd.DataFrame(rows)
    out["parent_similarity_bin"] = pd.Categorical(
        out["parent_similarity_bin"], categories=SIMILARITY_BIN_ORDER, ordered=True
    )
    return out


def _normalize_report_record(
    report_path: Path,
    dataset: str,
    prediction_df: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    data = _safe_json_load(report_path)
    required_top = {
        "mol_id",
        "counterfactuals",
        "cf_summary",
        "threshold",
        "p_base_std",
    }
    missing = required_top - set(data.keys())
    if missing:
        raise ValueError(
            f"Report {report_path} is missing required top-level fields: {sorted(missing)}"
        )

    parent_smiles = data.get("base_smiles_std") or data.get("base_smiles_raw")
    if not parent_smiles:
        raise ValueError(f"Report {report_path} is missing base SMILES.")

    parent_id = str(data["mol_id"])
    parent_prob = float(data["p_base_std"])
    parent_max_sim = (
        float(data["max_sim_to_train"])
        if data.get("max_sim_to_train") is not None
        else None
    )
    parent_bin = _normalize_similarity_bin(parent_max_sim, data.get("sim_bin"))

    prediction_row, warning = _extract_match_row(
        prediction_df=prediction_df,
        mol_id=parent_id,
        base_smiles=parent_smiles,
        p_base_std=parent_prob,
        max_sim_to_train=parent_max_sim,
        sim_bin=parent_bin,
    )
    warnings = [warning] if warning else []

    base_record = {
        "parent_id": parent_id,
        "parent_smiles": parent_smiles,
        "dataset": dataset,
        "split_type": prediction_row.get("split_type"),
        "split_seed": prediction_row.get("split_seed"),
        "run_seed": None,
        "parent_similarity_bin": parent_bin,
        "parent_max_sim_to_train": parent_max_sim,
        "parent_prob": parent_prob,
        "parent_threshold": float(data["threshold"]),
        "parent_y_true": data.get("y_true"),
        "dataset_fallback_used": bool(
            data.get("cf_summary", {}).get("dataset_fallback_used", False)
        ),
        "source_file": str(report_path),
        "source_report": str(report_path.with_name("report.md")),
        "source_run_dir": str(report_path.parents[2]),
        "similarity_field_note": SIMILARITY_FIELD_NOTE,
    }

    rows: list[dict[str, Any]] = []
    for idx, candidate in enumerate(data.get("counterfactuals", []), start=1):
        candidate_smiles = _require_candidate_field(
            candidate, ["smiles_std", "smiles", "raw_smiles"], report_path
        )
        candidate_prob = _require_candidate_field(
            candidate, ["p_std", "p", "p_raw"], report_path
        )
        delta_prob = _require_candidate_field(
            candidate, ["delta_p_std", "delta_p", "delta_p_raw"], report_path
        )
        sim_to_parent = _require_candidate_field(
            candidate, ["similarity_to_train", "similarity"], report_path
        )
        tier_num, tier_name, tier_label = _normalize_tier(candidate, "generated")

        rows.append(
            {
                **base_record,
                "candidate_rank": idx,
                "candidate_source": "generated",
                "candidate_smiles": str(candidate_smiles),
                "candidate_prob": float(candidate_prob),
                "delta_prob": float(delta_prob),
                "similarity_to_parent": float(sim_to_parent),
                "tier_num": tier_num,
                "tier_name": tier_name,
                "tier_label": tier_label,
                "relaxation": str(candidate.get("relaxation", "none")),
                "is_relaxed_candidate": str(candidate.get("relaxation", "none")) != "none",
                "candidate_alert_reported": (
                    bool(candidate.get("alert")) if candidate.get("alert") is not None else None
                ),
            }
        )

    for idx, candidate in enumerate(data.get("dataset_analogues", []), start=1):
        candidate_smiles = _require_candidate_field(
            candidate, ["smiles", "smiles_std", "raw_smiles"], report_path
        )
        candidate_prob = _require_candidate_field(candidate, ["p"], report_path)
        delta_prob = _require_candidate_field(candidate, ["delta_p"], report_path)
        sim_to_parent = _require_candidate_field(candidate, ["similarity"], report_path)
        tier_num, tier_name, tier_label = _normalize_tier(candidate, "dataset_analogue")

        rows.append(
            {
                **base_record,
                "candidate_rank": idx,
                "candidate_source": "dataset_analogue",
                "candidate_smiles": str(candidate_smiles),
                "candidate_prob": float(candidate_prob),
                "delta_prob": float(delta_prob),
                "similarity_to_parent": float(sim_to_parent),
                "tier_num": tier_num,
                "tier_name": tier_name,
                "tier_label": tier_label,
                "relaxation": str(candidate.get("relaxation", "none")),
                "is_relaxed_candidate": False,
                "candidate_alert_reported": (
                    bool(candidate.get("alert")) if candidate.get("alert") is not None else None
                ),
            }
        )

    return rows, warnings, data


def load_candidate_pairs(
    context: RunContext,
    dataset_override: Optional[str] = None,
    join_parent_novelty_from: Optional[Path] = None,
    parent_panel_file: Optional[Path] = None,
    max_parents: Optional[int] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    dataset = infer_dataset(context, dataset_override)
    prediction_df = load_prediction_context(context.prediction_files)
    report_paths = sorted(context.lead_reports_dir.rglob("report.json"))
    if not report_paths:
        raise FileNotFoundError(
            f"No report.json files found under {context.lead_reports_dir}"
        )

    selected_parent_ids: Optional[set[str]] = None
    selected_parent_smiles: Optional[set[str]] = None
    if parent_panel_file is not None:
        panel_df = pd.read_csv(parent_panel_file)
        if "mol_id" in panel_df.columns:
            selected_parent_ids = {
                str(value) for value in panel_df["mol_id"].dropna().astype(str).tolist()
            }
        if "smiles" in panel_df.columns:
            selected_parent_smiles = {
                str(value) for value in panel_df["smiles"].dropna().astype(str).tolist()
            }
        if not selected_parent_ids and not selected_parent_smiles:
            raise ValueError(
                f"Parent panel file {parent_panel_file} must contain mol_id and/or smiles."
            )

        filtered_paths: list[Path] = []
        for report_path in report_paths:
            report_parent_id = report_path.parent.name
            if selected_parent_ids and report_parent_id in selected_parent_ids:
                filtered_paths.append(report_path)
                continue
            if selected_parent_smiles:
                report_data = _safe_json_load(report_path)
                report_smiles = str(
                    report_data.get("base_smiles_std") or report_data.get("base_smiles_raw") or ""
                )
                if report_smiles in selected_parent_smiles:
                    filtered_paths.append(report_path)
        report_paths = filtered_paths

    if max_parents is not None and max_parents > 0:
        report_paths = report_paths[: int(max_parents)]

    if not report_paths:
        raise ValueError("No lead reports remained after applying parent subset filters.")

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    report_manifest_rows: list[dict[str, Any]] = []
    for report_path in report_paths:
        report_rows, report_warnings, report_data = _normalize_report_record(
            report_path=report_path,
            dataset=dataset,
            prediction_df=prediction_df,
        )
        rows.extend(report_rows)
        warnings.extend(w for w in report_warnings if w)
        report_manifest_rows.append(
            {
                "parent_id": str(report_data.get("mol_id")),
                "report_json": str(report_path),
                "report_md": str(report_path.with_name("report.md")),
                "n_counterfactuals": len(report_data.get("counterfactuals", [])),
                "n_dataset_analogues": len(report_data.get("dataset_analogues", [])),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(
            f"No candidate rows were parsed from reports under {context.lead_reports_dir}"
        )

    if join_parent_novelty_from is not None:
        join_df = load_parent_novelty_join(join_parent_novelty_from)
        report_level = df[
            ["parent_id", "parent_smiles", "parent_max_sim_to_train", "parent_similarity_bin"]
        ].drop_duplicates()
        if join_df["parent_id"].notna().any():
            df = df.drop(columns=["parent_max_sim_to_train", "parent_similarity_bin"]).merge(
                join_df,
                on="parent_id",
                how="left",
                suffixes=("", "_joined"),
            )
        else:
            df = df.drop(columns=["parent_max_sim_to_train", "parent_similarity_bin"]).merge(
                join_df,
                on="parent_smiles",
                how="left",
                suffixes=("", "_joined"),
            )
        df["parent_max_sim_to_train"] = pd.to_numeric(
            df["parent_max_sim_to_train"], errors="coerce"
        )
        df["parent_similarity_bin"] = df.apply(
            lambda r: _normalize_similarity_bin(
                r["parent_max_sim_to_train"], r["parent_similarity_bin"]
            ),
            axis=1,
        )
        if df["parent_similarity_bin"].isna().all():
            raise ValueError(
                f"Join file {join_parent_novelty_from} did not provide usable parent novelty values."
            )
        warnings.append(
            f"Parent novelty joined from {join_parent_novelty_from} and used in preference "
            "to any report-level novelty fields."
        )

    df["parent_similarity_bin"] = df["parent_similarity_bin"].apply(
        lambda value: _normalize_similarity_bin(None, value)
    )
    df["source_report"] = df["source_report"].astype(str)
    df["source_file"] = df["source_file"].astype(str)
    df = df.sort_values(
        ["parent_id", "candidate_source", "candidate_rank", "candidate_smiles"]
    ).reset_index(drop=True)

    manifest_df = pd.DataFrame(report_manifest_rows).sort_values(
        ["parent_id", "report_json"]
    )

    info = {
        "dataset": dataset,
        "report_count": len(report_paths),
        "prediction_files_used": [str(path) for path in context.prediction_files],
        "warnings": warnings,
        "notes": context.notes + [SIMILARITY_FIELD_NOTE],
        "parent_panel_file": str(parent_panel_file) if parent_panel_file else None,
        "max_parents": int(max_parents) if max_parents is not None else None,
    }
    return df, manifest_df, info


def apply_analysis_filters(
    df: pd.DataFrame,
    *,
    include_tier4: bool,
    include_dataset_analogues: bool,
    include_relaxed: bool,
    split_type: Optional[str],
    scaffold_preserved_only: bool,
    min_similarity_to_parent: Optional[float],
    top_n_per_parent: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    filtered = df.copy()
    counts = {
        "loaded_candidates": int(len(filtered)),
        "excluded_dataset_analogues": 0,
        "excluded_tier4": 0,
        "excluded_relaxed": 0,
        "excluded_split_type": 0,
        "excluded_similarity_to_parent": 0,
        "excluded_non_scaffold_preserved": 0,
        "excluded_by_top_n": 0,
        "remaining_candidates": 0,
    }

    if not include_dataset_analogues:
        mask = filtered["candidate_source"] == "dataset_analogue"
        counts["excluded_dataset_analogues"] = int(mask.sum())
        filtered = filtered[~mask].copy()

    if not include_tier4:
        mask = filtered["tier_num"] == 4
        counts["excluded_tier4"] = int(mask.sum())
        filtered = filtered[~mask].copy()

    if not include_relaxed:
        mask = filtered["is_relaxed_candidate"].fillna(False)
        counts["excluded_relaxed"] = int(mask.sum())
        filtered = filtered[~mask].copy()

    if split_type:
        mask = filtered["split_type"].astype(str).fillna("") != str(split_type)
        counts["excluded_split_type"] = int(mask.sum())
        filtered = filtered[~mask].copy()

    if min_similarity_to_parent is not None:
        mask = filtered["similarity_to_parent"].astype(float) < float(
            min_similarity_to_parent
        )
        counts["excluded_similarity_to_parent"] = int(mask.sum())
        filtered = filtered[~mask].copy()

    if scaffold_preserved_only:
        mask = ~filtered["scaffold_preserved"].fillna(False)
        counts["excluded_non_scaffold_preserved"] = int(mask.sum())
        filtered = filtered[~mask].copy()

    if top_n_per_parent > 0 and not filtered.empty:
        before = len(filtered)
        filtered = filtered.sort_values(
            ["parent_id", "candidate_rank", "candidate_smiles"]
        )
        filtered["_rank_within_parent"] = filtered.groupby("parent_id").cumcount() + 1
        filtered = filtered[filtered["_rank_within_parent"] <= int(top_n_per_parent)].copy()
        filtered = filtered.drop(columns="_rank_within_parent")
        counts["excluded_by_top_n"] = int(before - len(filtered))

    counts["remaining_candidates"] = int(len(filtered))
    return filtered.reset_index(drop=True), counts


def pick_best_per_parent(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    ranked = df.copy()
    ranked = ranked.sort_values(
        [
            "parent_id",
            "total_concordance_score",
            "literature_concordant_overall",
            "medicinal_locality_score",
            "delta_prob",
            "candidate_prob",
            "similarity_to_parent",
            "candidate_rank",
            "candidate_smiles",
        ],
        ascending=[True, False, False, False, False, True, False, True, True],
    )
    best = ranked.groupby("parent_id", as_index=False).head(1).reset_index(drop=True)
    return best


def _summary_template() -> pd.DataFrame:
    return pd.DataFrame({"parent_similarity_bin": SIMILARITY_BIN_ORDER})


def summarize_by_similarity_bin(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return _summary_template()

    def _agg(group: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "n_parents": int(group["parent_id"].nunique()),
                "n_candidates": int(len(group)),
                "fraction_tier1": float((group["tier_num"] == 1).mean()),
                "fraction_scaffold_preserved": float(group["scaffold_preserved"].mean()),
                "mean_concordance_score": float(group["total_concordance_score"].mean()),
                "median_concordance_score": float(group["total_concordance_score"].median()),
                "fraction_lowering_logp": float(group["rule_lower_logp"].mean()),
                "fraction_reducing_aromaticity": float(
                    group["rule_reduce_aromatic_rings"].mean()
                ),
                "fraction_reducing_rotatable_bonds": float(
                    group["rule_reduce_rotatable_bonds"].mean()
                ),
                "fraction_reducing_cationic_burden_proxy": float(
                    group["rule_reduce_cationic_burden_proxy"].mean()
                ),
                "fraction_literature_concordant_overall": float(
                    group["literature_concordant_overall"].mean()
                ),
            }
        )

    summary = (
        df.groupby("parent_similarity_bin", observed=False)
        .apply(_agg)
        .reset_index()
    )
    summary["parent_similarity_bin"] = pd.Categorical(
        summary["parent_similarity_bin"], categories=SIMILARITY_BIN_ORDER, ordered=True
    )
    return summary.sort_values("parent_similarity_bin").reset_index(drop=True)


def summarize_by_tier(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tier_num", "tier_label", "n_parents", "n_candidates"])

    def _agg(group: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "tier_label": group["tier_label"].iloc[0],
                "n_parents": int(group["parent_id"].nunique()),
                "n_candidates": int(len(group)),
                "fraction_scaffold_preserved": float(group["scaffold_preserved"].mean()),
                "mean_concordance_score": float(group["total_concordance_score"].mean()),
                "median_concordance_score": float(group["total_concordance_score"].median()),
                "fraction_literature_concordant_overall": float(
                    group["literature_concordant_overall"].mean()
                ),
            }
        )

    summary = df.groupby("tier_num", observed=False).apply(_agg).reset_index()
    return summary.sort_values("tier_num").reset_index(drop=True)


def summarize_by_split(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or df["split_type"].isna().all():
        return pd.DataFrame()

    def _agg(group: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "n_parents": int(group["parent_id"].nunique()),
                "n_candidates": int(len(group)),
                "fraction_scaffold_preserved": float(group["scaffold_preserved"].mean()),
                "mean_concordance_score": float(group["total_concordance_score"].mean()),
                "fraction_literature_concordant_overall": float(
                    group["literature_concordant_overall"].mean()
                ),
            }
        )

    summary = df.groupby("split_type", observed=False).apply(_agg).reset_index()
    return summary.sort_values("split_type").reset_index(drop=True)


def write_rule_snapshot(path: Path) -> None:
    payload = {
        "version": "v1",
        "note": (
            "Simple literature-concordant audit rules for anti-hERG directionality. "
            "These are heuristic, descriptive rules for post hoc auditing only."
        ),
        "core_rules": [{"name": name, "label": label} for name, label in CORE_RULES],
        "auxiliary_rules": [
            {"name": name, "label": label}
            for name, label in ALL_RULES
            if (name, label) not in CORE_RULES
        ],
        "medicinal_locality_components": [
            "scaffold_preserved",
            "similarity_to_parent >= 0.5",
            "abs(delta_heavy_atom_count) <= 2",
        ],
        "similarity_field_note": SIMILARITY_FIELD_NOTE,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_input_manifest(
    path: Path,
    context: RunContext,
    info: dict[str, Any],
    join_parent_novelty_from: Optional[Path],
) -> None:
    payload = {
        "input_root": str(context.input_root),
        "run_dir": str(context.run_dir),
        "lead_reports_dir": str(context.lead_reports_dir),
        "metadata_path": str(context.metadata_path) if context.metadata_path else None,
        "prediction_files": [str(p) for p in context.prediction_files],
        "dataset": info.get("dataset"),
        "report_count": info.get("report_count"),
        "warnings": info.get("warnings", []),
        "notes": context.notes + info.get("notes", []),
        "join_parent_novelty_from": (
            str(join_parent_novelty_from.resolve()) if join_parent_novelty_from else None
        ),
        "parent_panel_file": info.get("parent_panel_file"),
        "max_parents": info.get("max_parents"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_run_parameters(path: Path, params: dict[str, Any]) -> None:
    path.write_text(json.dumps(params, indent=2), encoding="utf-8")


def write_filter_counts(path: Path, counts: dict[str, int]) -> None:
    path.write_text(json.dumps(counts, indent=2), encoding="utf-8")


def write_summary_text(
    path: Path,
    *,
    candidate_df: pd.DataFrame,
    analysis_df: pd.DataFrame,
    best_df: pd.DataFrame,
    similarity_summary: pd.DataFrame,
    tier_summary: pd.DataFrame,
    include_tier4: bool,
    best_per_parent_only: bool,
) -> None:
    lines: list[str] = []
    lines.append("Lead Optimization Literature-Concordant Counterfactual Audit")
    lines.append("")
    lines.append(f"Parents analyzed: {analysis_df['parent_id'].nunique()}")
    lines.append(f"Candidates in candidate-level table: {len(candidate_df)}")
    lines.append(f"Candidates in summary cohort: {len(analysis_df)}")
    lines.append(
        "Tiers included: "
        + ("Tier 1-4 (including diagnostic Tier 4)" if include_tier4 else "Tier 1-3 only")
    )
    lines.append(
        "Summary cohort mode: "
        + ("best candidate per parent" if best_per_parent_only else "all retained candidates")
    )
    lines.append("")

    if not analysis_df.empty:
        scaffold_rate = float(analysis_df["scaffold_preserved"].mean())
        locality_rate = float(analysis_df["medicinal_locality_flag"].mean())
        concordance_rate = float(analysis_df["literature_concordant_overall"].mean())
        lines.append(
            f"Scaffold-preserved candidates in summary cohort: {scaffold_rate:.1%} "
            + (
                "(common)."
                if scaffold_rate >= 0.67
                else "(rare)." if scaffold_rate < 0.33 else "(mixed frequency)."
            )
        )
        lines.append(
            f"Medicinal locality flag rate: {locality_rate:.1%}. "
            f"Overall literature-concordant rate: {concordance_rate:.1%}."
        )

        if not similarity_summary.empty:
            similarity_summary = similarity_summary.dropna(
                subset=["mean_concordance_score"]
            ).copy()
            if not similarity_summary.empty:
                novel = similarity_summary[
                    similarity_summary["parent_similarity_bin"] == "<0.3"
                ]
                familiar = similarity_summary[
                    similarity_summary["parent_similarity_bin"] == ">0.7"
                ]
                if not novel.empty and not familiar.empty:
                    novel_score = float(novel["mean_concordance_score"].iloc[0])
                    familiar_score = float(familiar["mean_concordance_score"].iloc[0])
                    if novel_score < familiar_score:
                        lines.append(
                            "Mean concordance score was lower in the most novel parent bin "
                            f"(<0.3: {novel_score:.2f}) than in the most familiar bin "
                            f"(>0.7: {familiar_score:.2f})."
                        )
                    elif novel_score > familiar_score:
                        lines.append(
                            "Mean concordance score was not worse in the most novel parent bin; "
                            f"<0.3 averaged {novel_score:.2f} versus {familiar_score:.2f} in >0.7."
                        )
                    else:
                        lines.append(
                            "Mean concordance score was identical in the most novel and most familiar bins."
                        )

        rule_hits = {
            "lower logP": float(analysis_df["rule_lower_logp"].mean()),
            "increase TPSA": float(analysis_df["rule_increase_tpsa"].mean()),
            "reduce aromaticity": float(analysis_df["rule_reduce_aromatic_rings"].mean()),
            "reduce rotatable bonds": float(
                analysis_df["rule_reduce_rotatable_bonds"].mean()
            ),
            "reduce cationic burden proxy": float(
                analysis_df["rule_reduce_cationic_burden_proxy"].mean()
            ),
        }
        top_rule = max(rule_hits.items(), key=lambda item: item[1])
        bottom_rule = min(rule_hits.items(), key=lambda item: item[1])
        lines.append(
            f"Most common literature-concordant direction: {top_rule[0]} ({top_rule[1]:.1%})."
        )
        lines.append(
            f"Least common literature-concordant direction: {bottom_rule[0]} ({bottom_rule[1]:.1%})."
        )

        if not tier_summary.empty:
            tier_fragments = [
                f"{row['tier_label']}: n={int(row['n_candidates'])}, concordant={float(row['fraction_literature_concordant_overall']):.1%}"
                for _, row in tier_summary.iterrows()
            ]
            lines.append("Tier summary: " + "; ".join(tier_fragments) + ".")

    lines.append("")
    lines.append("Assumptions and boundaries:")
    lines.append(f"- {SIMILARITY_FIELD_NOTE}")
    lines.append(
        "- Concordance rules are simple heuristic literature-direction checks, not causal or experimental proof."
    )
    lines.append(
        "- Parent novelty refers to the parent molecule's train-test similarity regime when available."
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_tables(
    tables_dir: Path,
    *,
    candidate_df: pd.DataFrame,
    best_df: pd.DataFrame,
    similarity_summary: pd.DataFrame,
    tier_summary: pd.DataFrame,
    split_summary: pd.DataFrame,
) -> tuple[Path, Path, Path, Path, Optional[Path]]:
    candidate_path = tables_dir / "counterfactual_literature_audit_candidates.csv"
    best_path = tables_dir / "counterfactual_literature_audit_best_per_parent.csv"
    similarity_path = tables_dir / "concordance_by_similarity_bin.csv"
    tier_path = tables_dir / "concordance_by_tier.csv"
    split_path = tables_dir / "concordance_by_split.csv"

    candidate_df.to_csv(candidate_path, index=False)
    best_df.to_csv(best_path, index=False)
    similarity_summary.to_csv(similarity_path, index=False)
    tier_summary.to_csv(tier_path, index=False)

    saved_split_path: Optional[Path] = None
    if not split_summary.empty:
        split_summary.to_csv(split_path, index=False)
        saved_split_path = split_path

    return candidate_path, best_path, similarity_path, tier_path, saved_split_path


def _ordered_similarity_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["parent_similarity_bin"] = pd.Categorical(
        out["parent_similarity_bin"], categories=SIMILARITY_BIN_ORDER, ordered=True
    )
    return out.sort_values("parent_similarity_bin")


def plot_concordance_by_similarity_bin(df: pd.DataFrame, output_path: Path) -> None:
    matplotlib.use("Agg")
    ordered = _ordered_similarity_frame(df)
    fig, ax = plt.subplots(figsize=(6.2, 4.0))

    data = [
        ordered.loc[ordered["parent_similarity_bin"] == sim_bin, "total_concordance_score"].to_list()
        for sim_bin in SIMILARITY_BIN_ORDER
    ]
    valid_positions = [i + 1 for i, values in enumerate(data) if values]
    valid_data = [values for values in data if values]
    if valid_data:
        bp = ax.boxplot(
            valid_data,
            positions=valid_positions,
            widths=0.55,
            patch_artist=True,
            medianprops={"color": "black", "linewidth": 1.2},
        )
        for patch, sim_bin in zip(bp["boxes"], [SIMILARITY_BIN_ORDER[i - 1] for i in valid_positions]):
            patch.set_facecolor(SIMILARITY_BIN_COLORS[sim_bin])
            patch.set_alpha(0.55)
        for pos, values, sim_bin in zip(valid_positions, valid_data, [SIMILARITY_BIN_ORDER[i - 1] for i in valid_positions]):
            x = np.full(len(values), pos, dtype=float)
            jitter = np.linspace(-0.08, 0.08, len(values)) if len(values) > 1 else np.array([0.0])
            ax.scatter(
                x + jitter,
                values,
                color=SIMILARITY_BIN_COLORS[sim_bin],
                edgecolor="white",
                linewidth=0.5,
                s=28,
                zorder=3,
            )

    ax.set_xticks(range(1, len(SIMILARITY_BIN_ORDER) + 1))
    ax.set_xticklabels(SIMILARITY_BIN_ORDER)
    ax.set_xlabel("Parent novelty bin")
    ax.set_ylabel("Total concordance score")
    ax.set_title("Literature-concordance score by parent novelty bin")
    ax.set_ylim(-0.25, len(CORE_RULES) + 0.5)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_rule_hit_rates_by_similarity_bin(df: pd.DataFrame, output_path: Path) -> None:
    matplotlib.use("Agg")
    if df.empty:
        return

    rule_labels = [label for _, label in CORE_RULES]
    matrix = []
    for rule_name, _ in CORE_RULES:
        values = []
        for sim_bin in SIMILARITY_BIN_ORDER:
            sub = df[df["parent_similarity_bin"] == sim_bin]
            values.append(float(sub[rule_name].mean()) if not sub.empty else np.nan)
        matrix.append(values)

    arr = np.array(matrix, dtype=float)
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    im = ax.imshow(arr, cmap="OrRd", aspect="auto", vmin=0.0, vmax=1.0)
    ax.set_xticks(range(len(SIMILARITY_BIN_ORDER)))
    ax.set_xticklabels(SIMILARITY_BIN_ORDER)
    ax.set_yticks(range(len(rule_labels)))
    ax.set_yticklabels(rule_labels)
    ax.set_xlabel("Parent novelty bin")
    ax.set_title("Rule hit rates by novelty bin")

    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            value = arr[i, j]
            label = "NA" if np.isnan(value) else f"{100 * value:.0f}%"
            ax.text(
                j,
                i,
                label,
                ha="center",
                va="center",
                color="black",
                fontsize=8,
            )

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Fraction concordant")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_scaffold_preservation_by_similarity_bin(df: pd.DataFrame, output_path: Path) -> None:
    matplotlib.use("Agg")
    ordered = _ordered_similarity_frame(df)
    summary = (
        ordered.groupby("parent_similarity_bin", observed=False)["scaffold_preserved"]
        .mean()
        .reindex(SIMILARITY_BIN_ORDER)
    )

    fig, ax = plt.subplots(figsize=(5.8, 3.8))
    bars = ax.bar(
        range(len(SIMILARITY_BIN_ORDER)),
        summary.fillna(0.0).to_numpy(),
        color=[SIMILARITY_BIN_COLORS[sim_bin] for sim_bin in SIMILARITY_BIN_ORDER],
        alpha=0.8,
    )
    for bar, value in zip(bars, summary.to_numpy()):
        if not np.isnan(value):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.02,
                f"{100 * value:.0f}%",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    ax.set_xticks(range(len(SIMILARITY_BIN_ORDER)))
    ax.set_xticklabels(SIMILARITY_BIN_ORDER)
    ax.set_ylim(0, 1.1)
    ax.set_xlabel("Parent novelty bin")
    ax.set_ylabel("Scaffold preservation rate")
    ax.set_title("Scaffold preservation by novelty bin")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_delta_prob_vs_concordance(df: pd.DataFrame, output_path: Path) -> None:
    matplotlib.use("Agg")
    fig, ax = plt.subplots(figsize=(6.0, 4.2))

    for sim_bin in SIMILARITY_BIN_ORDER:
        sub = df[df["parent_similarity_bin"] == sim_bin]
        if sub.empty:
            continue
        ax.scatter(
            sub["delta_prob"],
            sub["total_concordance_score"],
            label=sim_bin,
            color=SIMILARITY_BIN_COLORS[sim_bin],
            alpha=0.8,
            edgecolor="white",
            linewidth=0.5,
            s=38,
        )

    ax.set_xlabel("Δ predicted hERG risk (parent - candidate)")
    ax.set_ylabel("Total concordance score")
    ax.set_title("Risk reduction vs literature concordance")
    ax.grid(alpha=0.2)
    ax.legend(title="Parent novelty bin", fontsize=8, title_fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def default_candidate_column_order(df: pd.DataFrame) -> list[str]:
    preferred = [
        "parent_id",
        "parent_smiles",
        "candidate_smiles",
        "candidate_source",
        "dataset",
        "split_type",
        "split_seed",
        "run_seed",
        "parent_similarity_bin",
        "parent_max_sim_to_train",
        "tier_num",
        "tier_label",
        "parent_prob",
        "candidate_prob",
        "delta_prob",
        "similarity_to_parent",
        "scaffold_preserved",
        "medicinal_locality_score",
        "medicinal_locality_flag",
        "total_concordance_score",
        "normalized_concordance_fraction",
        "literature_concordant_overall",
        "rule_lower_logp",
        "rule_increase_tpsa",
        "rule_reduce_aromatic_rings",
        "rule_reduce_rotatable_bonds",
        "rule_reduce_cationic_burden_proxy",
        "rule_increase_fraction_csp3",
        "rule_reduce_formal_charge",
        "rule_reduce_tertiary_amine_like",
        "delta_mol_logp",
        "delta_tpsa",
        "delta_fraction_csp3",
        "delta_aromatic_ring_count",
        "delta_total_ring_count",
        "delta_rotatable_bonds",
        "delta_formal_charge",
        "delta_heavy_atom_count",
        "delta_heteroatom_count",
        "delta_hbd_count",
        "delta_hba_count",
        "delta_tertiary_amine_like_count",
        "delta_basic_amine_proxy_count",
        "delta_formal_positive_n_count",
        "delta_cationic_burden_proxy",
        "relaxation",
        "is_relaxed_candidate",
        "dataset_fallback_used",
        "candidate_rank",
        "source_file",
        "source_report",
        "source_run_dir",
        "similarity_field_note",
    ]
    remainder = [col for col in df.columns if col not in preferred]
    return [col for col in preferred if col in df.columns] + remainder


def build_audit_outputs(
    *,
    input_root: Path,
    output_root: Path,
    dataset: Optional[str],
    split_type: Optional[str],
    include_tier4: bool,
    best_per_parent_only: bool,
    scaffold_preserved_only: bool,
    include_relaxed: bool,
    include_dataset_analogues: bool,
    min_similarity_to_parent: Optional[float],
    top_n_per_parent: int,
    join_parent_novelty_from: Optional[Path],
    parent_panel_file: Optional[Path],
    max_parents: Optional[int],
    workers: int,
    chunk_size: int,
    resume: bool,
    verbose: bool = False,
) -> tuple[AuditArtifacts, dict[str, Any]]:
    paths = ensure_output_tree(output_root)
    log_path = paths["logs"] / "audit.log"
    logger = setup_audit_logger(log_path, verbose=verbose)

    candidate_path = paths["tables"] / "counterfactual_literature_audit_candidates.csv"
    run_parameters_path = paths["inputs_snapshot"] / "run_parameters.json"
    requested_params = {
        "dataset": dataset,
        "split_type": split_type,
        "include_tier4": include_tier4,
        "best_per_parent_only": best_per_parent_only,
        "scaffold_preserved_only": scaffold_preserved_only,
        "include_relaxed": include_relaxed,
        "include_dataset_analogues": include_dataset_analogues,
        "min_similarity_to_parent": min_similarity_to_parent,
        "top_n_per_parent": top_n_per_parent,
        "join_parent_novelty_from": (
            str(join_parent_novelty_from.resolve()) if join_parent_novelty_from else None
        ),
        "parent_panel_file": str(parent_panel_file.resolve()) if parent_panel_file else None,
        "max_parents": max_parents,
        "workers": int(workers),
        "chunk_size": int(chunk_size),
    }

    context = resolve_run_context(input_root)
    logger.info("Input run directory: %s", context.run_dir)
    logger.info("Lead reports directory: %s", context.lead_reports_dir)
    if context.metadata_path:
        logger.info("Run metadata: %s", context.metadata_path)
    for note in context.notes:
        logger.info("Input note: %s", note)

    candidates_raw, report_manifest_df, info = load_candidate_pairs(
        context=context,
        dataset_override=dataset,
        join_parent_novelty_from=join_parent_novelty_from,
        parent_panel_file=parent_panel_file,
        max_parents=max_parents,
    )
    logger.info("Dataset label used: %s", info["dataset"])
    logger.info("Report files loaded: %d", info["report_count"])
    logger.info("Raw candidate rows parsed: %d", len(candidates_raw))
    for prediction_path in info.get("prediction_files_used", []):
        logger.info("Prediction context file: %s", prediction_path)
    if join_parent_novelty_from:
        logger.info("Parent novelty join file: %s", join_parent_novelty_from)
    for warning in info.get("warnings", []):
        logger.warning("%s", warning)

    filter_counts_path = paths["logs"] / "filter_counts.json"
    if resume and candidate_path.exists():
        if run_parameters_path.exists():
            saved_params = json.loads(run_parameters_path.read_text(encoding="utf-8"))
            mismatch = {
                key: {"requested": requested_params.get(key), "saved": saved_params.get(key)}
                for key in requested_params
                if requested_params.get(key) != saved_params.get(key)
            }
            if mismatch:
                raise ValueError(
                    "Resume requested but run parameters do not match the existing output root: "
                    + json.dumps(mismatch, indent=2)
                )
        logger.info("Resume mode: reusing existing candidate table at %s", candidate_path)
        filtered_df = pd.read_csv(candidate_path)
        if filter_counts_path.exists():
            filter_counts = json.loads(filter_counts_path.read_text(encoding="utf-8"))
        else:
            filter_counts = {"remaining_candidates": int(len(filtered_df))}
    else:
        candidates_scored = compute_concordance_fields(
            candidates_raw,
            workers=workers,
            chunk_size=chunk_size,
            logger=logger,
        )
        filtered_df, filter_counts = apply_analysis_filters(
            candidates_scored,
            include_tier4=include_tier4,
            include_dataset_analogues=include_dataset_analogues,
            include_relaxed=include_relaxed,
            split_type=split_type,
            scaffold_preserved_only=scaffold_preserved_only,
            min_similarity_to_parent=min_similarity_to_parent,
            top_n_per_parent=top_n_per_parent,
        )
    best_df = pick_best_per_parent(filtered_df)
    analysis_df = best_df if best_per_parent_only else filtered_df

    if analysis_df.empty:
        raise ValueError(
            "All candidates were excluded by the selected analysis filters; no audit cohort remains."
        )

    logger.info("Candidates after analysis filters: %d", len(filtered_df))
    logger.info("Best-per-parent rows: %d", len(best_df))
    logger.info(
        "Summary cohort rows: %d (%s)",
        len(analysis_df),
        "best-per-parent" if best_per_parent_only else "all retained candidates",
    )
    for key, value in filter_counts.items():
        logger.info("Filter count %s=%s", key, value)

    similarity_summary = summarize_by_similarity_bin(analysis_df)
    tier_summary = summarize_by_tier(analysis_df)
    split_summary = summarize_by_split(analysis_df)

    candidate_df = filtered_df.copy()
    best_df = best_df.copy()
    analysis_df = analysis_df.copy()

    candidate_df = candidate_df[default_candidate_column_order(candidate_df)]
    best_df = best_df[default_candidate_column_order(best_df)]

    candidate_path, best_path, similarity_path, tier_path, split_path = save_tables(
        paths["tables"],
        candidate_df=candidate_df,
        best_df=best_df,
        similarity_summary=similarity_summary,
        tier_summary=tier_summary,
        split_summary=split_summary,
    )

    concordance_fig = paths["figures"] / "concordance_by_similarity_bin.png"
    rule_hits_fig = paths["figures"] / "rule_hit_rates_by_similarity_bin.png"
    scaffold_fig = paths["figures"] / "scaffold_preservation_by_similarity_bin.png"
    scatter_fig = paths["figures"] / "delta_prob_vs_concordance.png"

    plot_concordance_by_similarity_bin(analysis_df, concordance_fig)
    plot_rule_hit_rates_by_similarity_bin(analysis_df, rule_hits_fig)
    plot_scaffold_preservation_by_similarity_bin(analysis_df, scaffold_fig)
    plot_delta_prob_vs_concordance(analysis_df, scatter_fig)

    summary_path = paths["summaries"] / "summary.txt"
    write_summary_text(
        summary_path,
        candidate_df=candidate_df,
        analysis_df=analysis_df,
        best_df=best_df,
        similarity_summary=similarity_summary,
        tier_summary=tier_summary,
        include_tier4=include_tier4,
        best_per_parent_only=best_per_parent_only,
    )

    manifest_path = paths["inputs_snapshot"] / "input_manifest.json"
    report_manifest_path = paths["inputs_snapshot"] / "report_file_manifest.csv"
    rule_snapshot_path = paths["inputs_snapshot"] / "rule_set.json"

    write_input_manifest(manifest_path, context, info, join_parent_novelty_from)
    report_manifest_df.to_csv(report_manifest_path, index=False)
    write_rule_snapshot(rule_snapshot_path)
    write_run_parameters(run_parameters_path, requested_params)
    write_filter_counts(filter_counts_path, filter_counts)

    artifacts = AuditArtifacts(
        candidate_table=candidate_path,
        best_table=best_path,
        summary_by_similarity=similarity_path,
        summary_by_tier=tier_path,
        summary_by_split=split_path,
        summary_txt=summary_path,
        concordance_by_similarity_fig=concordance_fig,
        rule_hit_rates_fig=rule_hits_fig,
        scaffold_preservation_fig=scaffold_fig,
        delta_prob_vs_concordance_fig=scatter_fig,
        input_manifest=manifest_path,
        report_manifest=report_manifest_path,
        rule_snapshot=rule_snapshot_path,
        run_parameters=run_parameters_path,
        filter_counts=filter_counts_path,
        log_path=log_path,
    )

    summary = {
        "dataset": info["dataset"],
        "reports_loaded": info["report_count"],
        "raw_candidates": len(candidates_raw),
        "filtered_candidates": len(filtered_df),
        "best_per_parent": len(best_df),
        "summary_candidates": len(analysis_df),
        "summary_parents": int(analysis_df["parent_id"].nunique()),
        "warnings": info.get("warnings", []),
        "filter_counts": filter_counts,
        "artifacts": asdict(artifacts),
    }
    return artifacts, summary
