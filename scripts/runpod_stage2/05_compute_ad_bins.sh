#!/usr/bin/env bash
# 05_compute_ad_bins.sh — Collect AD-bin metrics from all completed Stage 2 run dirs.
#
# Reads tables/applicability_domain_bins.csv from each run dir under reports/runs/
# and aggregates by dataset, split_type, seed, and sim_bin.
#
# Run from repo root:
#   bash scripts/runpod_stage2/05_compute_ad_bins.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

echo "=== 05 Compute AD-bin metrics for Stage 2 ==="

python - <<'PYEOF'
import logging
import sys
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")

from hergbench.analysis.stage2_multiseed_runner import run_stage2_multiseed, aggregate_stage2_results

for dataset in ["tdc", "chembl"]:
    print(f"\n--- {dataset.upper()} ---")
    try:
        raw = run_stage2_multiseed(dataset=dataset, skip_existing=True, allow_gpu=False)
        if raw.empty:
            print(f"  No rows collected for {dataset}. Did the runs complete?")
            continue
        agg = aggregate_stage2_results(raw)
        print(agg.to_string(index=False))
    except Exception as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
PYEOF

echo ""
echo "=== 05 AD-bin computation complete ==="
echo "  TDC:    reports/stage2_multiseed_analysis/"
echo "  ChEMBL: reports/chembl_stage2_multiseed_analysis/"
