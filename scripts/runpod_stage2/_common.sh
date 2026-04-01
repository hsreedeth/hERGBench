#!/usr/bin/env bash

set -euo pipefail

stage2_repo_root() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "${script_dir}/../.."
    pwd
}

detect_stage2_venv() {
    local repo_root="$1"
    local candidates=()

    if [[ -n "${VENV_DIR:-}" ]]; then
        candidates+=("${VENV_DIR}")
    fi

    candidates+=(
        "${repo_root}/.venv"
        "/workspace/venv_hergbench"
        "/workspace/hERGBench/.venv"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -n "${candidate}" && -f "${candidate}/bin/activate" ]]; then
            echo "${candidate}"
            return 0
        fi
    done

    return 1
}

activate_stage2_venv() {
    local repo_root="$1"
    if detected="$(detect_stage2_venv "${repo_root}")"; then
        # shellcheck disable=SC1090
        source "${detected}/bin/activate"
        export VENV_DIR="${detected}"
        echo "[stage2] using venv: ${VENV_DIR}"
        return 0
    fi

    echo "[stage2] WARNING: no venv found; using system Python" >&2
    return 1
}
