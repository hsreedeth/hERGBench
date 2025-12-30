
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
    min_tanimoto: float = 0.7
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


def generate_counterfactuals_exmol(
    base_smiles: str,
    model_class: Callable[[str], int],
    model_prob: Callable[[str], float],
    fp_cfg: FingerprintConfig,
    constraints: CFConstraints,
    safe_prob_max: float = 0.3,
    exmol_preset: str = "medium",
    nmols: int = 5,
    search_nmols: int = 250,
    delta_min: float = 0.10,
    fpscores_cache_dir: Optional[Path] = None,
    logger: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generate and filter counterfactuals around base_smiles using ExMol + medicinal-chemist filters.

    Returns a ranked list of dicts with smiles, similarity, p, delta_p, logp, qed, sascore, alert.
    """
    import exmol  # type: ignore

    p_base = float(model_prob(base_smiles))
    mol_base = Chem.MolFromSmiles(base_smiles)
    if mol_base is None:
        return [], {"error": "invalid_base_smiles"}

    base_props = mol_props(mol_base, cache_dir=fpscores_cache_dir)
    fp_base = mol_to_ecfp_bits(mol_base, fp_cfg)

    # ExMol expects a classifier f(smiles)->0/1 for counterfactual search.
    space = exmol.sample_space(
        base_smiles,
        model_class,
        batched=False,
        preset=exmol_preset,
        use_selfies=False,
        quiet=True,
        method_kwargs=None,
    )
    if isinstance(space, tuple):
        space = space[0]

    # counterfactual search (large pool)
    cfs = exmol.cf_explain(space, nmols=search_nmols, filter_nondrug=False)
    if isinstance(cfs, tuple):
        cfs = cfs[0]

    def _filter_candidates(
        min_tanimoto: float,
        prob_max: Optional[float],
        logp_delta_max: float,
        sa_max: float,
        require_delta: bool,
        delta_min: float,
        mode: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        counts = {
            "n_total": 0,
            "n_invalid": 0,
            "n_sim": 0,
            "n_prob": 0,
            "n_sa": 0,
            "n_logp": 0,
            "n_qed": 0,
            "n_alert": 0,
            "n_delta": 0,
        }
        rows: List[Dict[str, Any]] = []
        for ex in cfs:
            counts["n_total"] += 1
            smi = getattr(ex, "smiles", None)
            if not smi or smi == base_smiles:
                counts["n_invalid"] += 1
                continue
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                counts["n_invalid"] += 1
                continue
            try:
                Chem.SanitizeMol(mol)
            except Exception:
                counts["n_invalid"] += 1
                continue

            fp = mol_to_ecfp_bits(mol, fp_cfg)
            sim = float(DataStructs.TanimotoSimilarity(fp_base, fp))
            if sim < min_tanimoto:
                counts["n_sim"] += 1
                continue

            p = float(model_prob(smi))
            delta_p = p_base - p
            if prob_max is not None and p > prob_max:
                counts["n_prob"] += 1
                continue
            if require_delta and delta_p < delta_min:
                counts["n_delta"] += 1
                continue

            props = mol_props(mol, cache_dir=fpscores_cache_dir)
            if props["sascore"] > sa_max:
                counts["n_sa"] += 1
                continue

            if abs(props["logp"] - base_props["logp"]) > logp_delta_max:
                counts["n_logp"] += 1
                continue

            if constraints.qed_min > 0 and props["qed"] < constraints.qed_min:
                counts["n_qed"] += 1
                continue

            alert = has_structural_alerts(mol) if constraints.pains else False
            if alert:
                counts["n_alert"] += 1
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
                    "mode": mode,
                }
            )
        counts["n_final"] = len(rows)
        return rows, counts

    attempts: List[Dict[str, Any]] = []

    # Tier A: strict flip
    rows, counts = _filter_candidates(
        min_tanimoto=constraints.min_tanimoto,
        prob_max=safe_prob_max,
        logp_delta_max=constraints.logp_delta_max,
        sa_max=constraints.sa_max,
        require_delta=False,
        delta_min=0.0,
        mode="flip",
    )
    attempts.append({"tier": "strict", "counts": counts})
    if logger:
        logger.info("CF filtering (strict): %s", counts)

    # Tier B: relaxed filters but still require flip (p <= target)
    if not rows:
        rows, counts = _filter_candidates(
            min_tanimoto=max(0.55, constraints.min_tanimoto - 0.10),
            prob_max=safe_prob_max,
            logp_delta_max=constraints.logp_delta_max + 0.75,
            sa_max=constraints.sa_max + 0.5,
            require_delta=False,
            delta_min=0.0,
            mode="flip",
        )
        attempts.append({"tier": "relaxed_flip", "counts": counts})
        if logger:
            logger.info("CF filtering (relaxed flip): %s", counts)

    # Tier C: risk reduction (relaxed filters, require delta_p >= delta_min)
    if not rows:
        rows, counts = _filter_candidates(
            min_tanimoto=max(0.55, constraints.min_tanimoto - 0.10),
            prob_max=None,  # allow above threshold but require risk reduction
            logp_delta_max=constraints.logp_delta_max + 0.75,
            sa_max=constraints.sa_max + 0.5,
            require_delta=True,
            delta_min=delta_min,
            mode="risk_reduction",
        )
        attempts.append({"tier": "risk_reduction", "counts": counts})
        if logger:
            logger.info("CF filtering (risk reduction): %s", counts)

    # Final fallback: any chem-valid candidates ranked by delta_p
    weak_rows: List[Dict[str, Any]] = []
    if not rows:
        weak_rows, weak_counts = _filter_candidates(
            min_tanimoto=max(0.55, constraints.min_tanimoto - 0.10),
            prob_max=None,
            logp_delta_max=constraints.logp_delta_max + 0.75,
            sa_max=constraints.sa_max + 0.5,
            require_delta=False,
            delta_min=0.0,
            mode="weak_reduction",
        )
        attempts.append({"tier": "weak_reduction", "counts": weak_counts})
        if logger:
            logger.info("CF filtering (weak reduction): %s", weak_counts)
        rows = weak_rows

    rows = _dedupe_by_smiles(rows)

    # rank: high sim, high risk drop; simple linear score
    rows.sort(key=lambda r: (r["delta_p"], r["similarity"]), reverse=True)
    rows = rows[:nmols]

    diag = {
        "target_prob_max": float(safe_prob_max),
        "attempts": attempts,
        "final_tier": attempts[-1]["tier"] if attempts else "none",
        "final_count": len(rows),
    }
    return rows, diag


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
    cf_summary: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a single-molecule lead optimization report as Markdown + PNG images."""
    out_dir.mkdir(parents=True, exist_ok=True)
    depict_smiles(base_smiles, out_dir / "base.png")

    for i, cf in enumerate(counterfactuals, start=1):
        depict_smiles(cf["smiles"], out_dir / f"cf_{i:02d}.png")

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

    md.append("\n## Counterfactual suggestions (filtered)\n")
    if not counterfactuals:
        md.append("_No valid counterfactuals found under current constraints._\n")
    else:
        md.append("| Rank | Image | Similarity | p(toxic) | Δp | LogP | QED | SA | Mode |\n")
        md.append("|---:|:---:|---:|---:|---:|---:|---:|---:|---|\n")
        for i, cf in enumerate(counterfactuals, start=1):
            img = f"cf_{i:02d}.png"
            md.append(
                f"| {i} | ![]({img}) | {cf['similarity']:.3f} | {cf['p']:.3f} | {cf['delta_p']:.3f} | "
                f"{cf['logp']:.2f} | {cf['qed']:.2f} | {cf['sascore']:.2f} | {cf.get('mode','')} |\n"
            )
        md.append("\n### Raw counterfactual records\n")
        md.append("```json\n")
        md.append(json.dumps(counterfactuals, indent=2))
        md.append("\n```\n")

    md.append("\n## CF generation summary\n")
    if cf_summary:
        md.append(f"- Target prob max: {cf_summary.get('target_prob_max', 'n/a')}\n")
        md.append(f"- Final tier: {cf_summary.get('final_tier', 'n/a')} (kept {cf_summary.get('final_count', 0)})\n")
        attempts = cf_summary.get("attempts", [])
        if attempts:
            md.append("- Filter counts by tier:\n")
            for a in attempts:
                md.append(f"  - {a.get('tier')}: {a.get('counts')}\n")
    else:
        md.append("- No CF diagnostics available.\n")

    (out_dir / "report.md").write_text("".join(md), encoding="utf-8")
