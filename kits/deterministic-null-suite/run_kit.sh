#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 1-Command Runner for Kit 1 (`kits/deterministic-null-suite/`, Shot on Goal #1)
# Usage: ./kits/deterministic-null-suite/run_kit.sh [--quick] [--candidate-cmd "..."]

set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

echo "=== [Kit 1: deterministic-null-suite] Running unit, adapter & receipt tests ==="
if command -v pytest >/dev/null 2>&1; then
    pytest -q "${KIT_DIR}/tests/test_deterministic_null_suite.py"
else
    python3 -m unittest "${KIT_DIR}/tests/test_deterministic_null_suite.py"
fi

echo "=== [Kit 1: deterministic-null-suite] Running 5-arm classical control benchmark ==="
python3 "${KIT_DIR}/dnull_suite/suite_runner.py" "$@"
