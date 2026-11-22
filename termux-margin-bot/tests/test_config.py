import tempfile
import unittest
from pathlib import Path

from bot.config import ConfigError, load_settings, parse_env_file


def write(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / ".env"
    p.write_text(text, encoding="utf-8")
    return p


BASE = "TELEGRAM_BOT_TOKEN=123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\nTELEGRAM_CHAT_ID=42\n"


class TestConfig(unittest.TestCase):
    def test_parse(self):
        p = write('# yorum\nA=1\nB="iki kelime"\nexport C=3 # satir sonu\nD=\'x#y\'\n')
        self.assertEqual(parse_env_file(p), {"A": "1", "B": "iki kelime", "C": "3", "D": "x#y"})

    def test_defaults_ok(self):
        s = load_settings(write(BASE))
        self.assertEqual(s.mode, "paper")
        self.assertEqual(s.max_notional_usdt, 150.0)
        self.assertEqual(s.timeframe_ms, 7_200_000)

    def test_live_requires_keys(self):
        with self.assertRaises(ConfigError):
            load_settings(write(BASE + "MODE=live\nEXEC_EXCHANGE=okx\nOKX_API_KEY=a\nOKX_API_SECRET=b\n"))

    def test_sl_vs_liquidation(self):
        # 5x'te likidasyon ~%19.5 -> max SL %13.65 altinda olmali
        with self.assertRaises(ConfigError):
            load_settings(write(BASE + "MAX_SL_PCT=15\n"))
        with self.assertRaises(ConfigError):
            load_settings(write(BASE + "LEVERAGE=20\nMAX_SL_PCT=4\n"))  # 20x: liq ~%4.5

    def test_bad_symbol(self):
        with self.assertRaises(ConfigError):
            load_settings(write(BASE + "SYMBOLS=BTCUSDT\n"))

    def test_bad_number(self):
        with self.assertRaises(ConfigError):
            load_settings(write(BASE + "LEVERAGE=bes\n"))

    def test_env_example_is_valid(self):
        ex = Path(__file__).resolve().parent.parent / ".env.example"
        text = ex.read_text(encoding="utf-8").replace("TELEGRAM_BOT_TOKEN=\n", "").replace("TELEGRAM_CHAT_ID=\n", "")
        s = load_settings(write(BASE + text))
        self.assertEqual((s.margin_usdt, s.leverage, s.timeframe), (30.0, 5, "2h"))
        self.assertEqual(len(s.symbols), 9)
        self.assertNotIn("BTC/USDT", s.symbols)  # 30 USDT'de asgari tutara takilir
        # 4 yillik testte secilen degerler
        self.assertEqual((s.strategy, s.st_len, s.st_mult, s.st_stop_atr), ("supertrend", 10, 3.0, 1.0))
        self.assertEqual((s.risk_mode, s.fixed_margin_usdt, s.leverage, s.tp_roi_pct, s.sl_loss_usdt),
                         ("fixed", 30.0, 5, 25.0, 2.5))
        self.assertEqual((s.max_open_positions, s.max_daily_loss_usdt), (1, 5.0))
        self.assertFalse(s.trailing)  # sabit semada hedef var


if __name__ == "__main__":
    unittest.main()
