#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

USE_TMUX=1 TMUX_SESSION="${TMUX_SESSION:-stage2_runpod}" bash "${SCRIPT_DIR}/run_all.sh"
