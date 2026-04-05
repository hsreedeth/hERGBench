#!/usr/bin/env bash
# 07_package_results.sh — Bundle Stage 2 outputs for download.
#
# What is included in the export:
#   - All 30 Stage 2 run directories (15 TDC + 15 ChEMBL), each containing:
#       chemprop_input_full.csv               — full dataset with split labels
#       predictions/preds.csv                 — raw model output probabilities
#       predictions/test_preds_*_with_sim.csv — calibrated preds + AD similarity bins
#       tables/applicability_domain_bins.csv  — per-run AD-bin metrics
#       tables/benchmark_results.csv          — overall benchmark metrics
#       models/calibrator_*.joblib            — fitted calibrator object
#       models/threshold_*.json               — threshold & calibration metadata
#   - reports/stage2_multiseed_analysis/      — TDC aggregated AD-bin results
#   - reports/chembl_stage2_multiseed_analysis/ — ChEMBL aggregated AD-bin results
#   - reports/cross_model_comparison/         — D-MPNN vs XGBoost comparison
#   - configs/stage2_multiseed/               — TDC configs used
#   - configs/chembl_stage2_multiseed/        — ChEMBL configs used
#   - reports/stage2_provenance/              — git hash, pip freeze, GPU info
#
# FAILS if any manifest-listed run dir is missing (prevents silent partial exports).
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
EXPORT_LABEL="hERGBench_Stage2_FULL_${TIMESTAMP}"
ARCHIVE_NAME="${EXPORT_LABEL}.tar.gz"
EXPORT_ROOT="reports/stage2_exports"
EXPORT_DIR="${EXPORT_ROOT}/${EXPORT_LABEL}"
ARCHIVE_ROOT="reports/runs/archive_stage2_superseded"
ARCHIVE_DIR="${ARCHIVE_ROOT}/${TIMESTAMP}"

echo "=== 07 Package Stage 2 results ==="
echo "    Export label  : ${EXPORT_LABEL}"
echo "    Export dir    : ${EXPORT_DIR}"
echo "    Archive       : ${ARCHIVE_NAME}"
echo ""

PROV_DIR="reports/stage2_provenance"
mkdir -p "${PROV_DIR}" "${EXPORT_ROOT}" "${ARCHIVE_ROOT}"

# ── Provenance ────────────────────────────────────────────────────────────────
git rev-parse HEAD > "${PROV_DIR}/git_commit.txt" 2>/dev/null || echo "unknown" > "${PROV_DIR}/git_commit.txt"
git diff --stat HEAD >> "${PROV_DIR}/git_commit.txt" 2>/dev/null || true
nvidia-smi --query-gpu=name,driver_version,memory.total \
    --format=csv,noheader > "${PROV_DIR}/gpu_info.txt" 2>/dev/null || echo "no GPU" > "${PROV_DIR}/gpu_info.txt"
python -m pip freeze > "${PROV_DIR}/pip_freeze.txt" 2>/dev/null || true

echo "  Provenance written to ${PROV_DIR}/"

# ── Pre-flight: verify all manifest run dirs exist ────────────────────────────
python - <<'PYEOF'
import sys
from pathlib import Path
import pandas as pd

MANIFESTS = [
    ("tdc",    Path("reports/stage2_multiseed_analysis/stage2_run_manifest.csv")),
    ("chembl", Path("reports/chembl_stage2_multiseed_analysis/stage2_run_manifest.csv")),
]

missing = []
found_total = 0
for dataset, manifest_path in MANIFESTS:
    if not manifest_path.exists():
        print(f"  ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)
    df = pd.read_csv(manifest_path)
    # Deduplicate: keep latest entry per config_stem
    latest = {}
    for _, row in df.iterrows():
        latest[str(row["config_stem"])] = str(row["run_dir"])
    print(f"  {dataset.upper()}: {len(latest)} runs in manifest")
    for config_stem, run_dir_str in sorted(latest.items()):
        run_dir = Path(run_dir_str) if Path(run_dir_str).is_absolute() else Path.cwd() / run_dir_str
        # Verify required files are present
        required = [
            run_dir / "chemprop_input_full.csv",
            run_dir / "predictions" / "preds.csv",
            run_dir / "tables" / "applicability_domain_bins.csv",
        ]
        for req in required:
            if not req.exists():
                missing.append(f"{dataset}/{config_stem}: {req}")
        if run_dir.exists():
            found_total += 1
            print(f"    OK  {run_dir.name}")
        else:
            missing.append(f"{dataset}/{config_stem}: run dir not found: {run_dir}")
            print(f"    MISSING  {run_dir}", file=sys.stderr)

if missing:
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"PREFLIGHT FAILED — {len(missing)} missing items:", file=sys.stderr)
    for m in missing:
        print(f"  {m}", file=sys.stderr)
    print(f"\nRe-run the training steps with SKIP_EXISTING=0 before packaging.", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    sys.exit(1)

print(f"\n  Pre-flight passed: {found_total} run dirs verified.")
PYEOF

echo "  Pre-flight passed."

# ── Build package manifest ────────────────────────────────────────────────────
PACKAGE_LIST="${PROV_DIR}/package_manifest.txt"
CURRENT_RUNS_LIST="${PROV_DIR}/current_stage2_run_dirs.txt"
: > "${PACKAGE_LIST}"
: > "${CURRENT_RUNS_LIST}"

# Fixed directories
for d in \
    "reports/stage2_multiseed_analysis" \
    "reports/chembl_stage2_multiseed_analysis" \
    "reports/cross_model_comparison" \
    "reports/stage2_provenance" \
    "configs/stage2_multiseed" \
    "configs/chembl_stage2_multiseed"; do
    if [[ -d "${d}" ]]; then
        echo "${d}" >> "${PACKAGE_LIST}"
        echo "  queued: ${d}"
    else
        echo "  WARNING skipping (not found): ${d}"
    fi
done

# Run directories from manifests
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
    latest = {}
    for _, row in df.iterrows():
        latest[str(row["config_stem"])] = str(row["run_dir"])
    run_dirs.extend(latest.values())

unique_run_dirs = sorted(set(run_dirs))
existing = package_list.read_text()
package_list.write_text(existing + "\n".join(unique_run_dirs) + "\n")
current_runs_list.write_text("\n".join(unique_run_dirs) + ("\n" if unique_run_dirs else ""))
for run_dir in unique_run_dirs:
    print(f"  queued run dir: {run_dir}")
PYEOF

# ── Copy to export directory ──────────────────────────────────────────────────
echo ""
echo "  Copying to export directory..."

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

copied = 0
for src in sources:
    if not src.exists():
        # Already caught by pre-flight; log and abort rather than silently skip
        raise RuntimeError(f"Source vanished after pre-flight: {src}")
    dest = export_dir / src
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    copied += 1

print(f"  Copied {copied} items to {export_dir}")

# Archive redundant run dirs (old runs not in the current manifest)
keep_run_dirs = {
    Path(line.strip()).resolve()
    for line in current_runs_list.read_text().splitlines()
    if line.strip()
}
if not keep_run_dirs:
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

redundant = sorted(path for path in candidate_run_dirs if path not in keep_run_dirs)
if not redundant:
    print("  No redundant run dirs to archive.")
    raise SystemExit(0)

archive_dir.mkdir(parents=True, exist_ok=True)
for src in redundant:
    dest = archive_dir / src.name
    shutil.move(str(src), str(dest))
    print(f"  Archived redundant: {src.name}")
PYEOF

# ── Tar and summarise ─────────────────────────────────────────────────────────
if [[ ! -s "${PACKAGE_LIST}" ]]; then
    echo "ERROR: package manifest is empty. Run steps 03-06 first." >&2
    exit 1
fi

tar -czf "${ARCHIVE_NAME}" -C "${EXPORT_ROOT}" "$(basename "${EXPORT_DIR}")"

ARCHIVE_SIZE="$(du -sh "${ARCHIVE_NAME}" | cut -f1)"
RUN_DIR_COUNT="$(wc -l < "${CURRENT_RUNS_LIST}" | tr -d ' ')"

echo ""
echo "=== Export complete ==="
echo ""
echo "  Contents:"
echo "    ${RUN_DIR_COUNT} Stage 2 run dirs (each with predictions + tables + models)"
echo "    Analysis CSVs: stage2_ad_bins_raw, stage2_ad_bins_aggregated, stage2_run_manifest"
echo "    Cross-model comparison: cross_model_summary.csv"
echo "    Configs: configs/stage2_multiseed/, configs/chembl_stage2_multiseed/"
echo "    Provenance: git hash, pip freeze, GPU info"
echo ""
echo "  Export dir : ${EXPORT_DIR}"
echo "  Archive    : ${ARCHIVE_NAME}  (${ARCHIVE_SIZE})"
echo ""
echo "Download with:"
echo "  scp -P <PORT> root@<HOST>:$(pwd)/${ARCHIVE_NAME} ."
echo ""
echo "Then locally:"
echo "  mkdir -p reports && tar -xzf ${ARCHIVE_NAME} --strip-components=2 -C reports"
echo ""
echo "=== 07 Complete ==="
