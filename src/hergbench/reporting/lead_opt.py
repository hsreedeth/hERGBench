
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import inspect
from rdkit import Chem, DataStructs
from rdkit.Chem import Crippen, Draw, QED
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

from hergbench.features.fingerprints import FingerprintConfig, mol_to_ecfp_bits
from hergbench.reporting.sascorer import calculate_sa_score
from hergbench.data.standardize import StandardizeConfig, canonical_smiles, smiles_to_mol, standardize_mol

try:
    from rdkit.Chem.MolStandardize import rdMolStandardize
except Exception:  # pragma: no cover
    rdMolStandardize = None



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

_STD_CFG_SCORING = StandardizeConfig(
    tautomer_canonicalize=True,
    strip_salts=True,
)

_UNCHARGER = None


def _std_for_scoring(smiles: str) -> tuple[Optional[str], Optional[Chem.Mol]]:
    """
    Project-canonical scoring identity:
      1) project standardization (salts/tautomers, etc.)
      2) neutralize/charge-parent to kill ionization-only variants
      3) canonical smiles
    """
    if not smiles:
        return None, None

    m = smiles_to_mol(smiles)
    m = standardize_mol(m, _STD_CFG_SCORING)
    if m is None:
        return None, None

    # Neutralize/charge-parent: this is the critical "no fake progress from [O-]" step.
    # We keep it local to reporting so you don't silently change training unless you choose to.
    if rdMolStandardize is not None:
        try:
            # ChargeParent is more aggressive; if not available in your RDKit build, fall back to Uncharger.
            if hasattr(rdMolStandardize, "ChargeParent"):
                m = rdMolStandardize.ChargeParent(m)
            else:
                global _UNCHARGER
                if _UNCHARGER is None:
                    _UNCHARGER = rdMolStandardize.Uncharger()
                m = _UNCHARGER.uncharge(m)
        except Exception:
            pass

    try:
        Chem.SanitizeMol(m)
    except Exception:
        return None, None

    return canonical_smiles(m), m

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
    fp_cfg: Optional[FingerprintConfig],
    constraints: Optional[CFConstraints] = None,
    top_k: int = 5,
    min_sim: float = 0.3,
    fpscores_cache_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return dataset-derived analogues (lowest predicted risk, similar to base)."""

    base_std_smi, base_std_mol = _std_for_scoring(base_smiles)
    if base_std_smi is None or base_std_mol is None:
        return []

    base_fp_std = mol_to_ecfp_bits(base_std_mol, fp_cfg) if fp_cfg is not None else base_fp
    base_fp_use = base_fp_std if base_fp_std is not None else base_fp
    base_p_use = base_p

    sa_cutoff = float(constraints.sa_max) if constraints is not None else 4.5
    use_pains = bool(constraints.pains) if constraints is not None else True

    entries: List[Dict[str, Any]] = []
    for raw_smi, fp, p in zip(dataset_smiles, dataset_fps, dataset_probs):
        std_smi, mol = _std_for_scoring(raw_smi)
        if std_smi is None or mol is None:
            continue

        # Remove trivial identity-equivalents to base under scoring convention
        if std_smi == base_std_smi:
            continue

        # Avoid mixing identities: only keep cases where standardize/neutralize does not change the dataset row identity.
        if std_smi != raw_smi:
            continue

        sim = float(DataStructs.TanimotoSimilarity(base_fp_use, fp))

        props = mol_props(mol, cache_dir=fpscores_cache_dir)
        sa_val = float(props["sascore"])
        alert = has_structural_alerts(mol) if use_pains else False

        sa_status = "ok" if np.isfinite(sa_val) else "failed"
        if not np.isfinite(sa_val):
            sa_val = float("nan")

        actionable = (not alert) and (not np.isnan(sa_val)) and (sa_val <= sa_cutoff) and ((base_p - float(p)) > 0)

        entries.append(
            {
                "raw_smiles": raw_smi,
                "smiles": std_smi,
                "similarity": sim,
                "p": float(p),
                "delta_p": base_p_use - float(p),
                "logp": float(props["logp"]),
                "qed": float(props["qed"]),
                "sascore": sa_val,
                "sa_status": sa_status,
                "actionable": actionable,
                "alert": alert,
                "tier": "dataset_analogue",
                "tier_label": "Dataset analogue",
                "relaxation": "none",
                "relaxation_desc": "dataset fallback",
                "sa_max_used": sa_cutoff,
                "pains_used": use_pains,
            }
        )

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

    _prob_cache: Dict[str, float] = {}

    def prob_cached(s: str) -> float:
        if s in _prob_cache:
            return _prob_cache[s]
        v = float(model_prob(s))
        _prob_cache[s] = v
        return v


    base_std_smi, mol_base = _std_for_scoring(base_smiles)
    if mol_base is None or base_std_smi is None:
        return [], {
            "error": "invalid_base_smiles",
            "sampled": 0,
            "final_tier": "none",
            "final_count": 0,
            "scarcity": True,
        }

    # IMPORTANT: score the *standardized identity*
    p_base = float(prob_cached(base_std_smi))


    # Enforce a large ExMol budget (bounded) to give rare counterfactuals a chance under strict medicinal filters.
    sample_budget = int(search_nmols if search_nmols is not None else exmol_n_samples)

    # Production guardrail: enforce a large budget only when user did not explicitly override with search_nmols.
    # This keeps real runs robust, but allows small debug/pytest runs to request small budgets.
    if search_nmols is None:
        sample_budget = min(max(sample_budget, 1500), 2000)
    else:
        # Still enforce basic sanity bounds for explicit overrides
        sample_budget = max(sample_budget, 1)


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

    def _exmol_f(x, *args):
        """Wrapper matching ExMol expectations for batched scoring.

        Critical: always score the standardized identity, not the raw SMILES.
        """
        def _score_one(smi: Any) -> float:
            std_smi, _mol = _std_for_scoring(str(smi))
            if std_smi is None:
                # Treat unstandardizable molecules as toxic so ExMol doesn't prefer them.
                return 1.0
            return float(model_prob(std_smi))

        if isinstance(x, list):
            return [_score_one(s) for s in x]
        return [_score_one(x)]



    def _exmol_sample_space(base: str, preset: str, budget: int) -> Tuple[List[Any], Optional[str]]:
        err_msg: Optional[str] = None
        examples: List[Any] = []

        try:
            sig = inspect.signature(exmol.sample_space)
        except Exception:
            sig = None

        method_kwargs: Dict[str, Any] = {"min_mutations": 1, "max_mutations": 1}
        try:
            method_kwargs["alphabet"] = exmol.get_basic_alphabet()
        except Exception:
            pass

        base_kwargs: Dict[str, Any] = {}

        def _maybe_add(name: str, value: Any) -> None:
            if sig is None or name in sig.parameters:
                base_kwargs[name] = value

        # scorer callable name
        if sig is None:
            base_kwargs["f"] = _exmol_f
        else:
            if "f" in sig.parameters:
                base_kwargs["f"] = _exmol_f
            elif "model_class" in sig.parameters:
                base_kwargs["model_class"] = _exmol_f
            elif "model" in sig.parameters:
                base_kwargs["model"] = _exmol_f

        _maybe_add("batched", True)
        _maybe_add("preset", preset)
        _maybe_add("method_kwargs", method_kwargs)
        _maybe_add("quiet", True)
        _maybe_add("use_selfies", False)
        _maybe_add("sanitize_smiles", True)

        # budget arg
        if sig is None:
            base_kwargs["num_samples"] = budget
        else:
            if "num_samples" in sig.parameters:
                base_kwargs["num_samples"] = budget
            elif "nmols" in sig.parameters:
                base_kwargs["nmols"] = budget

        # base-smiles arg key candidates
        if sig is None:
            base_keys = ["origin_smiles", "smiles", "base"]
        else:
            if "origin_smiles" in sig.parameters:
                base_keys = ["origin_smiles"]
            elif "smiles" in sig.parameters:
                base_keys = ["smiles"]
            elif "base" in sig.parameters:
                base_keys = ["base"]
            else:
                base_keys = [next(iter(sig.parameters))]

        last_type_error: Optional[Exception] = None

        try:
            space = None
            for k in base_keys:
                try:
                    call_kwargs = dict(base_kwargs)
                    call_kwargs[k] = base
                    space = exmol.sample_space(**call_kwargs)
                    break
                except TypeError as e:
                    last_type_error = e
                    continue

            if space is None:
                raise last_type_error if last_type_error is not None else RuntimeError("ExMol sample_space failed")

            # normalize common return shapes
            if isinstance(space, tuple):
                space = space[0]

            # try to extract examples directly
            if isinstance(space, list):
                examples = list(space)
            elif getattr(space, "examples", None) is not None:
                examples = list(getattr(space, "examples"))
            elif getattr(space, "mols", None) is not None:
                examples = list(getattr(space, "mols"))
            else:
                examples = []

            # fallback: cf_explain if we still have nothing but have a space object
            if not examples and hasattr(exmol, "cf_explain"):
                try:
                    cf_sig = inspect.signature(exmol.cf_explain)
                except Exception:
                    cf_sig = None

                cf_kwargs: Dict[str, Any] = {}
                if cf_sig is None or "nmols" in getattr(cf_sig, "parameters", {}):
                    cf_kwargs["nmols"] = budget
                if cf_sig is None or "filter_nondrug" in getattr(cf_sig, "parameters", {}):
                    cf_kwargs["filter_nondrug"] = False

                explained = exmol.cf_explain(space, **cf_kwargs)

                if isinstance(explained, list):
                    examples = list(explained)
                elif getattr(explained, "examples", None) is not None:
                    examples = list(getattr(explained, "examples"))
                else:
                    examples = []

        except Exception as e:
            err_msg = str(e)
            examples = []

        return examples, err_msg


    # ExMol sampling from sample_space; prefer direct examples, but allow cf_explain fallback.
    examples, sample_err = _exmol_sample_space(base=base_std_smi, preset=exmol_preset, budget=sample_budget)
    sample_count = len(examples)

    if logger:
        logger.info(
            "ExMol requested budget=%d, sampled=%d (err=%s)",
            sample_budget,
            sample_count,
            sample_err,
        )

    if sample_err and sample_count == 0:
        diag = {
            "sampled": 0,
            "sample_budget": sample_budget,
            "sample_error": sample_err,
            "target_prob_max": float(safe_prob_max),
            "attempts": [],
            "final_tier": "error",
            "final_tier_label": "error",
            "final_relaxation": "none",
            "final_relaxation_desc": "sampling failed",
            "relaxation_used": False,
            "final_count": 0,
            "scarcity": True,
            "error": sample_err,
        }
        return [], diag


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

    def _resolve_min_tanimoto(tier, constraint_set):
        if tier["min_key"] == "flip":
            if constraint_set.min_tanimoto_flip is not None:
                return constraint_set.min_tanimoto_flip, "min_tanimoto_flip"
            if constraint_set.min_tanimoto is not None:
                return constraint_set.min_tanimoto, "min_tanimoto (legacy)"
            return tier["default_min_tanimoto"], "tier_default"
        else:
            if constraint_set.min_tanimoto_improve is not None:
                return constraint_set.min_tanimoto_improve, "min_tanimoto_improve"
            if constraint_set.min_tanimoto is not None:
                return constraint_set.min_tanimoto, "min_tanimoto (legacy)"
            return tier["default_min_tanimoto"], "tier_default"

    def _filter_candidates(
        tier: Dict[str, Any],
        constraint_set: CFConstraints,
        relaxation_name: str,
        relaxation_desc: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        min_sim, min_source = _resolve_min_tanimoto(tier, constraint_set)
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
            "min_tanimoto_source": min_source,
            "prob_max_used": tier["prob_max"],
            "delta_min_used": tier["delta_min"] if tier["require_delta"] else None,
            "sa_max_used": constraint_set.sa_max,
            "logp_delta_max_used": constraint_set.logp_delta_max,
            "qed_min_used": constraint_set.qed_min,
            "pains_used": constraint_set.pains,
        }
        rows: List[Dict[str, Any]] = []
        seen = set()
        for ex in examples:
            smi = getattr(ex, "smiles", None)
            if smi is None and isinstance(ex, dict):
                smi = ex.get("smiles")
            if not smi or smi == base_smiles:
                counts["invalid"] += 1
                continue
            raw_smi = smi
            std_smi, mol = _std_for_scoring(raw_smi)
            if std_smi is None or mol is None:
                counts["invalid"] += 1
                continue

            # If it collapses back to the base identity, it's an ionization/protonation artifact (or equivalent).
            if std_smi == base_std_smi:
                counts["duplicate"] += 1
                continue

            if std_smi in seen:
                counts["duplicate"] += 1
                continue
            seen.add(std_smi)

            fp = mol_to_ecfp_bits(mol, fp_cfg)
            sim = float(DataStructs.TanimotoSimilarity(fp_base, fp))
            if sim < min_sim:
                counts["similarity_filtered"] += 1
                continue

            p = float(prob_cached(std_smi))
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
                    "raw_smiles": raw_smi,
                    "smiles": std_smi,
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
    final_tier_label = ""
    final_relaxation = "none"
    final_relaxation_desc = "baseline constraints"
    relaxation_used = False

    def _record_attempt(tier: Dict[str, Any], relaxation_name: str, relaxation_desc: str, counts: Dict[str, Any]) -> None:
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

    # Search order: Tier 1–3 under baseline constraints, then per-tier relaxations; Tier 4 only if all fail.
    for tier in tier_specs:
        rows, counts = _filter_candidates(tier, constraints, "none", "baseline constraints")
        _record_attempt(tier, "none", "baseline constraints", counts)
        if rows:
            final_rows = rows
            final_tier = tier["name"]
            final_tier_label = tier["label"]
            final_relaxation = "none"
            final_relaxation_desc = "baseline constraints"
            break

        for step in relaxation_steps:
            relaxed_constraints = _apply_relaxation(constraints, step["updates"])
            rows, counts = _filter_candidates(tier, relaxed_constraints, step["name"], step["description"])
            _record_attempt(tier, step["name"], step["description"], counts)
            if rows:
                final_rows = rows
                final_tier = tier["name"]
                final_tier_label = tier["label"]
                final_relaxation = step["name"]
                final_relaxation_desc = step["description"]
                relaxation_used = True
                break
        if final_rows:
            break

    # Tier 4 diagnostic fallback: closest edits from sampled space if nothing survived Tier 1–3.
    if (not final_rows) and examples:
        diag_rows: List[Dict[str, Any]] = []
        seen_std: set[str] = set()

        for ex in examples:
            raw_smi = getattr(ex, "smiles", None)
            if raw_smi is None and isinstance(ex, dict):
                raw_smi = ex.get("smiles")
            if not raw_smi:
                continue

            # Standardize/neutralize ONCE to establish scoring identity.
            std_smi, mol = _std_for_scoring(raw_smi)
            if std_smi is None or mol is None:
                continue

            # Skip if this candidate collapses to the base standardized identity.
            if std_smi == base_std_smi:
                continue

            # CRITICAL: dedupe on standardized identity BEFORE any scoring calls.
            if std_smi in seen_std:
                continue
            seen_std.add(std_smi)

            # Similarity computed on standardized identity (mol).
            fp = mol_to_ecfp_bits(mol, fp_cfg)
            sim = float(DataStructs.TanimotoSimilarity(fp_base, fp))

            # CRITICAL: compute p ONCE per kept standardized identity.
            p_std = float(prob_cached(std_smi))
            delta_std = p_base - p_std

            props = mol_props(mol, cache_dir=fpscores_cache_dir)
            alert = has_structural_alerts(mol) if constraints.pains else False

            diag_rows.append(
                {
                    "raw_smiles": raw_smi,
                    "smiles": std_smi,
                    "similarity": sim,
                    "p": p_std,
                    "delta_p": delta_std,
                    "logp": props["logp"],
                    "qed": props["qed"],
                    "sascore": props["sascore"],
                    "alert": alert,
                    "tier": "diagnostic_close_edits",
                    "tier_label": "Tier 4 — Closest edits (diagnostic)",
                    "relaxation": "none",
                    "relaxation_desc": "diagnostic fallback (no valid improvements found)",
                }
            )

        diag_rows.sort(key=lambda r: r["similarity"], reverse=True)
        final_rows = diag_rows[:nmols]
        final_tier = "diagnostic_close_edits"
        final_tier_label = "Tier 4 — Closest edits (diagnostic)"
        final_relaxation = "none"
        final_relaxation_desc = "diagnostic fallback (no valid improvements found)"



    # rank: high risk drop then high similarity to prefer meaningful and close suggestions
    final_rows.sort(key=lambda r: (r["delta_p"], r["similarity"]), reverse=True)
    final_rows = final_rows[:nmols]

    diag = {
        "sampled": sample_count,
        "sample_budget": sample_budget,
        "sample_error": sample_err,
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

    def _ood_flag(sim: float) -> str:
        if sim < 0.30:
            return "Very out-of-domain"
        if sim < 0.50:
            return "Out-of-domain"
        if sim < 0.70:
            return "Borderline"
        return "In-domain"

    ood = _ood_flag(max_sim)

    def _display_meta(
        counterfactuals: List[Dict[str, Any]],
        dataset_analogues: Optional[List[Dict[str, Any]]],
        cf_summary: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        """
        Single source of truth for what we *display* as the survivor tier/relaxation.
        Prefer the actual rows we are about to print; only fall back to cf_summary if empty.
        """
        if counterfactuals:
            tiers = {str(cf.get("tier", "")) for cf in counterfactuals}
            labels = {str(cf.get("tier_label", cf.get("tier", ""))) for cf in counterfactuals}
            relaxes = {str(cf.get("relaxation", "none")) for cf in counterfactuals}

            tier = next(iter(tiers)) if len(tiers) == 1 else "mixed"
            tier_label = next(iter(labels)) if len(labels) == 1 else ("Mixed tiers: " + ", ".join(sorted(labels)))
            relaxation = next(iter(relaxes)) if len(relaxes) == 1 else "mixed"

            return {"tier": tier, "tier_label": tier_label, "relaxation": relaxation, "source": "rows"}

        if dataset_analogues:
            return {"tier": "dataset_analogue", "tier_label": "Dataset analogue (fallback)", "relaxation": "none", "source": "dataset"}

        if cf_summary:
            return {
                "tier": str(cf_summary.get("final_tier", "none")),
                "tier_label": str(cf_summary.get("final_tier_label", cf_summary.get("final_tier", "none"))),
                "relaxation": str(cf_summary.get("final_relaxation", "none")),
                "source": "cf_summary",
            }

        return {"tier": "none", "tier_label": "None", "relaxation": "none", "source": "none"}

    display = _display_meta(counterfactuals, dataset_analogues, cf_summary)

    # Fail-fast correctness check: if we have rows, cf_summary must agree (allowing dataset-fallback aliasing).
    if cf_summary and counterfactuals:
        expected = str(cf_summary.get("final_tier", ""))
        actual = display["tier"]

        # Allow common aliasing when the orchestration layer calls it "dataset_fallback"
        # but rows are tagged "dataset_analogue".
        alias_ok = (expected == "dataset_fallback" and actual == "dataset_analogue")

        if expected and expected not in ("none", "unknown") and (expected != actual) and (not alias_ok):
            raise ValueError(
                f"Report tier mismatch: cf_summary.final_tier={expected!r} but displayed rows tier={actual!r}. "
                "This indicates stale/misaligned cf_summary vs survivors."
            )

    if counterfactuals:
        result_class = f"Generated suggestions available (Tier: {display['tier_label']})"
    elif dataset_analogues:
        result_class = "No generated suggestions; dataset analogues provided"
    else:
        result_class = "No suggestions available"

    def _ood_sentence(flag: str) -> str:
        if flag == "Very out-of-domain":
            return "Similarity is very low; generated suggestions may be scarce and fallback analogues are provided for context."
        if flag == "Out-of-domain":
            return "Similarity is low; treat any suggestions cautiously and consult fallback analogues."
        if flag == "Borderline":
            return "Similarity is borderline; suggestions may be limited but still informative."
        return "Similarity is in-domain; suggestions should be more reliable locally."

    y_pred = int(p_cal >= threshold)
    md = []
    md.append(f"# Lead Optimization Report — {mol_id}\n")
    md.append("## Summary\n")
    md.append(f"- **Calibrated p(toxic):** {p_cal:.3f}\n")
    md.append(f"- **Threshold:** {threshold:.3f} → **Predicted class:** {y_pred}\n")
    md.append(f"- **Max similarity to train:** {max_sim:.3f} (**bin:** {sim_bin})\n")
    md.append(f"- **OOD classification:** {ood}\n")
    md.append(f"- **Result classification:** {result_class}\n")
    md.append(f"- {_ood_sentence(ood)}\n")

    md.append("## Base molecule\n")
    md.append(f"- **SMILES:** `{base_smiles}`\n")
    md.append(f"- **True label:** {int(y_true)}\n")
    md.append("\n![](base.png)\n")

    md.append("\n## Counterfactual search summary\n")
    if cf_summary:
        sampled = cf_summary.get("sampled", "n/a")
        sample_budget = cf_summary.get("sample_budget", sampled)
        attempts = cf_summary.get("attempts", [])
        final_tier = display["tier"]
        final_tier_label = display["tier_label"]
        final_relax = display["relaxation"]
        relaxation_used = bool(cf_summary.get("relaxation_used", False))
        scarcity = bool(cf_summary.get("scarcity", False))
        fallback_used = bool(dataset_analogues)
        md.append(f"- ExMol requested: {sample_budget} | drawn: {sampled}\n")
        md.append(f"- Generated tier (Tier 1–4): {display['tier_label'] if display['tier'] != 'none' else 'None'}\n")
        md.append(f"- Relaxation used: {bool(display['relaxation'] != 'none' and display['relaxation'] != 'mixed')} (applied: {display['relaxation']})\n")
        md.append(f"- Generated survivors (Tier 1–4): {len(counterfactuals)}\n")
        md.append(f"- Dataset analogue fallback count (not included in survivors): {len(dataset_analogues or [])}\n")
        if scarcity:
            md.append("- Scarcity: No candidates survived medicinal constraints.\n")
        if cf_summary.get("final_relaxation_desc"):
            md.append(f"- Relaxation note: {cf_summary.get('final_relaxation_desc')}\n")
        if attempts:
            winner_relax = display["relaxation"] if display["relaxation"] else "none"
            md.append("\n### Filter attrition by tier (baseline + final relaxation)\n")
            md.append("<table>\n")
            md.append("<tr><th>Tier</th><th>Relaxation</th><th>Sampled</th><th>Kept</th><th>Invalid</th><th>Duplicate</th><th>Similarity</th><th>Prob</th><th>Δp</th><th>SA</th><th>ΔLogP</th><th>QED</th><th>Alerts</th></tr>\n")
            for a in attempts:
                if a.get("relaxation") not in ("none", winner_relax):
                    continue
                c = a.get("counts", {})
                md.append(
                    f"<tr><td>{a.get('tier_label', a.get('tier'))}</td>"
                    f"<td>{a.get('relaxation', 'none')}</td>"
                    f"<td>{c.get('sampled', 0)}</td><td>{c.get('kept', 0)}</td><td>{c.get('invalid', 0)}</td><td>{c.get('duplicate', 0)}</td>"
                    f"<td>{c.get('similarity_filtered', 0)}</td><td>{c.get('prob_filtered', 0)}</td><td>{c.get('delta_filtered', 0)}</td>"
                    f"<td>{c.get('sa_filtered', 0)}</td><td>{c.get('logp_filtered', 0)}</td><td>{c.get('qed_filtered', 0)}</td><td>{c.get('alert_filtered', 0)}</td></tr>\n"
                )
            md.append("</table>\n")
            md.append("\n<details><summary>All filter attempts (diagnostic)</summary>\n")
            md.append("```json\n")
            md.append(json.dumps(attempts, indent=2))
            md.append("\n```\n")
            md.append("</details>\n")
    else:
        md.append("- Counterfactual diagnostics unavailable; see logs.\n")

    md.append("\n## Counterfactual suggestions (filtered)\n")
    if counterfactuals:
        md.append(f"_Rows below are generated from {display['tier_label']} (relaxation: {display['relaxation']})._ \n")
        md.append("<table>\n")
        md.append("<tr><th>Rank</th><th>Structure</th><th>Tier</th><th>Relaxation</th><th>Similarity</th><th>p(toxic)</th><th>Δp</th><th>LogP</th><th>QED</th><th>SA</th></tr>\n")
        for i, cf in enumerate(counterfactuals, start=1):
            img = f"cf_{i:02d}.png"
            tier_label = cf.get("tier_label", cf.get("tier", ""))
            alert_flag = "⚠" if cf.get("alert") else "OK"
            md.append(
                f"<tr><td>{i}</td><td><img src=\"{img}\" width=\"260\"></td>"
                f"<td>{tier_label}</td><td>{cf.get('relaxation','none')}</td>"
                f"<td>{cf['similarity']:.3f}</td><td>{cf['p']:.3f}</td><td>{cf['delta_p']:.3f}</td>"
                f"<td>{cf['logp']:.2f}</td><td>{cf['qed']:.2f}</td><td>{cf['sascore']:.2f}</td></tr>\n"
            )
        md.append("</table>\n")
    else:
        md.append("No candidates survived medicinal constraints. This does not mean the model is broken; it means local edits that reduce risk are rare under the current policy.\n")
        if cf_summary:
            md.append(f"- Total candidates sampled: {cf_summary.get('sampled', 'n/a')}\n")
            tiers_seen = [a.get("tier_label", a.get("tier")) for a in cf_summary.get("attempts", [])]
            md.append(f"- Highest generated tier attempted: {cf_summary.get('final_tier_label', cf_summary.get('final_tier', 'none'))}\n")
            md.append(f"- Tiers evaluated: {', '.join(tiers_seen)}\n")
            md.append("- Interpretation: Local detoxification may not be feasible near this chemistry under current constraints.\n")
        else:
            md.append("- Interpretation: Counterfactual search failed before filtering; check logs.\n")

    if dataset_analogues:
        md.append("\n## Dataset-derived analogues (fallback)\n")
        md.append("_Nearest analogues from the dataset (context only, not generated edits)._ \n")
        md.append("<table>\n")
        md.append("<tr><th>Rank</th><th>Structure</th><th>Similarity</th><th>p(toxic)</th><th>Δp</th><th>LogP</th><th>QED</th><th>SA</th><th>Alerts</th><th>Actionable?</th></tr>\n")
        for i, ana in enumerate(dataset_analogues, start=1):
            img = f"ds_{i:02d}.png"
            alerts = "⚠" if ana.get("alert") else "OK"
            sa_val = ana["sascore"]
            sa_display = "NA" if np.isnan(sa_val) else f"{sa_val:.2f}"
            actionable = "YES" if ana.get("actionable") else "NO"
            md.append(
                f"<tr><td>{i}</td><td><img src=\"{img}\" width=\"260\"></td>"
                f"<td>{ana['similarity']:.3f}</td><td>{ana['p']:.3f}</td><td>{ana['delta_p']:.3f}</td>"
                f"<td>{ana['logp']:.2f}</td><td>{ana['qed']:.2f}</td><td>{sa_display}</td><td>{alerts}</td><td>{actionable}</td></tr>\n"
            )
        md.append("</table>\n")
        if all(not ana.get("actionable") for ana in dataset_analogues):
            md.append("Fallback analogues are context-only; none meet feasibility constraints.\n")
    def _json_sanitize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove non-JSON-serializable fields from report rows.
        This is a reporting-layer guardrail: never allow RDKit Mol objects (or other objects)
        into the audit JSON.
        """
        drop_keys = {"_std_mol"}  # extend if needed later
        out: List[Dict[str, Any]] = []
        for r in rows:
            rr = {k: v for k, v in r.items() if k not in drop_keys}
            # Optional: defensively drop any remaining RDKit Mol-like objects
            rr = {k: v for k, v in rr.items() if not hasattr(v, "GetNumAtoms")}
            out.append(rr)
        return out

    md.append("\n## Raw records (for audit)\n")
    md.append("### Counterfactuals JSON\n")
    md.append("```json\n")
    md.append(json.dumps(_json_sanitize_rows(counterfactuals or []), indent=2))
    md.append("\n```\n")

    md.append("### Dataset analogues JSON\n")
    md.append("```json\n")
    md.append(json.dumps(_json_sanitize_rows(dataset_analogues or []), indent=2))
    md.append("\n```\n")


    (out_dir / "report.md").write_text("".join(md), encoding="utf-8")
