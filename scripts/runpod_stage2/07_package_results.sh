#!/usr/bin/env bash
# 07_package_results.sh — Bundle Stage 2 outputs, selected run dirs, and provenance.
#
# Run from repo root:
#   bash scripts/runpod_stage2/07_package_results.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
REPO_ROOT="$(stage2_repo_root)"
cd "${REPO_ROOT}"

activate_stage2_venv "${REPO_ROOT}" || true

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_NAME="hERGBench_Stage2_results_${TIMESTAMP}.tar.gz"

echo "=== 07 Package Stage 2 results ==="

PROV_DIR="reports/stage2_provenance"
mkdir -p "${PROV_DIR}"

git rev-parse HEAD > "${PROV_DIR}/git_commit.txt" 2>/dev/null || echo "unknown" > "${PROV_DIR}/git_commit.txt"
git diff --stat HEAD >> "${PROV_DIR}/git_commit.txt" 2>/dev/null || true
nvidia-smi --query-gpu=name,driver_version,memory.total \
    --format=csv,noheader > "${PROV_DIR}/gpu_info.txt" 2>/dev/null || echo "no GPU" > "${PROV_DIR}/gpu_info.txt"
python -m pip freeze > "${PROV_DIR}/pip_freeze.txt" 2>/dev/null || true

echo "  provenance written to ${PROV_DIR}/"

PACKAGE_LIST="${PROV_DIR}/package_manifest.txt"
: > "${PACKAGE_LIST}"

for d in \
    "reports/stage2_multiseed_analysis" \
    "reports/chembl_stage2_multiseed_analysis" \
    "reports/cross_model_comparison" \
    "reports/stage2_provenance" \
    "configs/stage2_multiseed" \
    "configs/chembl_stage2_multiseed"; do
    if [[ -d "${d}" ]]; then
        echo "${d}" >> "${PACKAGE_LIST}"
        echo "  including: ${d}"
    else
        echo "  skipping (not found): ${d}"
    fi
done

python - <<'PYEOF'
from pathlib import Path
import pandas as pd

package_list = Path("reports/stage2_provenance/package_manifest.txt")
manifest_paths = [
    Path("reports/stage2_multiseed_analysis/stage2_run_manifest.csv"),
    Path("reports/chembl_stage2_multiseed_analysis/stage2_run_manifest.csv"),
]

run_dirs = []
for manifest_path in manifest_paths:
    if not manifest_path.exists():
        continue
    df = pd.read_csv(manifest_path)
    if "config_stem" in df.columns:
        latest_by_config = {}
        for _, row in df.iterrows():
            latest_by_config[str(row["config_stem"])] = str(row["run_dir"])
        run_dirs.extend(latest_by_config.values())
    else:
        run_dirs.extend(df["run_dir"].astype(str).tolist())

unique_run_dirs = sorted(set(run_dirs))
existing = package_list.read_text()
package_list.write_text(existing + "\n".join(unique_run_dirs) + "\n")
for run_dir in unique_run_dirs:
    print(f"  including run dir: {run_dir}")
PYEOF

if [[ ! -s "${PACKAGE_LIST}" ]]; then
    echo "ERROR: nothing to package. Run steps 03-06 first." >&2
    exit 1
fi

tar -czf "${ARCHIVE_NAME}" -T "${PACKAGE_LIST}"

echo ""
echo "  Archive: ${ARCHIVE_NAME}"
echo "  Size:    $(du -sh "${ARCHIVE_NAME}" | cut -f1)"
echo ""
echo "Download with:"
echo "  scp -P <PORT> root@<HOST>:$(pwd)/${ARCHIVE_NAME} ."
echo "=== 07 Complete ==="
