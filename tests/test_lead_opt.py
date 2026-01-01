import sys
from types import SimpleNamespace

import pytest
from rdkit import Chem

from hergbench.features.fingerprints import FingerprintConfig
from hergbench.reporting.lead_opt import CFConstraints, dataset_analogues, generate_counterfactuals_exmol


def _install_fake_exmol(monkeypatch, smiles_list):
    """Install a lightweight fake exmol module that returns a controlled candidate list."""

    class _FakeEx:
        @staticmethod
        def sample_space(base, model_class, batched=False, preset=None, use_selfies=False, quiet=True, method_kwargs=None):
            return SimpleNamespace(base=base)

        @staticmethod
        def cf_explain(space, nmols=10, filter_nondrug=False):
            return [SimpleNamespace(smiles=s) for s in smiles_list]

    monkeypatch.setitem(sys.modules, "exmol", _FakeEx)


def test_generate_counterfactuals_exmol_flip_success(monkeypatch):
    """Tier 1 flip should succeed when similarity and prob threshold satisfied."""
    base = "CCO"  # ethanol
    cand = "CCCO"  # propanol (similar >0.5)
    _install_fake_exmol(monkeypatch, [cand])
    monkeypatch.setattr("hergbench.reporting.lead_opt.DataStructs.TanimotoSimilarity", lambda a, b: 0.8)

    # Deterministic model: base high risk, candidate safe
    probs = {base: 0.9, cand: 0.1}
    model_prob = lambda smi: probs.get(smi, 0.5)
    model_class = lambda smi: int(model_prob(smi) >= 0.51)

    constraints = CFConstraints(min_tanimoto_flip=0.5, min_tanimoto_improve=0.7, sa_max=10.0)
    fp_cfg = FingerprintConfig(radius=2, n_bits=2048)
    cfs, diag = generate_counterfactuals_exmol(
        base_smiles=base,
        model_class=model_class,
        model_prob=model_prob,
        fp_cfg=fp_cfg,
        constraints=constraints,
        safe_prob_max=0.51,  # calibrated threshold
        exmol_n_samples=50,
    )
    assert diag["final_tier"] == "flip", diag
    assert diag["final_count"] == 1
    assert not diag["scarcity"]
    assert cfs[0]["smiles"] == cand


def test_generate_counterfactuals_exmol_relaxation_applied(monkeypatch):
    """When baseline similarity is too strict, relaxation should unlock a flip candidate."""
    base = "CCO"
    cand = "CCCCO"  # similarity <0.9 but >0.4
    _install_fake_exmol(monkeypatch, [cand])
    monkeypatch.setattr("hergbench.reporting.lead_opt.DataStructs.TanimotoSimilarity", lambda a, b: 0.55)

    probs = {base: 0.95, cand: 0.2}
    model_prob = lambda smi: probs.get(smi, 0.5)
    model_class = lambda smi: int(model_prob(smi) >= 0.51)

    # Force stringent baseline similarity, so relaxation is required.
    constraints = CFConstraints(min_tanimoto=0.9, min_tanimoto_flip=0.9, min_tanimoto_improve=0.9, sa_max=10.0)
    fp_cfg = FingerprintConfig(radius=2, n_bits=2048)
    cfs, diag = generate_counterfactuals_exmol(
        base_smiles=base,
        model_class=model_class,
        model_prob=model_prob,
        fp_cfg=fp_cfg,
        constraints=constraints,
        safe_prob_max=0.51,
        exmol_n_samples=50,
    )
    assert diag["relaxation_used"] is True, diag
    assert diag["final_tier"] == "flip", diag
    assert diag["final_count"] == 1
    # Ensure we lowered similarity at least once (to the relaxed 0.5 floor)
    min_used = [a["counts"]["min_tanimoto_used"] for a in diag["attempts"] if a["counts"]["kept"] > 0]
    assert min_used and min(min_used) <= 0.5
    assert cfs[0]["smiles"] == cand


def test_dataset_analogues_fallback_ordering():
    """Dataset analogue fallback returns lowest-risk similar molecules first."""
    base = "CCO"
    base_fp = Chem.RDKFingerprint(Chem.MolFromSmiles(base))
    dataset_smiles = ["CCCO", "CCCC", "Cl"]
    dataset_fps = [Chem.RDKFingerprint(Chem.MolFromSmiles(s)) for s in dataset_smiles]
    dataset_probs = [0.2, 0.8, 0.1]

    analogues = dataset_analogues(
        base_smiles=base,
        base_fp=base_fp,
        base_p=0.9,
        dataset_smiles=dataset_smiles,
        dataset_fps=dataset_fps,
        dataset_probs=dataset_probs,
        fp_cfg=None,
        top_k=2,
        min_sim=0.0,
    )

    assert len(analogues) == 2
    # Lowest predicted risk that is reasonably similar should come first
    assert analogues[0]["smiles"] in {"CCCO", "Cl"}
    assert analogues[0]["p"] <= analogues[1]["p"]
