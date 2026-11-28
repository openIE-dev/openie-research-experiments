#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 1-Command Runner for Kit #8 (`kits/spec-fidelity-barrier/`)
# Usage: ./kits/spec-fidelity-barrier/run_kit.sh [--quick] [--no-write]

set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

echo "=== [Kit 8: spec-fidelity-barrier] Running unit, AST mutant, & receipt tests ==="
if command -v pytest >/dev/null 2>&1; then
    pytest -q "${KIT_DIR}/tests/test_spec_fidelity_barrier.py"
else
    python3 -m unittest discover -s "${KIT_DIR}/tests" -p "test_*.py"
fi

echo "=== [Kit 8: spec-fidelity-barrier] Running 40-task 4-arm evaluation ==="
python3 "${KIT_DIR}/spec_barrier_eval.py" "$@"
