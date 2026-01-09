import json
from pathlib import Path

import pandas as pd

# Expect this module/function to exist after your patch.
# Put it at hergbench/reporting/yield_tables.py if needed.
from hergbench.reporting.yield_tables import compute_yield_tables



def _write_report(run_dir: Path, mol_id: str, ad_bin: str, best_tier_num: int, n_tier123: int):
    lead_dir = run_dir / "lead_reports" / mol_id
    lead_dir.mkdir(parents=True, exist_ok=True)

    # Minimal valid report.json
    thr = 0.5
    tier_map = {1: "flip", 2: "risk_reduction", 3: "weak_improvement", 4: "diagnostic_close_edits"}
    report = {
        "mol_id": mol_id,
        "threshold": thr,
        "max_sim_to_train": 0.6,
        "sim_bin": ad_bin,
        "cf_summary": {
            "final_best_tier_num": best_tier_num,
            "final_tier": tier_map[best_tier_num],
            "final_tier_label": tier_map[best_tier_num],
            "final_count_total": 3,
            "final_count_tier123": n_tier123,
            "dataset_fallback_used": False,
            "dataset_fallback_count": 0,
            "scarcity": False,
        },
        "counterfactuals": [
            {
                "raw_smiles": "CCN",
                "smiles_std": "CCN",
                "tier_num_std": best_tier_num,
                "tier_label_std": tier_map[best_tier_num],
                "p_std": 0.2 if best_tier_num == 1 else 0.7,
                "delta_p_std": 0.2 if best_tier_num in (2, 3) else 0.6,
                "similarity_to_train": 0.4,
                "qed": 0.5,
                "logp": 1.0,
                "sascore": 2.0,
                "alert": False,
            }
        ],
        "dataset_analogues": [],
    }
    (lead_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def test_compute_yield_tables_from_report_json(tmp_path: Path):
    run_dir = tmp_path / "run"
    (run_dir / "tables").mkdir(parents=True, exist_ok=True)

    # Panel with 2 molecules in different AD bins
    panel_dir = run_dir / "panel"
    panel_dir.mkdir(parents=True, exist_ok=True)
    panel = pd.DataFrame(
        [
            {"mol_id": "m1", "smiles": "CCCCN", "ad_bin": "<0.3"},
            {"mol_id": "m2", "smiles": "CCN", "ad_bin": ">0.7"},
        ]
    )
    panel_csv = panel_dir / "panel.csv"
    panel.to_csv(panel_csv, index=False)

    _write_report(run_dir, "m1", "<0.3", best_tier_num=1, n_tier123=1)
    _write_report(run_dir, "m2", ">0.7", best_tier_num=4, n_tier123=0)

    per_mol, by_bin = compute_yield_tables(run_dir=run_dir, panel_csv=panel_csv)

    # Files written
    assert (run_dir / "tables" / "yield_per_molecule.csv").exists()
    assert (run_dir / "tables" / "yield_by_ad_bin.csv").exists()

    # Key columns
    for col in ["mol_id", "report_found", "best_tier_num", "best_tier_label", "tier123_success", "n_survivors_tier123"]:
        assert col in per_mol.columns

    # Sanity: m1 is success; m2 is failure
    r1 = per_mol.loc[per_mol["mol_id"] == "m1"].iloc[0]
    r2 = per_mol.loc[per_mol["mol_id"] == "m2"].iloc[0]
    assert bool(r1["report_found"]) is True
    assert bool(r1["tier123_success"]) is True
    assert int(r1["best_tier_num"]) == 1

    assert bool(r2["report_found"]) is True
    assert bool(r2["tier123_success"]) is False
    assert int(r2["best_tier_num"]) == 4
