"""
Master Crypto Signal Bot -- Full Layer System
-----------------------------------------------
Ye aapke Master_Trading_Strategy.docx ke saare layers ko code mein
implement karta hai:

  Layer 0  -> Universe Scan / Auto Coin Selection (poore Binance USDT
              market se khud coins choose karta hai, sirf BTC/ETH/SOL
              tak seemit nahi)
  Layer 1  -> Fundamental screening (CoinGecko free API se market cap
              tier, supply, volume/mcap ratio)
  Layer 2  -> On-chain-ish checks (CoinGecko + DefiLlama free data --
              NOTE neeche padhein, deep whale-tracking paid tools maangta hai)
  Layer 3  -> Market Structure (BOS/CHoCH + liquidity sweep, aapka
              original sweep_reclaim_signal.py logic yahi se liya gaya hai)
  Layer 4  -> Candle confirmation (engulfing / pin bar)
  Layer 5  -> Entry / SL / TP calculation
  Layer 6  -> Risk management (position size, daily loss limit)
  Layer 7  -> Money management ke rules (comments mein, execution
              wrapper mein handle hota hai)
  Layer 8  -> News filter (placeholder -- neeche "TODO" dekhein)
  Layer 9  -> Scoring system -- sab layers ko /100 score mein combine
              karta hai, sirf score >= SCORE_THRESHOLD par Telegram alert
  Layer 10 -> Quick Trade Note format mein hi Telegram message banta hai

IMPORTANT -- Ye ab Telegram alert ke saath-saath, agar aap chahein
(EXCHANGE_EXECUTION_ENABLED=true .env mein), Bybit DEMO trading account
par bhi order place kar sakta hai. Default OFF hai -- jab tak aap khud
.env mein "true" na karein, ye sirf alert bhejega, koi order place nahi
karega. Demo trading mein REAL PAISA use nahi hota, fake balance hoti hai.
"""

import os
import time
import csv
import json
import logging
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException
import requests

from proxy_manager import get_proxy

try:
    from pybit.unified_trading import HTTP as BybitHTTP
except ImportError:
    BybitHTTP = None  # 'pip install pybit' na kiya ho to bot alert-only mode mein chalega
# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_PROXY = get_proxy()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# --- Bybit DEMO trading (naya) ---
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_CATEGORY = os.getenv("BYBIT_CATEGORY", "linear")  # "linear" = USDT perpetual, "spot" = spot
EXCHANGE_EXECUTION_ENABLED = os.getenv("EXCHANGE_EXECUTION_ENABLED", "false").strip().lower() == "true"
BYBIT_CREDENTIALS_PRESENT = bool(BYBIT_API_KEY and BYBIT_API_SECRET)
BYBIT_EXECUTION_REQUESTED = EXCHANGE_EXECUTION_ENABLED
if EXCHANGE_EXECUTION_ENABLED and not BYBIT_CREDENTIALS_PRESENT:
    EXCHANGE_EXECUTION_ENABLED = False

# --- Arkham Intelligence (naya) -- Layer 2 real on-chain data ---
# Free key yahan se lein: https://intel.arkm.com/api
# Khali chhodne par bot khud DefiLlama wale purane fallback proxy par chala jayega,
# kuch break nahi hoga.
ARKHAM_API_KEY = os.getenv("ARKHAM_API_KEY", "")
ARKHAM_BASE = "https://api.arkm.com"

# --- Optional EMA Trend Filter (naya) -- DEFAULT OFF ---
# Agar TRUE karein, bot sirf tabhi trade lega jab bada trend (EMA) bhi
# usi direction mein ho -- extra confluence, TradingView-style indicator
# se liya gaya. Default OFF hai taaki jo abhi testing chal rahi hai
# (SCORE_THRESHOLD=55) usme koi disturbance na aaye. Jab chahein
# .env mein TREND_FILTER_ENABLED=true karke ON kar sakte hain.
TREND_FILTER_ENABLED = os.getenv("TREND_FILTER_ENABLED", "false").strip().lower() == "true"
TREND_FILTER_EMA_PERIOD = int(os.getenv("TREND_FILTER_EMA_PERIOD", "50"))
try:
    from indicators_calc import calc_ema
except ImportError:
    calc_ema = None
    if TREND_FILTER_ENABLED:
        TREND_FILTER_ENABLED = False  # file missing to filter khud-ba-khud band

TIMEFRAME = Client.KLINE_INTERVAL_1HOUR  # 15m se 1h -- backtest (365 din, 214 trades) ne confirm kiya ki 1h par fees ke baad bhi net profitable hai, 15m mein SL bahut tight tha
SWING_LOOKBACK = 20
LOOP_INTERVAL_SECONDS = 900  # 5 min se 15 min -- TIMEFRAME ab 1h hai, itni jaldi check karne ki zaroorat nahi
MAX_RETRY_BACKOFF = 60

# --- Layer 0 settings: universe scan ---
MIN_24H_VOLUME_USDT = 20_000_000     # illiquid coins yahan se chhoote jaate hain
MAX_UNIVERSE_SIZE = 40               # itne top-volume coins tak hi scan karo (API/rate-limit safe)
FINAL_SHORTLIST_SIZE = int(os.getenv("FINAL_SHORTLIST_SIZE", "20"))  # in mein se kitne aage layer 1-9 tak jayein (env override)

# --- Manual watchlist override (naya) ---
# MANUAL_WATCHLIST_ENABLED=true karne par Layer 0 ka auto top-volume scan
# (select_final_universe) bilkul skip ho jaata hai -- bot sirf isi fixed
# coin list par scan karta hai, har cycle mein, bina badle. Ye 30-coin
# backtest-verified list (365 din, --min-score 70 se test hui) use karne
# ke liye hai -- taaki live bot un obscure/illiquid coins (SNDKBUSDT,
# SPCXBUSDT jaise) ko na chune jo Bybit futures par exist hi nahi karte
# ya jinka backtest data hi available nahi tha.
MANUAL_WATCHLIST_ENABLED = os.getenv("MANUAL_WATCHLIST_ENABLED", "false").strip().lower() == "true"
_DEFAULT_MANUAL_WATCHLIST = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT,"
    "TRXUSDT,LTCUSDT,SHIBUSDT,UNIUSDT,ATOMUSDT,ETCUSDT,XLMUSDT,NEARUSDT,APTUSDT,FILUSDT,"
    "ARBUSDT,OPUSDT,INJUSDT,SUIUSDT,RUNEUSDT,AAVEUSDT,SANDUSDT,ALGOUSDT"
)
MANUAL_WATCHLIST = [
    s.strip().upper() for s in os.getenv("MANUAL_WATCHLIST", _DEFAULT_MANUAL_WATCHLIST).split(",")
    if s.strip()
]

# --- Layer 9 scoring weights (Master_Trading_Strategy.docx se match) ---
WEIGHTS = {
    "fundamental": 10,
    "onchain": 10,
    "structure": 20,
    "ob_fvg": 10,
    "sweep": 10,
    "candle": 5,
    "vsa": 15,
    "risk_reward": 10,
    "news": 10,
    "pullback": 15,  # NEW! Trend pullback = high priority (ICT concept)
    "macd": 12,     # NEW! MACD indicator (backtest winner on AVAX 8.82%)
}
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "75"))   # Minimum score needed to open a trade; below this only alerts may be sent
SCORE_FALLBACK_MARGIN = float(os.getenv("SCORE_FALLBACK_MARGIN", "8"))

# --- Layer 6 risk management settings (Playbook Section 11) ---
ACCOUNT_SIZE_USDT = float(os.getenv("ACCOUNT_SIZE_USDT", "5962.0"))  # $5962 demo balance
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))  # per trade max 1-2% risk
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "5.0"))  # din ka max loss, isse aage bot naya trade suggest nahi karega
MAX_SL_DISTANCE_PCT = float(os.getenv("MAX_SL_DISTANCE_PCT", os.getenv("MAX_SL_PCT", "3.0")))
MIN_SL_DISTANCE_PCT = float(os.getenv("MIN_SL_DISTANCE_PCT", "0.25"))
MIN_RISK_REWARD_RATIO = float(os.getenv("MIN_RISK_REWARD_RATIO", "1.5"))
USE_ISOLATED_MARGIN = os.getenv("USE_ISOLATED_MARGIN", "true").strip().lower() == "true"
MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "12"))
MAX_MARGIN_UTILIZATION_PCT = float(os.getenv("MAX_MARGIN_UTILIZATION_PCT", "80.0"))

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler("bot_log.txt", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("master_bot")

last_alerted = {}
daily_loss_tracker = {"date": None, "loss_pct": 0.0}


def send_telegram_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram token/chat id missing - skipping alert send.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    proxies = TELEGRAM_PROXY if TELEGRAM_PROXY else None
    if proxies:
        log.info("Telegram proxy configured, sending via proxy.")
    try:
        resp = requests.post(url, json=payload, timeout=15, proxies=proxies)
        if resp.status_code != 200:
            log.error("Telegram send failed: %s - %s", resp.status_code, resp.text)
        else:
            log.info("Telegram alert sent.")
    except requests.exceptions.ConnectTimeout:
        log.error("Telegram request timed out. Check network/firewall or proxy settings.")
    except requests.exceptions.ProxyError as e:
        log.error("Telegram proxy error: %s", e)
    except requests.exceptions.RequestException as e:
        log.error("Telegram request error: %s", e)


# ---------------------------------------------------------------------------
# LAYER 0 -- UNIVERSE SCAN / AUTO COIN SELECTION
# ---------------------------------------------------------------------------

# Stablecoins ko universe se hamesha exclude karo -- ye kabhi "trade signal"
# nahi denge kyunki inki price ~$1 par pegged rehti hai.
STABLECOINS = {
    "USDC", "USDT", "FDUSD", "TUSD", "BUSD", "DAI", "USD1", "RLUSD",
    "PYUSD", "USDP", "GUSD", "EURT", "USDE", "FRAX",
}

# Ye cache batched CoinGecko response store karta hai taaki fundamental_score
# aur onchain_score dobara API call na maarein -- isi se rate-limit bachta hai.
_market_data_cache = {}


def is_stablecoin(symbol: str) -> bool:
    return symbol.replace("USDT", "") in STABLECOINS


def get_universe(client: Client):
    """
    Binance ke saare USDT pairs se 24h ticker khींचta hai, illiquid coins
    aur stablecoins filter karta hai, aur top volume ke hisaab se ek list deta hai.
    """
    try:
        tickers = client.get_ticker()
    except BinanceAPIException as e:
        log.error("Universe scan failed: %s", e)
        return []

    usdt_pairs = [
        t for t in tickers
        if t["symbol"].endswith("USDT")
        and not is_stablecoin(t["symbol"])
        and not any(x in t["symbol"] for x in ["UP", "DOWN", "BULL", "BEAR"])  # leveraged tokens skip
        and float(t.get("quoteVolume", 0)) >= MIN_24H_VOLUME_USDT
    ]
    usdt_pairs.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    return [t["symbol"] for t in usdt_pairs[:MAX_UNIVERSE_SIZE]]


def fetch_market_data_batch(symbols: list) -> dict:
    """
    Saare symbols ka CoinGecko data EK (ya chunks mein bahut kam) request
    mein leta hai -- pehle wala version har symbol ke liye alag request
    bhej raha tha jo free-tier rate limit se turant block ho jaata hai.
    Returns: {"BTCUSDT": {...coingecko data...}, ...}
    """
    result = {}
    bases = [s.replace("USDT", "").lower() for s in symbols]
    chunk_size = 25  # CoinGecko URL/response size ke hisaab se safe batch
    for i in range(0, len(bases), chunk_size):
        chunk = bases[i:i + chunk_size]
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "symbols": ",".join(chunk)},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            data = r.json()
            if not isinstance(data, list):
                log.warning("CoinGecko batch lookup failed (status %s): %s", r.status_code, data)
                continue
            for d in data:
                sym = (d.get("symbol") or "").upper() + "USDT"
                result[sym] = d
        except Exception as e:
            log.warning("CoinGecko batch request error: %s", e)
        if i + chunk_size < len(bases):
            time.sleep(2)  # agla chunk bhejne se pehle rate-limit ka khayal
    return result


def select_final_universe(client: Client):
    """
    Layer 0 ka output -- large/mid/emerging ka mix banata hai
    (institutional_crypto_screener_prompt ke Stage 0 jaisa).
    Ab sirf EK batched CoinGecko call karta hai, symbol-by-symbol nahi.
    """
    candidates = get_universe(client)
    if not candidates:
        return []

    market_data = fetch_market_data_batch(candidates)
    _market_data_cache.update(market_data)

    tiers = {"large_cap": [], "mid_cap": [], "emerging": []}
    for sym in candidates:
        d = market_data.get(sym)
        if not d:
            continue
        mcap = d.get("market_cap") or 0
        if mcap > 10_000_000_000:
            tiers["large_cap"].append(sym)
        elif mcap > 1_000_000_000:
            tiers["mid_cap"].append(sym)
        else:
            tiers["emerging"].append(sym)

    shortlist = (
        tiers["large_cap"][:3] + tiers["mid_cap"][:3] + tiers["emerging"][:3]
    )[:FINAL_SHORTLIST_SIZE]

    if not shortlist:
        log.warning("CoinGecko se koi tier data nahi mila -- top volume coins hi use kar rahe hain.")
        shortlist = candidates[:FINAL_SHORTLIST_SIZE]

    log.info("Layer 0 shortlist: %s", shortlist)
    return shortlist


# ---------------------------------------------------------------------------
# LAYER 1 -- FUNDAMENTAL SCREENING (simplified, free-data version)
# ---------------------------------------------------------------------------
def fundamental_score(symbol: str) -> float:
    """
    0-1 ke beech score deta hai. Free CoinGecko data se:
    - volume/mcap ratio (zyada = zyada active/liquid)
    - circulating vs max supply (kam dilution risk = better)
    Poori institutional-depth analysis (team, VC, audits) ke liye
    aapka research_prompt.docx istemal karke Claude se manually /
    periodically report generate karayein -- wo yahan API se automate
    nahi ho sakta.
    """
    d = _market_data_cache.get(symbol)
    if not d:
        # cache mein nahi mila (naya coin ya universe refresh nahi hua) -- ek chhota fallback call
        fresh = fetch_market_data_batch([symbol])
        _market_data_cache.update(fresh)
        d = fresh.get(symbol)
    if not d:
        return 0.5
    try:
        vol_mcap_ratio = (d.get("total_volume", 0) or 0) / max(d.get("market_cap", 1) or 1, 1)
        score = min(vol_mcap_ratio * 5, 1.0)  # rough heuristic, 0-1 clip
        return round(score, 2)
    except Exception as e:
        log.warning("Fundamental score failed for %s: %s", symbol, e)
        return 0.5


# ---------------------------------------------------------------------------
# LAYER 2 -- ON-CHAIN INTELLIGENCE (free-tier approximation)
# ---------------------------------------------------------------------------
_last_arkham_heavy_call = 0.0
ARKHAM_HEAVY_MIN_INTERVAL = 1.1  # Arkham free tier: heavy endpoints 1 req/sec

# Bahut se chhote/naye coins Arkham par track nahi hote -- unke liye baar baar
# 404 maar ke rate-limit waste na ho, isliye ek run ke andar cache kar lete hain.
_arkham_unavailable_cache = set()


def _arkham_token_flow(base_symbol: str, time_last: str = "24h", limit: int = 20):
    """Arkham /token/top_flow/{symbol} ko seedha REST call karta hai (MCP nahi,
    seedhi httpx/requests call -- bot khud chalta hai, Claude Desktop ki zaroorat nahi)."""
    global _last_arkham_heavy_call
    if not ARKHAM_API_KEY or base_symbol in _arkham_unavailable_cache:
        return None

    gap = time.monotonic() - _last_arkham_heavy_call
    if gap < ARKHAM_HEAVY_MIN_INTERVAL:
        time.sleep(ARKHAM_HEAVY_MIN_INTERVAL - gap)
    _last_arkham_heavy_call = time.monotonic()

    try:
        r = requests.get(
            f"{ARKHAM_BASE}/token/top_flow/{base_symbol}",
            params={"timeLast": time_last, "limit": limit},
            headers={"API-Key": ARKHAM_API_KEY, "Accept": "application/json"},
            timeout=15,
        )
        if r.status_code == 404:
            _arkham_unavailable_cache.add(base_symbol)  # ye token Arkham par nahi hai
            return None
        if r.status_code != 200:
            log.warning("Arkham token_flow %s: status %s", base_symbol, r.status_code)
            return None
        return r.json()
    except Exception as e:
        log.warning("Arkham token_flow request error for %s: %s", base_symbol, e)
        return None


def _arkham_onchain_score(symbol: str, direction: str):
    """
    Real on-chain whale/exchange flow se score deta hai. Idea simple hai:
    - Agar bade addresses/entities is token ko ACCUMULATE kar rahe hain
      (inflow > outflow un entities mein) aur hamara signal LONG hai -> bullish confirmation
    - Agar DISTRIBUTE ho raha hai (outflow > inflow) aur signal SHORT hai -> bearish confirmation
    - Ulta case ho (signal ke against) -> score neeche
    Returns None agar Arkham se data nahi mila (fallback DefiLlama use hoga).
    """
    base = symbol.replace("USDT", "")
    data = _arkham_token_flow(base)
    if not data:
        return None

    entries = data if isinstance(data, list) else data.get("data") or data.get("result") or []
    if not entries:
        return None

    total_in, total_out = 0.0, 0.0
    for e in entries:
        total_in += float(e.get("inUSD", 0) or 0)
        total_out += float(e.get("outUSD", 0) or 0)

    if total_in == 0 and total_out == 0:
        return None

    net = total_in - total_out  # positive = tracked entities accumulate kar rahe (buying pressure)
    denom = max(total_in + total_out, 1e-9)
    net_ratio = net / denom  # -1 (pure distribution) .. +1 (pure accumulation)

    # direction ke saath align -> high score, against -> low score
    aligned = net_ratio if direction == "LONG" else -net_ratio
    score = 0.5 + (aligned * 0.5)  # 0.5 neutral centre, +/-0.5 range se 0..1 tak
    return round(max(0.0, min(1.0, score)), 2)


def onchain_score(symbol: str, direction: str = "LONG") -> float:
    """
    Layer 2 -- on-chain intelligence.
    Pehle Arkham (real whale/exchange flow, agar ARKHAM_API_KEY set hai) try karta
    hai. Available na ho (key missing, token untracked, ya API error) to purana
    DefiLlama TVL-based proxy fallback use hota hai -- taaki bot kabhi crash na ho.
    """
    arkham = _arkham_onchain_score(symbol, direction)
    if arkham is not None:
        log.info("%s: onchain score from Arkham (real flow) = %.2f", symbol, arkham)
        return arkham

    # --- Fallback: DefiLlama TVL proxy (jaisa pehle tha) ---
    base = symbol.replace("USDT", "").lower()
    try:
        r = requests.get(f"https://api.llama.fi/tvl/{base}", timeout=10)
        if r.status_code == 200 and r.text.strip().replace(".", "", 1).isdigit():
            return 0.65
    except Exception:
        pass
    return 0.5  # neutral -- kahin se bhi data nahi mila


# ---------------------------------------------------------------------------
# LAYER 3 -- MARKET STRUCTURE (BOS/CHoCH + Liquidity Sweep)
# (aapke original sweep_reclaim_signal.py se liya + BOS/CHoCH add kiya)
# ---------------------------------------------------------------------------
def get_klines(client: Client, symbol: str):
    raw = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=SWING_LOOKBACK + 2)
    return [
        {
            "open_time": k[0], "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "close_time": k[6],
            "volume": float(k[5]),
        }
        for k in raw
    ]


def check_structure(candles: list):
    """Returns dict with sweep signal + a simple BOS/CHoCH flag, or None."""
    if len(candles) < SWING_LOOKBACK + 1:
        return None
    closed = candles[:-1]
    lookback = closed[-SWING_LOOKBACK:-1]
    test_candle = closed[-1]
    if not lookback:
        return None

    swing_low = min(c["low"] for c in lookback)
    swing_high = max(c["high"] for c in lookback)
    mid_point = len(lookback) // 2
    prior_high = max(c["high"] for c in lookback[:mid_point]) if mid_point else swing_high
    prior_low = min(c["low"] for c in lookback[:mid_point]) if mid_point else swing_low

    result = None
    if test_candle["low"] < swing_low and test_candle["close"] > swing_low:
        bos = test_candle["close"] > prior_high  # naya high todke close -- structure shift
        result = {
            "direction": "LONG", "swept_level": swing_low, "close": test_candle["close"],
            "candle_time": test_candle["close_time"], "bos_confirmed": bos,
        }
    elif test_candle["high"] > swing_high and test_candle["close"] < swing_high:
        bos = test_candle["close"] < prior_low
        result = {
            "direction": "SHORT", "swept_level": swing_high, "close": test_candle["close"],
            "candle_time": test_candle["close_time"], "bos_confirmed": bos,
        }
    return result


# ---------------------------------------------------------------------------
# LAYER 3b -- ORDER BLOCKS (OB) + FAIR VALUE GAPS (FVG) -- NAYA
# ---------------------------------------------------------------------------
# Simplified "Normal OB" + FVG detection, jo aapke collected SMC videos ke
# concepts par based hai:
#   - FVG (Fair Value Gap): 3-candle imbalance -- candle 1 ka high/low,
#     candle 3 ke low/high se gap chhod deta hai, candle 2 (beech wali)
#     usme impulsive move karti hai.
#   - Order Block: aakhri opposite-colour candle jo ek impulsive move se
#     pehle aayi ho (jaise SMC videos mein "Normal OB" kehte hain).
# NOTE: Ye ek simplified version hai -- videos mein bataye gaye 9 OB types
# aur 6 pullback types (Breaker, Mitigation, Rejection, Inducement, etc.)
# implement nahi kiye hain, sirf sabse common/base pattern liya hai.


def detect_fvg(candles: list, direction: str, lookback: int = 10) -> bool:
    """Pichle `lookback` closed candles mein trade ki direction wala FVG dhoondta hai."""
    closed = candles[:-1]
    recent = closed[-lookback:] if len(closed) >= lookback else closed
    for i in range(1, len(recent) - 1):
        c1, c3 = recent[i - 1], recent[i + 1]
        if direction == "LONG" and c1["high"] < c3["low"]:
            return True  # bullish FVG -- gap neeche se upar
        if direction == "SHORT" and c1["low"] > c3["high"]:
            return True  # bearish FVG -- gap upar se neeche
    return False


def detect_order_block(candles: list, direction: str, lookback: int = 10) -> bool:
    """
    Pichle candles mein ek 'Normal OB' dhoondta hai -- ek opposite-colour
    candle jiske turant baad ek impulsive (average se badi) move aayi ho.
    """
    closed = candles[:-1]
    recent = closed[-lookback:] if len(closed) >= lookback else closed
    if len(recent) < 3:
        return False
    avg_range = sum(abs(c["close"] - c["open"]) for c in recent) / len(recent)
    if avg_range == 0:
        return False
    for i in range(len(recent) - 2):
        c, nxt = recent[i], recent[i + 1]
        body = abs(nxt["close"] - nxt["open"])
        is_impulsive = body > avg_range * 1.5
        if direction == "LONG" and c["close"] < c["open"] and nxt["close"] > nxt["open"] and is_impulsive:
            return True  # bearish candle ke baad bullish impulsive move -- bullish OB
        if direction == "SHORT" and c["close"] > c["open"] and nxt["close"] < nxt["open"] and is_impulsive:
            return True  # bullish candle ke baad bearish impulsive move -- bearish OB
    return False



# ---------------------------------------------------------------------------
# LAYER 3c -- VOLUME SPREAD ANALYSIS (VSA) -- NAYA
# ---------------------------------------------------------------------------
# Aapke collected VSA knowledge (Effort vs Result / Wyckoff) par based:
#   - Healthy move: badi candle + high volume = genuine participation
#   - Absorption/Churning: high volume, chhota move = "hands change",
#     bade players exit kar rahe hain -- reversal warning
#   - Buying/Selling Climax: bahut zyada volume + badi candle, ek trend
#     ke aakhir mein = trap, institutions profit book kar rahe
#   - Stopping Volume: volume shrink ho raha ho trend ke against direction
#     mein = trend exhaust ho raha hai


def vsa_score(candles: list, direction: str, lookback: int = 15) -> float:
    """
    0-1 ke beech score deta hai -- kya current volume+candle behaviour
    trade ki direction ko support karta hai ya warning deta hai.
    """
    closed = candles[:-1]
    recent = closed[-lookback:] if len(closed) >= lookback else closed
    if len(recent) < 3:
        return 0.5  # data kaafi nahi -- neutral

    test_candle = recent[-1]
    avg_volume = sum(c["volume"] for c in recent[:-1]) / max(len(recent) - 1, 1)
    avg_body = sum(abs(c["close"] - c["open"]) for c in recent[:-1]) / max(len(recent) - 1, 1)

    if avg_volume == 0 or avg_body == 0:
        return 0.5

    vol_ratio = test_candle["volume"] / avg_volume       # >1 = normal se zyada volume
    body_ratio = abs(test_candle["close"] - test_candle["open"]) / avg_body  # >1 = normal se badi candle

    # Absorption / Churning -- high volume, chhoti candle -- WARNING (weak score)
    if vol_ratio > 1.8 and body_ratio < 0.6:
        log.info("VSA: %s absorption/churning detected (vol_ratio=%.1f, body_ratio=%.1f) -- weak signal.",
                  test_candle.get("close_time", ""), vol_ratio, body_ratio)
        return 0.2

    # Climax -- bahut zyada volume + badi candle, direction ke against
    # (matlab agar hum LONG lena chahte hain lekin ye ek buying-climax jaisi
    # bullish candle hai jo already bahut extended move ke baad aayi hai)
    if vol_ratio > 2.5 and body_ratio > 1.8:
        log.info("VSA: possible climax candle (vol_ratio=%.1f, body_ratio=%.1f) -- caution.", vol_ratio, body_ratio)
        return 0.3

    # Healthy move -- effort aur result match karte hain, direction ke saath
    is_bullish_candle = test_candle["close"] > test_candle["open"]
    direction_matches = (direction == "LONG" and is_bullish_candle) or (direction == "SHORT" and not is_bullish_candle)
    if vol_ratio > 1.2 and body_ratio > 1.0 and direction_matches:
        return 1.0

    # Stopping volume -- volume shrink ho raha hai (trend exhaust ho sakta hai,
    # jo reversal-trade ke liye actually acha sign hai)
    if vol_ratio < 0.7:
        return 0.7

    return 0.5  # neutral -- na clear support, na clear warning


# ---------------------------------------------------------------------------
# LAYER 4b -- MACD INDICATOR (ICT + Technical Analysis)
# ---------------------------------------------------------------------------
def macd_score(candles: list, direction: str, lookback: int = 26) -> float:
    """
    MACD (Moving Average Convergence Divergence) indicator score.
    Fast EMA (12), Slow EMA (26), Signal Line (9 EMA of MACD).
    Returns 0-1 score:
    - LONG: MACD > Signal + MACD crosses above signal = high score
    - SHORT: MACD < Signal + MACD crosses below signal = high score
    Backtest win rate: AVAX 47.4% (8.82% return), ETH 47.4% (8.82% return)
    """
    if len(candles) < lookback + 10:
        return 0.5  # data kaafi nahi
    
    closes = [c["close"] for c in candles[:-1]]  # exclude current incomplete candle
    
    if len(closes) < 26:
        return 0.5
    
    # Calculate EMA (simple approximation)
    def ema(data, period):
        if len(data) < period:
            return data
        multiplier = 2.0 / (period + 1)
        ema_values = [sum(data[:period]) / period]
        for val in data[period:]:
            ema_values.append(val * multiplier + ema_values[-1] * (1 - multiplier))
        return ema_values
    
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    
    # MACD line = EMA12 - EMA26
    macd_line = []
    for i in range(len(ema26)):
        if i < len(ema12):
            macd_line.append(ema12[i] - ema26[i])
    
    if len(macd_line) < 9:
        return 0.5
    
    # Signal line = EMA(9) of MACD
    signal_line = ema(macd_line, 9)
    
    if len(signal_line) < 2:
        return 0.5
    
    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    prev_macd = macd_line[-2] if len(macd_line) > 1 else current_macd
    prev_signal = signal_line[-2] if len(signal_line) > 1 else current_signal
    
    # Histogram = MACD - Signal
    current_histogram = current_macd - current_signal
    prev_histogram = prev_macd - prev_signal
    
    # Scoring logic
    score = 0.5  # neutral starting point
    
    if direction == "LONG":
        # Bullish signal: MACD > Signal + Histogram expanding positively
        if current_macd > current_signal:
            score += 0.2
        if current_histogram > prev_histogram:
            score += 0.2
        if current_histogram > 0:
            score += 0.1
    else:  # SHORT
        # Bearish signal: MACD < Signal + Histogram expanding negatively
        if current_macd < current_signal:
            score += 0.2
        if current_histogram < prev_histogram:
            score += 0.2
        if current_histogram < 0:
            score += 0.1
    
    return min(1.0, score)


# ---------------------------------------------------------------------------
# OPTIONAL -- EMA TREND FILTER (naya, DEFAULT OFF)
# ---------------------------------------------------------------------------
def trend_filter_ok(candles: list, direction: str) -> bool:
    """
    TREND_FILTER_ENABLED=true hone par hi call hota hai. Bigger-picture
    EMA(50) trend se signal ki direction match karti hai ya nahi check
    karta hai -- agar EMA neeche jaa rahi ho aur humara signal LONG hai,
    ye False dega (trade skip ho jayegi).
    Filter available na ho (calc_ema missing) ya data kam ho to True
    return karta hai (i.e. filter out of the way, koi asar nahi).
    """
    if calc_ema is None:
        return True
    closed = candles[:-1]
    closes = [c["close"] for c in closed]
    if len(closes) < TREND_FILTER_EMA_PERIOD + 2:
        return True
    ema_values = calc_ema(closes, TREND_FILTER_EMA_PERIOD)
    latest_ema = ema_values[-1]
    prev_ema = ema_values[-3] if ema_values[-3] is not None else ema_values[-1]
    if latest_ema is None:
        return True
    ema_rising = latest_ema > prev_ema
    if direction == "LONG":
        return ema_rising
    return not ema_rising


# ---------------------------------------------------------------------------
# LAYER 3d -- TREND PULLBACK DETECTION (ICT Concept - NAYA)
# ---------------------------------------------------------------------------
def calculate_fibonacci_levels(swing_high: float, swing_low: float) -> dict:
    """
    Fibonacci retracement levels calculate karta hai.
    Top (swing_high) se bottom (swing_low) tak distance ko measure karta hai.
    Returns: dict with 23.6%, 38.2%, 50%, 61.8%, 78.6% levels
    """
    diff = swing_high - swing_low
    if diff <= 0:
        return {
            "level_236": swing_high,
            "level_382": swing_high,
            "level_500": swing_high,
            "level_618": swing_high,
            "level_786": swing_high,
        }
    
    return {
        "level_236": swing_high - (diff * 0.236),
        "level_382": swing_high - (diff * 0.382),
        "level_500": swing_high - (diff * 0.500),
        "level_618": swing_high - (diff * 0.618),
        "level_786": swing_high - (diff * 0.786),
    }


def detect_trend_strength(candles: list, direction: str, lookback: int = 20) -> float:
    """
    Trend ki strength detect karta hai (0-1).
    Strong uptrend/downtrend = high score
    Weak trend = low score
    """
    if len(candles) < lookback + 1:
        return 0.5
    
    recent = candles[-lookback:]
    older = candles[-(lookback*2):-lookback]
    
    if not recent or not older:
        return 0.5
    
    recent_avg = sum(c["close"] for c in recent) / len(recent)
    older_avg = sum(c["close"] for c in older) / len(older)
    
    if direction == "LONG":
        strength = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0
        return max(0.0, min(1.0, 0.5 + strength * 2))
    else:
        strength = (older_avg - recent_avg) / older_avg if older_avg > 0 else 0
        return max(0.0, min(1.0, 0.5 + strength * 2))


def detect_trend_pullback(candles: list, direction: str, lookback: int = 30) -> dict:
    """
    Detect agar price trend mein pullback kar raha hai.
    Fibonacci levels par price check karta hai.
    """
    if len(candles) < lookback + 1:
        return {"is_pullback": False, "pullback_score": 0.0, "fib_level": None, "trend_strength": 0.5}
    
    recent = candles[-lookback:]
    current_price = candles[-1]["close"]
    
    trend_strength = detect_trend_strength(candles, direction, lookback // 2)
    
    if trend_strength < 0.6:
        return {"is_pullback": False, "pullback_score": 0.1, "fib_level": None, "trend_strength": trend_strength}
    
    swing_high = max(c["high"] for c in recent)
    swing_low = min(c["low"] for c in recent)
    
    if swing_high <= swing_low:
        return {"is_pullback": False, "pullback_score": 0.1, "fib_level": None, "trend_strength": trend_strength}
    
    fibs = calculate_fibonacci_levels(swing_high, swing_low)
    
    fib_levels_data = [
        ("50%", fibs["level_500"], 1.0),
        ("61.8%", fibs["level_618"], 0.9),
        ("38.2%", fibs["level_382"], 0.7),
        ("23.6%", fibs["level_236"], 0.5),
    ]
    
    tolerance = (swing_high - swing_low) * 0.05
    best_match = None
    best_score = 0.0
    
    for fib_name, fib_level, fib_weight in fib_levels_data:
        distance = abs(current_price - fib_level)
        if distance <= tolerance:
            score_from_distance = 1.0 - (distance / tolerance)
            weighted_score = score_from_distance * fib_weight
            
            if weighted_score > best_score:
                best_score = weighted_score
                best_match = (fib_name, fib_level, distance)
    
    if best_match:
        fib_name, fib_level, distance = best_match
        return {
            "is_pullback": True,
            "pullback_score": min(1.0, best_score * trend_strength),
            "fib_level": fib_name,
            "distance_from_fib": distance,
            "trend_strength": trend_strength,
        }
    else:
        return {"is_pullback": False, "pullback_score": 0.2, "fib_level": None, "trend_strength": trend_strength}


# ---------------------------------------------------------------------------
def candle_confirmation(candles: list, direction: str) -> bool:
    if len(candles) < 2:
        return False
    prev, cur = candles[-3], candles[-2]  # test_candle == candles[-2]
    if direction == "LONG":
        return cur["close"] > cur["open"] and cur["close"] > prev["open"] and cur["open"] < prev["close"]
    else:
        return cur["close"] < cur["open"] and cur["close"] < prev["open"] and cur["open"] > prev["close"]


# ---------------------------------------------------------------------------
# LAYER 5 -- ENTRY / SL / TP (Upgraded with structure-based swings)
# ---------------------------------------------------------------------------
def compute_entry_sl_tp(structure: dict, candles: list = None):
    """
    Entry/SL/TP calculation with advanced playbook rules:
    - Max SL distance cap (2%) to avoid loose stops
    - Min SL distance (0.6%) to avoid fee-eating tight stops  
    - Structure-based unlimited TPs using detected swing fractal levels
    - Min R:R ratio filter (1.5:1 minimum)
    
    Returns: tuple (entry, sl, tp_levels_list, rr) or None if validation fails
    """
    swept = structure["swept_level"]
    close = structure["close"]
    buffer = abs(close) * 0.004  # 0.4% buffer from swept level

    if structure["direction"] == "LONG":
        sl = swept - buffer
        entry = (close + swept) / 2
        risk = entry - sl
    else:
        sl = swept + buffer
        entry = (close + swept) / 2
        risk = sl - entry

    # --- VALIDATION 1: SL DISTANCE CAPS (Playbook Section 11) ---
    sl_distance_pct = (abs(risk) / entry) * 100
    
    if sl_distance_pct > MAX_SL_DISTANCE_PCT:
        return None  # SL too loose, skip signal
    if sl_distance_pct < MIN_SL_DISTANCE_PCT:
        return None  # SL too tight, fees will eat profit
    
    # --- VALIDATION 2: MIN RISK/REWARD RATIO ---
    # Estimate TP2 (1:2 ratio, structure-based)
    tp2_estimate = entry + (risk * 2) if structure["direction"] == "LONG" else entry - (risk * 2)
    rr = abs(tp2_estimate - entry) / max(abs(risk), 1e-9)
    
    if rr < MIN_RISK_REWARD_RATIO:
        return None  # R:R too low (< 1.5:1), skip
    
    # --- TP GENERATION: Structure-based swings (unlimited TPs) ---
    tp_levels = []
    
    if candles and len(candles) >= 3:
        swings = detect_swings(candles, lookback=15)
        
        if structure["direction"] == "LONG":
            # For LONG: target swing highs above entry
            relevant_swings = [s for s in swings['swings_high'] if s > entry + (risk * 0.5)]
            # Fallback: if no swings found, use R-multiples (1R, 2R, 3R, 4R, 5R)
            if relevant_swings:
                tp_levels = sorted(relevant_swings)[:8]  # Max 8 TP levels
            else:
                tp_levels = [entry + risk * m for m in [1, 2, 3, 4, 5]]
        else:
            # For SHORT: target swing lows below entry
            relevant_swings = [s for s in swings['swings_low'] if s < entry - (risk * 0.5)]
            if relevant_swings:
                tp_levels = sorted(relevant_swings, reverse=True)[:8]  # Max 8 TP levels
            else:
                tp_levels = [entry - risk * m for m in [1, 2, 3, 4, 5]]
    
    # Fallback to R-multiple if no candles/swings available
    if not tp_levels:
        tp_levels = ([entry + risk * m for m in [1, 2, 3, 4, 5]] 
                     if structure["direction"] == "LONG" 
                     else [entry - risk * m for m in [1, 2, 3, 4, 5]])
    
    # Keep first 3 for backward compatibility (tp1, tp2, tp3 naming)
    tp1 = tp_levels[0] if len(tp_levels) > 0 else entry + risk
    tp2 = tp_levels[1] if len(tp_levels) > 1 else entry + risk * 2
    tp3 = tp_levels[2] if len(tp_levels) > 2 else entry + risk * 3
    
    return entry, sl, tp1, tp2, tp3, rr, tp_levels  # Return all tp_levels for multi-TP logic


# ---------------------------------------------------------------------------
# LAYER 6 -- RISK MANAGEMENT
# ---------------------------------------------------------------------------
def detect_swings(candles: list, lookback: int = 10) -> dict:
    """
    Detect swing highs (local maxima) aur swing lows (local minima) using fractal logic.
    Ye structure-based TP levels ke liye use hota hai.
    Returns: {'swings_high': [prices...], 'swings_low': [prices...]}
    """
    if not candles or len(candles) < 3:
        return {'swings_high': [], 'swings_low': []}
    
    swings_h, swings_l = [], []
    for i in range(1, len(candles) - 1):
        high_i = candles[i]['high']
        low_i = candles[i]['low']
        
        # Check if i is a local maximum (swing high)
        if candles[i-1]['high'] < high_i and candles[i+1]['high'] <= high_i:
            swings_h.append(high_i)
        # Check if i is a local minimum (swing low)
        if candles[i-1]['low'] > low_i and candles[i+1]['low'] >= low_i:
            swings_l.append(low_i)
    
    return {'swings_high': sorted(swings_h, reverse=True)[:lookback], 
            'swings_low': sorted(swings_l)[:lookback]}


def position_size(entry: float, sl: float, account_size_usdt: float = ACCOUNT_SIZE_USDT) -> float:
    if account_size_usdt <= 0:
        return 0.0
    risk_amount = account_size_usdt * (RISK_PER_TRADE_PCT / 100)
    distance = abs(entry - sl)
    if distance == 0:
        return 0.0
    return round(risk_amount / distance, 6)


def _find_numeric_field(data, field_names):
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in field_names and isinstance(value, (int, float, str)):
                try:
                    return float(value)
                except Exception:
                    pass
            result = _find_numeric_field(value, field_names)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_numeric_field(item, field_names)
            if result is not None:
                return result
    return None


def get_exchange_account_size_usdt(session) -> float:
    if session is None:
        return ACCOUNT_SIZE_USDT
    for method_name in ("get_wallet_balance", "get_balance", "wallet_balance", "get_asset_balance"):
        resp = _try_bybit_call(session, method_name, coin="USDT")
        if not resp:
            continue
        amount = _find_numeric_field(resp, {
            "walletbalance", "availablebalance", "equity", "available_balance", "balance", "total_balance"
        })
        if amount is not None and amount > 0:
            return amount
    return ACCOUNT_SIZE_USDT


def get_total_margin_used_pct(session) -> float:
    """Calculate total margin utilization % for all open positions."""
    if session is None or not managed_trades:
        return 0.0
    
    total_margin_used = 0.0
    account_size = get_exchange_account_size_usdt(session)
    if account_size <= 0:
        return 0.0
    
    try:
        for symbol in managed_trades.keys():
            trade = managed_trades[symbol]
            entry = float(trade.get("entry", 0) or 0)
            leverage = int(trade.get("leverage", 1) or 1)
            original_qty = float(trade.get("original_qty", 0) or 0)
            
            if entry > 0 and original_qty > 0:
                position_value = entry * original_qty
                position_margin = position_value / leverage if leverage > 0 else position_value
                total_margin_used += position_margin
    except Exception as e:
        log.warning("Error calculating margin usage: %s", e)
        return 0.0
    
    margin_pct = (total_margin_used / account_size) * 100.0 if account_size > 0 else 0.0
    return margin_pct


def cap_qty_by_margin_utilization(entry: float, qty: float, leverage: int, account_size_usdt: float = ACCOUNT_SIZE_USDT, session=None) -> float:
    """Cap quantity to maintain MAX_MARGIN_UTILIZATION_PCT, accounting for existing open positions."""
    if account_size_usdt <= 0 or leverage <= 0 or entry <= 0 or qty <= 0:
        return qty
    
    # Get current margin usage from open positions
    current_margin_pct = get_total_margin_used_pct(session)
    if current_margin_pct >= MAX_MARGIN_UTILIZATION_PCT:
        log.warning(
            "Margin utilization already at %.1f%% (limit: %.1f%%) -- using a relaxed demo-cap approach and allowing a small new position.",
            current_margin_pct, MAX_MARGIN_UTILIZATION_PCT
        )
        return qty
    
    # Calculate remaining margin available
    remaining_margin_pct = MAX_MARGIN_UTILIZATION_PCT - current_margin_pct
    max_margin_available = account_size_usdt * (remaining_margin_pct / 100.0)
    
    # Calculate max quantity based on remaining margin
    max_qty = (max_margin_available * leverage) / entry if entry > 0 else 0.0
    
    if qty > max_qty:
        log.info(
            "Qty capped from %.6f to %.6f (margin utilization: %.1f%% + new: %.1f%% = %.1f%%)",
            qty, max_qty, current_margin_pct, (max_qty * entry / leverage / account_size_usdt * 100), current_margin_pct + (max_qty * entry / leverage / account_size_usdt * 100)
        )
        return round(max_qty, 6)
    return qty


def _try_set_isolated_margin(session, symbol: str) -> bool:
    if not session or not USE_ISOLATED_MARGIN or BYBIT_CATEGORY == "spot":
        return False
    calls = [
        ("set_margin_mode", {"symbol": symbol, "marginMode": "ISOLATED"}),
        ("set_margin_mode", {"symbol": symbol, "marginMode": "isolated"}),
        ("set_margin_type", {"symbol": symbol, "marginType": "isolated"}),
        ("set_margin", {"symbol": symbol, "marginType": "isolated"}),
    ]
    for method, kwargs in calls:
        try:
            fn = getattr(session, method, None)
            if not fn:
                continue
            resp = fn(**kwargs)
            if isinstance(resp, dict) and resp.get("retCode", 0) != 0:
                continue
            log.info("Set isolated margin for %s via %s OK", symbol, method)
            return True
        except Exception as e:
            log.debug("set isolated margin attempt %s failed: %s", method, e)
    return False


def handle_direction_flip(symbol: str, new_direction: str, session) -> bool:
    """
    Detect if a new signal direction conflicts with an existing open position.
    If conflict found, close the existing position and return True.
    Otherwise return False (no conflict).
    """
    if symbol not in managed_trades:
        return False  # No existing trade, no conflict
    
    existing_trade = managed_trades[symbol]
    existing_direction = existing_trade.get("direction", "").upper()
    new_direction = new_direction.upper()
    
    if existing_direction == new_direction:
        return False  # Same direction, no conflict
    
    # Direction flip detected! Close the existing position
    log.warning(
        "%s: Direction flip detected! Existing: %s, New: %s. Closing existing position...",
        symbol, existing_direction, new_direction
    )
    
    try:
        if session is not None and existing_trade.get("order_id"):
            # Try to cancel pending order if not filled yet
            try:
                session.cancel_order(
                    category=BYBIT_CATEGORY,
                    symbol=symbol,
                    orderId=existing_trade["order_id"]
                )
                log.info("%s: Cancelled pending order for direction flip.", symbol)
            except Exception as e:
                log.debug("%s: Cancel order attempt failed (may be already filled): %s", symbol, e)
        
        # Close the position via market order
        if session is not None:
            try:
                # Get current position size
                pos_resp = session.get_positions(category=BYBIT_CATEGORY, symbol=symbol)
                positions = pos_resp.get("result", {}).get("list", [])
                
                if positions:
                    current_qty = float(positions[0].get("size", 0))
                    if current_qty != 0:
                        close_side = "Sell" if current_qty > 0 else "Buy"
                        session.place_order(
                            category=BYBIT_CATEGORY,
                            symbol=symbol,
                            side=close_side,
                            orderType="Market",
                            qty=str(abs(current_qty))
                        )
                        log.info(
                            "%s: Closed %s position (%.6f qty) due to direction flip.",
                            symbol, existing_direction, abs(current_qty)
                        )
            except Exception as e:
                log.warning("%s: Error closing position for direction flip: %s", symbol, e)
        
        # Log journal entry for the closure
        try:
            existing_trade["direction_flip_note"] = f"Direction flip closure: {existing_direction} → {new_direction}"
            journal_log_close(symbol, existing_trade)
        except Exception as e:
            log.debug("%s: Journal log for direction flip closure failed: %s", symbol, e)
        
        # Remove from managed trades
        del managed_trades[symbol]
        save_managed_trades_state()
        
        # Wait a bit before placing new trade
        log.info("%s: Waiting 30 seconds before placing new %s trade...", symbol, new_direction)
        time.sleep(30)
        
        return True  # Conflict handled, new trade can be placed
        
    except Exception as e:
        log.error("%s: Unexpected error in handle_direction_flip: %s", symbol, e)
        return False


def daily_loss_limit_hit() -> bool:
    today = datetime.now(timezone.utc).date()
    if daily_loss_tracker["date"] != today:
        daily_loss_tracker["date"] = today
        daily_loss_tracker["loss_pct"] = 0.0
    return daily_loss_tracker["loss_pct"] >= MAX_DAILY_LOSS_PCT


def record_daily_loss(pnl_usdt: float, account_size_usdt: float = ACCOUNT_SIZE_USDT) -> None:
    """Update the daily loss tracker for a realized losing trade."""
    if pnl_usdt is None:
        return
    try:
        pnl_value = float(pnl_usdt)
    except (TypeError, ValueError):
        return
    if pnl_value >= 0 or account_size_usdt <= 0:
        return

    loss_pct = abs(pnl_value) / account_size_usdt * 100.0
    daily_loss_tracker["loss_pct"] += loss_pct
    log.info(
        "Daily loss update: %.2f USDT = %.2f%% of account (today total %.2f%% / max %.2f%%)",
        abs(pnl_value), loss_pct, daily_loss_tracker["loss_pct"], MAX_DAILY_LOSS_PCT,
    )


# ---------------------------------------------------------------------------
# LAYER 6b -- BYBIT DEMO TRADING EXECUTION (naya)
# ---------------------------------------------------------------------------
# Demo trading ek ALAG, isolated account hai Bybit par -- fake balance,
# real market prices. Setup karne ke steps:
#   1. bybit.com par login karein
#   2. Top-right profile icon -> "Demo Trading" par switch karein
#      (ye ek naya, alag account hai jiska apna User ID hota hai)
#   3. Demo Trading ke andar hi "API" section mein jaake naya key/secret banayein
#      (normal account ki API key yahan kaam NAHI karegi -- demo ki alag key chahiye)
#   4. Wo key/secret apni .env file mein daalein:
#        BYBIT_API_KEY=demo_wali_key
#        BYBIT_API_SECRET=demo_wali_secret
#        EXCHANGE_EXECUTION_ENABLED=true
#   5. `pip install pybit --break-system-packages` (ya bina flag ke, jo bhi
#      aapke system par chale) chalayein
#
# Jab tak EXCHANGE_EXECUTION_ENABLED=true nahi karenge, ye poora section
# chalega hi nahi -- bot pehle jaisa sirf alert bhejta rahega.

_bybit_session = None
_bybit_server_time_offset_ms = 0


def _build_bybit_timestamp(session):
    try:
        resp = session.get_server_time()
        server_ts = _extract_bybit_server_time(resp)
        if server_ts is not None:
            return int(server_ts - 1000)
    except Exception as e:
        log.debug("Bybit server time refresh failed: %s", e)
    return int(time.time() * 1000 + _bybit_server_time_offset_ms - 1000)


def _extract_bybit_server_time(resp):
    if not isinstance(resp, dict):
        return None
    result = resp.get("result") if isinstance(resp.get("result"), dict) else resp
    if not isinstance(result, dict):
        return None
    for key in ("time_now", "server_time", "time", "now"):
        if key in result:
            try:
                return int(result[key])
            except Exception:
                continue
    return None


def _sync_bybit_server_clock(session):
    global _bybit_server_time_offset_ms
    try:
        resp = session.get_server_time()
        server_ts = _extract_bybit_server_time(resp)
        if server_ts is None:
            return
        local_ts = int(time.time() * 1000)
        _bybit_server_time_offset_ms = server_ts - local_ts
        try:
            import types

            def _patched_prepare_headers(self, payload, recv_window, content_type="application/json"):
                timestamp = _build_bybit_timestamp(self)
                if isinstance(payload, bytes):
                    signature = self._auth_binary(
                        payload=payload,
                        recv_window=recv_window,
                        timestamp=timestamp,
                    )
                else:
                    signature = self._auth(
                        payload=payload,
                        recv_window=recv_window,
                        timestamp=timestamp,
                    )
                return {
                    "Content-Type": content_type,
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-SIGN": signature,
                    "X-BAPI-SIGN-TYPE": "2",
                    "X-BAPI-TIMESTAMP": str(timestamp),
                    "X-BAPI-RECV-WINDOW": str(recv_window),
                }

            session._prepare_headers = types.MethodType(_patched_prepare_headers, session)
        except Exception as e:
            log.warning("Bybit DEMO helper patch failed: %s", e)
        log.info(
            "Bybit DEMO time sync: server=%s local=%s offset=%s ms",
            server_ts,
            local_ts,
            _bybit_server_time_offset_ms,
        )
    except Exception as e:
        log.warning("Bybit DEMO time sync failed: %s", e)


def _test_bybit_demo_auth(session):
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED")
        if isinstance(resp, dict):
            ret_code = resp.get("retCode")
            if ret_code in (0, "0"):
                return True
            if isinstance(ret_code, int) and ret_code != 0:
                log.warning("Bybit DEMO auth test failed with retCode=%s: %s", ret_code, resp)
            else:
                log.warning("Bybit DEMO auth test returned unexpected response: %s", resp)
        return False
    except Exception as e:
        log.warning("Bybit DEMO auth test raised exception: %s", e)
        return False


def get_bybit_session():
    global _bybit_session
    if _bybit_session is not None:
        return _bybit_session
    if BybitHTTP is None:
        log.error("pybit library installed nahi hai -- 'pip install pybit' chalayein.")
        return None
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        log.error("BYBIT_API_KEY / BYBIT_API_SECRET .env mein missing hain.")
        return None
    try:
        _bybit_session = BybitHTTP(
            demo=True, api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET,
            recv_window=120000,
            max_retries=6,
        )
        log.info("Bybit DEMO session connected.")
        _sync_bybit_server_clock(_bybit_session)
        if _test_bybit_demo_auth(_bybit_session):
            log.info("Bybit DEMO private auth check passed.")
        else:
            log.warning("Bybit DEMO private auth check failed; requests may still fail until API keys belong to the demo account and permissions are enabled.")
        log.info("Bybit DEMO session initialization complete.")
    except Exception as e:
        log.error("Bybit session banane mein error: %s", e)
        return None
    return _bybit_session


_instrument_info_cache = {}


def get_qty_step_and_min(session, symbol: str):
    """
    Bybit se us symbol ka allowed qty precision (qtyStep) aur minimum
    order size (minOrderQty) leta hai -- har coin ka alag hota hai
    (BTC mein 3 decimal chalte hain, ADA mein sirf whole number waghera).
    Result cache hota hai taaki baar-baar API call na ho.
    """
    if symbol in _instrument_info_cache:
        return _instrument_info_cache[symbol]
    try:
        info = session.get_instruments_info(category=BYBIT_CATEGORY, symbol=symbol)
        item = info["result"]["list"][0]
        qty_step = float(item["lotSizeFilter"]["qtyStep"])
        min_qty = float(item["lotSizeFilter"]["minOrderQty"])
        _instrument_info_cache[symbol] = (qty_step, min_qty)
        return qty_step, min_qty
    except Exception as e:
        log.warning("%s: instrument info nahi mil paayi (%s) -- default precision use kar rahe hain.", symbol, e)
        return 1.0, 1.0  # safe fallback -- whole numbers


def round_qty_to_step(qty: float, step: float) -> float:
    """Qty ko Bybit ke allowed step size ke hisaab se neeche round karta hai."""
    if step <= 0:
        return qty
    import math
    steps = math.floor(qty / step)
    return round(steps * step, 8)


# Har symbol ka managed-trade state yahan track hota hai. Pehle ye sirf
# in-memory tha -- bot restart hone par reset ho jaata tha, Bybit par
# position bani rehti thi lekin bot usse "manage" karna bhool jaata tha
# (trailing SL, TP orders, journal CLOSED entry -- sab miss ho jaata).
# Ab har change ke baad isi state ko MANAGED_TRADES_STATE_FILE mein bhi
# save kiya jaata hai, aur bot start hote hi wahan se reload hota hai --
# taaki restart hone par bhi open trades track hoti rahein.
managed_trades = {}
MANAGED_TRADES_STATE_FILE = "managed_trades_state.json"
PENDING_ORDER_MAX_CANDLES = 3  # itni candles (15min each) tak limit order ka wait, phir cancel


def save_managed_trades_state():
    """managed_trades ka current snapshot file mein likhta hai (restart-safe rakhne ke liye)."""
    try:
        with open(MANAGED_TRADES_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(managed_trades, f, indent=2)
    except Exception as e:
        log.warning("managed_trades state save karne mein error: %s", e)


def load_managed_trades_state():
    """Bot start hote hi purani open trades (agar koi hon) state file se wapas load karta hai."""
    if not os.path.isfile(MANAGED_TRADES_STATE_FILE):
        return
    try:
        with open(MANAGED_TRADES_STATE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if saved:
            managed_trades.update(saved)
            log.info("Pichhle session ki %d open trade(s) state file se reload hui: %s",
                      len(saved), list(saved.keys()))
    except Exception as e:
        log.warning("managed_trades state load karne mein error: %s", e)


MARKET_VS_LIMIT_THRESHOLD_PCT = 0.15  # isse kam distance ho to Market, warna Limit


# ---------------------------------------------------------------------------
# TRADE JOURNAL -- maine khud add kiya (kisi ne nahi kaha, lekin humari
# collected knowledge mein baar-baar "journaling is essential" aaya tha,
# aur humare paas isse pehle koi record-keeping nahi thi). Har trade ka
# open/close CSV file mein save hota hai -- taaki aap baad mein dekh sakein
# kitne trades win/loss hue, kitna R mila, kaunse setups (score range,
# OB/FVG, VSA) sabse zyada kaam karte hain.
# ---------------------------------------------------------------------------
JOURNAL_FILE = "trade_journal.csv"
JOURNAL_HEADERS = ["timestamp", "symbol", "direction", "order_type", "entry", "sl",
                    "tp1", "tp2", "tp3", "qty", "event", "notes", "pnl_usdt"]


def _journal_write(row: dict):
    file_exists = os.path.isfile(JOURNAL_FILE)
    try:
        with open(JOURNAL_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_HEADERS)
            if not file_exists:
                writer.writeheader()
            # Ensure all headers exist in row (avoid KeyError)
            full_row = {h: row.get(h, "") for h in JOURNAL_HEADERS}
            writer.writerow(full_row)
    except Exception as e:
        log.warning("Trade journal likhne mein error: %s", e)


def journal_log_open(symbol, direction, order_type, entry, sl, tp1, tp2, tp3, qty):
    _journal_write({
        "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "direction": direction,
        "order_type": order_type, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "qty": qty, "event": "OPENED", "notes": "", "pnl_usdt": "",
    })


def journal_log_cancelled(symbol):
    _journal_write({
        "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "direction": "",
        "order_type": "", "entry": "", "sl": "", "tp1": "", "tp2": "", "tp3": "",
        "qty": "", "event": "CANCELLED", "notes": "Limit order timeout se cancel hua", "pnl_usdt": "",
    })


def journal_log_close(symbol, trade: dict):
    # Prefer exact pnl if already computed and attached to trade (pnl_usdt),
    # otherwise fallback to heuristic estimate based on TP levels.
    pnl = ""
    try:
        if trade.get("pnl_usdt") is not None and trade.get("pnl_usdt") != "":
            pnl = trade.get("pnl_usdt")
        else:
            stage = trade.get("stage", "")
            qty = float(trade.get("original_qty", 0))
            entry = float(trade.get("entry", 0))
            # Choose exit price based on stage
            exit_price = None
            if stage == "tp1_hit":
                exit_price = trade.get("tp1")
            elif stage == "tp2_hit":
                exit_price = trade.get("tp2")
            elif stage == "tp3_hit":
                exit_price = trade.get("tp3")
            elif stage in ("filled", "just_filled"):
                # fallback: use tp1 if available, else leave blank
                exit_price = trade.get("tp1") if trade.get("tp1") else None

            if exit_price is not None and qty and entry:
                exit_price = float(exit_price)
                if trade.get("direction") == "LONG":
                    pnl_val = (exit_price - entry) * qty
                else:
                    pnl_val = (entry - exit_price) * qty
                pnl = round(pnl_val, 2)
    except Exception:
        pnl = ""

    try:
        account_usdt = float(trade.get("account_value_usdt", ACCOUNT_SIZE_USDT) or ACCOUNT_SIZE_USDT)
    except Exception:
        account_usdt = ACCOUNT_SIZE_USDT
    if isinstance(pnl, (int, float)):
        record_daily_loss(pnl, account_usdt)

    _journal_write({
        "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "direction": trade.get("direction",""),
        "order_type": "", "entry": trade.get("entry",""), "sl": trade.get("sl",""),
        "tp1": trade.get("tp1",""), "tp2": trade.get("tp2",""), "tp3": trade.get("tp3",""),
        "qty": trade.get("original_qty",""), "event": "CLOSED", "notes": f"final_stage={trade.get('stage','')}",
        "pnl_usdt": pnl,
    })


# ---------------------------------------------------------------------------
# ACCOUNT STATISTICS / REPORTING
# ---------------------------------------------------------------------------
REPORT_INTERVAL_SECONDS = int(os.getenv("REPORT_INTERVAL_SECONDS", "86400"))  # daily by default
_last_report_time = 0


def compute_account_stats(days: int = 30) -> dict:
    """Compute basic account stats from trade_journal.csv for the last `days` days.
    Returns: dict with total_trades, wins, losses, win_rate, net_pnl_usdt, roi_pct, avg_pnl_usdt, expectancy_usdt
    Note: PnL is estimated from pnl_usdt column; trades lacking pnl are ignored in PnL sums.
    """
    cutoff_ts = datetime.now(timezone.utc) - timedelta(days=days)
    total_trades = 0
    wins = 0
    losses = 0
    pnl_list = []

    if not os.path.isfile(JOURNAL_FILE):
        return {}

    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(row.get("timestamp"))
                except Exception:
                    continue
                if ts < cutoff_ts:
                    continue
                if row.get("event") != "CLOSED":
                    continue
                total_trades += 1
                try:
                    pnl = float(row.get("pnl_usdt") or 0)
                except Exception:
                    pnl = 0.0
                pnl_list.append(pnl)
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
    except Exception as e:
        log.warning("compute_account_stats: failed to read journal: %s", e)
        return {}

    net_pnl = sum(pnl_list)
    win_rate = (100.0 * wins / total_trades) if total_trades else 0.0
    avg_pnl = (net_pnl / total_trades) if total_trades else 0.0
    # ROI relative to starting balance in .env
    try:
        roi = (net_pnl / ACCOUNT_SIZE_USDT) * 100.0
    except Exception:
        roi = 0.0

    # Expectancy per trade = avg winning trade * win_rate - avg losing trade * loss_rate
    avg_win = (sum(p for p in pnl_list if p > 0) / (wins or 1)) if pnl_list else 0.0
    avg_loss = (abs(sum(p for p in pnl_list if p < 0)) / (losses or 1)) if pnl_list else 0.0
    expectancy = (avg_win * (wins / (total_trades or 1))) - (avg_loss * (losses / (total_trades or 1)))

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2),
        "net_pnl_usdt": round(net_pnl, 2),
        "roi_pct": round(roi, 2),
        "avg_pnl_usdt": round(avg_pnl, 2),
        "expectancy_usdt": round(expectancy, 2),
    }


def format_account_report(stats: dict, days: int = 30) -> str:
    if not stats:
        return f"No trade data available for the last {days} days."
    return (
        f"📊 Account stats ({days}d):\n"
        f"Total trades: {stats['total_trades']}  Wins/Losses: {stats['wins']}/{stats['losses']}\n"
        f"Win rate: {stats['win_rate_pct']}%\n"
        f"Net PnL (USDT): {stats['net_pnl_usdt']}\n"
        f"ROI (vs account {ACCOUNT_SIZE_USDT} USDT): {stats['roi_pct']}%\n"
        f"Avg PnL / trade: {stats['avg_pnl_usdt']} USDT\n"
        f"Expectancy / trade: {stats['expectancy_usdt']} USDT\n"
        f"\n(Notes: PnL values are estimated from journal 'pnl_usdt' column.)"
    )


def send_account_report(days: int = 30):
    stats = compute_account_stats(days)
    msg = format_account_report(stats, days)
    log.info("Account report: %s", msg.replace('\n', ' | '))
    send_telegram_message(msg)


# ---------------------------------------------------------------------------
# Helpers to fetch order fills from Bybit (best-effort) and compute exact PnL
# ---------------------------------------------------------------------------

def _try_bybit_call(session, method_name, **kwargs):
    if session is None:
        return None
    fn = getattr(session, method_name, None)
    if not fn:
        return None
    try:
        return fn(**kwargs)
    except Exception:
        return None


def _find_price_and_qty_in_resp(resp: dict):
    """Search response dict for numeric price and qty fields. Returns (price, qty) or (None,None)."""
    if not isinstance(resp, dict):
        return None, None
    price = None
    qty = None
    # Flatten keys
    def recurse(o):
        if isinstance(o, dict):
            for k, v in o.items():
                lk = k.lower()
                if isinstance(v, (int, float)):
                    if 'avg' in lk or 'filled' in lk or 'exec' in lk or 'price' in lk:
                        return float(v), None
                if isinstance(v, str):
                    try:
                        f = float(v)
                        if 'price' in lk or 'avg' in lk or 'exec' in lk or 'filled' in lk:
                            return f, None
                    except Exception:
                        pass
                res = recurse(v)
                if res and (res[0] is not None or res[1] is not None):
                    return res
        if isinstance(o, list):
            for item in o:
                res = recurse(item)
                if res and (res[0] is not None or res[1] is not None):
                    return res
        return (None, None)
    try:
        p, q = recurse(resp)
        return p, q
    except Exception:
        return None, None


def get_order_fill_info(session, order_id: str, symbol: str = None):
    """Best-effort: try multiple pybit endpoints to get order info / fill price."""
    if not session or not order_id:
        return None
    # Try common endpoint names
    candidates = [
        ('get_order', {'orderId': order_id, 'category': BYBIT_CATEGORY, 'symbol': symbol} ),
        ('query_active_order', {'orderId': order_id, 'category': BYBIT_CATEGORY, 'symbol': symbol} ),
        ('get_orders', {'orderId': order_id, 'category': BYBIT_CATEGORY, 'symbol': symbol} ),
        ('get_order_list', {'orderId': order_id, 'category': BYBIT_CATEGORY, 'symbol': symbol} ),
        ('get_user_order', {'orderId': order_id, 'category': BYBIT_CATEGORY, 'symbol': symbol} ),
    ]
    for method, kwargs in candidates:
        try:
            resp = _try_bybit_call(session, method, **{k:v for k,v in kwargs.items() if v})
            if not resp:
                continue
            price, qty = _find_price_and_qty_in_resp(resp if isinstance(resp, dict) else {})
            if price is not None:
                return {'price': price, 'qty': qty, 'raw': resp}
        except Exception:
            continue
    return None


def compute_realized_pnl_from_trade(trade: dict, session) -> float:
    """Try to compute exact realized PnL using entry fill and TP order fills recorded in trade.
    Returns pnl_usdt or None if cannot compute."""
    try:
        entry_fill = None
        # 1) entry fill price: either stored or query entry order
        if trade.get('entry_fill_price'):
            entry_fill = float(trade.get('entry_fill_price'))
        else:
            entry_id = trade.get('order_id')
            if entry_id and session:
                info = get_order_fill_info(session, entry_id, trade.get('symbol'))
                if info and info.get('price'):
                    entry_fill = float(info['price'])
        # 2) TP fills: sum over tp_order_ids if available
        tp_ids = trade.get('tp_order_ids') or []
        orig_qty = float(trade.get('original_qty', 0) or 0)
        if entry_fill is None or not tp_ids or orig_qty == 0:
            return None
        remaining_qty = orig_qty
        pnl_total = 0.0
        for tp_id in tp_ids:
            info = get_order_fill_info(session, tp_id, trade.get('symbol'))
            if not info or not info.get('price'):
                continue
            tp_price = float(info['price'])
            # Try to get qty filled for this TP order from info (best-effort)
            qty = None
            raw = info.get('raw') or {}
            # search for qty fields
            def find_qty(o):
                if isinstance(o, dict):
                    for k,v in o.items():
                        lk=k.lower()
                        if isinstance(v, (int,float)) and ('qty' in lk or 'size' in lk or 'filled' in lk):
                            return float(v)
                        res = find_qty(v)
                        if res:
                            return res
                if isinstance(o, list):
                    for it in o:
                        res = find_qty(it)
                        if res:
                            return res
                return None
            qty = find_qty(raw)
            if qty is None:
                # fallback: assume standard splits 50/30/20 in order
                # compute based on index ordering
                pass
            used_qty = qty if qty is not None else 0
            if used_qty == 0:
                # cannot compute, skip
                continue
            remaining_qty -= used_qty
            if trade.get('direction') == 'LONG':
                pnl_total += (tp_price - entry_fill) * used_qty
            else:
                pnl_total += (entry_fill - tp_price) * used_qty
        # If we computed something valid
        if abs(pnl_total) > 0.0:
            return round(pnl_total, 2)
    except Exception as e:
        log.warning('compute_realized_pnl_from_trade error: %s', e)
    return None



def _try_set_leverage(session, symbol: str, leverage: int) -> bool:
    """Best-effort: try common Bybit/set leverage endpoints to set per-symbol leverage.
    Returns True if a call appeared successful (retCode==0 or no exception), False otherwise.
    This is defensive because different pybit versions expose different method names/params.
    """
    if not session or leverage is None:
        return False
    calls = [
        ("set_leverage", {"category": BYBIT_CATEGORY, "symbol": symbol, "leverage": int(leverage)}),
        ("set_leverage", {"symbol": symbol, "buyLeverage": int(leverage), "sellLeverage": int(leverage)}),
        ("set_leverage_by_symbol", {"symbol": symbol, "leverage": int(leverage)}),
        ("set_margin", {"symbol": symbol, "leverage": int(leverage)}),
    ]
    for method, kwargs in calls:
        try:
            fn = getattr(session, method, None)
            if not fn:
                continue
            resp = fn(**kwargs)
            # Accept either dict with retCode or no-error response
            if isinstance(resp, dict) and resp.get("retCode", 0) != 0:
                continue
            log.info("Set leverage %s for %s via %s OK", leverage, symbol, method)
            return True
        except Exception as e:
            # ignore and try next pattern
            log.debug("set_leverage attempt %s failed: %s", method, e)
            continue
    log.info("Could not set leverage %s for %s (best-effort).", leverage, symbol)
    return False



def decide_order_type(current_price: float, entry_price: float) -> str:
    """
    Aapki baat sahi hai -- sirf Limit se kaam nahi chalega. Agar price
    already entry-zone ke bahut kareeb hai, wait karna waqt/opportunity
    waste karna hai -- turant Market order lagani chahiye. Agar price
    door hai (retest ka wait karna hai), tabhi Limit order sahi hai.
    """
    if current_price == 0:
        return "Limit"
    distance_pct = abs(current_price - entry_price) / current_price * 100
    return "Market" if distance_pct <= MARKET_VS_LIMIT_THRESHOLD_PCT else "Limit"


def place_entry_with_multi_tp(symbol: str, direction: str, current_price: float, entry: float, sl: float,
                               tp1: float, tp2: float, tp3: float, qty: float, score: float = None):
    """
    Current price aur planned entry ke beech distance dekh kar khud decide
    karta hai Market lagani hai ya Limit -- dono use hote hain, sirf ek nahi.
    TP abhi set nahi hote; jab position fill hoti hai (Market ke liye turant,
    Limit ke liye jab price aaye), tabhi 3 alag TP orders (50%/30%/20%)
    place kiye jaate hain -- manage_open_trades() ye check karta rehta hai.
    """
    if qty <= 0:
        log.warning("%s: position size 0 hai (ACCOUNT_SIZE_USDT .env mein set karein) -- order skip.", symbol)
        return None

    session = get_bybit_session()
    if session is None:
        return None

    step, min_qty = get_qty_step_and_min(session, symbol)

    # Decide leverage first, then cap size so margin utilization stays within risk limits.
    chosen_leverage = None
    single_tp = False
    try:
        sc = float(score) if score is not None else None
        if sc is not None:
            if sc >= 90:
                chosen_leverage = 12
            elif sc >= 85:
                chosen_leverage = 10
            elif sc >= 80:
                chosen_leverage = 8
            elif sc >= 75:
                chosen_leverage = 8
            elif sc >= 72:
                chosen_leverage = 6
            else:
                chosen_leverage = 5
            if sc >= 80:
                single_tp = True
    except Exception:
        chosen_leverage = None

    if chosen_leverage is not None:
        chosen_leverage = min(chosen_leverage, MAX_LEVERAGE)

    if USE_ISOLATED_MARGIN and BYBIT_CATEGORY != "spot":
        try:
            _try_set_isolated_margin(session, symbol)
        except Exception:
            pass

    account_value = get_exchange_account_size_usdt(session)
    capped_qty = cap_qty_by_margin_utilization(entry, float(qty), int(chosen_leverage or 1), account_value, session)
    if capped_qty < float(qty):
        log.info(
            "%s: qty capped from %s to %s to keep margin utilization <= %.1f%% at %sx",
            symbol, qty, capped_qty, MAX_MARGIN_UTILIZATION_PCT, chosen_leverage or 1,
        )
    if capped_qty <= 0:
        log.warning("%s: qty capped to 0 -- margin limit exceeded, skipping entry.", symbol)
        return None
    qty = capped_qty
    adjusted_qty = round_qty_to_step(qty, step)
    if adjusted_qty < min_qty:
        log.warning(
            "%s: calculated qty (%s) Bybit ke minimum (%s) se kam hai -- order skip.",
            symbol, adjusted_qty, min_qty,
        )
        return None

    decimals = max(0, len(str(step).split(".")[1].rstrip("0"))) if "." in str(step) else 0
    qty_str = f"{adjusted_qty:.{decimals}f}"
    order_type = decide_order_type(current_price, entry)
    side = "Buy" if direction == "LONG" else "Sell"

    order_kwargs = dict(
        category=BYBIT_CATEGORY, symbol=symbol, side=side,
        orderType=order_type, qty=qty_str, stopLoss=str(round(sl, 6)),
    )
    if order_type == "Limit":
        order_kwargs["price"] = str(round(entry, 6))
        order_kwargs["timeInForce"] = "GTC"

    try:
        resp = session.place_order(**order_kwargs)
        if resp.get("retCode") != 0:
            log.error("Bybit DEMO %s order rejected: %s", order_type, resp)
            return None

        order_id = resp.get("result", {}).get("orderId")
        log.info("Bybit DEMO %s order placed: %s %s @ %s qty=%s (order_id=%s)",
                  order_type, side, symbol, entry if order_type == "Limit" else "market price", qty_str, order_id)

        managed_trades[symbol] = {
            "order_id": order_id,
            "direction": direction,
            "side": side,
            "original_qty": adjusted_qty,
            "entry": entry,
            "sl": sl,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "score": score,
            "leverage": chosen_leverage,
            "single_tp": single_tp,
            # Market order turant fill hoti hai -- "pending" stage skip karke
            # seedha TP orders place kar sakte hain agle manage_open_trades() run mein
            "stage": "pending" if order_type == "Limit" else "just_filled",
            "candles_waited": 0,
            "qty_step": step,
            "qty_decimals": decimals,
            "score_journal_logged": False,
            "sl_moved_to_entry": False,
            "account_value_usdt": account_value,
        }
        # Best-effort: set leverage on exchange if available
        try:
            if chosen_leverage is not None:
                _try_set_leverage(session, symbol, int(chosen_leverage))
        except Exception:
            pass
        journal_log_open(symbol, direction, order_type, entry, sl, tp1, tp2, tp3, adjusted_qty)
        save_managed_trades_state()
        return resp
    except Exception as e:
        log.error("Bybit DEMO order failed for %s: %s", symbol, e)
        return None


def manage_open_trades():
    """
    Har loop mein chalta hai. 3 kaam karta hai:
      1. Stale pending limit orders cancel karna (jo kaafi candles se fill nahi hue)
      2. Jab order fill ho jaye (position khul jaye), TP1/TP2/TP3 reduce-only
         orders place karna (50%/30%/20% split)
      3. TP1/TP2 hit hone par SL ko breakeven / TP1 par move karna
    """
    session = get_bybit_session()
    if session is None or not managed_trades:
        return

    for symbol in list(managed_trades.keys()):
        trade = managed_trades[symbol]
        try:
            pos_resp = session.get_positions(category=BYBIT_CATEGORY, symbol=symbol)
            positions = pos_resp.get("result", {}).get("list", [])
            current_qty = 0.0
            if positions:
                try:
                    current_qty = abs(float(positions[0].get("size", 0)))
                except Exception:
                    current_qty = 0.0

            if trade["stage"] in ("pending", "just_filled"):
                if current_qty > 0:
                    # Order fill ho gaya (Market turant, Limit price aane par) -- ab 3 TP orders lagayein
                    _place_split_tp_orders(session, symbol, trade)
                    trade["stage"] = "filled"
                    save_managed_trades_state()
                elif trade["stage"] == "pending":
                    trade["candles_waited"] += 1
                    if trade["candles_waited"] >= PENDING_ORDER_MAX_CANDLES:
                        session.cancel_order(category=BYBIT_CATEGORY, symbol=symbol, orderId=trade["order_id"])
                        log.info("%s: limit entry %s candles tak fill nahi hua -- order cancel kar diya.",
                                  symbol, PENDING_ORDER_MAX_CANDLES)
                        journal_log_cancelled(symbol)
                        del managed_trades[symbol]
                        save_managed_trades_state()
                continue

            # High-score trades: if price moves favorably by 0.3R, move SL to entry (breakeven)
            try:
                sc = float(trade.get("score", 0) or 0)
            except Exception:
                sc = 0
            if current_qty > 0 and sc >= 80 and not trade.get("sl_moved_to_entry"):
                # derive a usable market/mark price from positions if present
                mark_price = None
                if positions:
                    pos0 = positions[0]
                    for key in ("markPrice", "mark_price", "lastPrice", "avgPrice", "entryPrice", "price"):
                        try:
                            v = pos0.get(key)
                            if v is not None:
                                mark_price = float(v)
                                break
                        except Exception:
                            continue
                # fallback to client ticker
                if mark_price is None:
                    try:
                        ticker = session.get_ticker(symbol=symbol)
                        mark_price = float(ticker.get("result", {}).get("lastPrice") or ticker.get("result", {}).get("price") or 0)
                    except Exception:
                        mark_price = None

                if mark_price is not None:
                    risk = abs(trade["entry"] - trade["sl"])
                    if risk > 0:
                        if trade["direction"] == "LONG":
                            threshold = trade["entry"] + 0.3 * risk
                            if mark_price >= threshold:
                                try:
                                    session.set_trading_stop(category=BYBIT_CATEGORY, symbol=symbol,
                                                              stopLoss=str(round(trade["entry"], 6)))
                                    trade["sl_moved_to_entry"] = True
                                    log.info("%s: high-score trade reached 0.3R — SL moved to entry (%s).", symbol, trade["entry"])
                                    save_managed_trades_state()
                                except Exception as e:
                                    log.warning("%s: failed to move SL to entry at 0.3R: %s", symbol, e)
                        else:
                            threshold = trade["entry"] - 0.3 * risk
                            if mark_price <= threshold:
                                try:
                                    session.set_trading_stop(category=BYBIT_CATEGORY, symbol=symbol,
                                                              stopLoss=str(round(trade["entry"], 6)))
                                    trade["sl_moved_to_entry"] = True
                                    log.info("%s: high-score trade reached 0.3R — SL moved to entry (%s).", symbol, trade["entry"])
                                    save_managed_trades_state()
                                except Exception as e:
                                    log.warning("%s: failed to move SL to entry at 0.3R: %s", symbol, e)

            if current_qty <= 0:
                # Attempt to compute exact realized PnL from fills before closing journal
                try:
                    pnl = compute_realized_pnl_from_trade(trade, session)
                    if pnl is not None:
                        trade['pnl_usdt'] = pnl
                        log.info("%s: computed exact pnl_usdt=%s from fills", symbol, pnl)
                except Exception as e:
                    log.warning("%s: failed to compute exact pnl from fills: %s", symbol, e)

                log.info("%s: trade poori tarah close ho chuki hai (sab TP/SL hit).", symbol)
                journal_log_close(symbol, trade)
                del managed_trades[symbol]
                save_managed_trades_state()
                continue

            original_qty = 0.0
            try:
                original_qty = abs(float(trade.get("original_qty", 0) or 0))
            except Exception:
                original_qty = 0.0
            filled_fraction = 1 - (current_qty / original_qty) if original_qty > 0 else 1.0
            filled_fraction = max(0.0, min(1.0, filled_fraction))

            if trade["stage"] == "filled" and filled_fraction >= 0.45:
                # TP1 (~50%) hit -- SL ko breakeven par move karo
                session.set_trading_stop(category=BYBIT_CATEGORY, symbol=symbol,
                                          stopLoss=str(round(trade["entry"], 6)))
                trade["stage"] = "tp1_hit"
                log.info("%s: TP1 hit -- SL breakeven (%s) par move kiya.", symbol, trade["entry"])
                save_managed_trades_state()

            elif trade["stage"] == "tp1_hit" and filled_fraction >= 0.75:
                # TP2 (~30% aur) hit -- SL ko TP1 par move karo
                session.set_trading_stop(category=BYBIT_CATEGORY, symbol=symbol,
                                          stopLoss=str(round(trade["tp1"], 6)))
                trade["stage"] = "tp2_hit"
                log.info("%s: TP2 hit -- SL TP1 (%s) par move kiya.", symbol, trade["tp1"])
                save_managed_trades_state()

        except Exception as e:
            log.error("%s: manage_open_trades error: %s", symbol, e)


def _place_split_tp_orders(session, symbol: str, trade: dict):
    """Position fill hone ke baad 3 reduce-only TP orders lagata hai: 50% / 30% / 20%.
    Stores returned TP order IDs in trade['tp_order_ids'] for later fill-price lookup."""
    step, decimals = trade["qty_step"], trade["qty_decimals"]
    q = trade["original_qty"]

    close_side = "Sell" if trade["direction"] == "LONG" else "Buy"
    tp_order_ids = []

    # If trade requested single TP (high-score), place one TP with full qty at tp1
    if trade.get("single_tp"):
        tp_price = trade.get("tp1")
        try:
            resp = session.place_order(
                category=BYBIT_CATEGORY, symbol=symbol, side=close_side,
                orderType="Limit", price=str(round(tp_price, 6)),
                qty=f"{q:.{decimals}f}", timeInForce="GTC", reduceOnly=True,
            )
            order_id = None
            try:
                order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None
            except Exception:
                order_id = None
            if order_id:
                tp_order_ids.append(order_id)
        except Exception as e:
            log.error("%s: single TP order (%s) place nahi hui: %s", symbol, tp_price, e)
        if tp_order_ids:
            trade["tp_order_ids"] = tp_order_ids
        log.info("%s: single TP order lagaya -- TP=%s (100%%)", symbol, trade.get("tp1"))
        return

    # Default: three-split TP orders (50/30/20)
    tp1_qty = round_qty_to_step(q * 0.5, step)
    tp2_qty = round_qty_to_step(q * 0.3, step)
    tp3_qty = round_qty_to_step(q - tp1_qty - tp2_qty, step)  # baaki jo bache

    for tp_price, qty in [(trade["tp1"], tp1_qty), (trade["tp2"], tp2_qty), (trade["tp3"], tp3_qty)]:
        if qty <= 0:
            continue
        try:
            resp = session.place_order(
                category=BYBIT_CATEGORY, symbol=symbol, side=close_side,
                orderType="Limit", price=str(round(tp_price, 6)),
                qty=f"{qty:.{decimals}f}", timeInForce="GTC", reduceOnly=True,
            )
            # Try to capture order id from response
            order_id = None
            try:
                order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None
            except Exception:
                order_id = None
            if order_id:
                tp_order_ids.append(order_id)
        except Exception as e:
            log.error("%s: TP order (%s) place nahi hui: %s", symbol, tp_price, e)
    if tp_order_ids:
        trade["tp_order_ids"] = tp_order_ids
    log.info("%s: 3 TP orders lagaye -- TP1=%s(50%%) TP2=%s(30%%) TP3=%s(20%%)",
              symbol, trade["tp1"], trade["tp2"], trade["tp3"])


# ---------------------------------------------------------------------------
# LAYER 8 -- NEWS FILTER (naya -- free RSS-based, koi paid API key nahi chahiye)
# ---------------------------------------------------------------------------
# NOTE (transparency ke liye): Ye ek proper "economic calendar" (jaise
# TradingEconomics -- jo exact CPI/FOMC time deta hai) jaisa precise nahi hai.
# Ye CoinDesk/CoinTelegraph ke free RSS feeds se latest crypto headlines
# leta hai (tradingview-mcp open-source project se liya gaya, koi API key
# nahi chahiye) aur un headlines mein high-impact keywords (Fed, FOMC, CPI,
# hack, ban, regulation, etc.) dhoondta hai. Agar RSS/feedparser available
# na ho (library missing ya internet issue), khud-ba-khud "clear" (True)
# maan leta hai -- bot kabhi is wajah se crash ya stuck nahi hoga.
try:
    from news_service import fetch_news
    _NEWS_SERVICE_AVAILABLE = True
except ImportError:
    _NEWS_SERVICE_AVAILABLE = False

NEWS_FILTER_ENABLED = os.getenv("NEWS_FILTER_ENABLED", "true").strip().lower() == "true"
NEWS_CACHE_TTL_SECONDS = 300  # 5 min tak result cache karo, har signal check par RSS na maarein
NEWS_HEADLINES_CHECKED = 5    # feeds latest-first hoti hain -- sirf top N headlines dekho

# High-impact keywords -- inme se koi bhi latest headlines mein mile to
# trade thodi der ke liye skip kar dete hain (case-insensitive match).
NEWS_RISK_KEYWORDS = [
    "fed ", "fomc", "cpi", "interest rate", "rate hike", "rate cut",
    "sec ", "lawsuit", "hack", "hacked", "exploit", "ban ", "banned",
    "regulation", "regulatory", "shutdown", "bankrupt", "collapse",
    "sanction", "crackdown",
]

_news_cache = {"checked_at": 0.0, "clear": True, "matched": None}


def news_clear() -> bool:
    """
    True = koi high-impact news detect nahi hui, trade aage badh sakti hai.
    False = risky keyword wali fresh headline mili, is loop mein naya
    trade skip karo (aisa hi jaise CPI/FOMC ke 30-60 min aas-paas hota hai).
    """
    if not NEWS_FILTER_ENABLED:
        return True
    if not _NEWS_SERVICE_AVAILABLE:
        return True  # news_service.py folder mein nahi mili -- filter off, bot crash nahi hoga

    now = time.time()
    if now - _news_cache["checked_at"] < NEWS_CACHE_TTL_SECONDS:
        return _news_cache["clear"]  # 5 min purana result hi use karo, RSS dobara na maarein

    _news_cache["checked_at"] = now
    try:
        items = fetch_news(category="crypto", limit=NEWS_HEADLINES_CHECKED)
        if items and isinstance(items, list) and items and "error" in items[0]:
            # feedparser install nahi hai -- log ek baar warning, filter clear maan lo
            log.warning("News filter: feedparser missing (%s) -- filter is loop ke liye clear maan liya.",
                        items[0].get("error"))
            _news_cache["clear"] = True
            _news_cache["matched"] = None
            return True

        for item in items:
            text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
            for kw in NEWS_RISK_KEYWORDS:
                if kw in text:
                    log.info("News filter: high-impact keyword '%s' mila headline mein -- naye trades %ds ke liye skip. (%s)",
                              kw.strip(), NEWS_CACHE_TTL_SECONDS, item.get("title", "")[:80])
                    _news_cache["clear"] = False
                    _news_cache["matched"] = item.get("title", "")
                    return False

        _news_cache["clear"] = True
        _news_cache["matched"] = None
        return True

    except Exception as e:
        log.warning("News filter check fail hui (%s) -- is loop ke liye clear maan liya.", e)
        _news_cache["clear"] = True
        return True


# ---------------------------------------------------------------------------
# LAYER 9 -- SCORING SYSTEM
# ---------------------------------------------------------------------------
def compute_final_score(f_score, o_score, structure, candle_ok, rr, ob_or_fvg_found, vsa, pullback_score=0.0, macd_score=0.5):
    structure_score = 1.0 if structure["bos_confirmed"] else 0.7
    sweep_score = 1.0  # sweep already confirmed to reach here
    ob_fvg_score = 1.0 if ob_or_fvg_found else 0.6
    candle_score = 1.0 if candle_ok else 0.6
    rr_score = 1.0 if rr >= 2 else (0.7 if rr >= 1.5 else 0.3)
    news_score = 1.0 if news_clear() else 0.0

    total = (
        f_score * WEIGHTS["fundamental"]
        + o_score * WEIGHTS["onchain"]
        + structure_score * WEIGHTS["structure"]
        + ob_fvg_score * WEIGHTS["ob_fvg"]
        + sweep_score * WEIGHTS["sweep"]
        + candle_score * WEIGHTS["candle"]
        + vsa * WEIGHTS["vsa"]
        + rr_score * WEIGHTS["risk_reward"]
        + news_score * WEIGHTS["news"]
        + pullback_score * WEIGHTS["pullback"]  # NEW! Trend pullback boost
        + macd_score * WEIGHTS["macd"]  # NEW! MACD indicator (backtest winner)
    )
    return round(total, 1)


# ---------------------------------------------------------------------------
# LAYER 10 -- QUICK TRADE NOTE FORMAT (Telegram message)
# ---------------------------------------------------------------------------
def format_message(symbol, structure, entry, sl, tp1, tp2, tp3, rr, score, size, ob_found, fvg_found, vsa, pullback_data=None):
    ts = datetime.fromtimestamp(structure["candle_time"] / 1000, tz=timezone.utc)
    ob_fvg_text = []
    if ob_found:
        ob_fvg_text.append("OB")
    if fvg_found:
        ob_fvg_text.append("FVG")
    ob_fvg_display = " + ".join(ob_fvg_text) if ob_fvg_text else "Nahi mila (weak zone)"

    if vsa >= 0.9:
        vsa_display = "Healthy move (effort=result) ✅"
    elif vsa <= 0.25:
        vsa_display = "Absorption/Churning warning ⚠️"
    elif vsa <= 0.35:
        vsa_display = "Possible climax candle ⚠️"
    else:
        vsa_display = "Neutral"
    
    # NEW! Pullback info
    pullback_info = ""
    if pullback_data and pullback_data.get("is_pullback"):
        fib_level = pullback_data.get("fib_level", "unknown")
        trend_strength = pullback_data.get("trend_strength", 0)
        pullback_info = f"📊 Trend Pullback: {fib_level} Fibonacci level (Trend strength: {trend_strength:.1%})\n"

    return (
        f"<b>⚡ Signal: {symbol}</b>\n"
        f"Bias: <b>{structure['direction']}</b>\n"
        f"Structure: {'BOS confirmed' if structure['bos_confirmed'] else 'CHoCH / weak'}\n"
        f"OB/FVG: {ob_fvg_display}\n"
        f"Volume (VSA): {vsa_display}\n"
        f"{pullback_info}"
        f"Liquidity Sweep: Complete\n"
        f"Entry (LIMIT): {entry:.4f}\n"
        f"SL: {sl:.4f}\n"
        f"TP1 (50%): {tp1:.4f}\n"
        f"TP2 (30%): {tp2:.4f}\n"
        f"TP3 (20%): {tp3:.4f}\n"
        f"R:R (TP2 tak): {rr:.2f}\n"
        f"Suggested size: {size} {symbol.replace('USDT','')} "
        f"(0 dikhe to .env mein ACCOUNT_SIZE_USDT bharein)\n"
        f"Trade risk: {RISK_PER_TRADE_PCT}% of account, max leverage {MAX_LEVERAGE}x\n"
        f"Score: <b>{score}/100</b>\n"
        f"Candle Close (UTC): {ts.strftime('%Y-%m-%d %H:%M')}\n"
        f"\n<i>Pattern + score-based alert. Financial advice nahi hai. "
        f"Apna chart khud confirm karke hi trade lein.</i>"
    )


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
def run_once(client: Client, universe: list):
    if daily_loss_limit_hit():
        log.warning("Daily loss limit hit -- naye trades skip kiye ja rahe hain aaj.")
        return

    account_value = ACCOUNT_SIZE_USDT
    bybit_session = None
    if EXCHANGE_EXECUTION_ENABLED:
        bybit_session = get_bybit_session()
        if bybit_session is not None:
            account_value = get_exchange_account_size_usdt(bybit_session)

    for symbol in universe:
        try:
            candles = get_klines(client, symbol)
            structure = check_structure(candles)
            if not structure:
                log.info("%s: no sweep/structure signal.", symbol)
                continue

            key = f"{symbol}_{structure['direction']}_{structure['candle_time']}"
            if last_alerted.get(symbol) == key:
                continue

            if TREND_FILTER_ENABLED and not trend_filter_ok(candles, structure["direction"]):
                log.info("%s: signal mila lekin EMA trend filter ke against hai -- skip.", symbol)
                continue

            f_score = fundamental_score(symbol)
            o_score = onchain_score(symbol, structure["direction"])
            candle_ok = candle_confirmation(candles, structure["direction"])
            ob_found = detect_order_block(candles, structure["direction"])
            fvg_found = detect_fvg(candles, structure["direction"])
            vsa = vsa_score(candles, structure["direction"])
            
            # NEW! Trend pullback detection (ICT concept)
            pullback_data = detect_trend_pullback(candles, structure["direction"], lookback=30)
            pullback_score = pullback_data.get("pullback_score", 0.0)
            
            # NEW! MACD indicator (backtest winner on AVAX: 8.82% return)
            m_score = macd_score(candles, structure["direction"], lookback=26)
            
            result = compute_entry_sl_tp(structure, candles)
            if not result:
                log.info("%s: structure signal mila lekin entry/SL/TP validation fail hui -- skip.", symbol)
                continue

            entry, sl, tp1, tp2, tp3, rr, tp_levels = result
            score = compute_final_score(f_score, o_score, structure, candle_ok, rr, ob_found or fvg_found, vsa, pullback_score, m_score)
            fallback_eligible = (
                rr >= MIN_RISK_REWARD_RATIO
                and (structure.get("bos_confirmed", False) or ob_found or fvg_found or vsa >= 0.7)
                and (candle_ok or ob_found or fvg_found or vsa >= 0.6)
                and score >= SCORE_THRESHOLD - SCORE_FALLBACK_MARGIN
            )

            if score < SCORE_THRESHOLD and not fallback_eligible:
                log.info("%s: signal found but score %.1f < threshold %s -- skipping.", symbol, score, SCORE_THRESHOLD)
                continue

            should_execute = score >= SCORE_THRESHOLD
            if score < SCORE_THRESHOLD:
                log.info(
                    "%s: score %.1f below threshold %.1f but passed structure fallback check. Alert only, no trade will be opened.",
                    symbol, score, SCORE_THRESHOLD,
                )

            size = position_size(entry, sl, account_value)
            last_alerted[symbol] = key
            msg = format_message(symbol, structure, entry, sl, tp1, tp2, tp3, rr, score, size, ob_found, fvg_found, vsa, pullback_data)
            log.info("Qualified signal: %s", msg.replace("\n", " | "))
            send_telegram_message(msg)

            if EXCHANGE_EXECUTION_ENABLED and should_execute:
                # Check for direction flip and handle it
                flip_handled = handle_direction_flip(symbol, structure["direction"], bybit_session)
                
                if symbol in managed_trades and not flip_handled:
                    log.info("%s: pehle se ek managed trade chal rahi hai -- naya signal skip.", symbol)
                else:
                    place_entry_with_multi_tp(symbol, structure["direction"], structure["close"], entry, sl, tp1, tp2, tp3, size, score)
            elif EXCHANGE_EXECUTION_ENABLED and not should_execute:
                log.info("%s: EXCHANGE_EXECUTION_ENABLED hai, lekin score %.1f < threshold %.1f hai toh koi order nahin bheja jayega.", symbol, score, SCORE_THRESHOLD)

        except BinanceAPIException as e:
            log.error("Binance API error for %s: %s", symbol, e)
        except Exception as e:
            log.error("Unexpected error checking %s: %s", symbol, e)


def main():
    log.info("Starting Master Crypto Signal Bot (Layer 0-10 system)")
    load_managed_trades_state()

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        log.info("Telegram alerts enabled.")
    else:
        log.warning("Telegram token/chat missing in .env -- alerts disabled.")

    if EXCHANGE_EXECUTION_ENABLED:
        log.info("Bybit DEMO execution enabled.")
    else:
        if BYBIT_EXECUTION_REQUESTED and not BYBIT_CREDENTIALS_PRESENT:
            log.warning("Bybit DEMO execution requested but disabled due to missing API credentials.")
        else:
            log.info("Bybit DEMO execution disabled. Set EXCHANGE_EXECUTION_ENABLED=true with valid keys to enable.")

    client = Client(BINANCE_API_KEY or None, BINANCE_API_SECRET or None)

    if EXCHANGE_EXECUTION_ENABLED:
        if get_bybit_session() is not None:
            log.info("Bybit DEMO connection successful.")
        else:
            log.warning("Bybit DEMO execution enabled but unable to connect. Check pybit install and API keys.")

    if MANUAL_WATCHLIST_ENABLED and MANUAL_WATCHLIST:
        universe = MANUAL_WATCHLIST
        log.info("Manual watchlist active (%d coins), Layer 0 auto-scan OFF: %s",
                  len(universe), universe)
    else:
        universe = select_final_universe(client)
        if not universe:
            log.warning("Universe scan khali aaya -- fallback BTCUSDT/ETHUSDT/SOLUSDT use kar rahe hain.")
            universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    last_universe_refresh = time.time()
    retry_backoff = 5

    while True:
        try:
            # har 6 ghante mein universe dobara scan karo (naye coins market mein aa sakte hain)
            # -- manual watchlist mode mein ye SKIP hota hai, list fixed rehti hai
            if not MANUAL_WATCHLIST_ENABLED and time.time() - last_universe_refresh > 6 * 3600:
                new_universe = select_final_universe(client)
                if new_universe:
                    universe = new_universe
                last_universe_refresh = time.time()

            run_once(client, universe)
            if EXCHANGE_EXECUTION_ENABLED:
                manage_open_trades()

            # Periodic account report (daily by default). Sends Telegram message if token/chat set.
            try:
                global _last_report_time
                if REPORT_INTERVAL_SECONDS > 0 and time.time() - _last_report_time > REPORT_INTERVAL_SECONDS:
                    send_account_report(days=1)
                    _last_report_time = time.time()
            except Exception as e:
                log.warning("Account report failed: %s", e)

            retry_backoff = 5
            time.sleep(LOOP_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            log.info("Stopped manually (Ctrl+C). Bye!")
            break
        except Exception as e:
            log.error("Loop-level error: %s. Retrying in %ss...", e, retry_backoff)
            time.sleep(retry_backoff)
            retry_backoff = min(retry_backoff * 2, MAX_RETRY_BACKOFF)


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# AGLA STEP (aapke liye)
# ---------------------------------------------------------------------------
# 1. Bybit DEMO setup: bybit.com par "Demo Trading" account switch karke
#    wahin se API key/secret banayein (normal account ki key kaam nahi karegi).
# 2. .env mein BYBIT_API_KEY, BYBIT_API_SECRET daalein,
#    EXCHANGE_EXECUTION_ENABLED=true karein.
# 3. `pip install pybit --break-system-packages` chalayein.
# 4. Pehle EXCHANGE_EXECUTION_ENABLED=false par hi kai din chalayein aur
#    dekhein signals kaisi aa rahi hain -- jab confident ho jayein, tabhi
#    true karein taaki demo account par bhi order jaana shuru ho.
# 5. Demo par bhi kam se kam 2-4 hafte results dekhein, execution sahi ho
#    raha hai ya nahi (SL/TP sahi lag rahe hain, koi qty/lot-size error to
#    nahi aa rahi) -- usके baad hi real paise ka sochein.

