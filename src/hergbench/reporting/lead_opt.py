
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import Crippen, Draw, QED
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

from hergbench.features.fingerprints import FingerprintConfig, mol_to_ecfp_bits
from hergbench.reporting.sascorer import calculate_sa_score


@dataclass(frozen=True)
class CFConstraints:
    # Backward-compatible default min_tanimoto; tier-specific overrides preferred.
    min_tanimoto: float = 0.7
    min_tanimoto_flip: Optional[float] = None
    min_tanimoto_improve: Optional[float] = None
    sa_max: float = 4.5
    logp_delta_max: float = 1.5
    qed_min: float = 0.0  # optional; set >0 to enforce
    pains: bool = True


def _make_filter_catalog() -> FilterCatalog:
    params = FilterCatalogParams()
    # PAINS A/B/C
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_A)
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_B)
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS_C)
    # "known reactive groups" proxies
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.BRENK)
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.NIH)
    return FilterCatalog(params)


_FILTER_CATALOG = None


def has_structural_alerts(mol: Chem.Mol) -> bool:
    global _FILTER_CATALOG
    if _FILTER_CATALOG is None:
        _FILTER_CATALOG = _make_filter_catalog()
    entry = _FILTER_CATALOG.GetFirstMatch(mol)
    return entry is not None


def mol_props(mol: Chem.Mol, fpscores_path: Optional[Path] = None, cache_dir: Optional[Path] = None) -> Dict[str, float]:
    return {
        "logp": float(Crippen.MolLogP(mol)),
        "qed": float(QED.qed(mol)),
        "sascore": float(calculate_sa_score(mol, fpscores_path=fpscores_path, cache_dir=cache_dir)),
    }


def depict_smiles(smiles: str, out_path: Path, size: Tuple[int, int] = (350, 250)) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return
    img = Draw.MolToImage(mol, size=size)
    img.save(str(out_path))


def _tanimoto(smi_a: str, smi_b: str, fp_cfg: FingerprintConfig) -> float:
    ma = Chem.MolFromSmiles(smi_a)
    mb = Chem.MolFromSmiles(smi_b)
    if ma is None or mb is None:
        return 0.0
    fa = mol_to_ecfp_bits(ma, fp_cfg)
    fb = mol_to_ecfp_bits(mb, fp_cfg)
    return float(DataStructs.TanimotoSimilarity(fa, fb))


def _dedupe_by_smiles(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for r in rows:
        s = r["smiles"]
        if s in seen:
            continue
        seen.add(s)
        out.append(r)
    return out


def dataset_analogues(
    base_smiles: str,
    base_fp,
    base_p: float,
    dataset_smiles: List[str],
    dataset_fps,
    dataset_probs: List[float],
    fp_cfg: FingerprintConfig,
    top_k: int = 5,
    min_sim: float = 0.3,
    fpscores_cache_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return dataset-derived analogues (lowest predicted risk, similar to base).

    If no molecules meet min_sim, fall back to top_k by similarity regardless of p.
    """
    entries: List[Dict[str, Any]] = []
    for smi, fp, p in zip(dataset_smiles, dataset_fps, dataset_probs):
        if smi == base_smiles:
            continue
        sim = float(DataStructs.TanimotoSimilarity(base_fp, fp))
        try:
            mol = Chem.MolFromSmiles(smi)
            Chem.SanitizeMol(mol)
        except Exception:
            continue
        props = mol_props(mol, cache_dir=fpscores_cache_dir)
        alert = has_structural_alerts(mol)
        entries.append(
            {
                "smiles": smi,
                "similarity": sim,
                "p": float(p),
                "delta_p": base_p - float(p),
                "logp": props["logp"],
                "qed": props["qed"],
                "sascore": props["sascore"],
                "alert": alert,
                "tier": "dataset_analogue",
                "tier_label": "Dataset analogue",
                "relaxation": "none",
                "relaxation_desc": "dataset fallback",
            }
        )

    # Primary filter: enforce similarity >= min_sim
    primary = [e for e in entries if e["similarity"] >= min_sim]
    pool = primary if primary else entries
    pool.sort(key=lambda r: (r["p"], -r["similarity"], r["smiles"]))
    return pool[:top_k]


def generate_counterfactuals_exmol(
    base_smiles: str,
    model_class: Callable[[str], int],
    model_prob: Callable[[str], float],
    fp_cfg: FingerprintConfig,
    constraints: CFConstraints,
    safe_prob_max: float = 0.3,
    exmol_preset: str = "medium",
    nmols: int = 5,
    exmol_n_samples: int = 1800,
    search_nmols: Optional[int] = None,
    delta_min: float = 0.10,
    delta_min_tier3: float = 0.05,
    relaxation_plan: Optional[List[Dict[str, Any]]] = None,
    fpscores_cache_dir: Optional[Path] = None,
    logger: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generate and filter counterfactuals around base_smiles using ExMol + medicinal-chemist filters.

    Returns a ranked list of dicts with smiles, similarity, p, delta_p, logp, qed, sascore, alert.
    Tiered filtering is deterministic and defers all pruning until after a full ExMol sample is drawn.
    """
    import exmol  # type: ignore

    p_base = float(model_prob(base_smiles))
    mol_base = Chem.MolFromSmiles(base_smiles)
    if mol_base is None:
        return [], {"error": "invalid_base_smiles", "sampled": 0, "final_tier": "none", "final_count": 0, "scarcity": True}

    # Enforce a large ExMol budget (bounded) to give rare counterfactuals a chance under strict medicinal filters.
    sample_budget = int(search_nmols if search_nmols is not None else exmol_n_samples)
    sample_budget = min(max(sample_budget, 1500), 2000)

    base_props = mol_props(mol_base, cache_dir=fpscores_cache_dir)
    fp_base = mol_to_ecfp_bits(mol_base, fp_cfg)

    # Tier specs encode the success definition; always evaluated on the full sampled pool.
    tier_specs = [
        {
            "name": "flip",
            "label": "Tier 1 — Flip",
            "default_min_tanimoto": 0.5,
            "prob_max": safe_prob_max,  # Tier 1 only
            "require_delta": False,
            "delta_min": 0.0,
            "min_key": "flip",
        },
        {
            "name": "risk_reduction",
            "label": "Tier 2 — Risk reduction",
            "default_min_tanimoto": 0.7,
            "prob_max": None,
            "require_delta": True,
            "delta_min": max(delta_min, 0.10),
            "min_key": "improve",
        },
        {
            "name": "weak_reduction",
            "label": "Tier 3 — Weak improvement",
            "default_min_tanimoto": 0.7,
            "prob_max": None,
            "require_delta": True,
            "delta_min": max(delta_min_tier3, 0.05),
            "min_key": "improve",
        },
    ]

    # Relaxation steps are optional and must alter only one constraint each for auditability.
    validated_relaxations: List[Dict[str, Any]] = []
    for step in relaxation_plan or []:
        updates = dict(step.get("updates", {}))
        if len(updates) > 1:
            raise ValueError("Each relaxation may adjust only one constraint.")
        validated_relaxations.append(
            {
                "name": str(step.get("name", "unnamed_relaxation")),
                "description": str(step.get("description", "")),
                "updates": updates,
            }
        )
    relaxation_steps: List[Dict[str, Any]] = [
        {"name": "relax_flip_0.4", "description": "lower flip min_tanimoto to 0.4", "updates": {"min_tanimoto_flip": 0.4}},
        {"name": "relax_flip_0.3", "description": "lower flip min_tanimoto to 0.3", "updates": {"min_tanimoto_flip": 0.3}},
        {"name": "relax_improve_0.6", "description": "lower improve min_tanimoto to 0.6", "updates": {"min_tanimoto_improve": 0.6}},
        {"name": "relax_improve_0.5", "description": "lower improve min_tanimoto to 0.5", "updates": {"min_tanimoto_improve": 0.5}},
        {"name": "relax_sa_5.5", "description": "raise SA max to 5.5", "updates": {"sa_max": 5.5}},
    ]
    relaxation_steps.extend(validated_relaxations)

    # ExMol expects a classifier f(smiles)->0/1 for counterfactual search.
    space = exmol.sample_space(
        base_smiles,
        model_class,
        batched=False,
        preset=exmol_preset,
        use_selfies=False,
        quiet=True,
        method_kwargs=None,  # cf_explain handles sampling budget; sample_space cannot accept nmols for some presets
    )
    if isinstance(space, tuple):
        space = space[0]

    # Counterfactual search (large pool; no early filtering).
    cfs = exmol.cf_explain(space, nmols=sample_budget, filter_nondrug=False)
    if isinstance(cfs, tuple):
        cfs = cfs[0]

    cfs = cfs or []
    sample_count = len(cfs)

    def _apply_relaxation(base_constraints: CFConstraints, updates: Dict[str, Any]) -> CFConstraints:
        # Only one constraint may change; field names match CFConstraints.
        kwargs = {
            "min_tanimoto": base_constraints.min_tanimoto,
            "min_tanimoto_flip": base_constraints.min_tanimoto_flip,
            "min_tanimoto_improve": base_constraints.min_tanimoto_improve,
            "sa_max": base_constraints.sa_max,
            "logp_delta_max": base_constraints.logp_delta_max,
            "qed_min": base_constraints.qed_min,
            "pains": base_constraints.pains,
        }
        kwargs.update({k: v for k, v in updates.items() if k in kwargs})
        return CFConstraints(**kwargs)

    def _resolve_min_tanimoto(tier: Dict[str, Any], constraint_set: CFConstraints) -> float:
        base_min = constraint_set.min_tanimoto
        if tier["min_key"] == "flip":
            cfg_min = constraint_set.min_tanimoto_flip if constraint_set.min_tanimoto_flip is not None else base_min
        else:
            cfg_min = constraint_set.min_tanimoto_improve if constraint_set.min_tanimoto_improve is not None else base_min
        return max(tier["default_min_tanimoto"], cfg_min)

    def _filter_candidates(
        tier: Dict[str, Any],
        constraint_set: CFConstraints,
        relaxation_name: str,
        relaxation_desc: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        min_sim = _resolve_min_tanimoto(tier, constraint_set)
        counts = {
            "sampled": sample_count,
            "invalid": 0,
            "duplicate": 0,
            "similarity_filtered": 0,
            "prob_filtered": 0,
            "delta_filtered": 0,
            "sa_filtered": 0,
            "logp_filtered": 0,
            "qed_filtered": 0,
            "alert_filtered": 0,
            "kept": 0,
            "min_tanimoto_used": min_sim,
            "prob_max_used": tier["prob_max"],
            "delta_min_used": tier["delta_min"] if tier["require_delta"] else None,
            "sa_max_used": constraint_set.sa_max,
            "logp_delta_max_used": constraint_set.logp_delta_max,
            "qed_min_used": constraint_set.qed_min,
            "pains_used": constraint_set.pains,
        }
        rows: List[Dict[str, Any]] = []
        seen = set()
        for ex in cfs:
            smi = getattr(ex, "smiles", None)
            if not smi or smi == base_smiles:
                counts["invalid"] += 1
                continue
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                counts["invalid"] += 1
                continue
            try:
                Chem.SanitizeMol(mol)
            except Exception:
                counts["invalid"] += 1
                continue

            smi_canon = Chem.MolToSmiles(mol, canonical=True)
            if smi_canon in seen:
                counts["duplicate"] += 1
                continue
            seen.add(smi_canon)

            fp = mol_to_ecfp_bits(mol, fp_cfg)
            sim = float(DataStructs.TanimotoSimilarity(fp_base, fp))
            if sim < min_sim:
                counts["similarity_filtered"] += 1
                continue

            p = float(model_prob(smi))
            delta_p = p_base - p
            if tier["prob_max"] is not None and p >= float(tier["prob_max"]):
                counts["prob_filtered"] += 1
                continue
            if tier["require_delta"] and delta_p < float(tier["delta_min"]):
                counts["delta_filtered"] += 1
                continue

            props = mol_props(mol, cache_dir=fpscores_cache_dir)
            if props["sascore"] > constraint_set.sa_max:
                counts["sa_filtered"] += 1
                continue

            if abs(props["logp"] - base_props["logp"]) > constraint_set.logp_delta_max:
                counts["logp_filtered"] += 1
                continue

            if constraint_set.qed_min > 0 and props["qed"] < constraint_set.qed_min:
                counts["qed_filtered"] += 1
                continue

            alert = has_structural_alerts(mol) if constraint_set.pains else False
            if alert:
                counts["alert_filtered"] += 1
                continue

            rows.append(
                {
                    "smiles": smi,
                    "similarity": sim,
                    "p": p,
                    "delta_p": delta_p,
                    "logp": props["logp"],
                    "qed": props["qed"],
                    "sascore": props["sascore"],
                    "alert": alert,
                    "tier": tier["name"],
                    "tier_label": tier["label"],
                    "relaxation": relaxation_name,
                    "relaxation_desc": relaxation_desc,
                }
            )
        rows = _dedupe_by_smiles(rows)
        counts["kept"] = len(rows)
        return rows, counts

    attempts: List[Dict[str, Any]] = []
    final_rows: List[Dict[str, Any]] = []
    final_tier = "none"
    final_relaxation = "none"
    final_relaxation_desc = "baseline constraints"

    def _run_tiers(
        active_constraints: CFConstraints, relaxation_name: str, relaxation_desc: str
    ) -> Tuple[List[Dict[str, Any]], str, str]:
        nonlocal attempts
        for tier in tier_specs:
            rows, counts = _filter_candidates(tier, active_constraints, relaxation_name, relaxation_desc)
            attempts.append(
                {
                    "tier": tier["name"],
                    "tier_label": tier["label"],
                    "relaxation": relaxation_name,
                    "relaxation_desc": relaxation_desc,
                    "counts": counts,
                }
            )
            if logger:
                logger.info(
                    "CF filtering %s (%s): %s",
                    tier["name"],
                    relaxation_name or "none",
                    counts,
                )
            if rows:
                return rows, tier["name"], tier["label"]
        return [], "none", ""

    # Baseline tiers
    final_rows, final_tier, final_tier_label = _run_tiers(
        constraints, relaxation_name="none", relaxation_desc="baseline constraints"
    )

    # Controlled single-constraint relaxation attempts, if configured and no hits yet.
    final_relaxation = "none"
    final_relaxation_desc = "baseline constraints"
    relaxation_used = False
    if not final_rows:
        for step in relaxation_steps:
            relaxed_constraints = _apply_relaxation(constraints, step["updates"])
            rows, tier_name, tier_label = _run_tiers(
                relaxed_constraints,
                relaxation_name=step["name"],
                relaxation_desc=step["description"],
            )
            if rows:
                final_rows = rows
                final_tier = tier_name
                final_tier_label = tier_label
                final_relaxation = step["name"]
                final_relaxation_desc = step["description"]
                relaxation_used = True
                break

    # rank: high risk drop then high similarity to prefer meaningful and close suggestions
    final_rows.sort(key=lambda r: (r["delta_p"], r["similarity"]), reverse=True)
    final_rows = final_rows[:nmols]

    diag = {
        "sampled": sample_count,
        "sample_budget": sample_budget,
        "target_prob_max": float(safe_prob_max),
        "attempts": attempts,
        "final_tier": final_tier,
        "final_tier_label": final_tier_label if final_tier_label else final_tier,
        "final_relaxation": final_relaxation,
        "final_relaxation_desc": final_relaxation_desc,
        "relaxation_used": relaxation_used,
        "final_count": len(final_rows),
        "scarcity": len(final_rows) == 0,
    }
    return final_rows, diag


def write_lead_report(
    out_dir: Path,
    mol_id: str,
    base_smiles: str,
    y_true: int,
    p_cal: float,
    threshold: float,
    max_sim: float,
    sim_bin: str,
    counterfactuals: List[Dict[str, Any]],
    dataset_analogues: Optional[List[Dict[str, Any]]] = None,
    cf_summary: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a single-molecule lead optimization report as Markdown + PNG images."""
    out_dir.mkdir(parents=True, exist_ok=True)
    depict_smiles(base_smiles, out_dir / "base.png")

    for i, cf in enumerate(counterfactuals, start=1):
        depict_smiles(cf["smiles"], out_dir / f"cf_{i:02d}.png")
    for i, ana in enumerate(dataset_analogues or [], start=1):
        depict_smiles(ana["smiles"], out_dir / f"ds_{i:02d}.png")

    y_pred = int(p_cal >= threshold)
    md = []
    md.append(f"# Lead Optimization Report — {mol_id}\n")
    md.append("## Base molecule\n")
    md.append(f"- **SMILES:** `{base_smiles}`\n")
    md.append(f"- **True label:** {int(y_true)}\n")
    md.append(f"- **Calibrated p(toxic):** {p_cal:.3f}\n")
    md.append(f"- **Threshold:** {threshold:.3f} → **Predicted class:** {y_pred}\n")
    md.append(f"- **Max similarity to train:** {max_sim:.3f} (**bin:** {sim_bin})\n")
    md.append("\n![](base.png)\n")

    md.append("\n## Counterfactual search summary\n")
    if cf_summary:
        sampled = cf_summary.get("sampled", "n/a")
        sample_budget = cf_summary.get("sample_budget", sampled)
        attempts = cf_summary.get("attempts", [])
        final_tier = cf_summary.get("final_tier", "none")
        final_tier_label = cf_summary.get("final_tier_label", final_tier)
        final_relax = cf_summary.get("final_relaxation", "none")
        relaxation_used = bool(cf_summary.get("relaxation_used", False))
        scarcity = bool(cf_summary.get("scarcity", False))
        fallback_used = bool(dataset_analogues)
        md.append(f"- ExMol sample budget: {sample_budget} (drawn: {sampled})\n")
        md.append(f"- Candidates sampled (ExMol): {sampled}\n")
        md.append(f"- Target prob max (flip goal): {cf_summary.get('target_prob_max', 'n/a')}\n")
        md.append(
            f"- Tier used: {final_tier_label if final_tier != 'none' else 'None'}"
            f" (relaxation: {final_relax if final_relax else 'none'})\n"
        )
        md.append(f"- Relaxation used: {relaxation_used}\n")
        md.append(f"- Survivors after filtering: {cf_summary.get('final_count', 0)}\n")
        md.append(f"- Dataset analogue fallback used: {fallback_used}\n")
        if scarcity:
            md.append("- Scarcity: No candidates survived medicinal constraints.\n")
        if cf_summary.get("final_relaxation_desc"):
            md.append(f"- Relaxation note: {cf_summary.get('final_relaxation_desc')}\n")
        if attempts:
            md.append("\n### Filter attrition by tier\n")
            md.append(
                "| Tier | Relaxation | Sampled | Kept | Invalid | Duplicate | Similarity | Prob | Δp | SA | ΔLogP | QED | Alerts |\n"
            )
            md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|\n")
            for a in attempts:
                c = a.get("counts", {})
                md.append(
                    f"| {a.get('tier_label', a.get('tier'))} | {a.get('relaxation', 'none')} | "
                    f"{c.get('sampled', 0)} | {c.get('kept', 0)} | {c.get('invalid', 0)} | {c.get('duplicate', 0)} | "
                    f"{c.get('similarity_filtered', 0)} | {c.get('prob_filtered', 0)} | {c.get('delta_filtered', 0)} | {c.get('sa_filtered', 0)} | "
                    f"{c.get('logp_filtered', 0)} | {c.get('qed_filtered', 0)} | {c.get('alert_filtered', 0)} |\n"
                )
    else:
        md.append("- Counterfactual diagnostics unavailable; see logs.\n")

    md.append("\n## Counterfactual suggestions (filtered)\n")
    if counterfactuals:
        md.append("| Rank | Image | Tier | Relaxation | Similarity | p(toxic) | Δp | LogP | QED | SA |\n")
        md.append("|---:|:---:|---|---|---:|---:|---:|---:|---:|---:|\n")
        for i, cf in enumerate(counterfactuals, start=1):
            img = f"cf_{i:02d}.png"
            md.append(
                f"| {i} | ![]({img}) | {cf.get('tier_label', cf.get('tier',''))} | {cf.get('relaxation','none')} | "
                f"{cf['similarity']:.3f} | {cf['p']:.3f} | {cf['delta_p']:.3f} | "
                f"{cf['logp']:.2f} | {cf['qed']:.2f} | {cf['sascore']:.2f} |\n"
            )
        md.append("\n### Raw counterfactual records\n")
        md.append("```json\n")
        md.append(json.dumps(counterfactuals, indent=2))
        md.append("\n```\n")
    else:
        md.append("### No valid counterfactuals under medicinal constraints\n")
        if cf_summary:
            md.append(f"- Total candidates sampled: {cf_summary.get('sampled', 'n/a')}\n")
            tiers_seen = [a.get("tier_label", a.get("tier")) for a in cf_summary.get("attempts", [])]
            md.append(f"- Tiers evaluated: {', '.join(tiers_seen)}\n")
            md.append("- Interpretation: Local detoxification may not be feasible near this chemistry under current constraints.\n")
        else:
            md.append("- Interpretation: Counterfactual search failed before filtering; check logs.\n")

    if dataset_analogues:
        md.append("\n## Dataset-derived analogues (fallback)\n")
        md.append("_Selected from dataset by lowest predicted p(toxic) with similarity ≥0.3; used when generated counterfactuals are unavailable._\n")
        md.append("| Rank | Image | Similarity | p(toxic) | Δp | LogP | QED | SA | Alerts |\n")
        md.append("|---:|:---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for i, ana in enumerate(dataset_analogues, start=1):
            img = f"ds_{i:02d}.png"
            md.append(
                f"| {i} | ![]({img}) | {ana['similarity']:.3f} | {ana['p']:.3f} | {ana['delta_p']:.3f} | "
                f"{ana['logp']:.2f} | {ana['qed']:.2f} | {ana['sascore']:.2f} | {('⚠' if ana.get('alert') else 'OK')} |\n"
            )
        md.append("\n### Raw analogue records\n")
        md.append("```json\n")
        md.append(json.dumps(dataset_analogues, indent=2))
        md.append("\n```\n")

    (out_dir / "report.md").write_text("".join(md), encoding="utf-8")
