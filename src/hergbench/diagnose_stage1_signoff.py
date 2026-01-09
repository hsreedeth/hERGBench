from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd
import yaml


def _median(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else 0.5 * (s[mid - 1] + s[mid])


def _load_cfg(run_dir: Path) -> Dict:
    cfg_path = run_dir / "config.resolved.yaml"
    with cfg_path.open() as f:
        return yaml.safe_load(f)


def _tier_num(cf: Dict) -> int:
    if "tier_num_std" in cf:
        return int(cf["tier_num_std"])
    lbl = str(cf.get("tier") or cf.get("tier_label") or "diagnostic_close_edits")
    inv = {"flip": 1, "risk_reduction": 2, "weak_improvement": 3, "diagnostic_close_edits": 4}
    return inv.get(lbl, 4)


def _check_tier(cf: Dict, thresh: float, deltas: Tuple[float, float], sim_floor: Tuple[float, float, float], cons) -> List[str]:
    out = []
    t = _tier_num(cf)
    p = float(cf.get("p") or cf.get("p_std") or 1.0)
    dp = float(cf.get("delta_p") or cf.get("delta_p_std") or 0.0)
    sim = float(cf.get("similarity") or cf.get("similarity_to_train") or 0.0)
    alert = bool(cf.get("alert", False))
    sas = cf.get("sascore", None)
    sa = float(sas) if sas is not None else None
    min_base, min_flip, min_imp = sim_floor
    if t == 1 and p >= (thresh - 1e-6):
        out.append(f"tier1_p_violation p={p:.4f}>=thr={thresh:.4f}")
    if t == 2 and dp < deltas[0]:
        out.append(f"tier2_delta_violation dp={dp:.4f}<delta_min={deltas[0]:.4f}")
    if t == 3 and dp < deltas[1]:
        out.append(f"tier3_delta_violation dp={dp:.4f}<delta_min_tier3={deltas[1]:.4f}")
    sim_req = min_base
    if t == 1:
        sim_req = min_flip
    if t in (2, 3):
        sim_req = min_imp
    if t in (1, 2, 3) and sim < sim_req:
        out.append(f"sim_violation sim={sim:.4f}<req={sim_req:.4f}")
    if t in (1, 2, 3) and cons.pains and alert:
        out.append("pains_violation")
    if t in (1, 2, 3) and sa is not None and sa > cons.sa_max:
        out.append(f"sa_violation sa={sa:.4f}>max={cons.sa_max}")
    if t in (1, 2, 3) and cons.qed_min and float(cf.get("qed", 0.0)) < cons.qed_min:
        out.append(f"qed_violation qed={float(cf.get('qed',0.0)):.4f}<min={cons.qed_min}")
    return out


def diagnose(run_dir: Path, signoff_root: Path, panel_csv: Path, lead_reports_dir: Path):
    cfg = _load_cfg(run_dir)
    cf_cfg = cfg["stage1"]["counterfactuals"]
    delta_min = float(cf_cfg.get("delta_min", 0.10))
    delta_min_t3 = float(cf_cfg.get("delta_min_tier3", 0.05))
    cons_raw = cf_cfg.get("constraints", {})
    from hergbench.reporting.lead_opt import CFConstraints

    cons = CFConstraints(
        min_tanimoto=float(cons_raw.get("min_tanimoto", 0.7)),
        min_tanimoto_flip=cons_raw.get("min_tanimoto_flip"),
        min_tanimoto_improve=cons_raw.get("min_tanimoto_improve"),
        sa_max=float(cons_raw.get("sa_max", 4.5)),
        logp_delta_max=float(cons_raw.get("logp_delta_max", 1.5)),
        qed_min=float(cons_raw.get("qed_min", 0.0)),
        pains=bool(cons_raw.get("pains", True)),
    )
    min_base = cons.min_tanimoto or 0.0
    min_flip = cons.min_tanimoto_flip if cons.min_tanimoto_flip is not None else min_base
    min_imp = cons.min_tanimoto_improve if cons.min_tanimoto_improve is not None else min_base

    panel = pd.read_csv(panel_csv)
    if "mol_id" in panel.columns:
        panel_ids = panel["mol_id"].astype(str).tolist()
        id_col = "mol_id"
    elif "smiles" in panel.columns:
        # Fallback to smiles-based ID if mol_id absent; warn via summary later.
        panel_ids = panel["smiles"].astype(str).tolist()
        id_col = "smiles"
    else:
        raise ValueError(f"Panel missing required identifier column (mol_id or smiles). Columns={list(panel.columns)}")
    uniq_ids = len(panel_ids) == len(set(panel_ids))

    rep_map = {}
    for jp in lead_reports_dir.rglob("report.json"):
        try:
            data = json.loads(jp.read_text())
        except Exception:
            continue
        rep_map[jp.parent.name] = data

    diag_rows = []
    tier_viol = 0
    cf_summary_mismatch = 0
    fallback_issue = 0
    report_missing = 0

    for _, row in panel.iterrows():
        mol_id = str(row[id_col])
        report_found = mol_id in rep_map
        violations: List[str] = []
        summary_mis = False
        fallback_mis = False
        if not report_found:
            report_missing += 1
        else:
            data = rep_map[mol_id]
            cfs = data.get("counterfactuals", [])
            cf_sum = dict(data.get("cf_summary", {}))
            thresh = float(data.get("threshold", 0.5))
            # per-CF checks
            tier_nums = []
            tier123 = []
            for i, cf in enumerate(cfs):
                v = _check_tier(cf, thresh, (delta_min, delta_min_t3), (min_base, min_flip, min_imp), cons)
                if v:
                    violations.extend([f"cf[{i}] {msg}" for msg in v])
                tnum = _tier_num(cf)
                tier_nums.append(tnum)
                if tnum in (1, 2, 3):
                    tier123.append(cf)
            best_tier = min(tier_nums) if tier_nums else 4
            if cf_sum:
                if int(cf_sum.get("final_best_tier_num", best_tier)) != best_tier:
                    summary_mis = True
                if int(cf_sum.get("final_count_total", len(cfs))) != len(cfs):
                    summary_mis = True
                if int(cf_sum.get("final_count_tier123", len(tier123))) != len(tier123):
                    summary_mis = True
            if cf_sum.get("dataset_fallback_used"):
                if len(tier123) > 0:
                    fallback_mis = True
            tier_viol += len(violations)
            if summary_mis:
                cf_summary_mismatch += 1
            if fallback_mis:
                fallback_issue += 1
        diag_rows.append(
            {
                "mol_id": mol_id,
                "report_found": report_found,
                "violations": ";".join(violations),
                "cf_summary_mismatch": summary_mis if report_found else None,
                "fallback_issue": fallback_mis if report_found else None,
            }
        )

    diag_df = pd.DataFrame(diag_rows)
    out_dir = signoff_root / "outputs" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    diag_df.to_csv(out_dir / "per_molecule_diagnostics.csv", index=False)

    summary_lines = []
    summary_lines.append(f"Panel size: {len(panel)}")
    summary_lines.append(f"Unique mol_id: {uniq_ids}")
    summary_lines.append(f"Reports found: {len(panel)-report_missing}/{len(panel)}")
    summary_lines.append(f"Tier violations: {tier_viol}")
    summary_lines.append(f"cf_summary mismatches: {cf_summary_mismatch}")
    summary_lines.append(f"fallback inconsistencies: {fallback_issue}")
    (out_dir / "diagnostic_summary.txt").write_text("\n".join(summary_lines), encoding="utf-8")
    print("\n".join(summary_lines))


def main():
    ap = argparse.ArgumentParser(description="Diagnose Stage-1 signoff consistency.")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--signoff-root", required=True)
    ap.add_argument("--panel-csv", required=True)
    ap.add_argument("--lead-reports-dir", required=True)
    args = ap.parse_args()

    diagnose(
        run_dir=Path(args.run_dir),
        signoff_root=Path(args.signoff_root),
        panel_csv=Path(args.panel_csv),
        lead_reports_dir=Path(args.lead_reports_dir),
    )


if __name__ == "__main__":
    main()
