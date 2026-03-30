#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUNDLE_DIR="hERGBench_Stage2_Cluster_None_MultiTorch_v1"
TARBALL="hERGBench_Stage2_Cluster_None_MultiTorch_v1.tar.gz"

cd "${REPO_ROOT}"

if [[ ! -d "${BUNDLE_DIR}" ]]; then
  echo "[06_package_results] bundle directory missing: ${BUNDLE_DIR}" >&2
  exit 1
fi

tar -czf "${TARBALL}" "${BUNDLE_DIR}"
echo "[06_package_results] packaged results: ${TARBALL}"
