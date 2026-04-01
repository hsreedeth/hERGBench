#!/usr/bin/env bash
# 04_package_results.sh — Bundle all ChEMBL benchmark outputs into a
# timestamped tarball ready for download.
#
# Run from repo root on the pod:
#   bash scripts/runpod_chembl/04_package_results.sh

set -euo pipefail

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_NAME="chembl_results_${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="reports/${ARCHIVE_NAME}"

DIRS_TO_PACK=(
    "reports/chembl_multiseed_analysis"
    "reports/combined_multiseed"
)

echo "=== 04 Packaging results ==="

EXISTING=()
for d in "${DIRS_TO_PACK[@]}"; do
    if [[ -d "${d}" ]]; then
        EXISTING+=("${d}")
    else
        echo "  WARNING: ${d} not found — skipping."
    fi
done

if [[ "${#EXISTING[@]}" -eq 0 ]]; then
    echo "ERROR: no result directories found. Run steps 02 and 03 first."
    exit 1
fi

tar -czf "${ARCHIVE_PATH}" "${EXISTING[@]}"
echo "  Archive: ${ARCHIVE_PATH}"
echo "  Size:    $(du -sh "${ARCHIVE_PATH}" | cut -f1)"
echo ""
echo "Download with:"
echo "  scp -P \${POD_PORT} \${POD_HOST}:$(pwd)/${ARCHIVE_PATH} ."
echo "=== 04 Complete ==="
