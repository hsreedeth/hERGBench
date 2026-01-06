import sys
import types
from dataclasses import dataclass

import pytest
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from hergbench.reporting import lead_opt as lo


# ----------------------------
# Helpers (offline, deterministic)
# ----------------------------

def _fp_bitvect(mol) -> "rdkit.DataStructs.cDataStructs.ExplicitBitVect":
    # Stable bitvect fingerprint for tests, independent of FingerprintConfig.
    return rdMolDescriptors.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)


def _install_dummy_exmol(monkeypatch, examples, record, call_f=False):
    class DummyExMol:
        @staticmethod
        def get_basic_alphabet():
            return ["C", "O", "N", "Cl", "Br", "F"]

        @staticmethod
        def sample_space(**kwargs):
            record["sample_space_kwargs"] = dict(kwargs)
            for k in ("origin_smiles", "smiles", "base"):
                if k in kwargs:
                    record["sample_space_base"] = kwargs[k]
                    break
            else:
                # Fallback: if only one kwarg is present (e.g., bare **kwargs), record its value.
                if len(kwargs) == 1:
                    record["sample_space_base"] = next(iter(kwargs.values()))

            # IMPORTANT: by default do NOT call f/model_prob during sampling in unit tests.
            if call_f:
                f = kwargs.get("f") or kwargs.get("model") or kwargs.get("model_class")
                if callable(f):
                    # emulate ExMol calling the scorer on the candidate set
                    smiles = [e["smiles"] if isinstance(e, dict) else getattr(e, "smiles") for e in examples]
                    f(smiles)

            return list(examples)

        @staticmethod
        def cf_explain(space, **kwargs):
            return list(space)

    monkeypatch.setitem(sys.modules, "exmol", DummyExMol)



def _patch_core_scoring(monkeypatch, *, std_map, prob_map, prob_calls, props=None, alerts=False):
    """
    Patch:
      - _std_for_scoring: deterministic mapping (raw -> std)
      - mol_to_ecfp_bits: fixed Morgan bitvect
      - mol_props: deterministic physchem/SA
      - has_structural_alerts: deterministic
    """
    def _std_for_scoring(raw_smi):
        std = std_map.get(raw_smi)
        if std is None:
            return None, None
        m = Chem.MolFromSmiles(std)
        if m is None:
            return None, None
        return std, m

    def _model_prob(smi):
        prob_calls.append(smi)
        return float(prob_map.get(smi, 0.9))

    # Default props: always pass constraints unless test overrides.
    if props is None:
        def _mol_props(_mol, **_kwargs):
            return {"logp": 2.0, "qed": 0.6, "sascore": 2.0}
    else:
        def _mol_props(_mol, **_kwargs):
            return dict(props)

    monkeypatch.setattr(lo, "_std_for_scoring", _std_for_scoring, raising=True)
    monkeypatch.setattr(lo, "mol_to_ecfp_bits", lambda mol, _cfg=None: _fp_bitvect(mol), raising=True)
    monkeypatch.setattr(lo, "mol_props", _mol_props, raising=True)
    monkeypatch.setattr(lo, "has_structural_alerts", lambda _mol: bool(alerts), raising=True)

    return _model_prob


# ----------------------------
# Tests: Standardization & ionization artifact exclusion
# ----------------------------

def test_tier123_filters_ionization_variants_and_scores_on_standardized_identity(monkeypatch):
    """
    If a candidate standardizes to the base identity, it must be excluded (ionization/protonation artifact).
    model_prob must only see standardized SMILES.
    """
    prob_calls = []

    # Base raw is ionic, base std is neutral.
    std_map = {
        "CC[O-]": "CCO",      # base raw -> base std
        "CCO": "CCO",         # candidate collapses to base
        "CCCO": "CCCO",       # real edit
        "CCCO_dup": "CCCO",   # duplicates on std identity
    }
    prob_map = {
        "CCO": 0.80,    # base p
        "CCCO": 0.20,   # safe (flip)
    }
    model_prob = _patch_core_scoring(
        monkeypatch,
        std_map=std_map,
        prob_map=prob_map,
        prob_calls=prob_calls,
    )

    # Dummy ExMol returns a collapsing candidate + a real candidate + a duplicate (on standardized identity)
    record = {}
    _install_dummy_exmol(
        monkeypatch,
        examples=[{"smiles": "CCO"}, {"smiles": "CCCO"}, {"smiles": "CCCO_dup"}],
        record=record,
    )

    rows, diag = lo.generate_counterfactuals_exmol(
        base_smiles="CC[O-]",
        model_class=lambda s: int(model_prob(s) >= 0.5),
        model_prob=model_prob,
        fp_cfg=object(),
        constraints=lo.CFConstraints(min_tanimoto=0.1, sa_max=4.5, pains=False),
        safe_prob_max=0.30,
        nmols=5,
        exmol_n_samples=50,
        search_nmols=10,
        logger=None,
    )

    assert diag["final_tier"] == "flip"
    assert len(rows) == 1
    assert rows[0]["smiles"] == "CCCO"
    assert rows[0]["raw_smiles"] in ("CCCO", "CCCO_dup")

    # Crucial: model_prob only ever sees standardized identities.
    assert "CC[O-]" not in prob_calls
    # Base is scored on standardized base identity
    assert prob_calls[0] == "CCO"
    # Candidate scored on standardized candidate identity
    assert "CCCO" in prob_calls


def test_tier4_dedupes_on_standardized_identity_and_skips_collapsing_variants(monkeypatch):
    """
    Tier 4 must:
      - standardize first
      - skip if std == base_std
      - dedupe on std_smi
      - compute p once per kept std identity
    """
    prob_calls = []
    std_map = {
        "CC[O-]": "CCO",       # base raw -> base std
        "CCO": "CCO",          # collapses to base -> must be skipped
        "CCC[O-]": "CCCO",     # candidate raw ionic -> std real
        "CCCO": "CCCO",        # duplicate on std identity
        "CCCCO": "CCCCO",
    }
    prob_map = {"CCO": 0.80, "CCCO": 0.70, "CCCCO": 0.60}

    model_prob = _patch_core_scoring(
        monkeypatch,
        std_map=std_map,
        prob_map=prob_map,
        prob_calls=prob_calls,
    )

    record = {}
    _install_dummy_exmol(
        monkeypatch,
        examples=[{"smiles": "CCO"}, {"smiles": "CCC[O-]"}, {"smiles": "CCCO"}, {"smiles": "CCCCO"}],
        record=record,
        call_f=False,
)


    # Force similarity to fail for Tier 1–3 deterministically, so Tier 4 is used.
    monkeypatch.setattr(lo.DataStructs, "TanimotoSimilarity", lambda *_args, **_kwargs: 0.0, raising=True)


    # Force tiers 1–3 to fail (very high similarity threshold), so Tier 4 is used.
    rows, diag = lo.generate_counterfactuals_exmol(
        base_smiles="CC[O-]",
        model_class=lambda s: int(model_prob(s) >= 0.5),
        model_prob=model_prob,
        fp_cfg=object(),
        constraints=lo.CFConstraints(min_tanimoto_flip=0.999, min_tanimoto_improve=0.999, sa_max=4.5, pains=False),
        safe_prob_max=0.01,
        nmols=5,
        exmol_n_samples=50,
        search_nmols=10,
        logger=None,
    )

    assert diag["final_tier"] == "diagnostic_close_edits"
    assert all(r["tier"] == "diagnostic_close_edits" for r in rows)

    # No row may collapse to base standardized identity
    assert all(r["smiles"] != "CCO" for r in rows)

    # Deduped on standardized identity => only one "CCCO"
    stds = [r["smiles"] for r in rows]
    assert stds.count("CCCO") == 1

    # model_prob calls: base_std once + p once per kept std identity (duplicates skipped before scoring)
    # Base is always scored first.
    assert prob_calls[0] == "CCO"
    assert prob_calls.count("CCCO") == 1


def test_tier4_does_not_override_successful_tier1(monkeypatch):
    """
    If Tier 1 succeeds, Tier 4 must not run / must not overwrite final_rows.
    """
    prob_calls = []
    std_map = {"CC[O-]": "CCO", "CCCO": "CCCO"}
    prob_map = {"CCO": 0.80, "CCCO": 0.20}

    model_prob = _patch_core_scoring(
        monkeypatch,
        std_map=std_map,
        prob_map=prob_map,
        prob_calls=prob_calls,
    )

    record = {}
    _install_dummy_exmol(monkeypatch, examples=[{"smiles": "CCCO"}], record=record)

    rows, diag = lo.generate_counterfactuals_exmol(
        base_smiles="CC[O-]",
        model_class=lambda s: int(model_prob(s) >= 0.5),
        model_prob=model_prob,
        fp_cfg=object(),
        constraints=lo.CFConstraints(min_tanimoto=0.1, sa_max=4.5, pains=False),
        safe_prob_max=0.30,
        nmols=5,
        exmol_n_samples=50,
        search_nmols=10,
        logger=None,
    )

    assert diag["final_tier"] == "flip"
    assert rows and all(r["tier"] == "flip" for r in rows)


def test_exmol_sampling_receives_standardized_base_and_scoring_standardizes_inputs(monkeypatch):
    """
    Two requirements:
      1) sample_space must be called with base_std_smi (not base raw)
      2) the scoring function passed to ExMol must call model_prob on standardized identities
    """
    prob_calls = []
    std_map = {"CC[O-]": "CCO", "CCC[O-]": "CCCO", "CCO": "CCO", "CCCO": "CCCO"}
    prob_map = {"CCO": 0.80, "CCCO": 0.20}

    model_prob = _patch_core_scoring(
        monkeypatch,
        std_map=std_map,
        prob_map=prob_map,
        prob_calls=prob_calls,
    )

    record = {}
    _install_dummy_exmol(monkeypatch, examples=[{"smiles": "CCC[O-]"}], record=record, call_f=True)

    lo.generate_counterfactuals_exmol(
        base_smiles="CC[O-]",
        model_class=lambda s: int(model_prob(s) >= 0.5),
        model_prob=model_prob,
        fp_cfg=object(),
        constraints=lo.CFConstraints(min_tanimoto=0.1, sa_max=4.5, pains=False),
        safe_prob_max=0.30,
        nmols=5,
        exmol_n_samples=50,
        search_nmols=10,
        logger=None,
    )

    assert record["sample_space_base"] == "CCO"  # standardized base identity
    # ExMol scoring wrapper should have called model_prob on standardized "CCCO" (from raw "CCC[O-]").
    assert "CCCO" in prob_calls


# ----------------------------
# Tests: dataset_analogues identity integrity + constraint wiring
# ----------------------------

def test_dataset_analogues_skips_rows_if_standardization_changes_identity(monkeypatch):
    """
    If std_smi != raw_smi, we must skip to avoid mixing dataset_fps/probs belonging to raw identity.
    """
    prob_calls = []  # unused here

    std_map = {
        "CCO": "CCO",        # base
        "CC[O-]": "CCO",     # would change identity => must be skipped
        "CCCO": "CCCO",      # unchanged => allowed
    }
    # Not used, but required by patch helper.
    prob_map = {"CCO": 0.8}

    _patch_core_scoring(
        monkeypatch,
        std_map=std_map,
        prob_map=prob_map,
        prob_calls=prob_calls,
    )

    base_m = Chem.MolFromSmiles("CCO")
    base_fp = _fp_bitvect(base_m)

    ds_smiles = ["CC[O-]", "CCCO"]
    ds_fps = [_fp_bitvect(Chem.MolFromSmiles(s)) for s in ds_smiles]
    ds_probs = [0.10, 0.20]

    out = lo.dataset_analogues(
        base_smiles="CCO",
        base_fp=base_fp,
        base_p=0.8,
        dataset_smiles=ds_smiles,
        dataset_fps=ds_fps,
        dataset_probs=ds_probs,
        fp_cfg=None,
        constraints=lo.CFConstraints(sa_max=4.5, pains=False),
        top_k=5,
    )

    # Must not include the row whose standardized identity differs from raw.
    assert all(r["smiles"] != "CC[O-]" for r in out)
    assert any(r["smiles"] == "CCCO" for r in out)


def test_dataset_analogues_marks_actionable_using_constraints(monkeypatch):
    """
    dataset_analogues is context-only but must compute 'actionable' consistently with constraints.
    """
    prob_calls = []

    std_map = {"CCO": "CCO", "CCCO": "CCCO"}
    prob_map = {"CCO": 0.8}

    # Force high SA to make it non-actionable under strict sa_max.
    model_prob = _patch_core_scoring(
        monkeypatch,
        std_map=std_map,
        prob_map=prob_map,
        prob_calls=prob_calls,
        props={"logp": 2.0, "qed": 0.6, "sascore": 8.0},
        alerts=False,
    )

    base_m = Chem.MolFromSmiles("CCO")
    base_fp = _fp_bitvect(base_m)

    out = lo.dataset_analogues(
        base_smiles="CCO",
        base_fp=base_fp,
        base_p=0.8,
        dataset_smiles=["CCCO"],
        dataset_fps=[_fp_bitvect(Chem.MolFromSmiles("CCCO"))],
        dataset_probs=[0.2],
        fp_cfg=None,
        constraints=lo.CFConstraints(sa_max=4.5, pains=False),
        top_k=5,
    )

    assert len(out) == 1
    assert out[0]["sascore"] == 8.0
    assert out[0]["actionable"] is False  # SA violates sa_max


# ----------------------------
# Tests: relaxation plan validation
# ----------------------------

def test_relaxation_plan_rejects_multiple_updates(monkeypatch):
    prob_calls = []
    std_map = {"CCO": "CCO"}
    prob_map = {"CCO": 0.8}
    model_prob = _patch_core_scoring(monkeypatch, std_map=std_map, prob_map=prob_map, prob_calls=prob_calls)

    record = {}
    _install_dummy_exmol(monkeypatch, examples=[], record=record)

    with pytest.raises(ValueError, match="only one constraint"):
        lo.generate_counterfactuals_exmol(
            base_smiles="CCO",
            model_class=lambda s: int(model_prob(s) >= 0.5),
            model_prob=model_prob,
            fp_cfg=object(),
            constraints=lo.CFConstraints(pains=False),
            relaxation_plan=[{"name": "bad", "updates": {"sa_max": 5.5, "min_tanimoto_flip": 0.4}}],
            search_nmols=10,
        )


# ----------------------------
# Tests: reporting fail-fast tier mismatch
# ----------------------------

def test_write_lead_report_raises_on_tier_mismatch(monkeypatch, tmp_path):
    # Avoid RDKit image writing in unit tests
    monkeypatch.setattr(lo, "depict_smiles", lambda *_args, **_kwargs: None, raising=True)

    out_dir = tmp_path / "rep"

    counterfactuals = [
        {"smiles": "CCCO", "similarity": 0.9, "p": 0.2, "delta_p": 0.6, "logp": 2.0, "qed": 0.6, "sascore": 2.0,
         "alert": False, "tier": "flip", "tier_label": "Tier 1 — Flip", "relaxation": "none", "relaxation_desc": "baseline"}
    ]

    cf_summary = {"final_tier": "risk_reduction", "final_tier_label": "Tier 2 — Risk reduction", "final_relaxation": "none"}

    with pytest.raises(ValueError, match="Report tier mismatch"):
        lo.write_lead_report(
            out_dir=out_dir,
            mol_id="X",
            base_smiles="CCO",
            y_true=1,
            p_cal=0.8,
            threshold=0.5,
            max_sim=0.9,
            sim_bin="in-domain",
            counterfactuals=counterfactuals,
            dataset_analogues=[],
            cf_summary=cf_summary,
        )
