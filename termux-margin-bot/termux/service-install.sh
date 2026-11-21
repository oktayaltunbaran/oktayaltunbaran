#!/data/data/com.termux/files/usr/bin/bash
# runit (termux-services) servisi kurar: cokerse otomatik yeniden baslar,
# loglar $PREFIX/var/log/sv/marginbot/current dosyasina yazilir.
set -euo pipefail
BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SV="$PREFIX/var/service/marginbot"

if [ ! -x "$BOT_DIR/.venv/bin/python" ]; then
  echo "Once: bash termux/install.sh" >&2; exit 1
fi

mkdir -p "$SV/log"
cat > "$SV/run" <<RUN
#!/data/data/com.termux/files/usr/bin/sh
exec 2>&1
cd "$BOT_DIR"
export BOT_SUPERVISED=1
export PYTHONUNBUFFERED=1
termux-wake-lock 2>/dev/null || true
exec ./.venv/bin/python -m bot
RUN
chmod 700 "$SV/run"
ln -sf "$PREFIX/share/termux-services/svlogger" "$SV/log/run"

# Termux:Boot -> telefon acilinca servisleri baslat
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/00-marginbot" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
. "$PREFIX/etc/profile.d/start-services.sh"
BOOT
chmod 700 "$HOME/.termux/boot/00-marginbot"

if ! command -v sv >/dev/null 2>&1 || [ -z "${SVDIR:-}" ]; then
  cat <<MSG
termux-services yeni kurulduysa servis yoneticisi henuz calismiyor.
Termux'u TAMAMEN kapatip (bildirimden 'Exit') yeniden acin, sonra:
  sv-enable marginbot && sv up marginbot
MSG
  exit 0
fi

sv-enable marginbot
sv up marginbot
sleep 2
sv status marginbot
echo "Log: tail -f \$PREFIX/var/log/sv/marginbot/current"
