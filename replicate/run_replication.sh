#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 1-Command Standalone External Replication Harness for openIE-dev/openie-research-experiments
# Usage: ./replicate/run_replication.sh [--quick] [--out replicate/out] [--skip-native]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 (>= 3.10, stdlib-only) is required." >&2
    exit 1
fi

PY_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 10)))')"
if [ "${PY_OK}" != "1" ]; then
    echo "ERROR: python3 >= 3.10 is required (found $(python3 --version))." >&2
    exit 1
fi

echo "========================================================================"
echo " OpenIE Independent External Replication Harness (Apache-2.0)"
echo " Comparing local machine execution against OpenIE Self-Checked"
echo " Reference Artifacts (never labeled 'Verified' by self-audit)."
echo "========================================================================"

exec python3 "${SCRIPT_DIR}/verify_expected.py" --repo-root "${REPO_ROOT}" "$@"
