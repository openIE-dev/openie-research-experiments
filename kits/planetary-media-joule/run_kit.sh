#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# 1-Command Runner for `kits/planetary-media-joule/` (Planetary Research Media Blueprint v1.0)
# Usage: ./kits/planetary-media-joule/run_kit.sh [--quick] [--tools-dir /path/to/tools]

set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

echo "=== [planetary-media-joule] Running unit, [G6] ASR gate & signed receipt tests ==="
if command -v pytest >/dev/null 2>&1; then
    pytest -q "${KIT_DIR}/tests/test_planetary_media_joule.py"
else
    python3 -m unittest "${KIT_DIR}/tests/test_planetary_media_joule.py"
fi

echo "=== [planetary-media-joule] Running Planetary Media J/min benchmark ==="
python3 "${KIT_DIR}/meter_media_pipeline.py" --out-dir "${KIT_DIR}/results" --tag local_repro "$@"
rm -f "${KIT_DIR}/results/media_joule_results_local_repro.json" "${KIT_DIR}/results/media_joule_receipt_local_repro.json"
