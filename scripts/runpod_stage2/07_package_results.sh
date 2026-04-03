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
EXPORT_ROOT="reports/stage2_exports"
EXPORT_DIR="${EXPORT_ROOT}/stage2_export_${TIMESTAMP}"
ARCHIVE_ROOT="reports/runs/archive_stage2_superseded"
ARCHIVE_DIR="${ARCHIVE_ROOT}/${TIMESTAMP}"

echo "=== 07 Package Stage 2 results ==="

PROV_DIR="reports/stage2_provenance"
mkdir -p "${PROV_DIR}"
mkdir -p "${EXPORT_ROOT}" "${ARCHIVE_ROOT}"

git rev-parse HEAD > "${PROV_DIR}/git_commit.txt" 2>/dev/null || echo "unknown" > "${PROV_DIR}/git_commit.txt"
git diff --stat HEAD >> "${PROV_DIR}/git_commit.txt" 2>/dev/null || true
nvidia-smi --query-gpu=name,driver_version,memory.total \
    --format=csv,noheader > "${PROV_DIR}/gpu_info.txt" 2>/dev/null || echo "no GPU" > "${PROV_DIR}/gpu_info.txt"
python -m pip freeze > "${PROV_DIR}/pip_freeze.txt" 2>/dev/null || true

echo "  provenance written to ${PROV_DIR}/"

PACKAGE_LIST="${PROV_DIR}/package_manifest.txt"
CURRENT_RUNS_LIST="${PROV_DIR}/current_stage2_run_dirs.txt"
: > "${PACKAGE_LIST}"
: > "${CURRENT_RUNS_LIST}"

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
current_runs_list = Path("reports/stage2_provenance/current_stage2_run_dirs.txt")
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
current_runs_list.write_text("\n".join(unique_run_dirs) + ("\n" if unique_run_dirs else ""))
for run_dir in unique_run_dirs:
    print(f"  including run dir: {run_dir}")
PYEOF

EXPORT_DIR="${EXPORT_DIR}" ARCHIVE_DIR="${ARCHIVE_DIR}" ARCHIVE_ROOT="${ARCHIVE_ROOT}" python - <<'PYEOF'
from pathlib import Path
import os
import shutil

package_list = Path("reports/stage2_provenance/package_manifest.txt")
current_runs_list = Path("reports/stage2_provenance/current_stage2_run_dirs.txt")
export_dir = Path(os.environ["EXPORT_DIR"])
archive_dir = Path(os.environ["ARCHIVE_DIR"])
archive_root = Path(os.environ["ARCHIVE_ROOT"]).resolve()
runs_root = Path("reports/runs").resolve()

sources = [Path(line.strip()) for line in package_list.read_text().splitlines() if line.strip()]
export_dir.mkdir(parents=True, exist_ok=True)

for src in sources:
    if not src.exists():
        print(f"  export skip (not found): {src}")
        continue

    dest = export_dir / src
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    print(f"  exported: {src} -> {dest}")

keep_run_dirs = {
    Path(line.strip()).resolve()
    for line in current_runs_list.read_text().splitlines()
    if line.strip()
}
if not keep_run_dirs:
    print("  archive skip: no current manifest-selected Stage 2 run dirs found.")
    raise SystemExit(0)

candidate_run_dirs = []
for path in runs_root.iterdir():
    if not path.is_dir():
        continue
    if "stage2_chemprop" not in path.name:
        continue
    resolved = path.resolve()
    if archive_root in resolved.parents:
        continue
    candidate_run_dirs.append(resolved)

redundant_run_dirs = sorted(path for path in candidate_run_dirs if path not in keep_run_dirs)
if not redundant_run_dirs:
    print("  archive skip: no redundant Stage 2 run dirs found.")
    raise SystemExit(0)

archive_dir.mkdir(parents=True, exist_ok=True)
for src in redundant_run_dirs:
    dest = archive_dir / src.name
    if dest.exists():
        raise SystemExit(f"Archive destination already exists: {dest}")
    shutil.move(str(src), str(dest))
    print(f"  archived redundant run dir: {src} -> {dest}")
PYEOF

if [[ ! -s "${PACKAGE_LIST}" ]]; then
    echo "ERROR: nothing to package. Run steps 03-06 first." >&2
    exit 1
fi

tar -czf "${ARCHIVE_NAME}" -C "${EXPORT_ROOT}" "$(basename "${EXPORT_DIR}")"

echo ""
echo "  Export dir: ${EXPORT_DIR}"
echo "  Archived redundant run dirs under: ${ARCHIVE_DIR}"
echo "  Archive: ${ARCHIVE_NAME}"
echo "  Size:    $(du -sh "${ARCHIVE_NAME}" | cut -f1)"
echo ""
echo "Download with:"
echo "  scp -P <PORT> root@<HOST>:$(pwd)/${ARCHIVE_NAME} ."
echo "  scp -r -P <PORT> root@<HOST>:$(pwd)/${EXPORT_DIR} ./reports/"
echo "=== 07 Complete ==="
