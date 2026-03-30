#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[run_all] 01_system_check"
"${SCRIPT_DIR}/01_system_check.sh"

echo "[run_all] 02_setup_repo_env"
"${SCRIPT_DIR}/02_setup_repo_env.sh"

echo "[run_all] 03_smoke_test_cluster_none"
"${SCRIPT_DIR}/03_smoke_test_cluster_none.sh"

echo "[run_all] 04_run_cluster_none_multitorch"
"${SCRIPT_DIR}/04_run_cluster_none_multitorch.sh"

echo "[run_all] 05_build_cluster_bundle"
"${SCRIPT_DIR}/05_build_cluster_bundle.sh"

echo "[run_all] 06_package_results"
"${SCRIPT_DIR}/06_package_results.sh"
