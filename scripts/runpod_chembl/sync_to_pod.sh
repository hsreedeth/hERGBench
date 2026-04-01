#!/usr/bin/env bash
# sync_to_pod.sh — Push repo + ChEMBL data to a RunPod instance.
#
# Usage:
#   POD_HOST=root@<pod-ip> POD_PORT=<ssh-port> bash scripts/runpod_chembl/sync_to_pod.sh
#
# Environment variables:
#   POD_HOST      e.g. root@123.45.67.89   (required)
#   POD_PORT      SSH port                  (default: 22)
#   REPO_DIR      destination on pod        (default: /workspace/hERGBench)

set -euo pipefail

POD_HOST="${POD_HOST:?Error: set POD_HOST=root@<pod-ip>}"
POD_PORT="${POD_PORT:-22}"
REPO_DIR="${REPO_DIR:-/workspace/hERGBench}"
LOCAL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

SSH_OPTS="-p ${POD_PORT} -o StrictHostKeyChecking=no"

echo "=== Syncing repo to ${POD_HOST}:${REPO_DIR} ==="
rsync -avz --progress \
    -e "ssh ${SSH_OPTS}" \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.venv' \
    --exclude 'reports/' \
    "${LOCAL_ROOT}/" \
    "${POD_HOST}:${REPO_DIR}/"

echo "=== Syncing ChEMBL data ==="
ssh ${SSH_OPTS} "${POD_HOST}" "mkdir -p ${REPO_DIR}/data/chembl"
rsync -avz --progress \
    -e "ssh ${SSH_OPTS}" \
    "${LOCAL_ROOT}/data/chembl/" \
    "${POD_HOST}:${REPO_DIR}/data/chembl/"

echo "=== Sync complete ==="
echo "Next: ssh -p ${POD_PORT} ${POD_HOST}"
echo "      cd ${REPO_DIR} && bash scripts/runpod_chembl/01_verify_data.sh"
