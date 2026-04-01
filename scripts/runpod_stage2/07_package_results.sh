#!/usr/bin/env bash
# 07_package_results.sh — Bundle all Stage 2 outputs, models, and provenance.
#
# Run from repo root:
#   bash scripts/runpod_stage2/07_package_results.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_NAME="hERGBench_Stage2_results_${TIMESTAMP}.tar.gz"

echo "=== 07 Package Stage 2 results ==="

# Provenance: git hash, GPU info, pip freeze
PROV_DIR="reports/stage2_provenance"
mkdir -p "${PROV_DIR}"

git rev-parse HEAD > "${PROV_DIR}/git_commit.txt" 2>/dev/null || echo "unknown" > "${PROV_DIR}/git_commit.txt"
git diff --stat HEAD >> "${PROV_DIR}/git_commit.txt" 2>/dev/null || true

nvidia-smi --query-gpu=name,driver_version,memory.total \
    --format=csv,noheader > "${PROV_DIR}/gpu_info.txt" 2>/dev/null || echo "no GPU" > "${PROV_DIR}/gpu_info.txt"

python -m pip freeze > "${PROV_DIR}/pip_freeze.txt" 2>/dev/null || true

echo "  provenance written to ${PROV_DIR}/"

# Collect directories to pack
DIRS_TO_PACK=()
for d in \
    "reports/stage2_multiseed_analysis" \
    "reports/chembl_stage2_multiseed_analysis" \
    "reports/cross_model_comparison" \
    "reports/stage2_provenance" \
    "configs/chembl_stage2_multiseed"; do
    if [[ -d "${d}" ]]; then
        DIRS_TO_PACK+=("${d}")
        echo "  including: ${d}"
    else
        echo "  skipping (not found): ${d}"
    fi
done

# Include run dirs (models + predictions) if they exist
if [[ -d "reports/runs" ]]; then
    STAGE2_RUNS=$(ls -d reports/runs/*stage2_chemprop* 2>/dev/null | wc -l | tr -d ' ')
    if [[ "${STAGE2_RUNS}" -gt 0 ]]; then
        DIRS_TO_PACK+=("reports/runs")
        echo "  including: reports/runs  (${STAGE2_RUNS} stage2 run dirs)"
    fi
fi

if [[ "${#DIRS_TO_PACK[@]}" -eq 0 ]]; then
    echo "ERROR: nothing to package. Run steps 03-06 first." >&2
    exit 1
fi

tar -czf "${ARCHIVE_NAME}" "${DIRS_TO_PACK[@]}"
echo ""
echo "  Archive: ${ARCHIVE_NAME}"
echo "  Size:    $(du -sh "${ARCHIVE_NAME}" | cut -f1)"
echo ""
echo "Download with:"
echo "  scp -P \${POD_PORT} \${POD_HOST}:$(pwd)/${ARCHIVE_NAME} ."
echo "=== 07 Complete ==="
