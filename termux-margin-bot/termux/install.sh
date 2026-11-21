#!/data/data/com.termux/files/usr/bin/bash
# Termux kurulum betigi. Kullanim:  bash termux/install.sh
set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BOT_DIR"
echo "==> Bot dizini: $BOT_DIR"

if [ -z "${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "HATA: Bu betik Termux icinde calistirilmalidir." >&2
  exit 1
fi

echo "==> Paketler guncelleniyor"
pkg update -y
pkg upgrade -y

echo "==> Sistem paketleri"
# python-cryptography: Termux reposundan HAZIR DERLENMIS gelir (pip ile derlemek
# Rust + clang ister ve telefonda 20+ dk surer / sik basarisiz olur).
pkg install -y python python-cryptography openssl ca-certificates termux-services termux-tools

echo "==> Sanal ortam (.venv) — sistemdeki cryptography'yi gorebilsin diye --system-site-packages"
if [ ! -d .venv ]; then
  python -m venv --system-site-packages .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip

echo "==> Python bagimliliklari"
# ccxt --no-deps: async bagimliliklari (aiohttp, yarl, aiodns) C derlemesi ister;
# bot yalnizca senkron ccxt kullanir.
pip install --no-deps "ccxt==4.5.93"
pip install "requests>=2.31" "certifi>=2024.2.2" "typing_extensions>=4.9"

python - <<'PY'
import ccxt, cryptography, requests
print("ccxt", ccxt.__version__, "| cryptography", cryptography.__version__, "| requests", requests.__version__)
PY

echo "==> Yapilandirma"
mkdir -p data
if [ ! -f .env ]; then
  cp .env.example .env
  echo "   .env olusturuldu -> duzenleyin: nano $BOT_DIR/.env"
fi
chmod 600 .env
chmod 700 data

echo "==> Testler"
python -m unittest discover -s tests -t . 2>&1 | tail -3

cat <<MSG

Kurulum tamam.
Sonraki adimlar:
  1) nano .env                      # Telegram token + chat id
  2) .venv/bin/python -m bot chatid  # chat id bilmiyorsaniz
  3) .venv/bin/python -m bot check   # baglanti testi
  4) bash termux/service-install.sh  # arka plan servisi + otomatik yeniden baslatma
MSG
