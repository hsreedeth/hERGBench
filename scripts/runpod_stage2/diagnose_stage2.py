#!/usr/bin/env python3
"""
diagnose_stage2.py — Audit Stage 2 AD-bin results for inversion bugs and
manifest duplication. Run from repo root:
    python scripts/runpod_stage2/diagnose_stage2.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAW_PATHS = {
    "tdc": Path("reports/stage2_multiseed_analysis/stage2_ad_bins_raw.csv"),
    "chembl": Path("reports/chembl_stage2_multiseed_analysis/stage2_ad_bins_raw.csv"),
}

MANIFEST_PATHS = {
    "tdc": Path("reports/stage2_multiseed_analysis/stage2_run_manifest.csv"),
    "chembl": Path("reports/chembl_stage2_multiseed_analysis/stage2_run_manifest.csv"),
}

# Ordered bins from most-dissimilar to most-similar
BIN_ORDER = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_csv_gracefully(path: Path, label: str) -> "pd.DataFrame | None":
    if not path.exists():
        print(f"[WARNING] {label} not found — skipping: {path}")
        return None
    df = pd.read_csv(path)
    if df.empty:
        print(f"[WARNING] {label} is empty — skipping: {path}")
        return None
    return df


def _fmt(mean: float, std: float, warn: bool, inv: bool) -> str:
    flag = ""
    if warn:
        flag += " [WARNING sub-random]"
    if inv:
        flag += " [INVERSION]"
    std_str = f"±{std:.4f}" if not math.isnan(std) else "±n/a"
    return f"AUROC = {mean:.4f} {std_str}{flag}"


# ---------------------------------------------------------------------------
# Phase 1 — Per-dataset × split_type AUROC tables
# ---------------------------------------------------------------------------

def audit_raw_results() -> tuple[int, int]:
    """Return (n_warnings, n_inversions)."""
    total_warnings = 0
    total_inversions = 0

    for dataset_key, raw_path in RAW_PATHS.items():
        df = _load_csv_gracefully(raw_path, f"{dataset_key} raw AD bins")
        if df is None:
            total_warnings += 1
            continue

        required = {"split_type", "sim_bin", "seed", "auroc"}
        missing = required - set(df.columns)
        if missing:
            print(f"[WARNING] {dataset_key} raw CSV missing columns: {missing}")
            total_warnings += 1
            continue

        if "dataset" not in df.columns:
            df["dataset"] = dataset_key

        for (dataset_val, split_type), grp in df.groupby(["dataset", "split_type"]):
            print(f"\n  {dataset_val.upper()} | split={split_type}")
            print(f"  {'sim_bin':<12}  {'AUROC':>8}   n_seeds")

            bin_stats: dict[str, tuple[float, float, int]] = {}
            for sim_bin, bin_grp in grp.groupby("sim_bin"):
                vals = bin_grp["auroc"].dropna()
                n = len(vals)
                mean = float(vals.mean()) if n > 0 else float("nan")
                std = float(vals.std()) if n > 1 else float("nan")
                bin_stats[str(sim_bin)] = (mean, std, n)

            ordered = [b for b in BIN_ORDER if b in bin_stats]
            ordered += [b for b in sorted(bin_stats) if b not in ordered]

            for sim_bin in ordered:
                mean, std, n = bin_stats[sim_bin]
                warn = (not math.isnan(mean)) and mean < 0.5
                if warn:
                    total_warnings += 1

                inv = False
                if sim_bin == ">0.7" and "0.5-0.7" in bin_stats:
                    m07 = bin_stats[">0.7"][0]
                    m0507 = bin_stats["0.5-0.7"][0]
                    if not math.isnan(m07) and not math.isnan(m0507) and m07 < m0507:
                        inv = True
                        total_inversions += 1

                std_str = f"±{std:.4f}" if not math.isnan(std) else "   ±n/a"
                flags = ""
                if warn:
                    flags += " [WARNING]"
                if inv:
                    flags += " [INVERSION]"
                print(f"  {sim_bin:<12}  {mean:>8.4f} {std_str}  (n={n}){flags}")

    return total_warnings, total_inversions


# ---------------------------------------------------------------------------
# Phase 2 — Manifest duplicate check
# ---------------------------------------------------------------------------

def audit_manifests() -> int:
    total_duplicates = 0

    for dataset_key, manifest_path in MANIFEST_PATHS.items():
        df = _load_csv_gracefully(manifest_path, f"{dataset_key} manifest")
        if df is None:
            continue

        if "config_stem" not in df.columns:
            print(f"[WARNING] {dataset_key} manifest missing 'config_stem' column")
            continue

        counts = df["config_stem"].value_counts()
        dups = counts[counts > 1]
        if len(dups) == 0:
            print(f"  [{dataset_key}] manifest OK — {len(df)} rows, {df['config_stem'].nunique()} unique stems")
        else:
            print(f"  [{dataset_key}] manifest has {len(dups)} duplicate config_stem(s):")
            for stem, count in dups.items():
                print(f"      {stem}  ({count}x)")
            total_duplicates += len(dups)

    return total_duplicates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 68)
    print("diagnose_stage2.py — Stage 2 AD-bin audit")
    print("=" * 68)

    print("\n[1/2] AD-bin AUROC by dataset × split_type × similarity bin")
    n_warnings, n_inversions = audit_raw_results()

    print("\n[2/2] Manifest duplicate check")
    n_duplicates = audit_manifests()

    print("\n" + "=" * 68)
    print("AUDIT SUMMARY")
    print(f"  sub-random AUROC bins : {n_warnings}")
    print(f"  >0.7 inversion flags  : {n_inversions}  (AUROC[>0.7] < AUROC[0.5-0.7])")
    print(f"  manifest duplicates   : {n_duplicates}")

    if n_warnings == 0 and n_inversions == 0 and n_duplicates == 0:
        print("\nRESULT: PASS")
        sys.exit(0)
    else:
        parts = []
        if n_warnings:
            parts.append(f"{n_warnings} sub-random AUROC bin(s)")
        if n_inversions:
            parts.append(f"{n_inversions} similarity-bin inversion(s)")
        if n_duplicates:
            parts.append(f"{n_duplicates} manifest duplicate(s)")
        print(f"\nRESULT: FAIL — {'; '.join(parts)}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
