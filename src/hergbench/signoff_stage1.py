from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


AD_BINS = [
    ("<0.3", 0.0, 0.3),
    ("0.3-0.5", 0.3, 0.5),
    ("0.5-0.7", 0.5, 0.7),
    (">0.7", 0.7, 1.01),
]


TIER_ORDER = {
    "flip": 1,
    "risk_reduction": 2,
    "weak_improve": 3,
    "diagnostic_close_edits": 4,
}


TIER_LABEL_FALLBACK = {
    1: "Tier 1 — Flip",
    2: "Tier 2 — Risk reduction",
    3: "Tier 3 — Weak improvement",
    4: "Tier 4 — Diagnostic close edits",
}


@dataclass(frozen=True)
class ReportParse:
    base_smiles: str
    counterfactuals: List[dict]
    analogues: List[dict]
    attempts: List[dict]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ad_bin(max_sim: float) -> str:
    for name, lo, hi in AD_BINS:
        if lo <= max_sim < hi:
            return name
    return "unknown"


def load_report_jsons(lead_reports_dir: Path) -> Dict[str, Tuple[Path, dict]]:
    """
    Load report.json files and map by standardized/base smiles (prefers base_smiles_std).
    """
    out: Dict[str, Tuple[Path, dict]] = {}
    for jp in sorted(lead_reports_dir.rglob("report.json")):
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        smi = data.get("base_smiles_std") or data.get("base_smiles_raw")
        if not smi:
            continue
        out.setdefault(str(smi), (jp, data))
    return out


def summarize_yield(
    panel_csv: Path,
    lead_reports_dir: Path,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_csv(panel_csv)
    required = {"smiles", "label", "max_sim_to_train"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"panel.csv missing columns: {sorted(missing)}")

    panel["ad_bin"] = panel["max_sim_to_train"].astype(float).apply(_ad_bin)

    report_map = load_report_jsons(lead_reports_dir)

    rows = []
    for _, r in panel.iterrows():
        smi = str(r["smiles"])
        label = int(r["label"])
        max_sim = float(r["max_sim_to_train"])
        ad_bin = str(r["ad_bin"])

        if smi not in report_map:
            rows.append(
                dict(
                    smiles=smi,
                    label=label,
                    max_sim_to_train=max_sim,
                    ad_bin=ad_bin,
                    report_found=False,
                    best_tier_num=None,
                    best_tier_label=None,
                    tier123_success=False,
                    n_survivors_total=0,
                    n_survivors_tier123=0,
                    median_cf_similarity=None,
                    median_delta_p=None,
                    min_p=None,
                )
            )
            continue

        _, parsed = report_map[smi]
        cf_summary = parsed.get("cf_summary", {}) if isinstance(parsed, dict) else {}
        cfs = parsed.get("counterfactuals", []) if isinstance(parsed, dict) else []

        tier123 = [cf for cf in cfs if cf.get("tier_num_std", 4) in (1, 2, 3)]
        tier123_success = len(tier123) > 0

        best_tier_num = int(cf_summary.get("final_best_tier_num", min([cf.get("tier_num_std", 4) for cf in cfs]) if cfs else 4))
        best_tier_label = cf_summary.get("final_tier_label") or cf_summary.get("final_tier") or TIER_LABEL_FALLBACK.get(best_tier_num)

        def _median(xs: List[float]) -> Optional[float]:
            if not xs:
                return None
            s = sorted(xs)
            n = len(s)
            mid = n // 2
            return s[mid] if n % 2 == 1 else 0.5 * (s[mid - 1] + s[mid])

        med_sim = _median([float(cf.get("similarity_to_train")) for cf in tier123 if cf.get("similarity_to_train") is not None])
        med_dp = _median([float(cf.get("delta_p_std")) for cf in tier123 if cf.get("delta_p_std") is not None])
        min_p = min([float(cf.get("p_std")) for cf in tier123 if cf.get("p_std") is not None], default=None)

        rows.append(
            dict(
                smiles=smi,
                label=label,
                max_sim_to_train=max_sim,
                ad_bin=ad_bin,
                report_found=True,
                best_tier_num=best_tier_num,
                best_tier_label=best_tier_label,
                tier123_success=tier123_success,
                n_survivors_total=int(cf_summary.get("final_count_total", len(cfs))),
                n_survivors_tier123=int(cf_summary.get("final_count_tier123", len(tier123))),
                median_cf_similarity=med_sim,
                median_delta_p=med_dp,
                min_p=min_p,
            )
        )

    yield_df = pd.DataFrame(rows)

    # Aggregate headline metrics per AD bin
    def agg(group: pd.DataFrame) -> pd.Series:
        g = group[group["report_found"]]
        return pd.Series(
            {
                "n_panel": len(group),
                "n_with_reports": len(g),
                "pct_with_reports": (len(g) / len(group) * 100.0) if len(group) else 0.0,
                "tier123_success_rate": (g["tier123_success"].mean() * 100.0) if len(g) else 0.0,
                "median_survivors_tier123": float(g["n_survivors_tier123"].median()) if len(g) else 0.0,
                "median_survivor_similarity": float(g["median_cf_similarity"].median())
                if len(g.dropna(subset=["median_cf_similarity"]))
                else None,
            }
        )

    summary_df = yield_df.groupby("ad_bin", dropna=False).apply(agg).reset_index()

    return yield_df, summary_df


def pick_failures_for_appendix(
    yield_df: pd.DataFrame,
    lead_reports_dir: Path,
    n: int = 5,
) -> pd.DataFrame:
    """
    Pick representative failures: report_found==True and tier123_success==False.
    Prioritize lowest max_sim_to_train (hardest) then random-ish stable by smiles.
    """
    fails = yield_df[(yield_df["report_found"]) & (~yield_df["tier123_success"])].copy()
    if fails.empty:
        return fails

    fails = fails.sort_values(["max_sim_to_train", "smiles"]).head(n).reset_index(drop=True)
    return fails


def copy_failure_reports(
    failures: pd.DataFrame,
    lead_reports_dir: Path,
    out_failure_dir: Path,
) -> Path:
    """
    Copies the entire lead report directory (the directory containing report.md)
    into representative_failures/<idx>_<hash_or_name>/...
    """
    out_failure_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for i, row in failures.iterrows():
        smi = row["smiles"]
        # Find report.md by parsing and matching base_smiles
        report_map = load_report_jsons(lead_reports_dir)
        if smi not in report_map:
            continue
        found_dir = report_map[smi][0].parent

        safe_name = hashlib.sha1(smi.encode("utf-8")).hexdigest()[:10]
        dest = out_failure_dir / f"{i+1:02d}_{safe_name}"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(found_dir, dest)
        copied.append(dict(smiles=smi, copied_dir=str(dest)))

    return out_failure_dir


def write_attrition_table_for_failures(
    failures: pd.DataFrame,
    lead_reports_dir: Path,
    out_csv: Path,
) -> None:
    rows = []
    report_map = load_report_jsons(lead_reports_dir)
    for _, row in failures.iterrows():
        smi = row["smiles"]
        if smi in report_map:
            _, data = report_map[smi]
            attempts = data.get("cf_summary", {}).get("attempts", [])
            final = attempts[-1] if attempts else {}
            c = final.get("counts", {})
            rows.append(
                dict(
                    smiles=smi,
                    max_sim_to_train=float(row["max_sim_to_train"]),
                    ad_bin=row["ad_bin"],
                    final_tier=final.get("tier_label", final.get("tier")),
                    relaxation=final.get("relaxation"),
                    sampled=c.get("sampled", 0),
                    kept=c.get("kept", 0),
                    invalid=c.get("invalid", 0),
                    duplicate=c.get("duplicate", 0),
                    similarity_filtered=c.get("similarity_filtered", 0),
                    prob_filtered=c.get("prob_filtered", 0),
                    delta_filtered=c.get("delta_filtered", 0),
                    sa_filtered=c.get("sa_filtered", 0),
                    logp_filtered=c.get("logp_filtered", 0),
                    qed_filtered=c.get("qed_filtered", 0),
                    alert_filtered=c.get("alert_filtered", 0),
                )
            )
        else:
            rows.append(
                dict(
                    smiles=smi,
                    max_sim_to_train=float(row["max_sim_to_train"]),
                    ad_bin=row["ad_bin"],
                    final_tier="(report not found)",
                    relaxation=None,
                    sampled=None,
                    kept=None,
                    invalid=None,
                    duplicate=None,
                    similarity_filtered=None,
                    prob_filtered=None,
                    delta_filtered=None,
                    sa_filtered=None,
                    logp_filtered=None,
                    qed_filtered=None,
                    alert_filtered=None,
                )
            )

    pd.DataFrame(rows).to_csv(out_csv, index=False)


def write_benchmark_summary(
    benchmark_results_csv: Path,
    out_csv: Path,
) -> None:
    """
    Minimal benchmark summary: mean±sd across seeds per split for AUROC/AUPRC/Brier.
    Assumes benchmark_results.csv contains columns:
      split_type, seed, auroc, auprc, brier (or similar)
    """
    df = pd.read_csv(benchmark_results_csv)

    # Be tolerant to column naming
    col_split = "split_type" if "split_type" in df.columns else ("split" if "split" in df.columns else None)
    if not col_split:
        raise ValueError(f"Cannot find split column in {benchmark_results_csv}. Columns={list(df.columns)}")

    metrics = [c for c in ["auroc", "auprc", "brier"] if c in df.columns]
    if not metrics:
        raise ValueError(f"No supported metric columns found in {benchmark_results_csv}. Columns={list(df.columns)}")

    out = (
        df.groupby(col_split)[metrics]
        .agg(["mean", "std"])
        .reset_index()
    )

    # Flatten columns
    out.columns = ["split_type" if c == col_split else f"{c[0]}_{c[1]}" for c in out.columns]
    out.to_csv(out_csv, index=False)


def write_manifest(signoff_root: Path, manifest_path: Path) -> None:
    """
    Write sha256 manifest for all files under signoff_root, excluding MANIFEST.sha256 itself.
    """
    entries = []
    for p in sorted(signoff_root.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(signoff_root).as_posix()
        if rel == manifest_path.name:
            continue
        entries.append((rel, _sha256_file(p)))

    lines = [f"{h}  {rel}\n" for rel, h in entries]
    manifest_path.write_text("".join(lines), encoding="utf-8")


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Build Stage-1 signoff outputs (yield + failure appendix + manifest).")
    ap.add_argument("--signoff-root", required=True, help="Path to hERGBench_Stage1_SignOff/")
    ap.add_argument("--panel-csv", required=True, help="inputs/panel/panel.csv (frozen panel)")
    ap.add_argument("--lead-reports-dir", required=True, help="Path to run lead_reports/ directory for the panel")
    ap.add_argument("--benchmark-results-csv", required=False, default=None, help="Optional benchmark_results.csv")

    args = ap.parse_args()

    signoff_root = Path(args.signoff_root)
    panel_csv = Path(args.panel_csv)
    lead_reports_dir = Path(args.lead_reports_dir)
    benchmark_results_csv = Path(args.benchmark_results_csv) if args.benchmark_results_csv else None

    # Outputs layout
    out_metrics = signoff_root / "outputs" / "metrics"
    out_failure = signoff_root / "outputs" / "failure_analysis"
    out_fail_rep = out_failure / "representative_failures"

    out_metrics.mkdir(parents=True, exist_ok=True)
    out_failure.mkdir(parents=True, exist_ok=True)

    # 1) Yield matrix
    yield_df, summary_df = summarize_yield(panel_csv=panel_csv, lead_reports_dir=lead_reports_dir)
    yield_path = out_metrics / "yield_matrix.csv"
    yield_df.to_csv(yield_path, index=False)

    yield_summary_path = out_metrics / "yield_summary_by_ad_bin.csv"
    summary_df.to_csv(yield_summary_path, index=False)

    # 2) Failure appendix (3–5)
    failures = pick_failures_for_appendix(yield_df, lead_reports_dir, n=5)
    failures_path = out_failure / "selected_failures.csv"
    failures.to_csv(failures_path, index=False)

    if not failures.empty:
        copy_failure_reports(failures, lead_reports_dir, out_fail_rep)
        attr_path = out_failure / "tier4_attrition.csv"
        write_attrition_table_for_failures(failures, lead_reports_dir, attr_path)

    # 3) Benchmark summary (optional)
    if benchmark_results_csv:
        bench_out = out_metrics / "benchmark_summary.csv"
        write_benchmark_summary(benchmark_results_csv, bench_out)

    # 4) Manifest
    manifest_path = signoff_root / "MANIFEST.sha256"
    write_manifest(signoff_root, manifest_path)

    print(f"Wrote:\n- {yield_path}\n- {yield_summary_path}")
    if benchmark_results_csv:
        print(f"- {out_metrics / 'benchmark_summary.csv'}")
    if not failures.empty:
        print(f"- {failures_path}\n- {out_failure / 'tier4_attrition.csv'}\n- {out_fail_rep}/")
    print(f"- {manifest_path}")


if __name__ == "__main__":
    main()
