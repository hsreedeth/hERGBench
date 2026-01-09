from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _bin_similarity(max_sim: float, bins: List[float]) -> str:
    if max_sim < bins[0]:
        return f"<{bins[0]}"
    if max_sim < bins[1]:
        return f"{bins[0]}-{bins[1]}"
    if max_sim < bins[2]:
        return f"{bins[1]}-{bins[2]}"
    return f">{bins[2]}"


def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if np.isnan(v):
            return None
        return v
    except Exception:
        return None


def _load_report_json(report_json_path: Path) -> Dict[str, Any]:
    return json.loads(report_json_path.read_text(encoding="utf-8"))


def compute_yield_tables(
    run_dir: Path,
    panel_csv: Path,
    *,
    lead_reports_dir: Optional[Path] = None,
    eval_bins: List[float] = (0.3, 0.5, 0.7),
    write_outputs: bool = True,
    out_dir: Optional[Path] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute:
      1) yield_per_molecule.csv
      2) yield_by_ad_bin.csv

    Source of truth:
      - panel CSV for membership + max_sim_to_train (or compute bin if present)
      - report.json per mol_id for standardized tiers and counts

    Assumptions about report.json:
      - top-level keys: mol_id, base_smiles (or base_smiles_raw), threshold, max_sim_to_train (optional),
        cf_summary (dict), counterfactuals (list)
      - cf_summary includes:
          final_best_tier_num
          final_count_total
          final_count_tier123
          dataset_fallback_used
    """
    run_dir = Path(run_dir)
    panel_csv = Path(panel_csv)
    lead_reports_dir = Path(lead_reports_dir) if lead_reports_dir else (run_dir / "lead_reports")

    panel = pd.read_csv(panel_csv)
    if "mol_id" not in panel.columns:
        raise ValueError("panel_csv must contain 'mol_id' (preferred for stable report lookup).")

    # Ensure AD bin exists
    if "ad_bin" not in panel.columns:
        if "max_sim_to_train" not in panel.columns:
            raise ValueError("panel_csv must include 'max_sim_to_train' if 'ad_bin' not present.")
        panel["ad_bin"] = panel["max_sim_to_train"].astype(float).apply(lambda s: _bin_similarity(float(s), list(eval_bins)))

    rows: List[Dict[str, Any]] = []
    for _, r in panel.iterrows():
        mol_id = str(r["mol_id"])
        smi = str(r["smiles"]) if "smiles" in panel.columns else ""
        y = int(r["label"]) if "label" in panel.columns else (int(r["y"]) if "y" in panel.columns else None)
        max_sim = _safe_float(r.get("max_sim_to_train", None))
        ad_bin = str(r["ad_bin"])

        report_json = lead_reports_dir / mol_id / "report.json"
        report_found = report_json.exists()

        best_tier_num = None
        best_tier_label = None
        tier123_success = False
        n_survivors_total = 0
        n_survivors_tier123 = 0
        median_cf_similarity = None
        median_delta_p = None
        min_p = None

        if report_found:
            rep = _load_report_json(report_json)

            # Prefer cf_summary if present (fast + canonical)
            cf_summary = rep.get("cf_summary", {}) or {}
            best_tier_num = cf_summary.get("final_best_tier_num", None)
            n_survivors_total = int(cf_summary.get("final_count_total", 0) or 0)
            n_survivors_tier123 = int(cf_summary.get("final_count_tier123", 0) or 0)
            tier123_success = bool((best_tier_num is not None) and int(best_tier_num) in (1, 2, 3) and n_survivors_tier123 > 0)

            # If you store label, use it; else map numeric
            tier_map = {1: "flip", 2: "risk_reduction", 3: "weak_improvement", 4: "diagnostic_close_edits"}
            if best_tier_num is not None:
                best_tier_label = tier_map.get(int(best_tier_num), None)

            # Compute medians from standardized Tier1–3 CFs (authoritative)
            cfs = rep.get("counterfactuals", []) or []
            cf_t123 = []
            for cf in cfs:
                tnum = cf.get("tier_num_std", None)
                if tnum is None:
                    # fall back to tier label if that’s what you stored
                    tlabel = cf.get("tier_label_std", cf.get("tier", None))
                    tnum = {"flip": 1, "risk_reduction": 2, "weak_improvement": 3, "diagnostic_close_edits": 4}.get(tlabel, None)
                if tnum in (1, 2, 3):
                    cf_t123.append(cf)

            if cf_t123:
                sims = [_safe_float(cf.get("similarity", cf.get("similarity_to_train", None))) for cf in cf_t123]
                deltas = [_safe_float(cf.get("delta_p", cf.get("delta_p_std", None))) for cf in cf_t123]
                ps = [_safe_float(cf.get("p", cf.get("p_std", None))) for cf in cf_t123]

                sims = [x for x in sims if x is not None]
                deltas = [x for x in deltas if x is not None]
                ps = [x for x in ps if x is not None]

                median_cf_similarity = float(np.median(sims)) if sims else None
                median_delta_p = float(np.median(deltas)) if deltas else None
                min_p = float(np.min(ps)) if ps else None

        rows.append(
            {
                "mol_id": mol_id,
                "smiles": smi,
                "label": y,
                "max_sim_to_train": max_sim,
                "ad_bin": ad_bin,
                "report_found": bool(report_found),
                "best_tier_num": best_tier_num,
                "best_tier_label": best_tier_label,
                "tier123_success": bool(tier123_success),
                "n_survivors_total": int(n_survivors_total),
                "n_survivors_tier123": int(n_survivors_tier123),
                "median_cf_similarity": median_cf_similarity,
                "median_delta_p": median_delta_p,
                "min_p": min_p,
            }
        )

    df_mol = pd.DataFrame(rows)

    # Aggregate by AD bin
    out_rows = []
    for ad_bin, g in df_mol.groupby("ad_bin", dropna=False):
        n_panel = int(len(g))
        n_with_reports = int(g["report_found"].sum())
        pct_with_reports = float(n_with_reports / n_panel) if n_panel else 0.0

        # Tier1–3 yield
        tier123_success_rate = float(g["tier123_success"].mean()) if n_panel else 0.0

        # Medians computed over molecules that actually have Tier1–3 survivors
        g_succ = g[g["tier123_success"] == True]
        median_survivors_tier123 = float(np.median(g_succ["n_survivors_tier123"])) if len(g_succ) else 0.0
        median_survivor_similarity = float(np.median(g_succ["median_cf_similarity"].dropna())) if len(g_succ) else np.nan

        out_rows.append(
            {
                "ad_bin": ad_bin,
                "n_panel": n_panel,
                "n_with_reports": n_with_reports,
                "pct_with_reports": pct_with_reports,
                "tier123_success_rate": tier123_success_rate,
                "median_survivors_tier123": median_survivors_tier123,
                "median_survivor_similarity": median_survivor_similarity,
            }
        )

    df_bin = pd.DataFrame(out_rows).sort_values("ad_bin")

    if write_outputs:
        out_dir = Path(out_dir) if out_dir else (run_dir / "tables")
        out_dir.mkdir(parents=True, exist_ok=True)
        df_mol.to_csv(out_dir / "yield_per_molecule.csv", index=False)
        df_bin.to_csv(out_dir / "yield_by_ad_bin.csv", index=False)

    return df_mol, df_bin
