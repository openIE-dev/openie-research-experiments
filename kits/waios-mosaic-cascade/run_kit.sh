#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 1-Command Runner for Kit 5 (`kits/waios-mosaic-cascade/`, Shots on Goal #3 & #5)
# Usage: ./kits/waios-mosaic-cascade/run_kit.sh [--quick]

set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

echo "=== [Kit 5: waios-mosaic-cascade] Running unit, invariance & fault-halt tests ==="
if command -v pytest >/dev/null 2>&1; then
    pytest -q "${KIT_DIR}/tests/test_waios_mosaic_cascade.py"
else
    python3 -m unittest "${KIT_DIR}/tests/test_waios_mosaic_cascade.py"
fi

echo "=== [Kit 5: waios-mosaic-cascade] Running cross-lane conformance & 4-stage RAPL cascade ==="
python3 "${KIT_DIR}/waios_mosaic/conformance_and_cascade.py" "$@"
