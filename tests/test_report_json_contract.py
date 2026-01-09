import json
from pathlib import Path

import numpy as np
from hergbench.reporting.lead_opt import write_lead_report


def _assert_cf_invariants(report: dict):
    thr = float(report["threshold"])

    for cf in report.get("counterfactuals", []):
        tier = cf.get("tier_label_std")
        p = cf.get("p_std")
        dp = cf.get("delta_p_std")

        # Missing values should never happen in a final report.json
        assert tier is not None
        assert p is not None
        assert dp is not None

        if tier == "flip":
            assert float(p) < thr
        elif tier == "risk_reduction":
            assert float(p) >= thr
            # dp must be >= delta_min (cannot assert exact without config; enforce sign at least)
            assert float(dp) > 0.0
        elif tier == "weak_improvement":
            assert float(p) >= thr
            assert float(dp) > 0.0
        elif tier == "diagnostic_close_edits":
            # no strict numeric requirement besides being the "else" bucket
            pass
        else:
            raise AssertionError(f"Unknown tier_label_std: {tier}")


def test_write_lead_report_emits_report_json(tmp_path: Path):
    out_dir = tmp_path / "lead_reports" / "mol123"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Minimal realistic example: standardized fields + raw provenance.
    counterfactuals = [
        {
            "raw_smiles": "CCN",
            "smiles": "CCN",  # std
            "tier_raw": "flip",
            "p_raw": 0.2,
            "delta_p_raw": 0.6,
            "tier_num_std": 1,
            "tier_label_std": "flip",
            "p": 0.2,
            "delta_p": 0.6,
            "similarity": 0.9,
            "qed": 0.5,
            "logp": 1.0,
            "sascore": 2.0,
            "alert": False,
        }
    ]

    cf_summary = {
        "final_best_tier_num": 1,
        "final_tier": "flip",
        "final_tier_label": "flip",
        "final_count_total": 1,
        "final_count_tier123": 1,
        "dataset_fallback_used": False,
        "dataset_fallback_count": 0,
        "scarcity": False,
    }

    write_lead_report(
        out_dir=out_dir,
        mol_id="mol123",
        base_smiles="CCCCN",
        y_true=1,
        p_cal=0.8,
        threshold=0.5,
        max_sim=0.6,
        sim_bin="0.5-0.7",
        counterfactuals=counterfactuals,
        dataset_analogues=[],
        cf_summary=cf_summary,
    )

    md_path = out_dir / "report.md"
    json_path = out_dir / "report.json"
    assert md_path.exists(), "report.md not written"
    assert json_path.exists(), "report.json not written"

    report = json.loads(json_path.read_text(encoding="utf-8"))

    # Required top-level keys for downstream yield computation
    for k in [
        "mol_id",
        "threshold",
        "cf_summary",
        "counterfactuals",
        "dataset_analogues",
    ]:
        assert k in report, f"Missing key in report.json: {k}"

    _assert_cf_invariants(report)
