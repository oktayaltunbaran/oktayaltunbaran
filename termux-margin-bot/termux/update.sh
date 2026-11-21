#!/data/data/com.termux/files/usr/bin/bash
# Kodu gunceller, testleri calistirir, servisi yeniden baslatir.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
git pull --ff-only
./.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -3
if command -v sv >/dev/null 2>&1; then sv restart marginbot && sv status marginbot; fi
