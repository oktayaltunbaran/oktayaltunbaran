"""Coin evreni: hacme gore Top-N coin ve Top-N meme coin + meme guvenlik taramasi.

Veri kaynaklari (hepsi ucretsiz):
* CoinMarketCap (CMC_API_KEY varsa; ucretsiz "Basic" anahtar yeterli): tek istekte
  hacim siralamasi + etiketler (stablecoin/memes/wrapped) + ag (platform) bilgisi.
* CoinGecko (anahtarsiz, varsayilan yedek): /coins/markets hacim siralamasi,
  kategori listeleriyle stablecoin/altin/wrapped ayiklama, /coins/{id} ile ag.
* GoPlus Security (anahtarsiz): EVM ve Solana token kontrat + holder analizi.
* RugCheck (anahtarsiz, Solana): ikinci goruş (risk listesi).
* DexScreener (anahtarsiz): DEX likiditesi ve havuz yasi.

ONEMLI: Guvenlik etiketi KONTRAT ve DAGILIM riskini olcer (rug pull, honeypot,
mint/freeze yetkisi, vergi, holder yogunlasmasi, likidite). "GUVENLI" fiyatin
dusmeyecegi anlamina GELMEZ; meme coinler yine de asiri oynaktir.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

log = logging.getLogger("bot.coins")

SAFE, MEDIUM, RISKY, UNKNOWN = "GUVENLI", "ORTA", "RISKLI", "BILINMIYOR"
LEVEL_ICON = {SAFE: "🟢 Guvenli", MEDIUM: "🟡 Orta derece", RISKY: "🔴 Riskli", UNKNOWN: "⚪ Taraniyor"}

# Ag adi normalizasyonu: (gorunen ad, GoPlus zincir kimligi; None = desteklenmiyor)
CHAINS: Dict[str, Tuple[str, Optional[str]]] = {
    "ethereum": ("Ethereum", "1"),
    "binance-smart-chain": ("BNB Chain", "56"),
    "bnb": ("BNB Chain", "56"),
    "bsc": ("BNB Chain", "56"),
    "base": ("Base", "8453"),
    "arbitrum-one": ("Arbitrum", "42161"),
    "arbitrum": ("Arbitrum", "42161"),
    "polygon-pos": ("Polygon", "137"),
    "polygon": ("Polygon", "137"),
    "avalanche": ("Avalanche", "43114"),
    "avalanche-c-chain": ("Avalanche", "43114"),
    "optimistic-ethereum": ("Optimism", "10"),
    "optimism": ("Optimism", "10"),
    "solana": ("Solana", "solana"),
    "tron": ("Tron", "tron"),
    "sui": ("Sui", None),
    "ton": ("TON", None),
    "the-open-network": ("TON", None),
    "aptos": ("Aptos", None),
    "hyperliquid": ("Hyperliquid", None),
    "ordinals": ("Bitcoin (Ordinals)", None),
}
CHAIN_PRIORITY = ["solana", "ethereum", "base", "binance-smart-chain", "bnb", "arbitrum-one", "tron", "polygon-pos"]

MAJOR_CEX = {"binance", "coinbase", "okx", "bybit", "kraken", "upbit", "bitget", "kucoin", "gate", "htx", "mexc"}
CEX_HOLDER_HINTS = ("binance", "coinbase", "okx", "bybit", "kraken", "upbit", "bitget", "kucoin", "gate", "htx",
                    "exchange", "hot wallet", "cold wallet", "robinhood", "crypto.com")
BURN_ADDRS = {"0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead",
              "1nc1nerator11111111111111111111111111111111"}


def split_multiplier_safe(base: str) -> str:
    """'1000PEPE' -> 'PEPE' (vadeli carpan oneki kaldirilir)."""
    from .exchanges import split_multiplier

    return split_multiplier(base.upper())[0]


def chain_label(slug: Optional[str]) -> str:
    if not slug:
        return "Kendi agi"
    return CHAINS.get(slug.lower(), (slug.replace("-", " ").title(), None))[0]


@dataclass
class CoinInfo:
    id: str
    symbol: str
    name: str
    price: float
    volume_24h: float
    change_24h: Optional[float]
    rank: Optional[int]
    chain: Optional[str] = None  # birincil ag slug'i (None = kendi agi / kontrat yok)
    address: Optional[str] = None
    other_chains: int = 0
    native: bool = False  # ag sorgusu BASARILI olup hicbir kontrat bulunmadiysa True

    @property
    def chain_name(self) -> str:
        if self.chain is None and not self.native:
            return "?"
        return chain_label(self.chain)


@dataclass
class SecurityReport:
    level: str
    reasons: List[str] = field(default_factory=list)
    holders: Optional[int] = None
    top10_pct: Optional[float] = None  # borsa/yakim/kilit cuzdanlari HARIC
    liquidity_usd: Optional[float] = None
    age_days: Optional[float] = None
    checked_at: float = 0.0
    sources: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- HTTP
class RateLimited(Exception):
    def __init__(self, host: str, retry_after: float):
        super().__init__(f"{host}: hiz limiti (429), {retry_after:.0f} sn sonra tekrar")
        self.host = host
        self.retry_after = retry_after


class Http:
    def __init__(self, session: Optional[requests.Session] = None, min_interval: float = 0.0):
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": "termux-margin-bot/1.0", "Accept": "application/json"})
        self.min_interval = min_interval
        self._last: Dict[str, float] = {}

    def get(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None, host_gap: float = 0.0) -> Any:
        host = url.split("/")[2]
        wait = self._last.get(host, 0) + host_gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()
        r = self.s.get(url, params=params, headers=headers, timeout=20)
        if r.status_code == 429:
            # Bekleyip tekrar DENEME: ana dongu (Telegram) bloklanmasin; ust katman geri cekilir.
            raise RateLimited(host, float(r.headers.get("Retry-After") or 120))
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------- kaynaklar
class CoinGecko:
    BASE = "https://api.coingecko.com/api/v3"
    GAP = 6.0  # anahtarsiz ucretsiz limit (~10/dk) altinda kal

    def __init__(self, http: Http, api_key: str = ""):
        self.http = http
        self.key = api_key
        if api_key:  # ucretsiz "Demo" anahtar: ~30 istek/dk
            self.http.s.headers["x-cg-demo-api-key"] = api_key
            self.GAP = 2.2
        self._excl: Tuple[float, set] = (0.0, set())
        self._platforms: Dict[str, Tuple[Optional[str], Optional[str], int]] = {}

    def _markets(self, **params) -> List[dict]:
        base = {"vs_currency": "usd", "order": "volume_desc", "per_page": 100, "page": 1}
        base.update(params)
        return self.http.get(f"{self.BASE}/coins/markets", base, host_gap=self.GAP)

    def excluded_ids(self) -> set:
        """Stablecoin, tokenize altin/emtia ve wrapped tokenlar (gunde bir yenilenir)."""
        if time.time() - self._excl[0] < 86_400 and self._excl[1]:
            return self._excl[1]
        ids: set = set()
        for cat in ("stablecoins", "tokenized-gold", "tokenized-commodities", "wrapped-tokens"):
            try:
                ids |= {x["id"] for x in self._markets(category=cat, order="market_cap_desc", per_page=250)}
            except Exception as e:  # noqa: BLE001
                log.warning("CoinGecko kategori %s: %s", cat, e)
        self._excl = (time.time(), ids)
        return ids

    @staticmethod
    def _coin(x: dict) -> CoinInfo:
        return CoinInfo(
            id=x["id"], symbol=str(x["symbol"]).upper(), name=x.get("name", ""),
            price=float(x.get("current_price") or 0), volume_24h=float(x.get("total_volume") or 0),
            change_24h=x.get("price_change_percentage_24h"), rank=x.get("market_cap_rank"),
        )

    def top_by_volume(self, n: int) -> List[CoinInfo]:
        excl = self.excluded_ids()
        out = []
        for x in self._markets(per_page=150):
            if x["id"] in excl or looks_stable(x):
                continue
            out.append(self._coin(x))
            if len(out) >= n:
                break
        return out

    def memes(self, n: int) -> List[CoinInfo]:
        return [self._coin(x) for x in self._markets(category="meme-token", per_page=n)][:n]

    def fill_platform(self, c: CoinInfo) -> None:
        """Birincil ag + kontrat adresi (kalici onbellek: adresler degismez)."""
        if c.id not in self._platforms:
            d = self.http.get(
                f"{self.BASE}/coins/{c.id}",
                {"localization": "false", "tickers": "false", "market_data": "false",
                 "community_data": "false", "developer_data": "false", "sparkline": "false"},
                host_gap=self.GAP,
            )
            plats = {k: v for k, v in (d.get("platforms") or {}).items() if k and v}
            primary = d.get("asset_platform_id") or pick_primary(plats)
            self._platforms[c.id] = (primary, plats.get(primary) if primary else None, max(0, len(plats) - 1))
        c.chain, c.address, c.other_chains = self._platforms[c.id]
        c.native = c.chain is None


class CoinMarketCap:
    BASE = "https://pro-api.coinmarketcap.com"

    def __init__(self, http: Http, api_key: str):
        self.http = http
        self.key = api_key
        self._cache: Tuple[float, List[dict]] = (0.0, [])

    def _listings(self) -> List[dict]:
        # 500 sonuc = 3 kredi; 30 dk onbellek -> ~4.300 kredi/ay (ucretsiz kota 10.000)
        if time.time() - self._cache[0] < 1800 and self._cache[1]:
            return self._cache[1]
        d = self.http.get(f"{self.BASE}/v1/cryptocurrency/listings/latest",
                          {"limit": 500, "sort": "volume_24h", "sort_dir": "desc", "convert": "USD"},
                          headers={"X-CMC_PRO_API_KEY": self.key})
        data = d.get("data") or []
        self._cache = (time.time(), data)
        return data

    @staticmethod
    def _coin(x: dict) -> CoinInfo:
        q = (x.get("quote") or {}).get("USD") or {}
        plat = x.get("platform") or {}
        slug = (plat.get("slug") or "").lower() or None
        return CoinInfo(
            id=str(x.get("slug") or x.get("id")), symbol=str(x.get("symbol", "")).upper(), name=x.get("name", ""),
            price=float(q.get("price") or 0), volume_24h=float(q.get("volume_24h") or 0),
            change_24h=q.get("percent_change_24h"), rank=x.get("cmc_rank"),
            chain=slug, address=plat.get("token_address"), native=not plat,
        )

    def top_by_volume(self, n: int) -> List[CoinInfo]:
        bad = {"stablecoin", "wrapped-tokens", "tokenized-gold", "tokenized-commodities", "asset-backed-stablecoin"}
        out = []
        for x in self._listings():
            tags = set(x.get("tags") or [])
            if tags & bad or looks_stable({"current_price": ((x.get("quote") or {}).get("USD") or {}).get("price")}):
                continue
            out.append(self._coin(x))
            if len(out) >= n:
                break
        return out

    def memes(self, n: int) -> List[CoinInfo]:
        return [self._coin(x) for x in self._listings() if "memes" in (x.get("tags") or [])][:n]

    def fill_platform(self, c: CoinInfo) -> None:  # CMC listesinde zaten var
        return None


def looks_stable(x: dict) -> bool:
    """Kategori etiketi eksik yeni stablecoinler icin yedek: fiyat ~1$ ve 24s aralik dar."""
    p = x.get("current_price")
    hi, lo = x.get("high_24h"), x.get("low_24h")
    if not p or abs(float(p) - 1.0) > 0.02:
        return False
    if hi and lo:
        return (float(hi) - float(lo)) / float(p) < 0.02
    return True


def pick_primary(plats: Dict[str, str]) -> Optional[str]:
    for k in CHAIN_PRIORITY:
        if k in plats:
            return k
    return next(iter(plats), None)


# --------------------------------------------------------------------------- guvenlik
class SecurityScanner:
    GOPLUS = "https://api.gopluslabs.io/api/v1"
    RUGCHECK = "https://api.rugcheck.xyz/v1"
    DEXS = "https://api.dexscreener.com/latest/dex/tokens"

    def __init__(self, http: Http):
        self.http = http

    def scan(self, c: CoinInfo) -> SecurityReport:
        if c.native:
            return SecurityReport(SAFE, ["Kendi agindaki coin: akilli kontrat yok, rug pull/honeypot kontrat riski yok"],
                                  checked_at=time.time(), sources=["-"])
        if not c.chain or not c.address:
            # Ag bilgisi henuz alinamadi: ASLA 'guvenli' varsayma
            return SecurityReport(UNKNOWN, ["Ag/kontrat bilgisi henuz alinamadi"], checked_at=0.0)
        slug = c.chain.lower()
        gp_chain = CHAINS.get(slug, (None, None))[1]
        feats: Dict[str, Any] = {"chain": slug, "rank": c.rank}
        sources = []
        if gp_chain == "solana":
            d = self.http.get(f"{self.GOPLUS}/solana/token_security", {"contract_addresses": c.address}, host_gap=2.0)
            feats["gp_sol"] = first_result(d, c.address)
            sources.append("GoPlus")
            try:
                feats["rugcheck"] = self.http.get(f"{self.RUGCHECK}/tokens/{c.address}/report/summary", host_gap=1.0)
                sources.append("RugCheck")
            except Exception as e:  # noqa: BLE001
                log.info("RugCheck %s: %s", c.symbol, e)
        elif gp_chain:
            d = self.http.get(f"{self.GOPLUS}/token_security/{gp_chain}", {"contract_addresses": c.address},
                              host_gap=2.0)
            feats["gp_evm"] = first_result(d, c.address)
            sources.append("GoPlus")
        try:
            feats["dex"] = (self.http.get(f"{self.DEXS}/{c.address}", host_gap=1.0) or {}).get("pairs") or []
            sources.append("DexScreener")
        except Exception as e:  # noqa: BLE001
            log.info("DexScreener %s: %s", c.symbol, e)
        rep = classify(feats)
        rep.checked_at = time.time()
        rep.sources = sources
        return rep


def first_result(d: Any, address: str) -> Optional[dict]:
    res = (d or {}).get("result") or {}
    if not res:
        return None
    return res.get(address) or res.get(address.lower()) or next(iter(res.values()))


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _flag(v: Any) -> bool:
    if isinstance(v, dict):
        return str(v.get("status")) == "1"
    return str(v) == "1"


def _concentration(holders: List[dict], is_solana: bool) -> Optional[float]:
    """En buyuk 10 cuzdanin payi; borsa, yakim, kilitli ve (EVM'de) kontrat/LP cuzdanlari HARIC."""
    if not holders:
        return None
    tot = 0.0
    for h in holders[:10]:
        tag = str(h.get("tag") or "").lower()
        addr = str(h.get("address") or "").lower()
        if any(x in tag for x in CEX_HOLDER_HINTS) or addr in BURN_ADDRS or str(h.get("is_locked")) == "1":
            continue
        if not is_solana and str(h.get("is_contract")) == "1":
            continue  # LP havuzu / vesting / koprü kontratlari
        tot += _f(h.get("percent"))
    return tot * 100


def classify(feats: Dict[str, Any]) -> SecurityReport:
    """3 seviyeli kural tabanli siniflandirma. Kritik bulgu -> RISKLI; uyarilar -> ORTA."""
    crit: List[str] = []
    warn: List[str] = []
    ok: List[str] = []
    rep = SecurityReport(UNKNOWN)
    evm, sol, rc, dex = feats.get("gp_evm"), feats.get("gp_sol"), feats.get("rugcheck"), feats.get("dex")
    # Piyasa degeri ilk 300'deki tokenlar pratikte buyuk borsalarda listelidir; en buyuk
    # cuzdanlarin bir kismi etiketsiz borsa/saklama cuzdanidir -> yogunluk esikleri gevsetilir.
    rank = feats.get("rank")
    on_cex = bool(rank and int(rank) <= 300)

    if evm is None and sol is None and not dex:
        rep.reasons = ["Guvenlik verisi alinamadi (desteklenmeyen ag veya servis hatasi)"]
        return rep

    if evm:
        owner = str(evm.get("owner_address") or "").lower()
        renounced = owner in ("", *BURN_ADDRS)
        cex = evm.get("is_in_cex") or {}
        cex_list = {str(x).lower() for x in (cex.get("cex_list") or [])} if isinstance(cex, dict) else set()
        on_cex = on_cex or bool(cex_list & MAJOR_CEX)
        if _flag(evm.get("is_honeypot")) or _flag(evm.get("cannot_sell_all")):
            crit.append("Honeypot: token satilamiyor")
        if _flag(evm.get("honeypot_with_same_creator")):
            crit.append("Ayni gelistiricinin baska honeypot tokeni var")
        bt, stx = _f(evm.get("buy_tax")) * 100, _f(evm.get("sell_tax")) * 100
        if max(bt, stx) > 10:
            crit.append(f"Yuksek vergi (alis %{bt:.0f} / satis %{stx:.0f})")
        elif max(bt, stx) > 0:
            warn.append(f"Alim/satim vergisi var (%{bt:.1f}/%{stx:.1f})")
        if str(evm.get("is_open_source")) == "0":
            crit.append("Kontrat kaynak kodu dogrulanmamis")
        if not renounced:
            if _flag(evm.get("owner_change_balance")) or _flag(evm.get("hidden_owner")) \
                    or _flag(evm.get("can_take_back_ownership")) or _flag(evm.get("selfdestruct")):
                crit.append("Sahip bakiyeleri degistirebilir / gizli sahip / sahiplik geri alinabilir")
            if _flag(evm.get("is_mintable")):
                crit.append("Sahibi yeni token basabilir (mint)")
            if _flag(evm.get("transfer_pausable")) or _flag(evm.get("is_blacklisted")) \
                    or _flag(evm.get("slippage_modifiable")):
                warn.append("Sahibi transferi durdurabilir / kara liste / vergi degistirebilir")
        else:
            ok.append("Kontrat sahipligi birakilmis (renounced)")
        if _flag(evm.get("is_proxy")):
            warn.append("Yukseltilebilir (proxy) kontrat")
        rep.holders = int(_f(evm.get("holder_count"))) or None
        rep.top10_pct = _concentration(evm.get("holders") or [], False)
        lp = evm.get("lp_holders") or []
        if lp and not on_cex:
            locked = sum(_f(h.get("percent")) for h in lp
                         if str(h.get("is_locked")) == "1" or str(h.get("address", "")).lower() in BURN_ADDRS)
            if locked < 0.5:
                warn.append(f"DEX likiditesinin yalnizca %{locked * 100:.0f}'i kilitli/yakilmis (LP cekilebilir)")

    if sol:
        if _flag(sol.get("mintable")):
            crit.append("Mint yetkisi acik: yeni token basilabilir")
        if _flag(sol.get("freezable")):
            crit.append("Freeze yetkisi acik: cuzdanlar dondurulabilir")
        if _flag(sol.get("balance_mutable_authority")) or _flag(sol.get("closable")):
            crit.append("Bakiye degistirme/hesap kapatma yetkisi var")
        if sol.get("transfer_fee"):
            warn.append("Transfer ucreti tanimli")
        if _flag(sol.get("transfer_fee_upgradable")) or _flag(sol.get("transfer_hook_upgradable")):
            warn.append("Transfer ucreti/hook sonradan degistirilebilir")
        if any(int(_f(x.get("malicious_address"))) for x in (sol.get("creators") or [])):
            crit.append("Olusturucu adres kotu niyetli olarak isaretli")
        if not crit:
            ok.append("Mint/freeze yetkileri kapali")
        rep.holders = int(_f(sol.get("holder_count"))) or None
        rep.top10_pct = _concentration(sol.get("holders") or [], True)

    if rc:
        dangers = [r.get("name") for r in (rc.get("risks") or []) if r.get("level") == "danger"]
        if dangers:
            warn.append("RugCheck uyarilari: " + ", ".join(str(x) for x in dangers[:3]))

    # Holder yogunlasmasi (borsa/yakim/kilit haric)
    t10 = rep.top10_pct
    if t10 is not None:
        hi_lim, mid_lim = (80, 50) if on_cex else (50, 30)
        if t10 > hi_lim:
            crit.append(f"Ilk 10 cuzdan arzin %{t10:.0f}'ini tutuyor (dump/rug riski)")
        elif t10 > mid_lim:
            warn.append(f"Ilk 10 cuzdan arzin %{t10:.0f}'ini tutuyor")
        else:
            ok.append(f"Dagilim makul (ilk 10 cuzdan %{t10:.0f})")
    if rep.holders is not None and rep.holders < 2000:
        warn.append(f"Az sayida holder ({rep.holders})")

    # Likidite ve yas (DexScreener)
    if dex:
        liq = sum(_f((p.get("liquidity") or {}).get("usd")) for p in dex)
        rep.liquidity_usd = liq
        created = [p.get("pairCreatedAt") for p in dex if p.get("pairCreatedAt")]
        if created:
            rep.age_days = (time.time() * 1000 - min(created)) / 86_400_000
        if not on_cex:
            if liq < 100_000:
                crit.append(f"DEX likiditesi cok dusuk (${liq:,.0f})")
            elif liq < 1_000_000:
                warn.append(f"DEX likiditesi dusuk (${liq:,.0f})")
        if rep.age_days is not None and rep.age_days < 30:
            warn.append(f"Cok yeni token ({rep.age_days:.0f} gunluk)")

    rep.level = RISKY if crit else (MEDIUM if warn else SAFE)
    rep.reasons = crit + warn + (ok if not crit and not warn else ok[:2])
    return rep


# --------------------------------------------------------------------------- evren yoneticisi
class CoinUniverse:
    """Top-N + meme listelerini ve guvenlik raporlarini arka planda guncel tutar.
    tick() ana donguden cagrilir; her cagrida en fazla 1 ag istegi zinciri calisir
    (Telegram yanit vermeye devam eder)."""

    def __init__(self, cfg, storage, http: Optional[Http] = None, source=None, scanner=None,
                 now: Callable[[], float] = time.time):
        self.cfg = cfg
        self.storage = storage
        self.http = http or Http()
        if source is not None:
            self.src = source
        elif getattr(cfg, "cmc_api_key", ""):
            self.src = CoinMarketCap(self.http, cfg.cmc_api_key)
        else:
            self.src = CoinGecko(self.http, getattr(cfg, "coingecko_api_key", ""))
        self.scanner = scanner or SecurityScanner(self.http)
        self.now = now
        self.top: List[CoinInfo] = [CoinInfo(**x) for x in storage.get("u_top", [])]
        self.memes: List[CoinInfo] = [CoinInfo(**x) for x in storage.get("u_memes", [])]
        self.security: Dict[str, SecurityReport] = {
            k: SecurityReport(**v) for k, v in (storage.get("u_security", {}) or {}).items()
        }
        self._t_top = float(storage.get("u_top_ts", 0))
        self._t_meme = float(storage.get("u_meme_ts", 0))
        self.last_error: Optional[str] = None
        self._pause_until = 0.0  # hata/429 sonrasi geri cekilme

    @property
    def source_name(self) -> str:
        return "CoinMarketCap" if isinstance(self.src, CoinMarketCap) else "CoinGecko"

    def _save(self) -> None:
        self.storage.set("u_top", [asdict(x) for x in self.top])
        self.storage.set("u_memes", [asdict(x) for x in self.memes])
        self.storage.set("u_security", {k: asdict(v) for k, v in self.security.items()})
        self.storage.set("u_top_ts", self._t_top)
        self.storage.set("u_meme_ts", self._t_meme)

    def refresh_top(self) -> None:
        self.top = self.src.top_by_volume(self.cfg.universe_size)
        self._t_top = self.now()
        self._save()

    def refresh_memes(self) -> None:
        old = {m.id: m for m in self.memes}
        fresh = self.src.memes(self.cfg.meme_count)
        for m in fresh:  # bilinen ag bilgisini koru (adresler degismez)
            o = old.get(m.id)
            if m.chain is None and not m.native and o is not None:
                m.chain, m.address, m.other_chains, m.native = o.chain, o.address, o.other_chains, o.native
        self.memes = fresh
        self._t_meme = self.now()
        self._save()

    def tick(self) -> Optional[str]:
        """Bir adim is yap; ne yapildigini dondurur (log/test icin)."""
        if self.now() < self._pause_until:
            return None
        try:
            if self.now() - self._t_top > self.cfg.universe_refresh_min * 60 or not self.top:
                self.refresh_top()
                return "top"
            if self.now() - self._t_meme > self.cfg.meme_refresh_min * 60 or not self.memes:
                self.refresh_memes()
                return "memes"
            # Hacim sirasiyla ilerle: once agi bul, hemen ardindan o coini tara
            # (sonuclar kademeli gelir; hiz limiti ilk coinlerin sonucunu geciktirmez).
            ttl = self.cfg.security_ttl_min * 60
            for m in self.memes:
                if m.chain is None and not m.native:
                    self.src.fill_platform(m)
                    self._save()
                    return f"platform:{m.id}"
                rep = self.security.get(m.id)
                if rep is None or self.now() - rep.checked_at > ttl:
                    self.security[m.id] = self.scanner.scan(m)
                    self._save()
                    return f"scan:{m.id}"
            self.last_error = None
            return None
        except RateLimited as e:
            self.last_error = str(e)
            self._pause_until = self.now() + max(60.0, e.retry_after)
            log.info("CoinUniverse: %s", e)
            return "ratelimited"
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            self._pause_until = self.now() + 120
            log.warning("CoinUniverse: %s", self.last_error)
            return "error"

    def level_of(self, symbol: str) -> Optional[str]:
        base = split_multiplier_safe(symbol.split("/")[0])
        for m in self.memes:
            if m.symbol == base:
                rep = self.security.get(m.id)
                return rep.level if rep else UNKNOWN
        return None
