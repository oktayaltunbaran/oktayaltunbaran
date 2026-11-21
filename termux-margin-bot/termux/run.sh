#!/data/data/com.termux/files/usr/bin/bash
# On planda calistirma (test icin). Arka plan icin service-install.sh kullanin.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
termux-wake-lock 2>/dev/null || true
exec ./.venv/bin/python -m bot "$@"
