#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 1-Command Runner for Kit #9 (`kits/standards-bridge/`)
# Usage: ./kits/standards-bridge/run_kit.sh [--quick] [--no-write]

set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${HOME}/.wasmtime/bin:${PATH}"

echo "=== [Kit 9: standards-bridge] Running OTel, COSE/FlatBuf, Wasm, & CIRCT unit tests ==="
if command -v pytest >/dev/null 2>&1; then
    pytest -q "${KIT_DIR}/tests/test_standards_bridge.py"
else
    python3 -m unittest discover -s "${KIT_DIR}/tests" -p "test_*.py"
fi

echo "=== [Kit 9: standards-bridge] Running 4-module standards interop suite ==="
python3 "${KIT_DIR}/run_standards_bridge.py" "$@"
