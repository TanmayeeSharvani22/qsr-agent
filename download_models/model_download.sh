#!/usr/bin/env bash
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Model Download Script for the QSR Agent
# Downloads the OVMS-served OpenVINO LLM into the repo-local models/ directory:
#   OpenVINO/Qwen3-8B-int4-ov (pinned revision)

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

# Repo-local model tree. OVMS mounts this via docker-compose (MODEL_ROOT).
MODELS_DIR="${MODELS_DIR:-${PROJECT_ROOT}/models}"
MODEL_ID="${MODEL_ID:-OpenVINO/Qwen3-8B-int4-ov}"
# Pin to the validated commit so downloads are reproducible (matches setup.sh).
MODEL_REVISION="${MODEL_REVISION:-5c47abf4b8e12ebe8e99745bb0c1ec17e0c0abcc}"

TARGET_PATH="${MODELS_DIR}/${MODEL_ID}"

# Keep the HuggingFace cache project-local so the download never depends on the
# invoking user's $HOME being writable. Honor an inherited HF_HOME if writable.
LOCAL_HF_HOME="${SCRIPT_DIR}/.hf_cache"
_hf_writable() { mkdir -p "$1" 2>/dev/null && [ -w "$1" ]; }
if [ -n "${HF_HOME:-}" ] && _hf_writable "${HF_HOME}"; then
    echo "  Using inherited HF_HOME=${HF_HOME}"
else
    export HF_HOME="${LOCAL_HF_HOME}"
fi
mkdir -p "${HF_HOME}"
export HF_HUB_DISABLE_TELEMETRY=1

echo "=========================================="
echo "Model Setup — QSR Agent"
echo "=========================================="
echo "  Model:     ${MODEL_ID}"
echo "  Revision:  ${MODEL_REVISION}"
echo "  Target:    ${TARGET_PATH}"
echo "=========================================="

if [ -f "${TARGET_PATH}/config.json" ]; then
    echo "  ✓ Model already present, nothing to download"
    exit 0
fi

# Prefer the system interpreter when huggingface_hub is already available;
# otherwise create a project-local venv and install it there.
PY=python3
if ! python3 -c 'import huggingface_hub' >/dev/null 2>&1; then
    VENV_DIR="${SCRIPT_DIR}/.venv"
    if [ ! -x "${VENV_DIR}/bin/python" ]; then
        echo "  Creating download virtualenv at ${VENV_DIR}"
        python3 -m venv "${VENV_DIR}"
    fi
    PY="${VENV_DIR}/bin/python"
    if [ ! -f "${VENV_DIR}/.deps_installed" ]; then
        echo "  Installing huggingface_hub..."
        "${PY}" -m pip install -q --upgrade pip
        "${PY}" -m pip install -q huggingface_hub
        touch "${VENV_DIR}/.deps_installed"
    fi
fi

echo "  Downloading ${MODEL_ID}..."
mkdir -p "${TARGET_PATH}"
MODEL_ID="${MODEL_ID}" MODEL_REVISION="${MODEL_REVISION}" TARGET_PATH="${TARGET_PATH}" \
    "${PY}" - <<'PY'
import os
from huggingface_hub import snapshot_download

path = snapshot_download(
    repo_id=os.environ["MODEL_ID"],
    revision=os.environ["MODEL_REVISION"],
    local_dir=os.environ["TARGET_PATH"],
)
print(path)
PY

if [ -f "${TARGET_PATH}/config.json" ]; then
    echo "  ✓ Model ready at ${TARGET_PATH}"
else
    echo "  ✗ Download failed: ${TARGET_PATH}/config.json missing" >&2
    exit 1
fi
