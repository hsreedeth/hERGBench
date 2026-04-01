#!/usr/bin/env bash
# run_all.sh — Execute the full Stage 2 D-MPNN multi-seed pipeline.
#
# Each step is independently runnable if you need to resume.
# Estimated runtime: ~7 hours on RTX 4090.
#
# Usage:
#   bash scripts/runpod_stage2/run_all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== Stage 2 D-MPNN Multi-Seed Benchmark (Both Datasets) ==="
echo "Started: $(date)"
echo "Estimated runtime: ~7 hours on RTX 4090"
echo ""

bash "${SCRIPT_DIR}/01_verify_environment.sh"
bash "${SCRIPT_DIR}/02_generate_configs.sh"
bash "${SCRIPT_DIR}/03_run_tdc_stage2.sh"
bash "${SCRIPT_DIR}/04_run_chembl_stage2.sh"
bash "${SCRIPT_DIR}/05_compute_ad_bins.sh"
bash "${SCRIPT_DIR}/06_cross_model_comparison.sh"
bash "${SCRIPT_DIR}/07_package_results.sh"

echo ""
echo "=== All Stage 2 runs complete: $(date) ==="
