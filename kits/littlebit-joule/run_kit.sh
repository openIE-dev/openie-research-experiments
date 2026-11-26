#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 1-Command Runner for Kit 4 (`kits/littlebit-joule/`, Shot on Goal #2)
# Usage: ./kits/littlebit-joule/run_kit.sh [--quick]

set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

echo "=== [Kit 4: littlebit-joule] Running unit & receipt verification tests ==="
if command -v pytest >/dev/null 2>&1; then
    pytest -q "${KIT_DIR}/tests/test_littlebit_joule.py"
else
    python3 -m unittest "${KIT_DIR}/tests/test_littlebit_joule.py"
fi

echo "=== [Kit 4: littlebit-joule] Running hardware-metered 4-regime benchmark ==="
python3 "${KIT_DIR}/littlebit_joule/benchmark.py" "$@"
