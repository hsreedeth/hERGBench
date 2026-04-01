#!/usr/bin/env bash
# 06_cross_model_comparison.sh — Merge Stage 1 (XGBoost) and Stage 2 (D-MPNN) results.
#
# Requires both stages' raw CSVs. Stage 1 files are optional but recommended:
#   reports/multiseed_analysis/multiseed_ad_bins_raw.csv        (TDC Stage 1)
#   reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv (ChEMBL Stage 1)
#   reports/stage2_multiseed_analysis/stage2_ad_bins_raw.csv    (TDC Stage 2)
#   reports/chembl_stage2_multiseed_analysis/stage2_ad_bins_raw.csv (ChEMBL Stage 2)
#
# Run from repo root:
#   bash scripts/runpod_stage2/06_cross_model_comparison.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

echo "=== 06 Cross-model comparison (XGBoost vs D-MPNN) ==="

python - <<'PYEOF'
import sys
from pathlib import Path
import pandas as pd
from hergbench.analysis.calibration_by_bin import build_cross_model_comparison

S1_TDC    = Path("reports/multiseed_analysis/multiseed_ad_bins_raw.csv")
S1_CHEMBL = Path("reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv")
S2_TDC    = Path("reports/stage2_multiseed_analysis/stage2_ad_bins_raw.csv")
S2_CHEMBL = Path("reports/chembl_stage2_multiseed_analysis/stage2_ad_bins_raw.csv")

# Load what's available
s1_parts, s2_parts = [], []

for path, label, parts in [
    (S1_TDC,    "tdc",    s1_parts),
    (S1_CHEMBL, "chembl", s1_parts),
]:
    if path.exists():
        df = pd.read_csv(path)
        if "dataset" not in df.columns:
            df.insert(0, "dataset", label)
        parts.append(df)
        print(f"  Stage 1 {label}: {len(df)} rows from {path}")
    else:
        print(f"  Stage 1 {label}: not found ({path})")

for path, label, parts in [
    (S2_TDC,    "tdc",    s2_parts),
    (S2_CHEMBL, "chembl", s2_parts),
]:
    if path.exists():
        df = pd.read_csv(path)
        if "dataset" not in df.columns:
            df.insert(0, "dataset", label)
        parts.append(df)
        print(f"  Stage 2 {label}: {len(df)} rows from {path}")
    else:
        print(f"  Stage 2 {label}: not found ({path})")

if not s1_parts and not s2_parts:
    print("ERROR: no Stage 1 or Stage 2 results found.", file=sys.stderr)
    sys.exit(1)

if not s1_parts:
    print("WARNING: no Stage 1 results — comparison will show Stage 2 only.")
    stage1_raw = pd.DataFrame()
else:
    stage1_raw = pd.concat(s1_parts, ignore_index=True)

if not s2_parts:
    print("ERROR: no Stage 2 results found. Run steps 03-05 first.", file=sys.stderr)
    sys.exit(1)

stage2_raw = pd.concat(s2_parts, ignore_index=True)

if stage1_raw.empty:
    # Can't do cross-model comparison without both sides; still save Stage 2 only
    stage1_raw = stage2_raw.iloc[0:0].copy()  # empty with same schema

comparison = build_cross_model_comparison(
    stage1_raw=stage1_raw,
    stage2_raw=stage2_raw,
    output_dir="reports/cross_model_comparison",
)
print("\n=== Cross-model AD-bin comparison ===")
print(comparison.to_string(index=False))
print("\nSaved to reports/cross_model_comparison/")
PYEOF

echo ""
echo "=== 06 Complete ==="
