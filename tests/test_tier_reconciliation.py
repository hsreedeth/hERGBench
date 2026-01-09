import pytest

from hergbench.reporting.lead_opt import CFConstraints

# Expect this to exist after your patch; place it in lead_opt.py if needed
from hergbench.stage1_pipeline import reconcile_tier_std


@pytest.fixture
def constraints_default():
    return CFConstraints(
        min_tanimoto=0.7,
        min_tanimoto_flip=None,
        min_tanimoto_improve=None,
        sa_max=4.5,
        logp_delta_max=1.5,
        qed_min=0.0,
        pains=True,
    )


def test_flip_when_below_threshold_and_constraints_ok(constraints_default):
    tier_num, tier_label = reconcile_tier_std(
        p_cf=0.20,
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.05,
        sim_to_train=0.90,
        constraints=constraints_default,
        alert=False,
        sascore=2.0,
    )
    assert tier_num == 1
    assert tier_label == "flip"


def test_force_tier4_if_similarity_below_min_even_if_flip(constraints_default):
    tier_num, tier_label = reconcile_tier_std(
        p_cf=0.20,          # would flip
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.05,
        sim_to_train=0.60,  # violates min_tanimoto
        constraints=constraints_default,
        alert=False,
        sascore=2.0,
    )
    assert tier_num == 4
    assert tier_label == "diagnostic_close_edits"


def test_force_tier4_if_alert_and_pains_enabled(constraints_default):
    tier_num, tier_label = reconcile_tier_std(
        p_cf=0.20,
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.05,
        sim_to_train=0.90,
        constraints=constraints_default,
        alert=True,     # PAINS triggered
        sascore=2.0,
    )
    assert tier_num == 4
    assert tier_label == "diagnostic_close_edits"


def test_force_tier4_if_sascore_exceeds_max(constraints_default):
    tier_num, tier_label = reconcile_tier_std(
        p_cf=0.20,
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.05,
        sim_to_train=0.90,
        constraints=constraints_default,
        alert=False,
        sascore=7.0,    # too hard to make
    )
    assert tier_num == 4
    assert tier_label == "diagnostic_close_edits"


def test_tier2_when_delta_meets_delta_min(constraints_default):
    tier_num, tier_label = reconcile_tier_std(
        p_cf=0.70,       # not a flip if threshold=0.5
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.05,
        sim_to_train=0.90,
        constraints=constraints_default,
        alert=False,
        sascore=2.0,
    )
    assert tier_num == 2
    assert tier_label == "risk_reduction"


def test_tier3_when_delta_meets_delta_min_tier3_only(constraints_default):
    tier_num, tier_label = reconcile_tier_std(
        p_cf=0.81,       # delta=0.04 -> tier4 if delta_min_tier3=0.05; adjust
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.03,
        sim_to_train=0.90,
        constraints=constraints_default,
        alert=False,
        sascore=2.0,
    )
    assert tier_num == 3
    assert tier_label == "weak_improvement"


def test_min_tanimoto_flip_and_improve_overrides_min_tanimoto():
    constraints = CFConstraints(
        min_tanimoto=0.7,
        min_tanimoto_flip=0.85,
        min_tanimoto_improve=0.80,
        sa_max=4.5,
        logp_delta_max=1.5,
        qed_min=0.0,
        pains=True,
    )

    # Would flip, but sim < min_tanimoto_flip -> must be tier4
    tier_num, _ = reconcile_tier_std(
        p_cf=0.20,
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.05,
        sim_to_train=0.84,
        constraints=constraints,
        alert=False,
        sascore=2.0,
    )
    assert tier_num == 4

    # Would be tier2 (delta), but sim < min_tanimoto_improve -> must be tier4
    tier_num, _ = reconcile_tier_std(
        p_cf=0.70,
        base_p=0.85,
        threshold=0.50,
        delta_min=0.10,
        delta_min_tier3=0.05,
        sim_to_train=0.79,
        constraints=constraints,
        alert=False,
        sascore=2.0,
    )
    assert tier_num == 4
