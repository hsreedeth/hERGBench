#!/usr/bin/env bash
# 05_compute_ad_bins.sh — Aggregate Stage 2 AD-bin metrics from existing raw CSVs.
#
# This step is intentionally aggregation-only. It does not launch training jobs.
#
# Run from repo root:
#   bash scripts/runpod_stage2/05_compute_ad_bins.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
REPO_ROOT="$(stage2_repo_root)"
cd "${REPO_ROOT}"

activate_stage2_venv "${REPO_ROOT}" || true

echo "=== 05 Compute AD-bin metrics for Stage 2 ==="

python - <<'PYEOF'
import sys
from pathlib import Path

import pandas as pd

from hergbench.analysis.stage2_multiseed_runner import aggregate_stage2_results

datasets = {
    "tdc": Path("reports/stage2_multiseed_analysis"),
    "chembl": Path("reports/chembl_stage2_multiseed_analysis"),
}

for dataset, out_dir in datasets.items():
    raw_path = out_dir / "stage2_ad_bins_raw.csv"
    print(f"\n--- {dataset.upper()} ---")
    if not raw_path.exists():
        print(f"  ERROR: missing {raw_path}. Run the training step first.", file=sys.stderr)
        continue

    raw = pd.read_csv(raw_path)
    if raw.empty:
        print(f"  ERROR: {raw_path} is empty.", file=sys.stderr)
        continue

    agg = aggregate_stage2_results(raw, output_dir=str(out_dir))
    print(agg.to_string(index=False))
    print(f"  Aggregated: {out_dir / 'stage2_ad_bins_aggregated.csv'}")

PYEOF

echo ""
echo "=== 05 AD-bin computation complete ==="
echo "  TDC:    reports/stage2_multiseed_analysis/"
echo "  ChEMBL: reports/chembl_stage2_multiseed_analysis/"
