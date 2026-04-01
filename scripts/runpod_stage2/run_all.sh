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
source "${SCRIPT_DIR}/_common.sh"
cd "$(stage2_repo_root)"

USE_TMUX="${USE_TMUX:-0}"
TMUX_SESSION="${TMUX_SESSION:-stage2_runpod}"

if [[ "${USE_TMUX}" == "1" ]] && [[ -z "${TMUX:-}" ]]; then
    if ! command -v tmux >/dev/null 2>&1; then
        echo "ERROR: tmux not installed. Install tmux or run without USE_TMUX=1." >&2
        exit 1
    fi
    if tmux has-session -t "${TMUX_SESSION}" 2>/dev/null; then
        echo "ERROR: tmux session '${TMUX_SESSION}' already exists." >&2
        echo "Attach with: tmux attach -t ${TMUX_SESSION}" >&2
        exit 1
    fi
    tmux new-session -d -s "${TMUX_SESSION}" "cd $(pwd) && USE_TMUX=0 bash scripts/runpod_stage2/run_all.sh"
    echo "Started detached tmux session: ${TMUX_SESSION}"
    echo "Attach with: tmux attach -t ${TMUX_SESSION}"
    exit 0
fi

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
