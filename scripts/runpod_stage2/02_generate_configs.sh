#!/usr/bin/env bash
# 02_generate_configs.sh — Generate ChEMBL Stage 2 configs and verify TDC configs.
#
# Idempotent: running twice produces the same configs.
#
# Run from repo root:
#   bash scripts/runpod_stage2/02_generate_configs.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
REPO_ROOT="$(stage2_repo_root)"
cd "${REPO_ROOT}"

activate_stage2_venv "${REPO_ROOT}" || true

echo "=== 02 Generate Stage 2 Configs ==="

# Regenerate TDC configs from the current base template.
echo "  Regenerating TDC configs..."
python src/make_stage2_multiseed_configs.py

# ChEMBL configs (3 splits × 5 seeds = 15 files)
echo "  Regenerating ChEMBL configs..."
python src/make_chembl_stage2_configs.py

CHEMBL_COUNT=$(ls configs/chembl_stage2_multiseed/*.yaml 2>/dev/null | wc -l | tr -d ' ')
echo "  ChEMBL configs: ${CHEMBL_COUNT}/15"
if [[ "${CHEMBL_COUNT}" -ne 15 ]]; then
    echo "ERROR: expected 15 ChEMBL configs, found ${CHEMBL_COUNT}" >&2
    exit 1
fi

# TDC configs — verify all 15 exist after regeneration
TDC_COUNT=$(ls configs/stage2_multiseed/*.yaml 2>/dev/null | wc -l | tr -d ' ')
echo "  TDC configs:    ${TDC_COUNT}/15"
if [[ "${TDC_COUNT}" -ne 15 ]]; then
    echo "ERROR: expected 15 TDC configs in configs/stage2_multiseed/, found ${TDC_COUNT}." >&2
    exit 1
fi

echo "  Patching all Stage 2 configs for explicit GPU execution on RunPod..."
python - <<'PYEOF'
from pathlib import Path
import yaml

for config_dir in [Path("configs/stage2_multiseed"), Path("configs/chembl_stage2_multiseed")]:
    for path in sorted(config_dir.glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text())
        cfg.setdefault("chemprop", {})
        cfg["chemprop"]["accelerator"] = "cuda"
        cfg["chemprop"]["devices"] = 1
        path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        print(f"    GPU-ready: {path}")

base_cfg = yaml.safe_load(Path("configs/stage2_chemprop.yaml").read_text())
expected_cal = str(base_cfg.get("calibration", {}).get("method", "none")).lower()
for config_dir in [Path("configs/stage2_multiseed"), Path("configs/chembl_stage2_multiseed")]:
    for path in sorted(config_dir.glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text())
        actual_cal = str(cfg.get("calibration", {}).get("method", "none")).lower()
        if actual_cal != expected_cal:
            raise SystemExit(
                f"Calibration mismatch in {path}: expected {expected_cal}, found {actual_cal}"
            )
print(f"  Calibration method validated across all configs: {expected_cal}")

for config_dir in [Path("configs/stage2_multiseed"), Path("configs/chembl_stage2_multiseed")]:
    for path in sorted(config_dir.glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text())
        tm = cfg.get("chemprop", {}).get("tracking_metric", "NOT SET")
        if tm == "prc":
            raise SystemExit(
                f"UNSAFE CONFIG: {path} uses tracking_metric=prc which "
                f"checkpoints incorrectly in ChemProp 2.2.2. "
                f"Change to auroc or apply the patch in "
                f"scripts/chemprop_cli_patched.py."
            )
        print(f"    tracking_metric OK ({tm}): {path}")
PYEOF

echo ""
echo "=== 02 Config generation complete ==="
echo "  TDC:    configs/stage2_multiseed/"
echo "  ChEMBL: configs/chembl_stage2_multiseed/"
