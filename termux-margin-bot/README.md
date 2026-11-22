# Termux Margin Long/Short Bot

Binance, OKX ve Bybit'in **spot + vadeli (perpetual)** verilerini birlikte okuyan,
**2 saatlik** grafikte sinyal üreten, **izole marjin / 5x kaldıraç / 30 USDT** sermaye
için tasarlanmış, tamamen **telefonda (Android + Termux)** çalışan Telegram botu.

> ⚠️ **Risk uyarısı.** Kaldıraçlı işlem sermayenin tamamını kaybettirebilir. Bu yazılım
> kâr garantisi vermez; bir karar destek ve emir otomasyonu aracıdır. Varsayılan mod
> `paper`'dır (simülasyon). Gerçek parayla başlamadan önce aşağıdaki
> [Kademeli geçiş planını](#kademeli-geçiş-planı) uygulayın. Bulunduğunuz ülkedeki
> mevzuata (Türkiye'de SPK/kripto varlık düzenlemeleri) ve borsanın bölge
> kısıtlamalarına uymak sizin sorumluluğunuzdadır.

---

## İçindekiler

1. [Mimari](#mimari)
2. [Strateji](#strateji)
3. [Risk matematiği (30 USDT, 5x)](#risk-matematiği-30-usdt-5x)
4. [Güvenlik tasarımı](#güvenlik-tasarımı)
5. [Kurulum (Termux)](#kurulum-termux)
6. [Telegram ve borsa API ayarları](#telegram-ve-borsa-api-ayarları)
7. [Arka planda kesintisiz çalıştırma](#arka-planda-kesintisiz-çalıştırma)
8. [Telegram komutları](#telegram-komutları)
9. [Kademeli geçiş planı](#kademeli-geçiş-planı)
10. [Backtest](#backtest)
11. [Doğrulama ve testler](#doğrulama-ve-testler)
12. [Sorun giderme](#sorun-giderme)
13. [Bilinen sınırlamalar](#bilinen-sınırlamalar)

---

## Mimari

```
                 ┌──────────────────────── Android telefon / Termux ────────────────────────┐
                 │                                                                          │
 Binance ─┐      │  exchanges.py         strategy.py          risk.py          execution.py │
 OKX     ─┼─REST─┼─► MarketData ──────►  2s trend+pullback ─► boyutlama ─────►  Paper/Live   │──REST──► Borsa (emir,
 Bybit   ─┘      │  spot+perp+funding    + türev filtresi     + koruma         Broker        │          SL/TP sunucuda)
                 │  +OI (3 borsa)              │                  │                │        │
                 │                             ▼                  ▼                ▼        │
                 │                       engine.py (tek iş parçacıklı olay döngüsü)         │
                 │                        ├─ zamanlayıcı: her 2s mum kapanışı + 20 sn       │
                 │                        ├─ pozisyon izleme: 30 sn                         │
                 │                        └─ Telegram long-polling: 5 sn                    │
                 │                             │                    │                       │
                 │                       storage.py (SQLite/WAL)   telegram_api.py ◄────────┼──► Telegram (siz)
                 │                                                                          │
                 │  runit (termux-services): çökerse yeniden başlat · Termux:Boot: açılışta │
                 └──────────────────────────────────────────────────────────────────────────┘
```

| Dosya | Görev |
|---|---|
| `bot/config.py` | `.env` okuma, tip/aralık doğrulaması (örn. stop'un likidasyondan önce gelmesi) |
| `bot/indicators.py` | Saf Python EMA/RSI/ATR/ADX — **TA-Lib ile ~1e-14 hassasiyette birebir** |
| `bot/exchanges.py` | ccxt istemci fabrikası, 3 borsadan spot/perp fiyat, funding, açık pozisyon (OI) |
| `bot/strategy.py` | Sinyal kuralları, türev/çapraz-borsa filtreleri, SL/TP |
| `bot/risk.py` | Risk bazlı pozisyon boyutu, likidasyon kontrolü, günlük/seri kayıp korumaları |
| `bot/execution.py` | `PaperBroker` (simülasyon) ve `LiveBroker` (gerçek emir) |
| `bot/engine.py` | Zamanlayıcı, onay akışı, izleme, breakeven, zaman stopu, komutlar |
| `bot/storage.py` | SQLite: işlemler, durum, OI geçmişi, sinyal günlüğü |
| `bot/telegram_api.py` | Bağımlılıksız Telegram istemcisi (long-polling, flood/429 yönetimi) |
| `bot/backtest.py` | Kötümser varsayımlı geriye dönük test |
| `termux/*.sh` | Kurulum, servis, açılışta başlatma, güncelleme |

**Neden bu tercihler?**

- **numpy/pandas yok.** Termux'ta bu paketlerin derlenmesi uzun sürer ve sık kırılır.
  2 saatlik grafikte 1000 mum × 3 sembol için saf Python yeterince hızlıdır.
- **ccxt `--no-deps`, yalnızca senkron API.** Async bağımlılıklar (aiohttp, yarl) C
  derlemesi ister. `cryptography` ise Termux deposundan hazır derlenmiş gelir.
- **Tek iş parçacığı.** Yarış durumu (race condition) yok, davranış deterministik, pil dostu.
- **Long-polling.** Webhook/açık port gerekmez; mobil ağ ve NAT arkasında sorunsuz.
- **SQLite WAL.** Android süreci aniden öldürse bile veri bozulmaz.

---

## Strateji

Analiz **yalnızca kapanmış mumlarda** yapılır (canlı mum atılır → "repaint" yok).
Her 2 saatlik kapanıştan 20 sn sonra (UTC 00:00, 02:00, …) çalışır.

### Teknik koşullar (LONG; SHORT tam aynası)

| # | Koşul | Amaç |
|---|---|---|
| 1 | Kapanış > EMA200 **ve** EMA50 > EMA200 | Ana trend yukarı |
| 2 | ADX(14) ≥ 20 | Yatay/testere piyasayı ele |
| 3 | Son 2 mumun dibi EMA21 + 0.25·ATR'ye değmiş | Geri çekilmeden alım (tepeden değil) |
| 4 | Kapanış > EMA21 ve mum yeşil | Trende geri dönüş teyidi |
| 5 | RSI(14) 45–70 (short: 30–55) | Aşırı alım/satımda girme |
| 6 | Kapanış − EMA21 ≤ 1·ATR | Kaçan fiyatı kovalama |

### Türev ve çapraz-borsa filtreleri (Binance + OKX + Bybit)

| Filtre | Kural |
|---|---|
| Fiyat sapması | Borsalar arası spot/perp sapması > %0.5 → veri anomalisi, işlem yok |
| Çapraz doğrulama | En az 2 borsadan perp fiyatı gelmeli |
| Funding (8s eşdeğerine normalize) | Ortalama > +%0.05 → long kalabalık, long yok; < −%0.05 → short yok |
| Spot–perp bazı | > +%0.5 long'u, < −%0.5 short'u engeller |
| Açık pozisyon (OI) değişimi | Bilgi amaçlı: fiyat ve OI aynı yönde → teyit; ters → kapanış hareketi |

### Çıkış

- **Stop:** 1.5 × ATR(14). %0.4'ten dar olamaz; %4'ten genişse işlem yapılmaz.
- **Hedef:** 2R (stop mesafesinin 2 katı).
- **Breakeven:** Fiyat 1R lehte gidince stop, giriş + komisyon seviyesine taşınır.
- **Zaman stopu:** 24 mum (48 saat) içinde sonuç yoksa piyasa fiyatından kapanır.
- Aynı anda **tek pozisyon**. Birden fazla sinyalde ADX'i en yüksek olan seçilir.

---

## Risk matematiği (30 USDT, 5x)

Bot kaldıracı **risk değil, tavan** olarak kullanır:

```
nominal = RISK_PER_TRADE / (SL% + 2 × komisyon + kayma)
nominal = min(nominal, MARGIN_USDT × LEVERAGE = 150 USDT, serbest bakiye × 5)
```

**Örnek** — ETH 3000 USDT, ATR(2s) = %1.0:

| Kalem | Değer |
|---|---|
| Stop mesafesi | 1.5 × %1.0 = **%1.5** → 2955 |
| Hedef | 2R = %3.0 → 3090 |
| Maliyet oranı | 1.5 + 2×0.06 + 0.05 = %1.67 |
| Nominal | 1.5 / 0.0167 = **89.8 USDT** (150 tavanının altında) |
| Kullanılan marjin | 89.8 / 5 = **18.0 USDT** (izole) |
| Stopta kayıp | ≈ **1.50 USDT** (sermayenin %5'i) |
| Hedefte kâr | ≈ 89.8 × (3% − 0.12%) ≈ **2.59 USDT** |
| Tahmini likidasyon | 3000 × (1 − 1/5 + 0.005) ≈ 2415 (**%19.5 uzakta**, stop %1.5'te) |

Korumalar:

- Günlük zarar 4.5 USDT'ye ulaşınca UTC 00:00'a kadar yeni işlem yok.
- Üst üste 3 kayıpta bot kendini duraklatır (`/devam`).
- Bakiye 20 USDT altına düşerse işlem açılmaz.
- `MAX_SL_PCT`, 5x'teki likidasyon mesafesinin %70'inden büyükse bot **başlamaz**.

> **"Her işlemde 30 × 5 = 150 USDT kullanmak istiyorum"** diyorsanız
> `RISK_PER_TRADE_USDT`'yi yükseltin. Ancak örnekteki %1.5'lik stopta 150 USDT nominal
> ≈ 2.5 USDT (sermayenin %8.3'ü) kayıptır; üst üste 4 stop sermayenin üçte birini
> götürür. Önerilen değer 1–1.5 USDT'dir.

> **Borsa asgari tutarları:** Bot, sembolün asgari nominal/miktar değerini borsadan
> okur. Örneğin Binance BTCUSDT perpetual'da asgari nominal yüksektir (yazım
> anında 100 USDT); 1.5 USDT riskle hesaplanan nominal bunun altında kalırsa sinyal
> "risk kuralı" gerekçesiyle **reddedilir**, asla riski aşacak şekilde büyütülmez.
> ETH ve SOL'de asgari tutarlar düşüktür.

---

## Güvenlik tasarımı

**Emir yürütme (`LiveBroker`):**

1. Tek yönlü (one-way/net) pozisyon modu, **izole** marjin, sabit kaldıraç ayarlanır.
2. Girişten sonra pozisyon borsadan okunur; **gerçek** giriş fiyatı, miktar,
   likidasyon fiyatı ve marjin modu doğrulanır. Marjin modu izole değilse veya
   likidasyon stop'a çok yakınsa pozisyon **anında kapatılır**.
3. Stop-loss **borsada (sunucu tarafında)**, `reduceOnly`, **mark fiyatla** tetiklenen
   emir olarak durur. Telefon kapansa, internet kesilse, Termux öldürülse bile çalışır.
4. Stop-loss 3 denemede konamazsa pozisyon **derhal kapatılır**; korumasız pozisyon kalmaz.
5. Stop taşırken önce **yeni** stop konur, sonra eskisi iptal edilir (arada korumasız an yok).
6. Pozisyon kapanınca kalan tetik emirleri (yetim SL/TP) temizlenir.
7. Borsada botun bilmediği pozisyon varsa uyarı verir ve o sembolde işlem açmaz.

**Sinyal onayı:** Varsayılan olarak her sinyal Telegram'da `✅ Pozisyonu aç / ❌ Geç`
düğmesiyle gelir (15 dk geçerli). Onay anında fiyat sinyalden 0.5R'den fazla
uzaklaşmışsa işlem açılmaz. Bot yeniden başlarken birikmiş eski düğme basışlarını yok sayar.

**Erişim:** Yalnızca `TELEGRAM_CHAT_ID`'den gelen mesaj/düğmeler işlenir. Botu grup
yerine **özel sohbette** kullanın.

**Anahtarlar:** `.env` dosyası `chmod 600`, git dışı. Log'larda token ve API
anahtarları maskelenir. **Para çekme (withdraw) iznini asla açmayın.**

Borsaya giden **gerçek HTTP istekleri** test edildi (`tests/test_ccxt_wire.py`):

| Borsa | Stop-loss isteği |
|---|---|
| Binance | `POST /fapi/v1/algoOrder` · `type=STOP_MARKET` · `reduceOnly=true` · `workingType=MARK_PRICE` |
| Bybit | `POST /v5/order/create` · `triggerDirection` (long: 2, short: 1) · `triggerBy=MarkPrice` · `reduceOnly` |
| OKX | `POST /api/v5/trade/order-algo` · `ordType=conditional` · `slOrdPx=-1` · `slTriggerPxType=mark` · `tdMode=isolated` |

---

## Kurulum (Termux)

### 1. Uygulamalar

- **Termux** ve **Termux:Boot** — ikisini de **aynı kaynaktan** kurun
  (F-Droid veya Termux'un GitHub sürümleri). Farklı kaynaklardan kurulan eklentiler
  imza uyuşmazlığı nedeniyle çalışmaz.
- Termux:Boot'u kurduktan sonra **bir kez açın** (Android açılış iznini böylece alır).

### 2. Kodu indirin ve kurun

```bash
pkg update -y && pkg install -y git
git clone -b claude/telegram-margin-long-short-bot-w7fh3f \
    https://github.com/oktayaltunbaran/oktayaltunbaran.git
cd oktayaltunbaran/termux-margin-bot
bash termux/install.sh
```

> Depo özel (private) ise `git clone` GitHub kullanıcı adı ve bir
> **Personal Access Token** ister (şifre kabul edilmez).

`install.sh` şunları yapar: sistem paketleri (`python`, `python-cryptography`,
`termux-services`), `.venv` sanal ortamı, `ccxt==4.5.93` (`--no-deps`), `.env`
şablonu (`chmod 600`) ve testler.

### 3. Yapılandırma

```bash
nano .env                         # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
.venv/bin/python -m bot chatid    # chat id'nizi bilmiyorsanız
.venv/bin/python -m bot check     # Telegram + 3 borsa + strateji bağlantı testi
bash termux/run.sh                # ön planda deneme (Ctrl+C ile durdur)
```

---

## Telegram ve borsa API ayarları

### Telegram

1. Telegram'da **@BotFather** → `/newbot` → isim verin → **token**'ı `.env`'ye yazın.
2. Kendi botunuza `/start` yazın.
3. `.venv/bin/python -m bot chatid` → çıkan sayıyı `TELEGRAM_CHAT_ID`'ye yazın.

### Borsa API anahtarı (yalnızca `MODE=live`)

Genel kural: **Okuma + Vadeli işlem (Futures/Contract trade)** izni. **Çekim izni asla.**
Mobil IP adresi sürekli değiştiği için IP kısıtlaması çoğu zaman uygulanamaz; bu
yüzden izinleri minimumda tutmak kritik. Borsalar IP bağlanmamış anahtarların
geçerlilik süresini veya izinlerini sınırlayabilir — süre dolarsa anahtarı yenileyin.

| Borsa | Notlar |
|---|---|
| **Binance** | USDⓈ-M Futures hesabını açın. API Management → "Enable Futures". `.env`: `BINANCE_API_KEY/SECRET` |
| **Bybit** | Unified Trading hesabı → API → System-generated → *Contract: Orders & Positions*. **Not:** Unified hesapta izole marjin **hesap düzeyinde** bir ayardır; bot `ISOLATED_MARGIN`'e geçmeyi dener. Hesapta cross modda başka pozisyon varsa geçiş başarısız olur ve `REQUIRE_ISOLATED=true` olduğu için bot işlemi açıp hemen kapatır — böyle bir durumda hesabı elle izole moda alın. |
| **OKX** | Hesap modu vadeli işleme izin vermeli ("Spot and futures" veya üstü). API → *Trade* izni + **passphrase** (`OKX_API_PASSWORD`). Bot pozisyon modunu "net"e almayı dener; açık pozisyon varken bu ayar değişmez, bot o durumda long/short modunu algılayıp ona göre emir gönderir. |

**Demo hesap:** `USE_TESTNET=true` → Binance/Bybit "Demo Trading", OKX "Demo Trading"
anahtarlarıyla çalışır (demo anahtarlarını ilgili borsanın demo panelinden oluşturun).

---

## Arka planda kesintisiz çalıştırma

```bash
bash termux/service-install.sh
# termux-services yeni kurulduysa: Termux'u bildirimden "Exit" ile kapatıp açın, sonra:
sv-enable marginbot && sv up marginbot
```

| İşlem | Komut |
|---|---|
| Durum | `sv status marginbot` |
| Durdur / başlat | `sv down marginbot` / `sv up marginbot` |
| Yeniden başlat | `sv restart marginbot` |
| Canlı log | `tail -f $PREFIX/var/log/sv/marginbot/current` |
| Ayrıntılı log | `tail -f data/logs/bot.log` |
| Güncelle | `bash termux/update.sh` |

- **runit** botu çökerse otomatik yeniden başlatır. Hatalı `.env`'de saniyede bir
  yeniden başlama döngüsüne girmemek için 60 sn bekler.
- **Termux:Boot** telefon açılınca `termux-wake-lock` alır ve servisleri başlatır.

### Android ayarları (çok önemli)

Android, arka plandaki uygulamaları agresif biçimde öldürür:

1. **Ayarlar → Uygulamalar → Termux → Pil → Kısıtlamasız** (Unrestricted / "Optimize etme").
2. Termux bildiriminde **"Acquire wakelock"** görünmeli (servis bunu otomatik alır).
3. Üretici pil yöneticileri (Xiaomi/MIUI, Samsung, Huawei vb.): Termux'u
   "otomatik başlatma" ve "uyutulmayacak uygulamalar" listesine ekleyin.
4. **Android 12+ "phantom process killer"**: Android 14+ cihazlarda
   *Geliştirici seçenekleri → "Alt süreç kısıtlamalarını devre dışı bırak"*.
   Daha eski sürümlerde bilgisayardan ADB ile:
   `adb shell "settings put global settings_enable_monitor_phantom_procs false"`
5. Telefonu mümkünse şarjda ve Wi-Fi'da tutun. Unutmayın: telefon kapansa bile
   **stop-loss borsada** durur; yalnızca breakeven, zaman stopu ve yeni sinyaller durur.

---

## Telegram komutları

| Komut | Açıklama |
|---|---|
| `/durum` | Mod, bakiye, açık pozisyon, risk korumaları, sonraki analiz zamanı |
| `/analiz [ETH]` | Sembol(ler)i şimdi analiz eder: tüm kontroller ✅/▫️, 3 borsanın spot/perp/funding tablosu. Sinyal yoksa **tahmini işlem planı**: giriş bölgesi, stop, hedef, iptal seviyesi ve beklenen koşullar (işlem açmaz) |
| `/backtest [ETH] [gün]` | Geçmiş veride test (varsayılan: tüm semboller, 365 gün; 30–1095). Borsanın gerçek asgari tutarlarıyla; isabet, kâr faktörü, maks. düşüş, long/short ayrımı, son işlemlerin giriş→çıkış fiyatları |
| `/pozisyon` | Açık pozisyon, stop/hedef/likidasyon, gerçekleşmemiş K/Z |
| `/kapat` | Açık pozisyonu piyasa fiyatından kapatır (onay düğmesiyle) |
| `/rapor` | Son 7 gün ve tüm zamanlar: isabet, net K/Z, kâr faktörü, maks. düşüş |
| `/dur` / `/devam` | Yeni işlemleri duraklat / sürdür (`/devam` seri kayıp sayacını sıfırlar) |
| `/oto ac` / `/oto kapat` | Otomatik işlem (onaysız) aç/kapat |
| `/ayarlar` | Geçerli ayarlar |

Mod (`paper`/`live`) ve borsa değişikliği **bilerek** Telegram'dan yapılamaz:
`.env` düzenlenip servis yeniden başlatılmalıdır.

---

## Kademeli geçiş planı

| Aşama | Ayar | Süre | Geçiş kriteri |
|---|---|---|---|
| 1. Paper | `MODE=paper`, `AUTO_TRADE=false` | 2–4 hafta | ≥ 20 işlem, kurallar anlaşıldı, `/rapor` makul |
| 2. Demo | `MODE=live`, `USE_TESTNET=true` | 1–2 hafta | Emirler, SL/TP, breakeven borsa panelinde doğru görünüyor |
| 3. Canlı (onaylı) | `MODE=live`, `USE_TESTNET=false`, `AUTO_TRADE=false` | 2+ hafta | Her sinyali siz onaylıyorsunuz |
| 4. Canlı (otomatik) | `/oto ac` | — | Yalnızca 3. aşama sonuçlarından memnunsanız |

Her aşamada önce `.venv/bin/python -m bot check` çalıştırın.

---

## Backtest

Telegram'dan: `/backtest` (tüm semboller, 365 gün) veya `/backtest ETH 730`.
Termux'tan:

```bash
.venv/bin/python -m bot backtest ETH 365
.venv/bin/python -m bot backtest          # tüm semboller
```

Rapor nasıl okunur:

| Satır | Anlamı | Kabaca iyi |
|---|---|---|
| Kar fakt. | Toplam kazanç / toplam kayıp | > 1.3 |
| Isabet | Kazanan işlem oranı (2R hedefte %35–45 normaldir) | > %35 |
| Maks. dusus | Zirveden en büyük sermaye düşüşü | < %25 |
| Acilamayan sinyal | Borsa asgari tutarı riskinize göre yüksek (örn. BTC) | düşük |
| Al-tut | Aynı dönemde sadece fiyat değişimi (karşılaştırma için) | — |

Tek bir sembol/dönemde iyi görünen sonuç yeterli değildir: en az 3 sembol ve
1–2 yıl test edin, sonuçlar tutarlıysa paper modda gerçek zamanlı doğrulayın.

Varsayımlar **bilerek kötümser**: giriş sinyalden sonraki mumun açılışından + kayma;
aynı mumda hem SL hem TP'ye değildiyse SL sayılır; breakeven bir sonraki mumdan
geçerli; her iki bacakta komisyon. Funding/OI/baz filtreleri geçmiş veride
uygulanmaz (canlı bot daha seçicidir). Funding ödemeleri dahil değildir.

> Backtest sonucu gelecek performansın garantisi değildir. Parametreleri tek bir
> backtest'e göre "optimize etmek" aşırı uyuma (overfitting) yol açar.

---

## Doğrulama ve testler

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

69 test (ağ gerektirmez):

| Test | Kapsam |
|---|---|
| `test_indicators` | EMA/RSI/ATR/ADX bilinen değerler ve uç durumlar (geliştirmede TA-Lib ile 5 rastgele seride ≤ 2e-14 fark) |
| `test_config` | `.env` ayrıştırma, likidasyon/stop tutarlılığı, hatalı değerler |
| `test_risk` | Riskin aşılmaması, 150 USDT tavanı, bakiye tavanı, OKX kontrat büyüklüğü, asgari tutar reddi |
| `test_strategy` | Long/short sinyali, funding/sapma/eksik borsa blokları, canlı mumun atılması |
| `test_execution` | LiveBroker: emir sırası, SL başarısızsa acil kapatma, cross marjin reddi, likidasyon kontrolü, stop taşıma sırası, yetim emir temizliği |
| `test_ccxt_wire` | ccxt'nin her borsaya ürettiği **gerçek HTTP isteği** (endpoint + parametreler) |
| `test_engine` | Uçtan uca: sinyal → onay → pozisyon → TP/SL/BE/zaman stopu → K/Z; yetkisiz sohbet; tekrar basma; seri kayıp koruması; bayat sinyal |
| `test_data_backtest` | 1000 mumluk sayfalı veri çekimi, snapshot matematiği, backtest muhasebesi ve canlı analizle tutarlılık |

> ccxt sürümünü yükseltmeden önce `test_ccxt_wire` mutlaka çalıştırılmalıdır
> (borsalar emir uç noktalarını değiştirebilir — örn. Binance koşullu emirleri algo
> servisine taşıdı).

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `ModuleNotFoundError: cryptography` | `pkg install python-cryptography`; `.venv`'i `--system-site-packages` ile yeniden oluşturun: `rm -rf .venv && bash termux/install.sh` |
| Termux Python sürümü yükseldi, bot açılmıyor | `rm -rf .venv && bash termux/install.sh` |
| `sv: command not found` | `pkg install termux-services`, Termux'u tamamen kapatıp açın |
| Bot birkaç saat sonra duruyor | [Android ayarları](#android-ayarları-çok-önemli) bölümü |
| `Timestamp for this request is outside of the recvWindow` | Telefonda otomatik saat/saat dilimini açın (bot ayrıca sunucu saat farkını hesaplar) |
| Bir borsa sürekli `NetworkError` | Bölge kısıtı olabilir: `.env` → `DATA_EXCHANGES`'tan çıkarın (en az 2 borsa kalmalı) |
| "risk kuralı nedeniyle reddedildi: Nominal … < borsa min" | Sembolün asgari nominali risk limitinize göre yüksek; sembolü çıkarın veya riski bilinçli artırın |
| Telegram'a mesaj gelmiyor | `python -m bot check`; token/chat id; bota önce `/start` yazın |

---

## Bilinen sınırlamalar

- **Geliştirme ortamında borsa API'lerine ağ erişimi yoktu.** Bu nedenle canlı borsa
  verisiyle backtest ve uçtan uca demo-hesap testi burada yapılamadı; emir
  istekleri ccxt'nin HTTP katmanı yakalanarak doğrulandı. İlk kullanımda mutlaka
  `python -m bot check` ve demo hesap aşamasını uygulayın.
- Canlı K/Z, `FEE_RATE` ile **tahmini** komisyon içerir; funding ödemeleri dahil
  değildir. Kesin rakam için borsa geçmişine bakın.
- Paper modda funding ödenmez, emir defteri derinliği modellenmez.
- Funding aralığını bildirmeyen borsalarda 8 saat varsayılır.
- Aynı anda tek pozisyon; kısmi kâr alma yok (bilinçli sadelik).
- Breakeven, zaman stopu ve eksik TP'nin yeniden denenmesi botun çalışıyor olmasını
  gerektirir; stop-loss ise her durumda borsadadır.
