#!/usr/bin/env bash
# 03_aggregate_and_compare.sh — Merge ChEMBL + TDC raw results and produce
# the unified comparison CSV.
#
# Requires both datasets' raw CSVs to exist:
#   reports/multiseed_analysis/multiseed_ad_bins_raw.csv       (TDC)
#   reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv (ChEMBL)
#
# Run from repo root on the pod:
#   bash scripts/runpod_chembl/03_aggregate_and_compare.sh

set -euo pipefail

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"
COMBINED_DIR="${COMBINED_DIR:-reports/combined_multiseed}"

TDC_RAW="reports/multiseed_analysis/multiseed_ad_bins_raw.csv"
CHEMBL_RAW="reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv"

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

echo "=== 03 Aggregate and compare TDC vs ChEMBL ==="

for f in "${TDC_RAW}" "${CHEMBL_RAW}"; do
    if [[ ! -f "${f}" ]]; then
        echo "ERROR: missing ${f}"
        echo "Run steps 01/02 for the relevant dataset first."
        exit 1
    fi
done

python - <<'PYEOF'
import pandas as pd
from pathlib import Path
from hergbench.analysis.multiseed_benchmark import aggregate_multiseed_results

tdc    = pd.read_csv("reports/multiseed_analysis/multiseed_ad_bins_raw.csv")
chembl = pd.read_csv("reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv")

# Stamp dataset column if not already present
if "dataset" not in tdc.columns:
    tdc.insert(0, "dataset", "tdc")
if "dataset" not in chembl.columns:
    chembl.insert(0, "dataset", "chembl")

combined = pd.concat([tdc, chembl], ignore_index=True)
out_dir = Path("reports/combined_multiseed")
out_dir.mkdir(parents=True, exist_ok=True)
combined.to_csv(out_dir / "combined_multiseed_raw.csv", index=False)

agg = aggregate_multiseed_results(combined, output_dir=str(out_dir))
print(agg.to_string(index=False))
print(f"\nCombined results saved to {out_dir}/")
PYEOF

echo "=== 03 Complete ==="
