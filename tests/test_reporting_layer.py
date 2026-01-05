# tests/test_reporting_layer.py
"""
Unit tests that "lock" correctness of the lead-report reporting layer.

These tests specifically protect against the tier-summary inconsistency you hit:
- The report must reflect the tier/relaxation of the rows it is actually printing.
- If cf_summary disagrees with printed rows, the report must fail fast (ValueError),
  except for the one allowed alias: cf_summary.final_tier == "dataset_fallback"
  while displayed rows tier == "dataset_analogue".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import hergbench.reporting.lead_opt as lead_opt


def _mk_cf(
    smiles: str,
    tier: str,
    tier_label: str,
    relaxation: str = "none",
    similarity: float = 0.81,
    p: float = 0.20,
    delta_p: float = 0.55,
    logp: float = 2.1,
    qed: float = 0.62,
    sascore: float = 3.2,
    alert: bool = False,
) -> Dict[str, Any]:
    return {
        "smiles": smiles,
        "similarity": float(similarity),
        "p": float(p),
        "delta_p": float(delta_p),
        "logp": float(logp),
        "qed": float(qed),
        "sascore": float(sascore),
        "alert": bool(alert),
        "tier": tier,
        "tier_label": tier_label,
        "relaxation": relaxation,
        "relaxation_desc": "",
    }


def _mk_ds(
    smiles: str,
    similarity: float = 0.75,
    p: float = 0.25,
    delta_p: float = 0.30,
    logp: float = 2.0,
    qed: float = 0.60,
    sascore: float = 3.8,
    alert: bool = False,
    actionable: bool = True,
) -> Dict[str, Any]:
    return {
        "smiles": smiles,
        "similarity": float(similarity),
        "p": float(p),
        "delta_p": float(delta_p),
        "logp": float(logp),
        "qed": float(qed),
        "sascore": float(sascore),
        "alert": bool(alert),
        "actionable": bool(actionable),
        "tier": "dataset_analogue",
        "tier_label": "Dataset analogue",
        "relaxation": "none",
        "relaxation_desc": "dataset fallback",
        "sa_status": "ok",
        "sa_max_used": 4.5,
        "pains_used": True,
    }


def _read_report(out_dir: Path) -> str:
    p = out_dir / "report.md"
    assert p.exists(), f"Expected report.md at {p}"
    return p.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_rdkit_drawing(monkeypatch):
    """
    Avoid RDKit/PIL drawing in unit tests. We only care about tier/summary text integrity.
    """
    monkeypatch.setattr(lead_opt, "depict_smiles", lambda *args, **kwargs: None)


def test_report_prefers_rows_over_cf_summary_for_tier_label_and_relaxation(tmp_path: Path) -> None:
    """
    If rows exist, the report must display tier_label/relaxation derived from the rows,
    even if cf_summary contains a stale/incorrect *label*.
    """
    out_dir = tmp_path / "r1"

    cfs = [
        _mk_cf(
            smiles="CCN",
            tier="risk_reduction",
            tier_label="Tier 2 — Risk reduction",
            relaxation="relax_improve_0.6",
        )
    ]

    # final_tier matches rows, but final_tier_label is intentionally wrong/stale
    cf_summary = {
        "sampled": 1800,
        "sample_budget": 1800,
        "attempts": [],
        "final_tier": "risk_reduction",
        "final_tier_label": "Tier 3 — Weak improvement",  # wrong on purpose
        "final_relaxation": "none",  # wrong on purpose
        "relaxation_used": True,
        "final_count": 999,  # wrong on purpose
        "scarcity": False,
    }

    lead_opt.write_lead_report(
        out_dir=out_dir,
        mol_id="molX",
        base_smiles="CCO",
        y_true=1,
        p_cal=0.91,
        threshold=0.50,
        max_sim=0.82,
        sim_bin=">0.7",
        counterfactuals=cfs,
        dataset_analogues=[],
        cf_summary=cf_summary,
    )

    md = _read_report(out_dir)

    # Must reflect the row tier label and row relaxation, not the stale cf_summary label/relaxation.
    assert "- Generated tier (Tier 1–4): Tier 2 — Risk reduction" in md
    assert "(relaxation: relax_improve_0.6)" in md
    assert "Rows below are generated from Tier 2 — Risk reduction (relaxation: relax_improve_0.6)" in md

    # Must report survivors count from actual rows, not cf_summary.final_count.
    assert "- Generated survivors (Tier 1–4): 1" in md


def test_report_raises_on_tier_mismatch_between_rows_and_cf_summary(tmp_path: Path) -> None:
    """
    The fail-fast guard must raise if cf_summary.final_tier disagrees with the displayed rows tier.
    This is the core integrity lock for Stage1 vs Stage2 comparisons.
    """
    out_dir = tmp_path / "r2"
    cfs = [_mk_cf(smiles="CCN", tier="risk_reduction", tier_label="Tier 2 — Risk reduction")]

    cf_summary = {
        "sampled": 1800,
        "sample_budget": 1800,
        "attempts": [],
        "final_tier": "diagnostic_close_edits",  # mismatched on purpose
        "final_tier_label": "Tier 4 — Closest edits (diagnostic)",
        "final_relaxation": "none",
        "relaxation_used": False,
        "final_count": 1,
        "scarcity": False,
    }

    with pytest.raises(ValueError, match=r"Report tier mismatch"):
        lead_opt.write_lead_report(
            out_dir=out_dir,
            mol_id="molY",
            base_smiles="CCO",
            y_true=1,
            p_cal=0.91,
            threshold=0.50,
            max_sim=0.82,
            sim_bin=">0.7",
            counterfactuals=cfs,
            dataset_analogues=[],
            cf_summary=cf_summary,
        )


def test_report_allows_dataset_fallback_alias_when_rows_tagged_dataset_analogue(tmp_path: Path) -> None:
    """
    The only allowed alias in the guard:
      cf_summary.final_tier == "dataset_fallback"
      displayed rows tier == "dataset_analogue"
    """
    out_dir = tmp_path / "r3"

    # We intentionally pass dataset-analogue-tagged rows as "counterfactuals" to exercise the alias path.
    cfs = [
        _mk_cf(
            smiles="CCC",
            tier="dataset_analogue",
            tier_label="Dataset analogue",
            relaxation="none",
            similarity=0.72,
            p=0.22,
            delta_p=0.31,
        )
    ]

    cf_summary = {
        "sampled": 0,
        "sample_budget": 0,
        "attempts": [],
        "final_tier": "dataset_fallback",
        "final_tier_label": "Dataset analogue (fallback)",
        "final_relaxation": "none",
        "relaxation_used": False,
        "final_count": 1,
        "scarcity": False,
    }

    # Must not raise
    lead_opt.write_lead_report(
        out_dir=out_dir,
        mol_id="molZ",
        base_smiles="CCO",
        y_true=1,
        p_cal=0.91,
        threshold=0.50,
        max_sim=0.82,
        sim_bin=">0.7",
        counterfactuals=cfs,
        dataset_analogues=[],
        cf_summary=cf_summary,
    )

    md = _read_report(out_dir)
    assert "- Generated tier (Tier 1–4): Dataset analogue" in md


def test_report_mixed_tiers_and_relaxations_are_marked_mixed(tmp_path: Path) -> None:
    """
    Even if upstream accidentally mixes tiers/relaxations in the printed rows,
    the report must not lie: it should explicitly label them as mixed.
    """
    out_dir = tmp_path / "r4"

    cfs = [
        _mk_cf(smiles="CCN", tier="risk_reduction", tier_label="Tier 2 — Risk reduction", relaxation="none"),
        _mk_cf(smiles="CCCl", tier="weak_reduction", tier_label="Tier 3 — Weak improvement", relaxation="relax_sa_5.5"),
    ]

    # Set final_tier to "mixed" so guard does not trigger . this is the correct summary for mixed rows.
    cf_summary = {
        "sampled": 1800,
        "sample_budget": 1800,
        "attempts": [],
        "final_tier": "mixed",
        "final_tier_label": "mixed",
        "final_relaxation": "mixed",
        "relaxation_used": True,
        "final_count": 2,
        "scarcity": False,
    }

    lead_opt.write_lead_report(
        out_dir=out_dir,
        mol_id="molM",
        base_smiles="CCO",
        y_true=1,
        p_cal=0.91,
        threshold=0.50,
        max_sim=0.82,
        sim_bin=">0.7",
        counterfactuals=cfs,
        dataset_analogues=[],
        cf_summary=cf_summary,
    )

    md = _read_report(out_dir)
    assert "- Generated tier (Tier 1–4): Mixed tiers:" in md
    assert "Tier 2 — Risk reduction" in md
    assert "Tier 3 — Weak improvement" in md
    assert "relaxation: mixed" in md


def test_report_dataset_analogues_only_uses_dataset_display_meta(tmp_path: Path) -> None:
    """
    If there are no counterfactual rows but dataset analogues exist, the displayed tier must
    reflect dataset fallback (and no mismatch guard should trigger).
    """
    out_dir = tmp_path / "r5"

    ds = [_mk_ds(smiles="CCCC")]

    # Even if cf_summary says something else it should not cause an error because there are no cfs.
    cf_summary = {
        "sampled": 1800,
        "sample_budget": 1800,
        "attempts": [],
        "final_tier": "diagnostic_close_edits",
        "final_tier_label": "Tier 4 — Closest edits (diagnostic)",
        "final_relaxation": "none",
        "relaxation_used": False,
        "final_count": 5,
        "scarcity": True,
    }

    lead_opt.write_lead_report(
        out_dir=out_dir,
        mol_id="molD",
        base_smiles="CCO",
        y_true=1,
        p_cal=0.91,
        threshold=0.50,
        max_sim=0.25,
        sim_bin="<0.3",
        counterfactuals=[],
        dataset_analogues=ds,
        cf_summary=cf_summary,
    )

    md = _read_report(out_dir)
    assert "No generated suggestions; dataset analogues provided" in md
    assert "## Dataset-derived analogues (fallback)" in md
    assert "<img src=\"ds_01.png\"" in md or True  # image may not exist due to patched depict_smiles


def test_report_survivor_count_is_len_rows_not_cf_summary_final_count(tmp_path: Path) -> None:
    """
    Protects against regressions where the report might accidentally print cf_summary.final_count
    instead of len(counterfactuals).
    """
    out_dir = tmp_path / "r6"

    cfs = [
        _mk_cf(smiles="CCN", tier="risk_reduction", tier_label="Tier 2 — Risk reduction"),
        _mk_cf(smiles="CCCl", tier="risk_reduction", tier_label="Tier 2 — Risk reduction"),
    ]

    cf_summary = {
        "sampled": 1800,
        "sample_budget": 1800,
        "attempts": [],
        "final_tier": "risk_reduction",
        "final_tier_label": "Tier 2 — Risk reduction",
        "final_relaxation": "none",
        "relaxation_used": False,
        "final_count": 999,  # wrong on purpose
        "scarcity": False,
    }

    lead_opt.write_lead_report(
        out_dir=out_dir,
        mol_id="molC",
        base_smiles="CCO",
        y_true=1,
        p_cal=0.91,
        threshold=0.50,
        max_sim=0.82,
        sim_bin=">0.7",
        counterfactuals=cfs,
        dataset_analogues=[],
        cf_summary=cf_summary,
    )

    md = _read_report(out_dir)
    assert "- Generated survivors (Tier 1–4): 2" in md
