#!/usr/bin/env bash
# sync_to_pod.sh — Sync repo, both datasets, and Stage 1 results to RunPod.
#
# Usage:
#   POD_HOST=root@<ip> POD_PORT=<port> bash scripts/runpod_stage2/sync_to_pod.sh
#
# Environment variables:
#   POD_HOST      e.g. root@123.45.67.89   (required)
#   POD_PORT      SSH port                  (default: 22)
#   REPO_DIR      destination on pod        (default: /workspace/hERGBench)
#   SYNC_REPORTS  set to 1 to also sync existing Stage 1 reports (default: 0)

set -euo pipefail

POD_HOST="${POD_HOST:?Error: set POD_HOST=root@<pod-ip>}"
POD_PORT="${POD_PORT:-22}"
REPO_DIR="${REPO_DIR:-/workspace/hERGBench}"
SYNC_REPORTS="${SYNC_REPORTS:-0}"

LOCAL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SSH_OPTS="-p ${POD_PORT} -o StrictHostKeyChecking=no"

echo "=== Sync to ${POD_HOST}:${REPO_DIR} ==="

# Source code and configs
echo "  → Syncing repo (src, scripts, configs)..."
rsync -avz --progress \
    -e "ssh ${SSH_OPTS}" \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.venv' \
    --exclude 'reports/' \
    --exclude 'data/' \
    "${LOCAL_ROOT}/" \
    "${POD_HOST}:${REPO_DIR}/"

# TDC dataset + splits
echo "  → Syncing TDC dataset and splits..."
ssh ${SSH_OPTS} "${POD_HOST}" "mkdir -p ${REPO_DIR}/data/processed ${REPO_DIR}/data/splits"
rsync -avz --progress \
    -e "ssh ${SSH_OPTS}" \
    "${LOCAL_ROOT}/data/processed/" \
    "${POD_HOST}:${REPO_DIR}/data/processed/"
rsync -avz --progress \
    -e "ssh ${SSH_OPTS}" \
    "${LOCAL_ROOT}/data/splits/" \
    "${POD_HOST}:${REPO_DIR}/data/splits/"

# ChEMBL dataset + splits
echo "  → Syncing ChEMBL dataset and splits..."
ssh ${SSH_OPTS} "${POD_HOST}" "mkdir -p ${REPO_DIR}/data/chembl"
rsync -avz --progress \
    -e "ssh ${SSH_OPTS}" \
    "${LOCAL_ROOT}/data/chembl/" \
    "${POD_HOST}:${REPO_DIR}/data/chembl/"

# Stage 1 results (for cross-model comparison in step 06)
if [[ "${SYNC_REPORTS}" == "1" ]]; then
    echo "  → Syncing Stage 1 reports..."
    for dir in "multiseed_analysis" "chembl_multiseed_analysis"; do
        local_path="${LOCAL_ROOT}/reports/${dir}"
        if [[ -d "${local_path}" ]]; then
            ssh ${SSH_OPTS} "${POD_HOST}" "mkdir -p ${REPO_DIR}/reports/${dir}"
            rsync -avz --progress \
                -e "ssh ${SSH_OPTS}" \
                "${local_path}/" \
                "${POD_HOST}:${REPO_DIR}/reports/${dir}/"
        fi
    done
fi

echo ""
echo "=== Sync complete ==="
echo "Next steps on the pod:"
echo "  ssh -p ${POD_PORT} ${POD_HOST}"
echo "  cd ${REPO_DIR}"
echo "  bash scripts/runpod_stage2/run_all.sh"
