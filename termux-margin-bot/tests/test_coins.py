"""Coin evreni: Top-N, meme listesi, ag bilgisi, guvenlik siniflandirmasi.
Fixture'lar gercek GoPlus / RugCheck / DexScreener / CoinGecko yanitlarindan kucultuldu."""

import copy
import json
import time
import unittest
from pathlib import Path

from bot.coins import (MEDIUM, RISKY, SAFE, UNKNOWN, CoinGecko, CoinInfo, CoinMarketCap, CoinUniverse,
                       RateLimited, SecurityScanner, classify, looks_stable, split_multiplier_safe)
from bot.engine import Engine
from bot.exchanges import MarketData, resolve_perp, split_multiplier
from bot.storage import Storage
from tests.helpers import FakeTelegram, settings

FX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FX / name).read_text())


def evm_pepe():
    return copy.deepcopy(list(fx("goplus_evm_pepe.json")["result"].values())[0])


class TestClassify(unittest.TestCase):
    def test_pepe_real_data_safe(self):
        rep = classify({"gp_evm": evm_pepe(), "rank": 52, "dex": [{"liquidity": {"usd": 25e6}, "pairCreatedAt": 1}]})
        self.assertEqual(rep.level, SAFE, rep.reasons)
        self.assertTrue(any("renounced" in r for r in rep.reasons))
        self.assertGreater(rep.holders, 100_000)

    def test_owner_active_with_mint_is_risky(self):
        d = evm_pepe()
        d["owner_address"] = "0x1234567890abcdef1234567890abcdef12345678"
        d["is_mintable"] = "1"
        rep = classify({"gp_evm": d, "rank": 52})
        self.assertEqual(rep.level, RISKY)
        self.assertTrue(any("mint" in r for r in rep.reasons))

    def test_honeypot_and_taxes(self):
        d = evm_pepe()
        d["is_honeypot"] = "1"
        self.assertEqual(classify({"gp_evm": d, "rank": 52}).level, RISKY)
        d = evm_pepe()
        d["sell_tax"] = "0.05"
        self.assertEqual(classify({"gp_evm": d, "rank": 52}).level, MEDIUM)
        d["sell_tax"] = "0.15"
        self.assertEqual(classify({"gp_evm": d, "rank": 52}).level, RISKY)

    def test_unverified_source_risky(self):
        d = evm_pepe()
        d["is_open_source"] = "0"
        self.assertEqual(classify({"gp_evm": d, "rank": 52}).level, RISKY)

    def test_concentration_excludes_cex_burn_locked_contracts(self):
        d = evm_pepe()
        d["holders"] = [
            {"address": "0xa", "percent": "0.40", "tag": "Binance 14", "is_contract": 0, "is_locked": 0},
            {"address": "0x000000000000000000000000000000000000dead", "percent": "0.30", "is_contract": 0},
            {"address": "0xb", "percent": "0.10", "is_locked": 1, "is_contract": 0},
            {"address": "0xc", "percent": "0.10", "is_contract": 1, "is_locked": 0},
            {"address": "0xd", "percent": "0.05", "is_contract": 0, "is_locked": 0},
        ]
        rep = classify({"gp_evm": d, "rank": 900})
        self.assertAlmostEqual(rep.top10_pct, 5.0)

    def test_small_cap_concentration_and_liquidity(self):
        d = evm_pepe()
        d["is_in_cex"] = {"listed": "0", "cex_list": []}  # kucuk, yalnizca DEX'te
        d["holders"] = [{"address": f"0x{i}", "percent": "0.07", "is_contract": 0, "is_locked": 0} for i in range(10)]
        rep = classify({"gp_evm": d, "rank": 900, "dex": [{"liquidity": {"usd": 50_000}, "pairCreatedAt": 1}]})
        self.assertEqual(rep.level, RISKY)  # %70 > %50 ve likidite < 100K
        self.assertTrue(any("likiditesi cok dusuk" in r for r in rep.reasons))

    def test_trump_real_solana_risky(self):
        sol = list(fx("goplus_sol_trump.json")["result"].values())[0]
        rep = classify({"gp_sol": sol, "rugcheck": fx("rugcheck_trump.json"),
                        "dex": fx("dexscreener_trump.json")["pairs"], "rank": 135})
        self.assertEqual(rep.level, RISKY, rep.reasons)
        self.assertGreater(rep.top10_pct, 80)
        self.assertTrue(any("RugCheck" in r for r in rep.reasons))

    def test_solana_authorities(self):
        sol = list(fx("goplus_sol_trump.json")["result"].values())[0]
        sol = copy.deepcopy(sol)
        sol["holders"] = []
        self.assertEqual(classify({"gp_sol": sol, "rank": 100}).level, SAFE)
        sol["mintable"] = {"status": "1", "authority": [{"address": "x"}]}
        self.assertEqual(classify({"gp_sol": sol, "rank": 100}).level, RISKY)

    def test_no_data_unknown(self):
        self.assertEqual(classify({}).level, UNKNOWN)

    def test_young_token_medium(self):
        d = evm_pepe()
        recent = (time.time() - 5 * 86400) * 1000
        rep = classify({"gp_evm": d, "rank": 52, "dex": [{"liquidity": {"usd": 5e6}, "pairCreatedAt": recent}]})
        self.assertEqual(rep.level, MEDIUM)
        self.assertTrue(any("yeni" in r for r in rep.reasons))


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, headers=None, host_gap=0.0):
        self.calls.append((url, dict(params or {})))
        for key, val in self.routes.items():
            if key in url and (not isinstance(val, dict) or "_match" not in val or
                               all((params or {}).get(k) == v for k, v in val["_match"].items())):
                v = val["body"] if isinstance(val, dict) and "body" in val else val
                if isinstance(v, Exception):
                    raise v
                return v
        raise AssertionError(f"route yok: {url} {params}")


class TestSources(unittest.TestCase):
    def test_coingecko_top_excludes_stables(self):
        top = fx("cg_top.json")
        stables = [{"id": x["id"]} for x in top if x["symbol"] in ("usdt", "usdc", "usd1", "dai", "usdg", "rlusd")]
        http = FakeHttp({
            "coins/markets": {"_matchers": True, "body": None},
        })

        def get(url, params=None, headers=None, host_gap=0.0):
            cat = (params or {}).get("category")
            if cat == "stablecoins":
                return stables
            if cat:
                return []
            return top

        http.get = get
        cg = CoinGecko(http)
        coins = cg.top_by_volume(10)
        syms = [c.symbol for c in coins]
        self.assertEqual(len(coins), 10)
        for s in ("USDT", "USDC", "USD1", "U"):  # 'u' kategori disi ama ~1$ -> looks_stable
            self.assertNotIn(s, syms)
        self.assertEqual(syms[0], "BTC")

    def test_coingecko_platform(self):
        http = FakeHttp({"coins/pepe": {"asset_platform_id": "ethereum",
                                        "platforms": {"ethereum": "0xabc", "arbitrum-one": "0xdef"}},
                         "coins/dogecoin": {"asset_platform_id": None, "platforms": {"": ""}}})
        cg = CoinGecko(http)
        pepe = CoinInfo("pepe", "PEPE", "Pepe", 1e-5, 1e8, 1.0, 52)
        doge = CoinInfo("dogecoin", "DOGE", "Dogecoin", 0.2, 3e8, 1.0, 13)
        cg.fill_platform(pepe)
        cg.fill_platform(doge)
        self.assertEqual((pepe.chain, pepe.address, pepe.other_chains, pepe.chain_name), ("ethereum", "0xabc", 1, "Ethereum"))
        self.assertTrue(doge.native)
        self.assertEqual(doge.chain_name, "Kendi agi")

    def test_cmc_listing_tags_and_platform(self):
        def coin(sym, slug, vol, tags, plat=None, price=1.0):
            return {"symbol": sym, "slug": slug, "name": sym, "cmc_rank": 1, "tags": tags, "platform": plat,
                    "quote": {"USD": {"price": price, "volume_24h": vol, "percent_change_24h": 1.0}}}
        data = {"data": [
            coin("USDT", "tether", 5e10, ["stablecoin"]),
            coin("BTC", "bitcoin", 3e10, [], price=60000),
            coin("PEPE", "pepe", 2e8, ["memes"], {"slug": "ethereum", "name": "Ethereum", "token_address": "0x69"}, 1e-5),
            coin("WBTC", "wrapped-bitcoin", 1e8, ["wrapped-tokens"], {"slug": "ethereum", "token_address": "0x22"}, 60000),
            coin("DOGE", "dogecoin", 3e8, ["memes"], None, 0.2),
        ]}
        cmc = CoinMarketCap(FakeHttp({"listings/latest": data}), "key")
        self.assertEqual([c.symbol for c in cmc.top_by_volume(5)], ["BTC", "PEPE", "DOGE"])
        memes = cmc.memes(5)
        self.assertEqual([m.symbol for m in memes], ["PEPE", "DOGE"])
        self.assertEqual((memes[0].chain_name, memes[0].address), ("Ethereum", "0x69"))
        self.assertTrue(memes[1].native)

    def test_looks_stable(self):
        self.assertTrue(looks_stable({"current_price": 1.0003, "high_24h": 1.001, "low_24h": 0.999}))
        self.assertFalse(looks_stable({"current_price": 1.01, "high_24h": 1.08, "low_24h": 0.95}))
        self.assertFalse(looks_stable({"current_price": 60000}))


class TestScanner(unittest.TestCase):
    def test_native_and_unknown(self):
        sc = SecurityScanner(FakeHttp({}))
        doge = CoinInfo("dogecoin", "DOGE", "Dogecoin", 0.2, 3e8, 1.0, 13, native=True)
        self.assertEqual(sc.scan(doge).level, SAFE)
        pending = CoinInfo("x", "X", "X", 1, 1, 0, 999)  # ag henuz bilinmiyor
        self.assertEqual(sc.scan(pending).level, UNKNOWN)

    def test_scan_solana_uses_goplus_rugcheck_dex(self):
        addr = "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN"
        http = FakeHttp({"solana/token_security": fx("goplus_sol_trump.json"),
                         "rugcheck": fx("rugcheck_trump.json"),
                         "dexscreener": fx("dexscreener_trump.json")})
        c = CoinInfo("official-trump", "TRUMP", "Trump", 5, 8e7, -1, 135, chain="solana", address=addr)
        rep = SecurityScanner(http).scan(c)
        self.assertEqual(rep.level, RISKY)
        self.assertEqual(rep.sources, ["GoPlus", "RugCheck", "DexScreener"])
        self.assertIsNotNone(rep.liquidity_usd)


class FakeSource:
    def __init__(self):
        self.top_calls = 0
        self.fail = None

    def top_by_volume(self, n):
        self.top_calls += 1
        if self.fail:
            raise self.fail
        return [CoinInfo("bitcoin", "BTC", "Bitcoin", 6e4, 3e10, 1, 1),
                CoinInfo("pepe", "PEPE", "Pepe", 1e-5, 2e8, 2, 52),
                CoinInfo("official-trump", "TRUMP", "Trump", 5, 8e7, -1, 135),
                CoinInfo("newcoin", "NEWC", "New", 1, 1e8, 3, 400)]

    def memes(self, n):
        return [CoinInfo("pepe", "PEPE", "Pepe", 1e-5, 2e8, 2, 52),
                CoinInfo("official-trump", "TRUMP", "Trump", 5, 8e7, -1, 135),
                CoinInfo("dogecoin", "DOGE", "Dogecoin", 0.2, 3e8, 1, 13)]

    def fill_platform(self, c):
        c.chain, c.address, c.other_chains = {"pepe": ("ethereum", "0x69", 3),
                                              "official-trump": ("solana", "6p6x", 0),
                                              "dogecoin": (None, None, 0)}[c.id]
        c.native = c.chain is None


class FakeScanner:
    def scan(self, c):
        from bot.coins import SecurityReport
        lvl = {"pepe": SAFE, "official-trump": RISKY, "dogecoin": SAFE}[c.id]
        return SecurityReport(lvl, ["test"], checked_at=time.time(), sources=["fake"])


def universe(clock=None):
    cfg = settings(coins_enabled=True, auto_symbols=True)
    st = Storage(cfg.data_dir / "u.sqlite3")
    unittest.addModuleCleanup(st.close)
    t = [1000.0]
    u = CoinUniverse(cfg, st, source=FakeSource(), scanner=FakeScanner(), now=clock or (lambda: t[0]))
    return u, cfg, st, t


class TestUniverse(unittest.TestCase):
    def test_tick_pipeline_and_persistence(self):
        u, cfg, st, t = universe()
        steps = [u.tick() for _ in range(10)]
        self.assertEqual(steps[:2], ["top", "memes"])
        # hacim sirasiyla: ag -> tarama -> sonraki coin
        self.assertEqual(steps[2:8], ["platform:pepe", "scan:pepe", "platform:official-trump",
                                      "scan:official-trump", "platform:dogecoin", "scan:dogecoin"])
        self.assertIsNone(steps[-1])  # is bitti
        self.assertEqual(u.level_of("1000PEPE/USDT"), SAFE)
        self.assertEqual(u.level_of("TRUMP/USDT"), RISKY)
        self.assertIsNone(u.level_of("BTC/USDT"))  # meme degil
        self.assertTrue(next(m for m in u.memes if m.id == "dogecoin").native)
        # yeniden baslatma: onbellekten yuklenir, ag cagrisi gerekmez
        u2 = CoinUniverse(cfg, st, source=FakeSource(), scanner=FakeScanner(), now=lambda: t[0])
        self.assertEqual([c.symbol for c in u2.top], ["BTC", "PEPE", "TRUMP", "NEWC"])
        self.assertIsNone(u2.tick())

    def test_rescan_after_ttl_and_refresh(self):
        u, cfg, st, t = universe()
        for _ in range(10):
            u.tick()
        t[0] += cfg.security_ttl_min * 60 + 1
        self.assertTrue((u.tick() or "").startswith(("memes", "scan:")))

    def test_rate_limit_pauses(self):
        u, cfg, st, t = universe()
        u.src.fail = RateLimited("api.coingecko.com", 90)
        self.assertEqual(u.tick(), "ratelimited")
        self.assertIsNone(u.tick())  # geri cekilme suresinde ag cagrisi yok
        self.assertEqual(u.src.top_calls, 1)
        t[0] += 91
        u.src.fail = None
        self.assertEqual(u.tick(), "top")


class MarketsEx:
    def __init__(self, markets):
        self.markets = markets


class TestSymbols(unittest.TestCase):
    def test_split_multiplier(self):
        self.assertEqual(split_multiplier("1000PEPE"), ("PEPE", 1000))
        self.assertEqual(split_multiplier("1000000MOG"), ("MOG", 1_000_000))
        self.assertEqual(split_multiplier("1MBABYDOGE"), ("BABYDOGE", 1_000_000))
        self.assertEqual(split_multiplier("BTC"), ("BTC", 1))
        self.assertEqual(split_multiplier("1INCH"), ("1INCH", 1))  # rakamla baslayan gercek ad
        self.assertEqual(split_multiplier_safe("1000PEPE"), "PEPE")

    def test_resolve_perp(self):
        ex = MarketsEx({"BTC/USDT:USDT": {"linear": True}, "1000PEPE/USDT:USDT": {"linear": True},
                        "DEAD/USDT:USDT": {"linear": True, "active": False}})
        self.assertEqual(resolve_perp(ex, "BTC"), ("BTC/USDT", 1))
        self.assertEqual(resolve_perp(ex, "PEPE"), ("1000PEPE/USDT", 1000))
        self.assertIsNone(resolve_perp(ex, "DEAD"))
        self.assertIsNone(resolve_perp(ex, "XYZ"))

    def test_snapshot_scales_multiplier_symbols(self):
        class Ex:
            def __init__(self, markets, prices):
                self.markets, self.prices = markets, prices
                self.options = {}
                self.id = "x"

            def fetch_ticker(self, s):
                return {"last": self.prices[s]}

            def fetch_funding_rate(self, s):
                return {"fundingRate": 0.0001, "interval": "8h"}

            def fetch_open_interest(self, s):
                return {"openInterestValue": 1e6}

            def market(self, s):
                return {"contractSize": 1}

        md = MarketData.__new__(MarketData)
        md.names = ["binance", "okx"]
        md._loaded, md._candles = {}, {}
        md._ensure = lambda e: None
        p = 1e-5
        md.spot = {"binance": Ex({}, {"PEPE/USDT": p}), "okx": Ex({}, {"PEPE/USDT": p * 1.001})}
        md.swap = {"binance": Ex({"1000PEPE/USDT:USDT": {}}, {"1000PEPE/USDT:USDT": p * 1000}),
                   "okx": Ex({"PEPE/USDT:USDT": {}}, {"PEPE/USDT:USDT": p * 1.0005})}
        snap = md.snapshot("1000PEPE/USDT")
        self.assertAlmostEqual(snap.per_exchange["binance"].spot, p * 1000)
        self.assertAlmostEqual(snap.per_exchange["okx"].perp, p * 1.0005 * 1000)
        self.assertLess(snap.divergence_pct, 0.2)  # sahte 1000x sapma yok


class TestEngineUniverse(unittest.TestCase):
    def _engine(self):
        u, cfg, st, t = universe()
        for _ in range(10):
            u.tick()
        cfg.auto_symbols = True

        class Swap:
            markets = {"BTC/USDT:USDT": {"linear": True}, "1000PEPE/USDT:USDT": {"linear": True},
                       "TRUMP/USDT:USDT": {"linear": True}}

        class MD:
            swap = {"binance": Swap()}

            def _ensure(self, ex):
                pass

        tg = FakeTelegram()
        eng = Engine(cfg, tg=tg, md=MD(), storage=st, broker=object.__new__(type("B", (), {"mode": "paper"})),
                     universe=u)
        return eng, tg

    def test_symbols_from_universe(self):
        eng, tg = self._engine()
        # NEWC borsada yok; TRUMP 'Riskli' meme -> islem listesinde yok; PEPE -> 1000PEPE
        self.assertEqual(eng.symbols(), ["BTC/USDT", "1000PEPE/USDT"])

    def test_top30_and_meme_commands(self):
        eng, tg = self._engine()
        eng.cmd_top30([])
        txt = tg.sent[-1]["text"]
        self.assertIn("1000PEPE", txt)
        self.assertIn("riskli meme", txt)
        self.assertIn("vadelide yok", txt)
        eng.cmd_meme([])
        txt = tg.sent[-1]["text"]
        self.assertIn("Ethereum +3", txt)
        self.assertIn("Solana", txt)
        self.assertIn("Kendi agi", txt)
        self.assertIn("🔴 Riskli", txt)
        self.assertIn("🟢 Guvenli", txt)
        eng.cmd_meme(["TRUMP"])
        self.assertIn("Kontrat", tg.sent[-1]["text"])


if __name__ == "__main__":
    unittest.main()
