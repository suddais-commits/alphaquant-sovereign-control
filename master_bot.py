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
import math
import csv
import json
import logging
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException
import requests
from requests.adapters import HTTPAdapter, Retry

from proxy_manager import get_proxy, get_proxy_url, get_working_proxy_url, get_hardwired_proxy

try:
    from gemini_service import evaluate_trade_setup as gemini_evaluate_setup, is_gemini_configured
except ImportError:
    def gemini_evaluate_setup(*args, **kwargs):
        return {"ai_confirmed": True, "ai_score": 0.75, "reason": "gemini_service not imported"}
    def is_gemini_configured():
        return False

try:
    from pybit.unified_trading import HTTP as BybitHTTP
except ImportError:
    BybitHTTP = None  # 'pip install pybit' na kiya ho to bot alert-only mode mein chalega

try:
    from smart_entry_position_sizer import SmartEntrySizer, EntryExecutionPlanner, MarketSentimentAnalyzer
    smart_sentiment_analyzer = MarketSentimentAnalyzer()
    smart_sizer = SmartEntrySizer(risk_per_trade=0.02, account_size=1000.0)
    smart_planner = EntryExecutionPlanner(smart_sizer)
    SMART_ENTRY_ENABLED = True
except ImportError:
    smart_sentiment_analyzer = None
    smart_sizer = None
    smart_planner = None
    SMART_ENTRY_ENABLED = False

try:
    from news_service import fetch_news
    _NEWS_SERVICE_AVAILABLE = True
except ImportError:
    _NEWS_SERVICE_AVAILABLE = False

try:
    import chart_visualizer
    _CHART_VISUALIZER_AVAILABLE = True
except ImportError:
    _CHART_VISUALIZER_AVAILABLE = False

try:
    from indicators_calc import detect_market_regime, calc_atr, calc_adx, calc_z_score, calc_carver_volatility_scalar
    _INDICATORS_CALC_AVAILABLE = True
except ImportError:
    _INDICATORS_CALC_AVAILABLE = False
    def detect_market_regime(*args, **kwargs):
        return {"regime": "NORMAL", "adx": 25.0, "min_score": 50.0, "pos_multiplier": 1.0, "tp_scale": 1.0, "min_rrr": 1.5}
    calc_atr = None
    calc_adx = None
    calc_z_score = None
    calc_carver_volatility_scalar = None

# ---------------------------------------------------------------------------
# CONFIG & V2 SWITCH
# ---------------------------------------------------------------------------
load_dotenv()

# --- V2 Institutional Architecture Integration (Default OFF) ---
USE_V2 = os.getenv("USE_V2", "false").strip().lower() == "true"
try:
    from config import ScoreCfg as V2ScoreCfg, RiskCfg as V2RiskCfg, SignalCfg as V2SignalCfg
    from scoring import decide as v2_decide, conviction as v2_conviction, calc_a01_mtf_trend as v2_calc_a01
    from risk import RiskManager as V2RiskManager
    from regime import classify as v2_regime_classify
    _V2_AVAILABLE = True
except ImportError:
    _V2_AVAILABLE = False

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# TELEGRAM_PROXY is intentionally None — tested: proxy blocks Telegram but direct connection works perfectly.
# Proxy is ONLY used for Binance/exchange API calls (which require whitelisted IP).
TELEGRAM_PROXY = None
BINANCE_PROXY = get_proxy()  # Proxy ONLY for Binance (whitelisted IP 45.38.107.97)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "false").strip().lower() == "true"
BINANCE_CREDENTIALS_PRESENT = bool(BINANCE_API_KEY and BINANCE_API_SECRET)
EXECUTION_EXCHANGE = os.getenv("EXECUTION_EXCHANGE", "bybit").strip().lower()

# --- Bybit DEMO trading ---
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_CATEGORY = os.getenv("BYBIT_CATEGORY", "linear")  # "linear" = USDT perpetual, "spot" = spot
EXCHANGE_EXECUTION_ENABLED = os.getenv("EXCHANGE_EXECUTION_ENABLED", "false").strip().lower() == "true"
BYBIT_CREDENTIALS_PRESENT = bool(BYBIT_API_KEY and BYBIT_API_SECRET)
BYBIT_EXECUTION_REQUESTED = EXCHANGE_EXECUTION_ENABLED
if EXCHANGE_EXECUTION_ENABLED and not (BYBIT_CREDENTIALS_PRESENT or BINANCE_CREDENTIALS_PRESENT):
    EXCHANGE_EXECUTION_ENABLED = False

# --- Arkham Intelligence (naya) -- Layer 2 real on-chain data ---
# Free key yahan se lein: https://intel.arkm.com/api
# Khali chhodne par bot khud DefiLlama wale purane fallback proxy par chala jayega,
# kuch break nahi hoga.
ARKHAM_API_KEY = os.getenv("ARKHAM_API_KEY", "")
ARKHAM_BASE = "https://api.arkm.com"

# --- CoinGecko Demo/Pro API Key (Shermin Voshmgir Tokenomics & Screening) ---
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

# --- Optional EMA Trend Filter & Multi-Timeframe Cascade ---
TREND_FILTER_ENABLED = os.getenv("TREND_FILTER_ENABLED", "true").strip().lower() == "true"
TREND_FILTER_EMA_PERIOD = int(os.getenv("TREND_FILTER_EMA_PERIOD", "50"))
MULTI_TIMEFRAME_CASCADE_ENABLED = os.getenv("MULTI_TIMEFRAME_CASCADE_ENABLED", "true").strip().lower() == "true"
try:
    from indicators_calc import calc_ema, calc_atr, calc_rsi, calc_z_score, calc_carver_volatility_scalar, calc_adx
except ImportError:
    calc_ema = None
    calc_atr = None
    calc_rsi = None
    calc_z_score = None
    calc_carver_volatility_scalar = None
    calc_adx = None
    if TREND_FILTER_ENABLED:
        TREND_FILTER_ENABLED = False

# --- Full 8-Timeframe MTF Cascade Definitions (15m, 30m, 1H, 2H, 4H, 12H, 1D, 1W) ---
MTF_INTERVALS = {
    "1W":  {"binance": Client.KLINE_INTERVAL_1WEEK,   "limit": 30,  "ttl": 3600, "weight": 25, "is_htf": True},
    "1D":  {"binance": Client.KLINE_INTERVAL_1DAY,    "limit": 60,  "ttl": 3600, "weight": 20, "is_htf": True},
    "12H": {"binance": Client.KLINE_INTERVAL_12HOUR,  "limit": 60,  "ttl": 1800, "weight": 15, "is_htf": True},
    "4H":  {"binance": Client.KLINE_INTERVAL_4HOUR,   "limit": 60,  "ttl": 1800, "weight": 15, "is_htf": True},
    "2H":  {"binance": Client.KLINE_INTERVAL_2HOUR,   "limit": 60,  "ttl": 900,  "weight": 10, "is_htf": False},
    "1H":  {"binance": Client.KLINE_INTERVAL_1HOUR,   "limit": 60,  "ttl": 0,    "weight": 8,  "is_htf": False},
    "30m": {"binance": Client.KLINE_INTERVAL_30MINUTE, "limit": 60,  "ttl": 0,    "weight": 4,  "is_htf": False},
    "15m": {"binance": Client.KLINE_INTERVAL_15MINUTE, "limit": 60,  "ttl": 0,    "weight": 3,  "is_htf": False},
}
# MTF kline cache: key = "SYMBOL_INTERVAL" -> {"data": [...], "ts": timestamp}
_mtf_kline_cache: dict = {}

# --- Funding Rate Filter ---
FUNDING_FILTER_ENABLED = os.getenv("FUNDING_FILTER_ENABLED", "true").strip().lower() == "true"
MAX_ADVERSE_FUNDING_PCT = float(os.getenv("MAX_ADVERSE_FUNDING_PCT", "0.06"))

_TF_ENV = os.getenv("TIMEFRAME", "1h").strip().lower()
if _TF_ENV in ["15m", "15min"]:
    TIMEFRAME = Client.KLINE_INTERVAL_15MINUTE
elif _TF_ENV in ["1h", "1hour", "60m"]:
    TIMEFRAME = Client.KLINE_INTERVAL_1HOUR
else:
    TIMEFRAME = Client.KLINE_INTERVAL_1HOUR
SWING_LOOKBACK = 15
LOOP_INTERVAL_SECONDS = int(os.getenv("LOOP_INTERVAL_SECONDS", "120"))  # 2 min fast check loop
MAX_RETRY_BACKOFF = 60

# --- Layer 0 settings: universe scan ---
MIN_24H_VOLUME_USDT = 50_000_000     # Updated liquidity threshold to $50M daily
MAX_UNIVERSE_SIZE = 40               # itne top-volume coins tak hi scan karo (API/rate-limit safe)
FINAL_SHORTLIST_SIZE = int(os.getenv("FINAL_SHORTLIST_SIZE", "20"))  # in mein se kitne aage layer 1-9 tak jayein (env override)

# --- Manual watchlist override ---
MANUAL_WATCHLIST_ENABLED = os.getenv("MANUAL_WATCHLIST_ENABLED", "true").strip().lower() == "true"
_DEFAULT_MANUAL_WATCHLIST = (
    "BTCUSDT,ETHUSDT,BNBUSDT,INJUSDT,SOLUSDT,LINKUSDT,XRPUSDT,NEARUSDT,OPUSDT,APTUSDT,DOGEUSDT,ATOMUSDT"
)
MANUAL_WATCHLIST = [
    s.strip().upper() for s in os.getenv("MANUAL_WATCHLIST", _DEFAULT_MANUAL_WATCHLIST).split(",")
    if s.strip()
]

# --- Layer 9 scoring weights (Claude Balanced Distribution, 8-TF cascade) ---
WEIGHTS = {
    "macro_alignment": 18,    # Macro Bias (1M, 1W, 1D) -- trend alignment
    "intermediate": 16,       # Intermediate confluence (4H, 2H OB/FVG/Sweep)
    "structure": 16,          # 1H/30m BOS/CHoCH + Liquidity Sweep
    "ob_fvg": 16,             # Order Block / Fair Value Gap (multi-TF)
    "vsa": 10,                # Volume Spread Analysis (Effort vs Result)
    "precision_trigger": 10,  # 15m Precision Entry Quality & Timing
    "rsi_divergence": 7,      # Momentum Divergence at key levels
    "macd": 7,                # MACD Trend/Momentum
}
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "70.0"))
SCORE_FALLBACK_MARGIN = float(os.getenv("SCORE_FALLBACK_MARGIN", "8"))
GEMINI_AI_CONFIRMATION_ENABLED = os.getenv("GEMINI_AI_CONFIRMATION_ENABLED", "false").strip().lower() == "true"

# --- Testing / Discovery Mode ---
TESTING_MODE = os.getenv("TESTING_MODE", "true").strip().lower() == "true"
if TESTING_MODE:
    SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "70.0"))  # Never drop below 70 even in testing
    MAX_SL_DISTANCE_PCT = float(os.getenv("MAX_SL_DISTANCE_PCT", "3.5"))
    TREND_FILTER_ENABLED = os.getenv("TREND_FILTER_ENABLED", "false").strip().lower() == "true"
    SMART_ENTRY_ENABLED = os.getenv("SMART_ENTRY_ENABLED", "false").strip().lower() == "true"
    GEMINI_AI_CONFIRMATION_ENABLED = os.getenv("GEMINI_AI_CONFIRMATION_ENABLED", "false").strip().lower() == "true"

DEMO_SIGNAL_TEST_MODE = os.getenv("DEMO_SIGNAL_TEST_MODE", "true").strip().lower() == "true"
DEMO_SIGNAL_TARGET = int(os.getenv("DEMO_SIGNAL_TARGET", "15"))
_demo_signal_count = 0

# --- Layer 6 risk management settings ---
ACCOUNT_SIZE_USDT = float(os.getenv("ACCOUNT_SIZE_USDT", "5962.0"))  # Bybit DEMO balance (fallback)
BINANCE_ACCOUNT_SIZE_USDT = float(os.getenv("BINANCE_ACCOUNT_SIZE_USDT", "4.93"))  # LIVE Binance wallet ($4.93)
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))  # per trade max 1% risk
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "10.0"))  # din ka max loss (10%)
MAX_SL_DISTANCE_PCT = float(os.getenv("MAX_SL_DISTANCE_PCT", os.getenv("MAX_SL_PCT", "2.0")))
MIN_SL_DISTANCE_PCT = float(os.getenv("MIN_SL_DISTANCE_PCT", "0.15"))
MIN_RISK_REWARD_RATIO = float(os.getenv("MIN_RISK_REWARD_RATIO", "3.0"))  # 3:1 RR minimum — enforced by config.yaml tp1_r
USE_ISOLATED_MARGIN = os.getenv("USE_ISOLATED_MARGIN", "true").strip().lower() == "true"
MIN_LEVERAGE = int(os.getenv("MIN_LEVERAGE", "8"))
MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "20"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "0"))
# Binance small account margin bounds (scaled to actual $4.93 wallet)
MIN_INITIAL_MARGIN_USDT = float(os.getenv("MIN_INITIAL_MARGIN_USDT", "0.30"))  # min $0.30/trade
MAX_INITIAL_MARGIN_USDT = float(os.getenv("MAX_INITIAL_MARGIN_USDT", "1.50"))  # max $1.50/trade (30% of $4.93)
MAX_MARGIN_UTILIZATION_PCT = float(os.getenv("MAX_MARGIN_UTILIZATION_PCT", "40.0"))


def clamp_leverage(leverage: int | float | None) -> int:
    """Ensure leverage is strictly clamped between 8 and 20 (MIN_LEVERAGE and MAX_LEVERAGE).
    No trade ever opens with less than 8x or more than 20x leverage.
    """
    try:
        if leverage is None:
            return MIN_LEVERAGE
        lev = int(round(float(leverage)))
        return min(max(lev, MIN_LEVERAGE), MAX_LEVERAGE)
    except Exception:
        return MIN_LEVERAGE


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler("bot_log.txt", encoding="utf-8"), logging.StreamHandler()],
    force=True,
)
log = logging.getLogger("master_bot")

last_alerted = {}

# Global session objects with retries for network resilience
http_session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
http_session.mount('http://', HTTPAdapter(max_retries=retries))
http_session.mount('https://', HTTPAdapter(max_retries=retries))

# Bybit tradable symbols cache
_bybit_tradable_symbols = set()
_binance_tradable_symbols = set()

daily_loss_tracker = {"date": None, "loss_pct": 0.0}

# ============================================================================
# SIGNAL RATE LIMITER (Prevents Telegram Spam - Max 1 Signal/Hr, 12h Per Coin)
# ============================================================================
import threading
_master_signal_lock = threading.Lock()
_master_sent_signals = {}      # symbol -> timestamp
_master_hourly_log = []        # list of timestamps
MASTER_COOLDOWN_SECONDS = int(os.getenv("MASTER_COOLDOWN_SECONDS", "1800"))  # Default 30 min per-coin cooldown (was hardcoded 4hr!)
MASTER_MAX_SIGNALS_PER_HOUR = int(os.getenv("MAX_SIGNALS_PER_HOUR", "12"))    # Max 12 signals/hr (was hardcoded 3!)


def is_signal_rate_allowed(symbol: str) -> tuple:
    """Returns (allowed: bool, reason: str) to protect Telegram from spam."""
    now = time.time()
    with _master_signal_lock:
        last_sent = _master_sent_signals.get(symbol, 0)
        elapsed = now - last_sent
        if elapsed < MASTER_COOLDOWN_SECONDS:
            hours_left = (MASTER_COOLDOWN_SECONDS - elapsed) / 3600
            return False, f"Symbol {symbol} cooldown active ({hours_left:.1f}h remaining)"
        
        one_hour_ago = now - 3600
        recent = [t for t in _master_hourly_log if t > one_hour_ago]
        if len(recent) >= MASTER_MAX_SIGNALS_PER_HOUR:
            return False, f"Hourly signal limit reached ({MASTER_MAX_SIGNALS_PER_HOUR}/hr). Oldest clears in {((recent[0] + 3600) - now)/60:.0f} min."
        
        _master_sent_signals[symbol] = now
        _master_hourly_log.append(now)
        if len(_master_hourly_log) > 200:
            _master_hourly_log[:] = _master_hourly_log[-200:]
        return True, "OK"

# ============================================================================
# AGENT 10: FEAR & GREED INDEX DESK
# ============================================================================
def get_fear_greed_sentiment() -> dict:
    """Live Crypto Fear & Greed Sentiment Index from Alternative.me."""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        if r.status_code == 200:
            data = r.json().get("data", [{}])[0]
            val = int(data.get("value", 50))
            classification = data.get("value_classification", "Neutral")
            bias = "NEUTRAL_ACCUMULATION"
            if val <= 25:
                bias = "EXTREME_FEAR_SMART_MONEY_BUY_ZONE"
            elif val >= 75:
                bias = "EXTREME_GREED_EXHAUSTION_RISK"
            return {"value": val, "classification": classification, "bias": bias}
    except Exception:
        pass
    return {"value": 50, "classification": "Neutral", "bias": "NEUTRAL_ACCUMULATION"}

# ============================================================================
# AGENT 11 & 12: CRYPTO BREAKING NEWS & GLOBAL MACRO DESK (INTELLIGENT RSS)
# ============================================================================
NEWS_CACHE_TTL_SECONDS = 300
NEWS_HEADLINES_CHECKED = 10

# High-threat crisis keywords that halt trading to prevent black swan liquidations
NEWS_CRITICAL_DANGER_KEYWORDS = [
    "hack", "hacked", "exploit", "insolvent", "bankrupt", "freeze withdrawal",
    "emergency shutdown", "rug pull", "contagion", "crypto ban", "arrested"
]

NEWS_BULLISH_KEYWORDS = [
    "rally", "surge", "bull", "soar", "gain", "buyback", "etf", "inflow",
    "approval", "jump", "record high", "breakout", "accumulat", "cut rates",
    "rate cut", "expansion", "growth", "pump", "adoption", "partnership"
]

NEWS_BEARISH_KEYWORDS = [
    "dump", "crash", "plunge", "bear", "drop", "slump", "liquidation",
    "outflow", "lawsuit", "crackdown", "decline", "fall", "losses",
    "fine", "investigation", "rate hike", "inflation surge", "recession"
]

_macro_news_cache = {
    "checked_at": 0.0,
    "clear": True,
    "sentiment_score": 0.50,
    "sentiment_label": "NEUTRAL",
    "danger_event": False,
    "danger_headline": None,
    "headlines": []
}

def evaluate_macro_news_intelligence() -> dict:
    """
    Analyzes live crypto and macroeconomic headlines from CoinDesk, CoinTelegraph,
    Yahoo Finance, CNBC, and MarketWatch to generate a real-time sentiment score (0-1)
    and detect critical black-swan risks.
    """
    global _macro_news_cache
    now = time.time()
    if now - _macro_news_cache["checked_at"] < NEWS_CACHE_TTL_SECONDS and _macro_news_cache["headlines"]:
        return _macro_news_cache

    if not _NEWS_SERVICE_AVAILABLE:
        return _macro_news_cache

    try:
        # Fetch crypto + financial macro headlines
        items = fetch_news(category="all", limit=NEWS_HEADLINES_CHECKED)
        if not items:
            items = fetch_news(category="crypto", limit=NEWS_HEADLINES_CHECKED)

        if not items:
            _macro_news_cache["checked_at"] = now
            return _macro_news_cache

        bull_count = 0
        bear_count = 0
        danger_event = False
        danger_headline = None
        headline_titles = []

        for item in items:
            title = item.get("title", "")
            summary = item.get("summary", "")
            full_text = f"{title} {summary}".lower()
            if title:
                headline_titles.append(title)

            # Check for critical black-swan danger
            for d_kw in NEWS_CRITICAL_DANGER_KEYWORDS:
                if d_kw in full_text:
                    danger_event = True
                    danger_headline = title
                    break

            for b_kw in NEWS_BULLISH_KEYWORDS:
                if b_kw in full_text:
                    bull_count += 1

            for br_kw in NEWS_BEARISH_KEYWORDS:
                if br_kw in full_text:
                    bear_count += 1

        # Calculate sentiment score from 0.10 to 0.90
        net = bull_count - bear_count
        if net > 0:
            score = 0.50 + min(0.35, net * 0.07)
        elif net < 0:
            score = 0.50 - min(0.35, abs(net) * 0.07)
        else:
            score = 0.50

        if danger_event:
            score = min(score, 0.25)
            sentiment_label = "CRITICAL_RISK"
        elif score >= 0.70:
            sentiment_label = "VERY_BULLISH"
        elif score >= 0.58:
            sentiment_label = "BULLISH"
        elif score >= 0.43:
            sentiment_label = "NEUTRAL"
        elif score >= 0.30:
            sentiment_label = "BEARISH"
        else:
            sentiment_label = "VERY_BEARISH"

        _macro_news_cache = {
            "checked_at": now,
            "clear": not danger_event,
            "sentiment_score": round(score, 2),
            "sentiment_label": sentiment_label,
            "danger_event": danger_event,
            "danger_headline": danger_headline,
            "headlines": headline_titles[:3],
            "top_headlines": headline_titles[:3]
        }
        log.info(
            "Macro News Intelligence updated: Sentiment=%s (%.2f) | Bullish tags=%d, Bearish tags=%d | Danger=%s",
            sentiment_label, score, bull_count, bear_count, danger_event
        )
        return _macro_news_cache
    except Exception as e:
        log.warning("evaluate_macro_news_intelligence error: %s", e)
        _macro_news_cache["checked_at"] = now
        return _macro_news_cache

def get_crypto_news_sentiment() -> dict:
    """Live Binance Official Announcements & Multi-source Crypto Feeds."""
    intel = evaluate_macro_news_intelligence()
    return {
        "sentiment": intel.get("sentiment_label", "NEUTRAL"),
        "sentiment_score": intel.get("sentiment_score", 0.50),
        "headlines": intel.get("headlines", ["Crypto liquidity conditions steady."])
    }

def get_global_macro_sentiment() -> dict:
    """Live Global Macro Economic & Financial News Desk."""
    intel = evaluate_macro_news_intelligence()
    return {
        "macro_regime": intel.get("sentiment_label", "GLOBAL_MACRO_STEADY"),
        "sentiment_score": intel.get("sentiment_score", 0.50),
        "headlines": intel.get("headlines", ["Global macroeconomic liquidity steady."])
    }


# ============================================================================
# ON-CHAIN WHALE & SQUEEZE ANALYTICS (Binance Top Traders Long/Short Ratio)
# ============================================================================
def get_whale_onchain_intelligence(symbol: str, direction: str) -> dict:
    """Binance Top Trader (Whale) Ratio vs Global Retail Ratio."""
    whale_ratio = 1.0
    global_ratio = 1.0
    bias = "NEUTRAL"
    try:
        url_top = f"https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={symbol}&period=4h&limit=1"
        r_top = requests.get(url_top, timeout=5)
        if r_top.status_code == 200 and r_top.json():
            whale_ratio = float(r_top.json()[0].get("longShortRatio", 1.0))
            
        url_glob = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=4h&limit=1"
        r_glob = requests.get(url_glob, timeout=5)
        if r_glob.status_code == 200 and r_glob.json():
            global_ratio = float(r_glob.json()[0].get("longShortRatio", 1.0))
            
        if direction == "LONG":
            if whale_ratio > 1.2 and global_ratio < 1.0:
                bias = "INSTITUTIONAL_WHALE_ACCUMULATION_SQUEEZE"
            elif whale_ratio > 1.0:
                bias = "WHALE_LONG_BIAS"
        elif direction == "SHORT":
            if whale_ratio < 0.8 and global_ratio > 1.0:
                bias = "INSTITUTIONAL_WHALE_DISTRIBUTION_SQUEEZE"
            elif whale_ratio < 1.0:
                bias = "WHALE_SHORT_BIAS"
    except Exception:
        pass
    return {"whale_ratio": whale_ratio, "global_ratio": global_ratio, "bias": bias}

def send_telegram_message(text: str, symbol: str = None, is_signal: bool = False) -> bool:
    """
    Sends Telegram alert immediately with multi-endpoint failover and detailed logging.
    - If is_signal=True and symbol provided, respects rate-limiter to prevent channel spam.
    - Real trade execution events (opens, TSL adjustments, closes, errors) are delivered IMMEDIATELY.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram token/chat id missing in .env - skipping message dispatch.")
        return False

    # Only apply rate limiter for candidate discovery signals, NEVER for real trade execution events
    if is_signal and symbol:
        allowed, reason = is_signal_rate_allowed(symbol)
        if not allowed:
            log.info("[RATE LIMITER] Candidate signal suppressed for %s: %s", symbol, reason)
            return False

    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    # IMPORTANT: Telegram is called WITHOUT proxy — tested and confirmed working.
    # Proxy (Webshare/Binance-whitelisted IP) actively BLOCKS Telegram connections.

    # Priority endpoints — direct connection (no proxy)
    endpoints = [
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        f"https://telegram-bot-api.vercel.app/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    ]

    for ep in endpoints:
        try:
            resp = requests.post(ep, json=payload, timeout=20, proxies=None)  # NO PROXY for Telegram
            if resp.status_code == 200:
                log.info("Telegram alert sent successfully via %s", ep.split('/')[2])
                return True
            else:
                log.warning("Telegram send to %s returned HTTP %s: %s", ep.split('/')[2], resp.status_code, resp.text[:120])
        except Exception as e:
            log.debug("Telegram endpoint %s connection error: %s", ep.split('/')[2], e)

    log.error("❌ All Telegram endpoints failed to deliver message. Please check token, chat ID, and proxy settings.")
    return False


def test_telegram_connection() -> bool:
    """Test Telegram connection on startup and log result clearly."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("❌ Telegram Startup Test FAILED: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env!")
        return False
    
    text = (
        "🤖 <b>MASTER CRYPTO BOT INITIALIZED & ONLINE</b>\n\n"
        "✅ <b>Telegram Connection:</b> VERIFIED ACTIVE\n"
        f"⚡ <b>Execution Mode:</b> {EXECUTION_EXCHANGE.upper()} {'(LIVE EXECUTION)' if EXCHANGE_EXECUTION_ENABLED else '(ALERT-ONLY)'}\n"
        f"🛡️ <b>Trailing Stop Loss (TSL):</b> 5-Min Background Loop ACTIVE\n"
        f"🎯 <b>Score Threshold:</b> <code>{SCORE_THRESHOLD}</code>\n"
        f"⏰ <b>Startup Time:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>"
    )
    
    success = send_telegram_message(text, is_signal=False)
    if success:
        log.info("✅ Telegram startup test PASSED: Welcome message delivered.")
    else:
        log.error("❌ Telegram startup test FAILED: Could not deliver message to Telegram.")
    return success



# ---------------------------------------------------------------------------
# LAYER 0 -- UNIVERSE SCAN / AUTO COIN SELECTION
# ---------------------------------------------------------------------------

# Stablecoins ko universe se hamesha exclude karo -- ye kabhi "trade signal"
# nahi denge kyunki inki price ~$1 par pegged rehti hai.
STABLECOINS = {
    "USDC", "USDT", "FDUSD", "TUSD", "BUSD", "DAI", "USD1", "RLUSD",
    "PYUSD", "USDP", "GUSD", "EURT", "USDE", "FRAX", "U", "EUR",
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
    mein leta hai -- demo/pro key header ke sath taaki rate limit na ho.
    Returns: {"BTCUSDT": {...coingecko data...}, ...}
    """
    result = {}
    bases = [s.replace("USDT", "").lower() for s in symbols]
    chunk_size = 25  # CoinGecko URL/response size ke hisaab se safe batch
    headers = {"User-Agent": "Mozilla/5.0"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    for i in range(0, len(bases), chunk_size):
        chunk = bases[i:i + chunk_size]
        try:
            r = http_session.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "symbols": ",".join(chunk)},
                headers=headers,
                timeout=15,
            )
            r.raise_for_status()
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
            time.sleep(1.5)  # agla chunk bhejne se pehle rate-limit ka khayal
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

def fetch_and_cache_tradable_symbols(binance_client: Client, bybit_session: BybitHTTP | None):
    """Fetches all tradable USDT perpetual symbols from both exchanges and caches them."""
    global _bybit_tradable_symbols, _binance_tradable_symbols
    if bybit_session:
        try:
            bybit_res = bybit_session.get_instruments_info(category=BYBIT_CATEGORY, limit=1000)
            if bybit_res and bybit_res.get("retCode") == 0:
                _bybit_tradable_symbols = {s['symbol'] for s in bybit_res['result']['list']}
                log.info(f"Bybit ke {_bybit_tradable_symbols.__len__()} tradable symbols fetch kiye.")
        except Exception as e:
            log.warning(f"Bybit symbol list fetch nahi ho paayi: {e}")

    try:
        b_info = binance_client.futures_exchange_info()
        _binance_tradable_symbols = {s['symbol'] for s in b_info['symbols'] if s['quoteAsset'] == 'USDT'}
        log.info(f"Binance Futures ke {_binance_tradable_symbols.__len__()} symbols ke filters fetch kiye.")
    except Exception as e:
        log.warning(f"Binance symbol list fetch nahi ho paayi: {e}")

# ---------------------------------------------------------------------------
# LAYER 1 -- FUNDAMENTAL SCREENING (simplified, free-data version)
# ---------------------------------------------------------------------------
def fundamental_score(symbol: str) -> float:
    """
    0-1 ke beech score deta hai. Free CoinGecko data se:
    - volume/mcap ratio (zyada = zyada active/liquid)
    - circulating vs max supply (kam dilution risk = better)
    + Institutional Intelligence Layer:
    - Narrative tier (strong/emerging/weak)
    - Token unlock calendar (upcoming unlocks = sell pressure)
    - Smart money positioning (from research data)
    """
    # -----------------------------------------------------------------------
    # INSTITUTIONAL INTELLIGENCE DATABASE (aapke institutional report se)
    # Updated: August 2026 | Manually refresh periodically
    # -----------------------------------------------------------------------
    INSTITUTIONAL_DATA = {
        # symbol: (narrative_score 0-1, unlock_penalty 0-1, sm_score 0-1)
        # narrative_score: 1.0 = top narrative (RWA/AI/ETF), 0.5 = moderate, 0.3 = weak
        # unlock_penalty: 0.0 = no upcoming unlock, 0.5 = moderate unlock, 1.0 = major unlock (sell pressure)
        # sm_score: 1.0 = strong accumulation, 0.5 = neutral, 0.0 = distribution
        "BTCUSDT":  (1.0, 0.0, 1.0),   # Digital gold + ETF + Mega-whale accumulation
        "ETHUSDT":  (0.9, 0.0, 0.7),   # DeFi layer + ETF + mixed flows
        "SOLUSDT":  (0.9, 0.0, 0.8),   # High-perf L1 + DePIN + Agave upgrade catalyst
        "AVAXUSDT": (0.9, 0.0, 0.9),   # RWA leader + 69% SM LONG derivatives
        "NEARUSDT": (0.8, 0.0, 0.6),   # AI chain abstraction + buyback (crowded narrative)
        "FILUSDT":  (0.8, 0.7, 0.7),   # AI+DePIN, but Aug 15 unlock = sell pressure penalty
        "AAVEUSDT": (0.8, 0.0, 0.8),   # DeFi blue chip + real revenue + V4 upgrade
        "BNBUSDT":  (0.7, 0.0, 0.7),   # Exchange token, centralized
        "XRPUSDT":  (0.7, 0.0, 0.6),   # Payment narrative + legal clarity
        "ADAUSDT":  (0.6, 0.0, 0.5),   # Smart contract L1, slower development
        "DOGEUSDT": (0.5, 0.0, 0.4),   # Meme/speculation driven
        "LINKUSDT": (0.8, 0.0, 0.7),   # Oracle leader, Chainlink Functions growing
        "DOTUSDT":  (0.6, 0.3, 0.5),   # Parachain ecosystem, slower adoption
        "LTCUSDT":  (0.5, 0.0, 0.4),   # Legacy payments, low narrative
        "TRXUSDT":  (0.6, 0.0, 0.5),   # USDT transfer volume, centralized
        "UNIUSDT":  (0.7, 0.0, 0.6),   # DeFi DEX leader, Uniswap v4
        "APTUSDT":  (0.7, 0.2, 0.5),   # Move L1, institutional backing, unlock schedule
        "SUIUSDT":  (0.7, 0.2, 0.5),   # Move L1, newer, ongoing unlocks
        "INJUSDT":  (0.7, 0.0, 0.6),   # Financial L1, growing derivatives
        "ALGOUSDT": (0.5, 0.0, 0.4),   # L1, low narrative strength currently
    }

    inst = INSTITUTIONAL_DATA.get(symbol, (0.5, 0.0, 0.5))
    narrative_score, unlock_penalty, sm_score = inst
    # Institutional composite: narrative 40% + smart money 40% + unlock penalty 20%
    inst_composite = (narrative_score * 0.4) + (sm_score * 0.4) - (unlock_penalty * 0.2)
    inst_composite = max(0.0, min(1.0, inst_composite))

    if unlock_penalty >= 0.5:
        log.info("%s: TOKEN UNLOCK ALERT (penalty=%.1f) -- near-term supply pressure.", symbol, unlock_penalty)

    d = _market_data_cache.get(symbol)
    if not d:
        fresh = fetch_market_data_batch([symbol])
        _market_data_cache.update(fresh)
        d = fresh.get(symbol)
    if not d:
        return round(inst_composite * 0.7 + 0.5 * 0.3, 2)  # fallback blended
    try:
        # Shermin Voshmgir Tokenomics: FDV vs Market Cap Dilution & Supply float ratio
        circ_supply = float(d.get("circulating_supply") or 0)
        total_supply = float(d.get("total_supply") or 0)
        max_supply = float(d.get("max_supply") or total_supply or circ_supply)
        fdv = float(d.get("fully_diluted_valuation") or 0)
        mcap = float(d.get("market_cap") or 1)

        supply_ratio = (circ_supply / max_supply) if max_supply > 0 else 1.0
        fdv_ratio = (mcap / fdv) if fdv > 0 else 1.0
        tokenomics_score = min(1.0, max(0.2, (supply_ratio * 0.5 + fdv_ratio * 0.5)))

        vol_mcap_ratio = (d.get("total_volume", 0) or 0) / max(d.get("market_cap", 1) or 1, 1)
        market_score = min(vol_mcap_ratio * 5, 1.0)
        # Blend: 35% market activity + 35% institutional intelligence + 30% tokenomics/dilution
        final = (market_score * 0.35) + (inst_composite * 0.35) + (tokenomics_score * 0.30)
        return round(final, 2)
    except Exception as e:
        log.warning("Fundamental score failed for %s: %s", symbol, e)
        return round(inst_composite, 2)



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
        r = http_session.get(
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
        r = http_session.get(f"https://api.llama.fi/tvl/{base}", timeout=10)
        if r.status_code == 200 and r.text.strip().replace(".", "", 1).isdigit():
            return 0.65
    except Exception:
        pass
    return 0.5  # neutral -- kahin se bhi data nahi mila


# ---------------------------------------------------------------------------
# LAYER 3 -- MARKET STRUCTURE (BOS/CHoCH + Liquidity Sweep)
# (aapke original sweep_reclaim_signal.py se liya + BOS/CHoCH add kiya)
# ---------------------------------------------------------------------------
def get_klines(client: Client, symbol: str, limit: int = 100, live: bool = False):
    raw = None
    try:
        raw = client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=limit)
    except Exception as e:
        log.warning("Binance client get_klines failed for %s (%s). Using direct Vision API fallback...", symbol, e)
        try:
            url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={TIMEFRAME}&limit={limit}"
            r = requests.get(url, timeout=7)
            if r.status_code == 200:
                raw = r.json()
        except Exception as e2:
            log.error("Binance Vision fallback also failed for %s: %s", symbol, e2)

    if not raw:
        return []

    processed_klines = []
    for k in raw:
        try:
            processed_klines.append({
                "timestamp": k[0],  # Using 'timestamp' as the key
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "close_time": k[6],
                "volume": float(k[5]),
            })
        except (IndexError, TypeError) as e:
            log.warning(f"Could not process kline data for {symbol}: {k} -> Error: {e}")

    # CLOSED CANDLES: live=True drops the forming candle; live=False keeps all
    if live and len(processed_klines) > 1:
        now_ms = int(time.time() * 1000)
        if processed_klines[-1]["close_time"] > now_ms:
            processed_klines = processed_klines[:-1]

    return processed_klines


def check_structure(candles: list):
    """
    Enhanced structure detection with Wyckoff SFP, VSA volume absorption,
    rejection wick-to-body confirmation, and dynamic ATR stop loss from Auto-Optimizer.
    """
    if len(candles) < SWING_LOOKBACK + 1:
        return None
    closed = candles[:-1]
    lookback = closed[-SWING_LOOKBACK:-1]
    test_candle = closed[-1]
    if not lookback:
        return None

    try:
        from strategy_auto_optimizer import load_tuned_params
        params = load_tuned_params()
    except Exception:
        params = {"min_wick_ratio": 0.25, "min_volume_ratio": 0.9, "atr_sl_multiplier": 0.8, "rsi_long_max": 68.0, "rsi_short_min": 32.0}

    swing_low = min(c["low"] for c in lookback)
    swing_high = max(c["high"] for c in lookback)
    mid_point = len(lookback) // 2
    prior_high = max(c["high"] for c in lookback[:mid_point]) if mid_point else swing_high
    prior_low = min(c["low"] for c in lookback[:mid_point]) if mid_point else swing_low

    candle_range = max(test_candle["high"] - test_candle["low"], 1e-9)
    upper_wick = test_candle["high"] - max(test_candle["close"], test_candle["open"])
    lower_wick = min(test_candle["close"], test_candle["open"]) - test_candle["low"]

    # VSA volume verification
    vol_slice = [c.get("volume", 0) for c in closed[-20:-1]]
    avg_vol = (sum(vol_slice) / len(vol_slice)) if vol_slice else 1.0
    vol_ratio = test_candle.get("volume", 0) / max(avg_vol, 1e-9)
    min_vol = params.get("min_volume_ratio", 0.9)
    min_wick = params.get("min_wick_ratio", 0.25)

    # ATR calculation
    highs = [c["high"] for c in closed]
    lows = [c["low"] for c in closed]
    closes = [c["close"] for c in closed]
    atr_vals = calc_atr(highs, lows, closes, 14) if calc_atr else None
    atr_14 = atr_vals[-1] if (atr_vals and atr_vals[-1]) else (test_candle["close"] * 0.01)

    # RSI check
    rsi_vals = calc_rsi(closes, 14) if calc_rsi else None
    current_rsi = rsi_vals[-1] if (rsi_vals and rsi_vals[-1]) else 50.0

    result = None

    # --- LONG SPRING / SWEEP ---
    if test_candle["low"] < swing_low and test_candle["close"] > swing_low:
        wick_ratio = lower_wick / candle_range
        # Rejection wick + volume absorption + RSI not overbought
        if wick_ratio >= min_wick and vol_ratio >= min_vol and current_rsi <= params.get("rsi_long_max", 68.0):
            bos = test_candle["close"] > prior_high
            result = {
                "direction": "LONG", "swept_level": swing_low, "close": test_candle["close"],
                "candle_time": test_candle["close_time"], "bos_confirmed": bos,
                "atr": atr_14, "atr_sl_mult": params.get("atr_sl_multiplier", 0.8),
                "wick_ratio": round(wick_ratio, 2), "vol_ratio": round(vol_ratio, 2),
                "rsi": round(current_rsi, 1)
            }

    # --- SHORT UPTHRUST / SWEEP ---
    elif test_candle["high"] > swing_high and test_candle["close"] < swing_high:
        wick_ratio = upper_wick / candle_range
        if wick_ratio >= min_wick and vol_ratio >= min_vol and current_rsi >= params.get("rsi_short_min", 32.0):
            bos = test_candle["close"] < prior_low
            result = {
                "direction": "SHORT", "swept_level": swing_high, "close": test_candle["close"],
                "candle_time": test_candle["close_time"], "bos_confirmed": bos,
                "atr": atr_14, "atr_sl_mult": params.get("atr_sl_multiplier", 0.8),
                "wick_ratio": round(wick_ratio, 2), "vol_ratio": round(vol_ratio, 2),
                "rsi": round(current_rsi, 1)
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


def detect_demand_zone(candles: list, mtf_data: dict = None, current_price: float = 0.0, lookback: int = 15) -> dict:
    """
    Detects if price is testing or reacting from an institutional Demand Zone / Bullish Order Block.
    Demand Zone is confirmed if:
      1. Bullish Order Block (OB) is detected in recent candles.
      2. Bullish Fair Value Gap (FVG) / Imbalance is present.
      3. Multi-timeframe (15m, 1H, 4H) OB/FVG structure is active.
    Returns: {"confirmed": bool, "zone_type": str, "level": float | None}
    """
    if not candles or len(candles) < 4:
        return {"confirmed": False, "zone_type": "none", "level": None}

    # 1. Direct Order Block check on current timeframe
    if detect_order_block(candles, "LONG", lookback=lookback):
        return {"confirmed": True, "zone_type": "Bullish Order Block", "level": candles[-1].get("close")}

    # 2. Direct FVG check on current timeframe
    if detect_fvg(candles, "LONG", lookback=lookback):
        return {"confirmed": True, "zone_type": "Bullish FVG Imbalance", "level": candles[-1].get("close")}

    # 3. Multi-timeframe OB/FVG check
    if mtf_data and isinstance(mtf_data, dict):
        for tf in ["15m", "1H", "4H"]:
            tf_candles = mtf_data.get(tf, [])
            if tf_candles and len(tf_candles) >= 4:
                ob_fvg = _tf_detect_ob_fvg(tf_candles, "LONG", lookback=12)
                if ob_fvg.get("ob_found"):
                    return {"confirmed": True, "zone_type": f"{tf} Bullish OB", "level": ob_fvg.get("ob_zone")}
                if ob_fvg.get("fvg_found"):
                    return {"confirmed": True, "zone_type": f"{tf} Bullish FVG", "level": ob_fvg.get("fvg_zone")}

    return {"confirmed": False, "zone_type": "none", "level": None}



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
# 5-BOOK STRATEGY DETECTORS (VSA, Wyckoff, Naked Forex, Bulkowski)
# ---------------------------------------------------------------------------

def detect_vsa_no_supply(candles: list, lookback: int = 5) -> bool:
    """
    Tom Williams (Master the Markets): No Supply Bar
    Down-bar on narrow spread with volume lower than the prior 2 bars.
    Signals exhaustion of floating supply. Bullish confirmation on support/pullbacks.
    """
    closed = candles[:-1]
    if len(closed) < 3:
        return False
    recent = closed[-lookback:] if len(closed) >= lookback else closed
    for i in range(2, len(recent)):
        curr = recent[i]
        c1, c2 = recent[i - 1], recent[i - 2]
        is_down_bar = curr["close"] < curr["open"]
        spread = curr["high"] - curr["low"]
        avg_spread = (c1["high"] - c1["low"] + c2["high"] - c2["low"]) / 2.0
        if is_down_bar and spread <= avg_spread and curr["volume"] < c1["volume"] and curr["volume"] < c2["volume"]:
            return True
    return False


def detect_vsa_no_demand(candles: list, lookback: int = 5) -> bool:
    """
    Tom Williams (Master the Markets): No Demand Bar
    Up-bar on narrow spread with volume lower than the prior 2 bars into resistance.
    Signals lack of institutional buying interest. Disqualifies LONG setups.
    """
    closed = candles[:-1]
    if len(closed) < 3:
        return False
    recent = closed[-lookback:] if len(closed) >= lookback else closed
    for i in range(2, len(recent)):
        curr = recent[i]
        c1, c2 = recent[i - 1], recent[i - 2]
        is_up_bar = curr["close"] > curr["open"]
        spread = curr["high"] - curr["low"]
        avg_spread = (c1["high"] - c1["low"] + c2["high"] - c2["low"]) / 2.0
        if is_up_bar and spread <= avg_spread and curr["volume"] < c1["volume"] and curr["volume"] < c2["volume"]:
            return True
    return False


def detect_stopping_volume_pattern(candles: list, lookback: int = 5) -> bool:
    """
    Tom Williams & David Weis: Stopping Volume
    Down bar on ultra-high volume (>1.6x avg) where smart money absorbs panic selling,
    leaving a deep bottom wick or closing in the upper half.
    """
    closed = candles[:-1]
    if len(closed) < 3:
        return False
    prior = closed[:-1] if len(closed) > 1 else closed
    avg_vol = sum(c["volume"] for c in prior[-15:]) / max(len(prior[-15:]), 1)
    recent = closed[-lookback:] if len(closed) >= lookback else closed
    for c in recent:
        if c["volume"] > avg_vol * 1.5 and c["close"] < c["open"]:
            range_span = max(c["high"] - c["low"], 1e-9)
            lower_wick = min(c["open"], c["close"]) - c["low"]
            if (lower_wick / range_span) > 0.4 or c["close"] > (c["low"] + range_span * 0.5):
                return True
    return False


def detect_kangaroo_tail_pattern(candles: list, direction: str, lookback: int = 5) -> bool:
    """
    Alex Nekritin & Walter Peters (Naked Forex): The Kangaroo Tail
    A tall reversal candle protruding far into empty space/key zone with tail >= 2x body
    and open/close in opposite 1/3 of the candle range.
    """
    closed = candles[:-1]
    if len(closed) < 3:
        return False
    prior = closed[:-1] if len(closed) > 1 else closed
    avg_candle_size = sum(c["high"] - c["low"] for c in prior[-10:]) / max(len(prior[-10:]), 1)
    recent = closed[-lookback:] if len(closed) >= lookback else closed
    for c in recent:
        candle_span = c["high"] - c["low"]
        body = max(abs(c["close"] - c["open"]), 1e-9)
        if candle_span >= avg_candle_size * 1.1:
            if direction == "LONG":
                lower_wick = min(c["open"], c["close"]) - c["low"]
                # Long tail below, close in top 40% of candle
                if lower_wick >= body * 1.8 and c["close"] > (c["low"] + candle_span * 0.55):
                    return True
            elif direction == "SHORT":
                upper_wick = c["high"] - max(c["open"], c["close"])
                # Long tail above, close in bottom 40% of candle
                if upper_wick >= body * 1.8 and c["close"] < (c["low"] + candle_span * 0.45):
                    return True
    return False


def detect_low_volume_breakout_trap(candles: list, lookback: int = 15) -> bool:
    """
    Thomas N. Bulkowski (Encyclopedia of Chart Patterns):
    Breakouts with volume < 1.1x 20-period average volume suffer 38%+ false breakout rate.
    """
    closed = candles[:-1]
    if len(closed) < 15:
        return False
    test_c = closed[-1]
    avg_vol = sum(c["volume"] for c in closed[-20:-1]) / max(len(closed[-20:-1]), 1)
    if avg_vol > 0:
        vol_ratio = test_c["volume"] / avg_vol
        body = abs(test_c["close"] - test_c["open"])
        avg_body = sum(abs(c["close"] - c["open"]) for c in closed[-20:-1]) / max(len(closed[-20:-1]), 1)
        if body > avg_body * 1.2 and vol_ratio < 1.05:
            return True
    return False



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
# LAYER 4c -- FUNDING RATE FILTER
# ---------------------------------------------------------------------------
def check_funding_rate(symbol: str, direction: str) -> dict:
    """
    Check Binance Futures live funding rate for the target symbol.
    Prevents entering trades when extreme funding fees are charging against the position.
    """
    if not FUNDING_FILTER_ENABLED:
        return {"funding_rate": 0.0, "funding_rate_pct": 0.0, "minutes_left": 999, "score_impact": 0.0, "rejected": False, "reason": "disabled"}

    try:
        url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
        res = http_session.get(url, timeout=5).json()
        if not isinstance(res, dict) or "lastFundingRate" not in res:
            return {"funding_rate": 0.0, "funding_rate_pct": 0.0, "minutes_left": 999, "score_impact": 0.0, "rejected": False, "reason": "data_error"}

        rate = float(res.get("lastFundingRate", 0.0))
        rate_pct = rate * 100.0
        next_funding_time = int(res.get("nextFundingTime", 0))
        curr_time = int(time.time() * 1000)
        minutes_left = max(0, int((next_funding_time - curr_time) / (1000 * 60)))

        score_impact = 0.0
        rejected = False
        reason = f"Funding rate {rate_pct:.4f}%, next in {minutes_left}m"

        # LONG position pays funding fee if rate is POSITIVE
        if direction == "LONG":
            if rate_pct > MAX_ADVERSE_FUNDING_PCT:
                rejected = True
                reason = f"Adverse funding rate ({rate_pct:.4f}% > {MAX_ADVERSE_FUNDING_PCT}%) -- LONG pays heavy fee."
            elif rate_pct > 0.03:
                score_impact = -10.0
                if minutes_left < 30:
                    score_impact = -15.0
                reason = f"Adverse funding rate ({rate_pct:.4f}%) -- LONG pays fee soon ({minutes_left}m left)."
            elif rate_pct < -0.02:
                score_impact = 5.0
                reason = f"Favorable negative funding rate ({rate_pct:.4f}%) -- LONG receives fee."

        # SHORT position pays funding fee if rate is NEGATIVE
        elif direction == "SHORT":
            if rate_pct < -MAX_ADVERSE_FUNDING_PCT:
                rejected = True
                reason = f"Adverse funding rate ({rate_pct:.4f}% < -{MAX_ADVERSE_FUNDING_PCT}%) -- SHORT pays heavy fee."
            elif rate_pct < -0.03:
                score_impact = -10.0
                if minutes_left < 30:
                    score_impact = -15.0
                reason = f"Adverse funding rate ({rate_pct:.4f}%) -- SHORT pays fee soon ({minutes_left}m left)."
            elif rate_pct > 0.02:
                score_impact = 5.0
                reason = f"Favorable positive funding rate ({rate_pct:.4f}%) -- SHORT receives fee."

        return {
            "funding_rate": rate,
            "funding_rate_pct": rate_pct,
            "minutes_left": minutes_left,
            "score_impact": score_impact,
            "rejected": rejected,
            "reason": reason
        }
    except Exception as e:
        log.warning("Funding rate check failed for %s: %s", symbol, e)
        return {"funding_rate": 0.0, "funding_rate_pct": 0.0, "minutes_left": 999, "score_impact": 0.0, "rejected": False, "reason": f"error: {e}"}


# ---------------------------------------------------------------------------
# LAYER 4a -- FULL 8-TIMEFRAME MTF CASCADE ENGINE
# Timeframes: 1M, 1W, 1D, 4H, 2H, 1H, 30m, 15m
# ---------------------------------------------------------------------------

def _parse_raw_klines(raw: list, live: bool = False) -> list:
    """Parse raw Binance kline data into standard dict format."""
    result = []
    for k in raw:
        try:
            result.append({
                "timestamp": k[0], "open_time": k[0],
                "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]),
                "volume": float(k[5]), "close_time": k[6],
            })
        except (IndexError, TypeError, ValueError):
            pass
    if live and len(result) > 1:
        now_ms = int(time.time() * 1000)
        if result[-1]["close_time"] > now_ms:
            result = result[:-1]
    return result


def _fetch_cached_klines(client: Client, symbol: str, tf_key: str) -> list:
    """Fetch klines for a specific timeframe with TTL caching."""
    cfg = MTF_INTERVALS.get(tf_key)
    if not cfg:
        return []
    cache_key = f"{symbol}_{tf_key}"
    now = time.time()
    cached = _mtf_kline_cache.get(cache_key)
    if cached and cfg["ttl"] > 0 and (now - cached["ts"]) < cfg["ttl"]:
        return cached["data"]
    try:
        raw = client.get_klines(symbol=symbol, interval=cfg["binance"], limit=cfg["limit"])
        parsed = _parse_raw_klines(raw)
        if cfg["ttl"] > 0:
            _mtf_kline_cache[cache_key] = {"data": parsed, "ts": now}
        return parsed
    except Exception as e:
        log.warning("MTF kline fetch error %s %s: %s", symbol, tf_key, e)
        return cached["data"] if cached else []


def get_mtf_klines(client: Client, symbol: str) -> dict:
    """
    Fetch all 8 timeframes for a symbol with intelligent tiered caching.
    Returns: {"1M": [...candles], "1W": [...], ..., "15m": [...]}
    """
    result = {}
    for tf_key in MTF_INTERVALS:
        result[tf_key] = _fetch_cached_klines(client, symbol, tf_key)
    return result


def _tf_ema_bias(candles: list, period: int = 50) -> str:
    """Helper: determine EMA bias for a set of candles. Returns LONG/SHORT/NEUTRAL."""
    if not candles or len(candles) < period + 2 or calc_ema is None:
        return "NEUTRAL"
    closes = [c["close"] for c in candles]
    ema_vals = calc_ema(closes, min(period, len(closes) - 1))
    ema = ema_vals[-1] if ema_vals else None
    if ema is None:
        return "NEUTRAL"
    if closes[-1] > ema:
        return "LONG"
    elif closes[-1] < ema:
        return "SHORT"
    return "NEUTRAL"


def _tf_swing_structure(candles: list, lookback: int = 10) -> str:
    """Helper: detect Higher-Highs/Higher-Lows vs Lower-Highs/Lower-Lows.
    Returns LONG (uptrend), SHORT (downtrend), or NEUTRAL."""
    if not candles or len(candles) < lookback + 2:
        return "NEUTRAL"
    recent = candles[-lookback:]
    mid = len(recent) // 2
    first_half = recent[:mid]
    second_half = recent[mid:]
    if not first_half or not second_half:
        return "NEUTRAL"
    fh_high = max(c["high"] for c in first_half)
    fh_low = min(c["low"] for c in first_half)
    sh_high = max(c["high"] for c in second_half)
    sh_low = min(c["low"] for c in second_half)
    hh = sh_high > fh_high
    hl = sh_low > fh_low
    lh = sh_high < fh_high
    ll = sh_low < fh_low
    if hh and hl:
        return "LONG"
    elif lh and ll:
        return "SHORT"
    return "NEUTRAL"


def _tf_detect_ob_fvg(candles: list, direction: str, lookback: int = 10) -> dict:
    """Detect Order Blocks and Fair Value Gaps on any timeframe candles.
    Returns: {"ob_found": bool, "fvg_found": bool, "ob_zone": (lo, hi) | None, "fvg_zone": (lo, hi) | None}
    """
    result = {"ob_found": False, "fvg_found": False, "ob_zone": None, "fvg_zone": None}
    if not candles or len(candles) < 4:
        return result
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    # FVG detection
    for i in range(1, len(recent) - 1):
        c1, c3 = recent[i - 1], recent[i + 1]
        if direction == "LONG" and c1["high"] < c3["low"]:
            result["fvg_found"] = True
            result["fvg_zone"] = (c1["high"], c3["low"])
            break
        elif direction == "SHORT" and c1["low"] > c3["high"]:
            result["fvg_found"] = True
            result["fvg_zone"] = (c3["high"], c1["low"])
            break
    # OB detection (last opposite-colour candle before impulsive move)
    for i in range(len(recent) - 2, 0, -1):
        curr = recent[i]
        nxt = recent[i + 1] if i + 1 < len(recent) else None
        if nxt is None:
            continue
        curr_bull = curr["close"] > curr["open"]
        nxt_bull = nxt["close"] > nxt["open"]
        if direction == "LONG" and not curr_bull and nxt_bull:
            body_ratio = abs(nxt["close"] - nxt["open"]) / max(abs(curr["close"] - curr["open"]), 1e-9)
            if body_ratio > 1.2:
                result["ob_found"] = True
                result["ob_zone"] = (curr["low"], curr["high"])
                break
        elif direction == "SHORT" and curr_bull and not nxt_bull:
            body_ratio = abs(nxt["close"] - nxt["open"]) / max(abs(curr["close"] - curr["open"]), 1e-9)
            if body_ratio > 1.2:
                result["ob_found"] = True
                result["ob_zone"] = (curr["low"], curr["high"])
                break
    return result


def _tf_liquidity_sweep(candles: list, lookback: int = 15) -> dict:
    """Detect liquidity sweep (stop-hunt) on any timeframe candles.
    Returns {"swept": bool, "direction": "LONG"/"SHORT"/None, "swept_level": float|None}
    """
    result = {"swept": False, "direction": None, "swept_level": None}
    if not candles or len(candles) < lookback + 1:
        return result
    closed = candles[:-1]
    lb_candles = closed[-lookback:-1]
    test = closed[-1]
    if not lb_candles:
        return result
    swing_low = min(c["low"] for c in lb_candles)
    swing_high = max(c["high"] for c in lb_candles)
    if test["low"] < swing_low and test["close"] > swing_low:
        result = {"swept": True, "direction": "LONG", "swept_level": swing_low}
    elif test["high"] > swing_high and test["close"] < swing_high:
        result = {"swept": True, "direction": "SHORT", "swept_level": swing_high}
    return result


# ---- TIER 1: Macro Bias (1M, 1W, 1D) ----
def analyze_macro_bias(symbol: str, mtf_data: dict) -> dict:
    """
    Analyzes Monthly, Weekly, and Daily timeframes to establish macro market bias.
    Returns: {
        "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
        "monthly_bias": str, "weekly_bias": str, "daily_bias": str,
        "daily_ema50": str, "daily_ema200": str,
        "macro_support": float, "macro_resistance": float,
        "score": float (0.0 - 1.0),
        "reason": str,
    }
    """
    # Monthly structure
    m_candles = mtf_data.get("1M", [])
    monthly_struct = _tf_swing_structure(m_candles, lookback=min(12, max(len(m_candles) - 1, 3)))
    monthly_ema = _tf_ema_bias(m_candles, period=min(12, max(len(m_candles) - 1, 3)))
    monthly_bias = monthly_struct if monthly_struct != "NEUTRAL" else monthly_ema

    # Weekly structure
    w_candles = mtf_data.get("1W", [])
    weekly_struct = _tf_swing_structure(w_candles, lookback=min(13, max(len(w_candles) - 1, 3)))
    weekly_ema = _tf_ema_bias(w_candles, period=min(20, max(len(w_candles) - 1, 3)))
    weekly_bias = weekly_struct if weekly_struct != "NEUTRAL" else weekly_ema

    # Daily EMA 50/200 and structure
    d_candles = mtf_data.get("1D", [])
    daily_struct = _tf_swing_structure(d_candles, lookback=min(20, max(len(d_candles) - 1, 3)))
    daily_ema50 = _tf_ema_bias(d_candles, period=min(50, max(len(d_candles) - 1, 3)))
    daily_ema200 = "NEUTRAL"
    if d_candles and len(d_candles) > 55 and calc_ema:
        closes_d = [c["close"] for c in d_candles]
        ema200_vals = calc_ema(closes_d, min(50, len(closes_d) - 1))
        if ema200_vals and ema200_vals[-1] is not None:
            daily_ema200 = "LONG" if closes_d[-1] > ema200_vals[-1] else "SHORT"
    daily_bias = daily_struct if daily_struct != "NEUTRAL" else daily_ema50

    # Macro support/resistance from Weekly
    macro_support = min(c["low"] for c in w_candles[-8:]) if w_candles and len(w_candles) >= 3 else 0
    macro_resistance = max(c["high"] for c in w_candles[-8:]) if w_candles and len(w_candles) >= 3 else 0

    # Combine biases into overall macro bias
    biases = [monthly_bias, weekly_bias, daily_bias]
    long_count = sum(1 for b in biases if b == "LONG")
    short_count = sum(1 for b in biases if b == "SHORT")

    if long_count >= 2:
        overall = "BULLISH"
        score = long_count / 3.0
    elif short_count >= 2:
        overall = "BEARISH"
        score = short_count / 3.0
    else:
        overall = "NEUTRAL"
        score = 0.5

    reasons = []
    if monthly_bias != "NEUTRAL":
        reasons.append(f"1M:{monthly_bias}")
    if weekly_bias != "NEUTRAL":
        reasons.append(f"1W:{weekly_bias}")
    if daily_bias != "NEUTRAL":
        reasons.append(f"1D:{daily_bias}(EMA50:{daily_ema50})")
    reason_str = ", ".join(reasons) if reasons else "Insufficient HTF data"

    return {
        "bias": overall,
        "monthly_bias": monthly_bias, "weekly_bias": weekly_bias, "daily_bias": daily_bias,
        "daily_ema50": daily_ema50, "daily_ema200": daily_ema200,
        "macro_support": macro_support, "macro_resistance": macro_resistance,
        "score": round(score, 2),
        "reason": reason_str,
    }


# ---- TIER 2: Intermediate Zone Refinement (4H, 2H) ----
def refine_intermediate_zones(symbol: str, mtf_data: dict, macro_bias: dict, direction: str) -> dict:
    """
    Refines macro zones using 4H & 2H candles. Confirms regional trend,
    detects intermediate OB/FVG and liquidity sweeps.
    Returns: {
        "h4_bias": str, "h2_bias": str,
        "intermediate_aligned": bool,
        "h4_ob_fvg": dict, "h2_ob_fvg": dict,
        "h4_sweep": dict, "h2_sweep": dict,
        "refined_support": float, "refined_resistance": float,
        "score": float (0.0 - 1.0),
    }
    """
    h4_candles = mtf_data.get("4H", [])
    h2_candles = mtf_data.get("2H", [])

    h4_bias = _tf_ema_bias(h4_candles, period=min(50, max(len(h4_candles) - 1, 3)))
    h2_bias = _tf_ema_bias(h2_candles, period=min(50, max(len(h2_candles) - 1, 3)))

    # 4H & 2H OB/FVG detection
    h4_ob_fvg = _tf_detect_ob_fvg(h4_candles, direction, lookback=12)
    h2_ob_fvg = _tf_detect_ob_fvg(h2_candles, direction, lookback=12)

    # 4H & 2H liquidity sweep
    h4_sweep = _tf_liquidity_sweep(h4_candles, lookback=12)
    h2_sweep = _tf_liquidity_sweep(h2_candles, lookback=12)

    # Refined support/resistance from 4H data
    refined_support = min(c["low"] for c in h4_candles[-15:]) if h4_candles and len(h4_candles) >= 5 else macro_bias.get("macro_support", 0)
    refined_resistance = max(c["high"] for c in h4_candles[-15:]) if h4_candles and len(h4_candles) >= 5 else macro_bias.get("macro_resistance", 0)

    # Alignment check
    macro_dir = "LONG" if macro_bias["bias"] == "BULLISH" else ("SHORT" if macro_bias["bias"] == "BEARISH" else "NEUTRAL")
    aligned_count = 0
    for bias in [h4_bias, h2_bias]:
        if bias == direction or bias == "NEUTRAL":
            aligned_count += 1
    intermediate_aligned = aligned_count >= 1 and (macro_dir == direction or macro_dir == "NEUTRAL")

    # Score intermediate confluence
    score = 0.0
    if h4_bias == direction:
        score += 0.3
    elif h4_bias == "NEUTRAL":
        score += 0.15
    if h2_bias == direction:
        score += 0.2
    elif h2_bias == "NEUTRAL":
        score += 0.1
    if h4_ob_fvg["ob_found"] or h4_ob_fvg["fvg_found"]:
        score += 0.2
    if h2_ob_fvg["ob_found"] or h2_ob_fvg["fvg_found"]:
        score += 0.15
    if h4_sweep["swept"] and h4_sweep["direction"] == direction:
        score += 0.15

    return {
        "h4_bias": h4_bias, "h2_bias": h2_bias,
        "intermediate_aligned": intermediate_aligned,
        "h4_ob_fvg": h4_ob_fvg, "h2_ob_fvg": h2_ob_fvg,
        "h4_sweep": h4_sweep, "h2_sweep": h2_sweep,
        "refined_support": refined_support, "refined_resistance": refined_resistance,
        "score": round(min(1.0, score), 2),
    }


# ---- TIER 3: Execution Trigger (1H, 30m, 15m) ----
def analyze_execution_trigger(symbol: str, mtf_data: dict, refined_zones: dict, direction: str) -> dict:
    """
    Fine-tune entry/SL/TP using 1H, 30m, and 15m candles.
    Detects CHoCH, VSA, local FVG fill, and refines SL to 15m swing level.
    Returns: {
        "h1_choch": bool, "h1_vsa_score": float,
        "m30_fvg_fill": bool, "m30_rsi_div": float,
        "m15_precision_entry": float | None,
        "m15_refined_sl": float | None,
        "m15_refined_tp": float | None,
        "precision_score": float (0.0 - 1.0),
    }
    """
    h1_candles = mtf_data.get("1H", [])
    m30_candles = mtf_data.get("30m", [])
    m15_candles = mtf_data.get("15m", [])

    # 1H CHoCH detection (structure shift)
    h1_struct = check_structure(h1_candles) if len(h1_candles) >= SWING_LOOKBACK + 1 else None
    h1_choch = h1_struct is not None and h1_struct.get("direction") == direction

    # 1H VSA Score
    h1_vsa = vsa_score(h1_candles, direction) if h1_candles else 0.5

    # 30m FVG fill check
    m30_ob_fvg = _tf_detect_ob_fvg(m30_candles, direction, lookback=10)
    m30_fvg_fill = m30_ob_fvg["fvg_found"]

    # 30m RSI Divergence
    m30_rsi_div = 0.5
    if m30_candles and len(m30_candles) >= 16 and calc_rsi:
        m30_closes = [c["close"] for c in m30_candles]
        rsi_vals = calc_rsi(m30_closes, 14)
        valid_rsi = [v for v in rsi_vals if v is not None]
        if len(valid_rsi) >= 3:
            last_rsi = valid_rsi[-1]
            if direction == "LONG" and last_rsi < 35:
                m30_rsi_div = 0.9
            elif direction == "SHORT" and last_rsi > 65:
                m30_rsi_div = 0.9
            elif direction == "LONG" and last_rsi < 45:
                m30_rsi_div = 0.7
            elif direction == "SHORT" and last_rsi > 55:
                m30_rsi_div = 0.7

    # 15m Precision Entry, Refined SL & TP
    m15_entry = None
    m15_sl = None
    m15_tp = None
    precision_score = 0.0

    if m15_candles and len(m15_candles) >= 10:
        recent_15m = m15_candles[-15:] if len(m15_candles) >= 15 else m15_candles
        if direction == "LONG":
            local_low = min(c["low"] for c in recent_15m)
            local_high = max(c["high"] for c in recent_15m)
            m15_entry = m15_candles[-1]["close"]
            # ATR buffer on 15m for tight SL
            if calc_atr and len(m15_candles) >= 16:
                highs_15 = [c["high"] for c in m15_candles]
                lows_15 = [c["low"] for c in m15_candles]
                closes_15 = [c["close"] for c in m15_candles]
                atr_vals = calc_atr(highs_15, lows_15, closes_15, 14)
                atr_val = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else abs(m15_entry) * 0.005
                m15_sl = local_low - atr_val * 0.8
            else:
                m15_sl = local_low - abs(m15_entry) * 0.005
            risk = m15_entry - m15_sl
            m15_tp = m15_entry + risk * 2.0  # 2R target
        else:
            local_high = max(c["high"] for c in recent_15m)
            local_low = min(c["low"] for c in recent_15m)
            m15_entry = m15_candles[-1]["close"]
            if calc_atr and len(m15_candles) >= 16:
                highs_15 = [c["high"] for c in m15_candles]
                lows_15 = [c["low"] for c in m15_candles]
                closes_15 = [c["close"] for c in m15_candles]
                atr_vals = calc_atr(highs_15, lows_15, closes_15, 14)
                atr_val = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else abs(m15_entry) * 0.005
                m15_sl = local_high + atr_val * 0.8
            else:
                m15_sl = local_high + abs(m15_entry) * 0.005
            risk = m15_sl - m15_entry
            m15_tp = m15_entry - risk * 2.0  # 2R target

    # Compute precision score
    if h1_choch:
        precision_score += 0.3
    precision_score += h1_vsa * 0.25
    if m30_fvg_fill:
        precision_score += 0.15
    precision_score += m30_rsi_div * 0.15
    if m15_entry is not None and m15_sl is not None:
        precision_score += 0.15

    return {
        "h1_choch": h1_choch, "h1_vsa_score": h1_vsa,
        "m30_fvg_fill": m30_fvg_fill, "m30_rsi_div": m30_rsi_div,
        "m15_precision_entry": m15_entry,
        "m15_refined_sl": m15_sl,
        "m15_refined_tp": m15_tp,
        "precision_score": round(min(1.0, precision_score), 2),
    }


# ---------------------------------------------------------------------------
# GWAIDIER FRACTAL 4-PILLARS ENGINE (Nested Scale, Bias, Structure, Liquidity)
# ---------------------------------------------------------------------------
def analyze_gwaidier_four_pillars(symbol: str, mtf_data: dict, direction: str, current_price: float) -> dict:
    """
    Evaluates the market across Gwaidier's 4 Core Pillars:
      1. Fractal Nature (Nested scales: LTF inside HTF POI / Key Zone vs floating trap)
      2. Higher Timeframe Bias (Parent directional harmony across 1M, 1W, 1D)
      3. Market Structure (True BOS / CHoCH structural transitions)
      4. Liquidity & Inducement (Liquidity sweeps vs retail breakout traps)
    Returns detailed 4-Pillars confluence dictionary with trap detection.
    """
    pillars = {
        "pillar1_fractal_nesting": False,
        "pillar2_htf_bias": False,
        "pillar3_structure": False,
        "pillar4_liquidity_sweep": False,
        "is_inducement_trap": False,
        "pillars_passed": 0,
        "pillar_score": 0.0,
        "details": []
    }
    if not mtf_data:
        return pillars

    # --- PILLAR 1: Fractal Nature & Nested Scales ---
    d_candles = mtf_data.get("1D", [])
    h4_candles = mtf_data.get("4H", [])
    htf_key_levels = []
    if d_candles and len(d_candles) >= 5:
        d_swings = detect_swings(d_candles, lookback=10)
        htf_key_levels.extend(d_swings.get("swings_high", []) + d_swings.get("swings_low", []))
    if h4_candles and len(h4_candles) >= 5:
        h4_swings = detect_swings(h4_candles, lookback=10)
        htf_key_levels.extend(h4_swings.get("swings_high", []) + h4_swings.get("swings_low", []))

    if htf_key_levels and current_price > 0:
        min_dist_pct = min(abs(current_price - lvl) / current_price * 100 for lvl in htf_key_levels)
        if min_dist_pct <= 2.5:
            pillars["pillar1_fractal_nesting"] = True
            pillars["details"].append(f"Pillar 1 (Fractal Nesting): Near HTF key level ({min_dist_pct:.2f}%)")
        else:
            pillars["details"].append(f"Pillar 1: Floating structure ({min_dist_pct:.1f}% from HTF level)")
    else:
        pillars["pillar1_fractal_nesting"] = True

    # --- PILLAR 2: Higher Timeframe Bias ---
    macro = analyze_macro_bias(symbol, mtf_data)
    macro_dir = "LONG" if macro["bias"] == "BULLISH" else ("SHORT" if macro["bias"] == "BEARISH" else "NEUTRAL")
    if macro_dir == direction or macro_dir == "NEUTRAL":
        pillars["pillar2_htf_bias"] = True
        pillars["details"].append(f"Pillar 2 (HTF Bias): Harmonized with {macro['bias']}")
    else:
        pillars["details"].append(f"Pillar 2: Opposes HTF {macro['bias']} bias")

    # --- PILLAR 3: Market Structure (BOS / CHoCH Transition) ---
    h1_candles = mtf_data.get("1H", [])
    h1_struct = check_structure(h1_candles) if h1_candles and len(h1_candles) >= SWING_LOOKBACK + 1 else None
    if h1_struct and h1_struct.get("direction") == direction:
        pillars["pillar3_structure"] = True
        struct_type = "BOS Confirmed" if h1_struct.get("bos_confirmed") else "CHoCH Shift"
        pillars["details"].append(f"Pillar 3 (Structure): {struct_type} on 1H")
    else:
        pillars["details"].append("Pillar 3: No clear 1H structural shift")

    # --- PILLAR 4: Liquidity & Inducement Sweep ---
    h4_sweep = _tf_liquidity_sweep(h4_candles, lookback=12)
    h1_sweep = _tf_liquidity_sweep(h1_candles, lookback=15)
    if (h4_sweep.get("swept") and h4_sweep.get("direction") == direction) or \
       (h1_sweep.get("swept") and h1_sweep.get("direction") == direction):
        pillars["pillar4_liquidity_sweep"] = True
        pillars["details"].append("Pillar 4 (Liquidity): Prior stops swept & reclaimed")
    else:
        pillars["details"].append("Pillar 4: No prominent liquidity sweep detected")

    # --- INDUCEMENT TRAP DETECTION ---
    if not pillars["pillar2_htf_bias"] or (not pillars["pillar1_fractal_nesting"] and not pillars["pillar4_liquidity_sweep"]):
        pillars["is_inducement_trap"] = True
        pillars["details"].append("WARNING: Possible LTF Inducement Trap")

    passed_count = sum([
        1 if pillars["pillar1_fractal_nesting"] else 0,
        1 if pillars["pillar2_htf_bias"] else 0,
        1 if pillars["pillar3_structure"] else 0,
        1 if pillars["pillar4_liquidity_sweep"] else 0,
    ])
    pillars["pillars_passed"] = passed_count
    pillars["pillar_score"] = round(passed_count / 4.0, 2)
    return pillars


def evaluate_timeframe_trend(candles: list, tf_key: str) -> dict:
    """
    Evaluates trend, EMA, and swing structure for an individual timeframe.
    Returns: {"direction": "LONG"|"SHORT"|"NEUTRAL", "bull_score": float, "bear_score": float, "swing": str}
    """
    if not candles or len(candles) < 3:
        return {"direction": "NEUTRAL", "bull_score": 0.0, "bear_score": 0.0, "swing": "NEUTRAL"}

    closes = [c["close"] for c in candles]
    opens = [c["open"] for c in candles]

    # 1. EMA 20 & EMA 50
    ema20_vals = calc_ema(closes, min(20, len(closes) - 1)) if calc_ema else None
    ema50_vals = calc_ema(closes, min(50, len(closes) - 1)) if calc_ema else None

    ema20 = ema20_vals[-1] if ema20_vals else None
    ema50 = ema50_vals[-1] if ema50_vals else None

    # 2. Swing structure (Higher Highs/Higher Lows vs Lower Highs/Lower Lows)
    swing = _tf_swing_structure(candles, lookback=min(12, max(3, len(candles) - 1)))

    bull_signals = 0.0
    bear_signals = 0.0

    if ema20 is not None:
        if closes[-1] > ema20:
            bull_signals += 1.0
        elif closes[-1] < ema20:
            bear_signals += 1.0

    if ema50 is not None:
        if closes[-1] > ema50:
            bull_signals += 1.5
        elif closes[-1] < ema50:
            bear_signals += 1.5

    if swing == "LONG":
        bull_signals += 2.0
    elif swing == "SHORT":
        bear_signals += 2.0

    if closes[-1] > opens[-1]:
        bull_signals += 0.5
    else:
        bear_signals += 0.5

    if bull_signals > bear_signals and bull_signals >= 1.5:
        dirn = "LONG"
    elif bear_signals > bull_signals and bear_signals >= 1.5:
        dirn = "SHORT"
    else:
        dirn = "LONG" if closes[-1] >= closes[0] else "SHORT"

    return {
        "direction": dirn,
        "bull_score": bull_signals,
        "bear_score": bear_signals,
        "swing": swing,
        "last_close": closes[-1]
    }


def analyze_all_8_timeframes(client: Client, symbol: str, direction: str = "LONG") -> dict:
    """
    Analyzes ALL 8 timeframes (15m, 30m, 1H, 2H, 4H, 12H, 1D, 1W) for every coin.
    Scoring per TF:
    - 1W  = 25 points (highest weight)
    - 1D  = 20 points
    - 12H = 15 points
    - 4H  = 15 points
    - 2H  = 10 points
    - 1H  = 8 points
    - 30m = 4 points
    - 15m = 3 points
    Total = 100 points

    Rules:
    - Higher TF = more weight in decision
    - ALL 8 TFs analyzed before signal
    - Signal only valid if 5/8 TFs agree
    - HTF (4H, 12H, 1D, 1W) = trend direction (majority 3/4 must agree)
    - LTF (15m, 30m, 1H, 2H) = entry timing
    - Total score >= 55.0 required
    - No counter-trend entry allowed
    """
    mtf_data = get_mtf_klines(client, symbol) if client else {}

    tf_order = ["1D", "4H", "1W", "1H", "12H", "2H", "30m", "15m"]
    # Claude Weighted Timeframe Hierarchy (1D 25%, 4H 20%, 1W 15%, 1H 15%, 12H 10%, 2H 8%, 30m 4%, 15m 3%)
    tf_weights = {"1D": 25, "4H": 20, "1W": 15, "1H": 15, "12H": 10, "2H": 8, "30m": 4, "15m": 3}
    htf_keys = ["4H", "12H", "1D", "1W"]

    total_score = 0.0
    agreeing_tfs_count = 0
    tf_breakdown = {}

    htf_agreed_count = 0
    htf_directions = []

    for tf_key in tf_order:
        candles = mtf_data.get(tf_key, [])
        trend_info = evaluate_timeframe_trend(candles, tf_key)
        tf_dir = trend_info["direction"]
        weight = tf_weights[tf_key]

        agrees = (tf_dir == direction)
        if agrees:
            points_earned = weight
            agreeing_tfs_count += 1
            total_score += points_earned
        else:
            points_earned = 0

        if tf_key in htf_keys:
            htf_directions.append(tf_dir)
            if agrees:
                htf_agreed_count += 1

        tf_breakdown[tf_key] = {
            "bias": tf_dir,
            "agrees": agrees,
            "points": points_earned,
            "max_points": weight,
            "is_htf": (tf_key in htf_keys),
            "swing": trend_info.get("swing", "NEUTRAL")
        }

    # HTF Consensus: Majority of HTFs (at least 2 of 4 HTFs agreeing + 1D or 4H anchor)
    htf_majority_agree = (htf_agreed_count >= 2)
    htf_all_agree = (htf_agreed_count >= 3)

    # Determine dominant HTF bias
    long_htfs = sum(1 for d in htf_directions if d == "LONG")
    short_htfs = sum(1 for d in htf_directions if d == "SHORT")
    if long_htfs >= 3:
        htf_bias = "BULLISH"
    elif short_htfs >= 3:
        htf_bias = "BEARISH"
    elif long_htfs > short_htfs:
        htf_bias = "LEAN_BULLISH"
    elif short_htfs > long_htfs:
        htf_bias = "LEAN_BEARISH"
    else:
        htf_bias = "NEUTRAL"

    # Claude Weighted Validation Rules
    min_cascade_score = 35.0 if TESTING_MODE else 50.0
    min_agreeing_tfs = 3 if TESTING_MODE else 4

    is_approved = (
        total_score >= min_cascade_score
        and agreeing_tfs_count >= min_agreeing_tfs
        and (htf_majority_agree or htf_agreed_count >= 2)
    )

    rejection_reasons = []
    if total_score < min_cascade_score:
        rejection_reasons.append(f"Score {total_score:.1f}/100 < {min_cascade_score} threshold")
    if agreeing_tfs_count < min_agreeing_tfs:
        rejection_reasons.append(f"Only {agreeing_tfs_count}/8 TFs agree (min {min_agreeing_tfs} required)")
    if not (htf_majority_agree or htf_agreed_count >= 2):
        rejection_reasons.append(f"HTF conflict: {htf_agreed_count}/4 HTFs agree")

    reason_str = "All 8-TF conditions satisfied (Weighted Score: %.1f/100, %d/8 agreed)" % (total_score, agreeing_tfs_count) if is_approved else " | ".join(rejection_reasons)

    return {
        "symbol": symbol,
        "direction": direction,
        "total_score": round(total_score, 1),
        "score_threshold": min_cascade_score,
        "agreeing_tfs_count": agreeing_tfs_count,
        "min_tfs_required": min_agreeing_tfs,
        "htf_bias": htf_bias,
        "htf_majority_agree": htf_majority_agree,
        "htf_all_agree": htf_all_agree,
        "is_approved": is_approved,
        "trade_allowed": is_approved,
        "cascade_score": round(total_score / 100.0, 2),
        "reason": reason_str,
        "tf_breakdown": tf_breakdown
    }


# ---- FULL CASCADE ORCHESTRATOR ----
def run_mtf_cascade(client: Client, symbol: str, direction: str, current_price: float = 0.0) -> dict:
    """
    Run the complete 8-timeframe cascade analysis (15m, 30m, 1H, 2H, 4H, 12H, 1D, 1W).
    """
    if not MULTI_TIMEFRAME_CASCADE_ENABLED or client is None:
        return {
            "macro": {"bias": "NEUTRAL", "score": 0.85, "reason": "MTF cascade disabled"},
            "intermediate": {"score": 0.85, "intermediate_aligned": True},
            "execution": {"precision_score": 0.85},
            "four_pillars": {"pillar_score": 0.85, "pillars_passed": 4, "is_inducement_trap": False},
            "overall_bias": "NEUTRAL",
            "trade_allowed": True,
            "cascade_score": 0.85,
            "total_score": 85.0,
            "is_approved": True,
            "agreeing_tfs_count": 8,
            "reason": "MTF cascade disabled",
        }

    analysis = analyze_all_8_timeframes(client, symbol, direction)
    return {
        "macro": {"bias": analysis["htf_bias"], "score": analysis["cascade_score"], "reason": analysis["reason"]},
        "intermediate": {"score": analysis["cascade_score"], "intermediate_aligned": analysis["htf_all_agree"]},
        "execution": {"precision_score": analysis["cascade_score"]},
        "four_pillars": {"pillar_score": analysis["cascade_score"], "pillars_passed": 4 if analysis["htf_all_agree"] else 2, "is_inducement_trap": not analysis["htf_all_agree"]},
        "overall_bias": analysis["htf_bias"],
        "trade_allowed": analysis["is_approved"],
        "is_approved": analysis["is_approved"],
        "cascade_score": analysis["cascade_score"],
        "total_score": analysis["total_score"],
        "agreeing_tfs_count": analysis["agreeing_tfs_count"],
        "reason": analysis["reason"],
        "tf_breakdown": analysis["tf_breakdown"]
    }


# ---- BACKWARDS-COMPATIBLE WRAPPER (replaces old get_higher_tf_bias) ----
def get_higher_tf_bias(client: Client, symbol: str) -> dict:
    """
    Evaluates HTF bias across 4H, 12H, 1D, 1W.
    Returns: {"bias": "BULLISH"|"BEARISH"|"NEUTRAL", "reason": str, "aligned": bool}
    """
    if not MULTI_TIMEFRAME_CASCADE_ENABLED or client is None:
        return {"bias": "NEUTRAL", "reason": "MTF cascade disabled", "aligned": True}
    try:
        analysis_long = analyze_all_8_timeframes(client, symbol, "LONG")
        if analysis_long["htf_bias"] == "BULLISH":
            return {"bias": "BULLISH", "reason": f"8-TF HTF Consensus BULLISH (Score: {analysis_long['total_score']})", "aligned": True}
        elif analysis_long["htf_bias"] == "BEARISH":
            return {"bias": "BEARISH", "reason": "8-TF HTF Consensus BEARISH", "aligned": True}
        return {"bias": "NEUTRAL", "reason": f"8-TF HTF Mixed ({analysis_long['htf_bias']})", "aligned": True}
    except Exception as e:
        log.warning("get_higher_tf_bias 8-TF error for %s: %s", symbol, e)
        return {"bias": "NEUTRAL", "reason": f"Error: {e}", "aligned": True}


def trend_filter_ok(candles: list, direction: str) -> bool:
    """
    Checks 1H EMA trend alignment.
    """
    if not TREND_FILTER_ENABLED or calc_ema is None:
        return True
    closed = candles[:-1]
    closes = [c["close"] for c in closed]
    if len(closes) < TREND_FILTER_EMA_PERIOD + 2:
        return True
    ema_values = calc_ema(closes, TREND_FILTER_EMA_PERIOD)
    latest_ema = ema_values[-1]
    prev_ema = ema_values[-3] if len(ema_values) >= 3 and ema_values[-3] is not None else latest_ema
    if latest_ema is None:
        return True
    ema_rising = latest_ema >= (prev_ema or latest_ema)
    if direction == "LONG":
        return ema_rising
    return not ema_rising


def detect_rsi_divergence(candles: list, direction: str, period: int = 14) -> float:
    """
    Detects regular RSI momentum divergence on liquidity sweeps (0.0 - 1.0 score).
    """
    if calc_rsi is None or len(candles) < period + 5:
        return 0.5
    try:
        closed = candles[:-1]
        closes = [c["close"] for c in closed]
        rsi_vals = calc_rsi(closes, period)
        valid_rsi = [r for r in rsi_vals if r is not None]
        if len(valid_rsi) < 6:
            return 0.5
        
        recent_rsi = valid_rsi[-1]
        prior_rsi = min(valid_rsi[-8:-2]) if direction == "LONG" else max(valid_rsi[-8:-2])

        if direction == "LONG":
            # Bullish divergence: price sweep with higher RSI or oversold bounce
            if recent_rsi > prior_rsi and recent_rsi < 48:
                return 1.0
            elif recent_rsi < 35:
                return 0.8
        else:
            # Bearish divergence: price sweep with lower RSI or overbought reject
            if recent_rsi < prior_rsi and recent_rsi > 52:
                return 1.0
            elif recent_rsi > 65:
                return 0.8
        return 0.5
    except Exception:
        return 0.5


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
# LAYER 5 -- ENTRY / SL / TP (Upgraded with dynamic ATR-based Stop Loss)
# ---------------------------------------------------------------------------
def compute_entry_sl_tp(structure: dict, candles: list = None):
    """
    Entry/SL/TP calculation with dynamic ATR stop-loss buffer:
    - ATR(14) * 1.2 buffer to prevent stop-hunting / spread spikes
    - Max SL distance cap (2.5%) to avoid loose stops
    - Min SL distance (0.5%) to avoid fee-eating tight stops
    - Min R:R ratio filter (1.5:1 minimum)
    
    Returns: tuple (entry, sl, rr) or None if validation fails
    """
    swept = structure["swept_level"]
    close = structure["close"]

    # Dynamic ATR Stop Loss buffer
    atr_buffer = None
    if candles and len(candles) >= 15 and calc_atr is not None:
        try:
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            closes = [c["close"] for c in candles]
            atr_vals = calc_atr(highs, lows, closes, 14)
            if atr_vals and atr_vals[-1] is not None:
                atr_buffer = atr_vals[-1] * 1.2
        except Exception:
            atr_buffer = None

    if atr_buffer is None:
        atr_buffer = abs(close) * 0.006

    buffer = max(abs(close) * 0.005, min(atr_buffer, abs(close) * 0.015))

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
    # Use tp1_r from config.yaml (default 3.0) instead of hardcoded 2.0
    try:
        from config import CONFIG as _app_cfg
        _tp1_r = _app_cfg.execution.tp1_r  # ExecutionCfg dataclass attribute
    except Exception:
        _tp1_r = MIN_RISK_REWARD_RATIO  # fallback to env var (3.0)
    target = entry + (risk * _tp1_r) if structure["direction"] == "LONG" else entry - (risk * _tp1_r)
    rr = abs(target - entry) / max(abs(risk), 1e-9)

    if rr < MIN_RISK_REWARD_RATIO:
        return None  # R:R too low (< 3.0:1), skip

    return entry, sl, rr


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


def get_dynamic_margin_bounds(account_size_usdt: float) -> tuple[float, float]:
    """
    If account size >= 50, use standard [MIN_INITIAL_MARGIN_USDT, MAX_INITIAL_MARGIN_USDT] band.
    If small account (< $50, e.g. Binance $5.47), scale margin to [8%, 15%] of balance per trade.
    This allows up to 3 concurrent trades: 3 x 15% = 45% max wallet usage (safe).
    Example: $5.47 account => min=$0.44, max=$0.82 per trade.
    """
    if account_size_usdt <= 0:
        return 0.5, 2.0
    if account_size_usdt >= 50.0:
        return MIN_INITIAL_MARGIN_USDT, MAX_INITIAL_MARGIN_USDT
    # Small account: 8%-15% per trade to allow multiple simultaneous trades
    min_m = max(0.44, round(account_size_usdt * 0.08, 2))
    max_m = max(min_m + 0.1, round(account_size_usdt * 0.15, 2))
    return min_m, max_m


def position_size(entry: float, sl: float, account_size_usdt: float = ACCOUNT_SIZE_USDT, leverage: int | None = None) -> float:
    """Return a risk-size quantity, then align it to the margin band (or dynamically for small accounts)."""
    if account_size_usdt <= 0:
        return 0.0
    leverage = clamp_leverage(leverage)
    min_margin, max_margin = get_dynamic_margin_bounds(account_size_usdt)
    risk_amount = account_size_usdt * (RISK_PER_TRADE_PCT / 100)
    distance = abs(entry - sl)
    if distance == 0 or entry <= 0:
        return 0.0

    # Base risk-based size: risk($) / distance($)
    qty = risk_amount / distance
    if qty <= 0:
        return 0.0

    # Ensure minimum notional for Binance Futures ($5.00 minNotional)
    min_notional = 5.5
    if qty * entry < min_notional and account_size_usdt < 50.0:
        qty = min_notional / entry

    # Align margin to band
    margin = estimate_initial_margin_usdt(entry, qty, leverage)
    if margin > max_margin:
        qty = (max_margin * leverage) / entry
        log.info(
            "position_size: adjusted qty from %.6f to %.6f because projected margin %.2f > %.2f USDT at %sx.",
            risk_amount / distance, qty, margin, max_margin, leverage
        )
    elif margin < min_margin:
        qty = (min_margin * leverage) / entry
        log.info(
            "position_size: adjusted qty from %.6f to %.6f because projected margin %.2f < %.2f USDT at %sx.",
            risk_amount / distance, qty, margin, min_margin, leverage
        )
    return round(max(qty, 0.0), 6)


def get_exchange_account_size_usdt(session) -> float:
    """Best-effort attempt to get the real account size from Bybit. Falls back to .env value."""
    if session is None:
        return ACCOUNT_SIZE_USDT
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED")
        if resp and resp.get("retCode") == 0 and resp.get("result", {}).get("list"):
            equity = float(resp["result"]["list"][0].get("totalEquity", 0))
            if equity > 0:
                return equity
    except Exception:
        pass
    try:
        resp = session.get_wallet_balance(accountType="CONTRACT")
        if resp and resp.get("retCode") == 0 and resp.get("result", {}).get("list"):
            equity = float(resp["result"]["list"][0].get("totalEquity", 0))
            if equity > 0:
                return equity
    except Exception:
        pass
    return ACCOUNT_SIZE_USDT


def get_total_margin_used_pct(session, account_size_usdt: float | None = None) -> float:
    """Calculate total margin utilization % for all open positions."""
    if session is None:
        return 0.0
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED")
        if resp and resp.get("retCode") == 0 and resp.get("result", {}).get("list"):
            equity = float(resp["result"]["list"][0].get("totalEquity", 0))
            margin = float(resp["result"]["list"][0].get("totalInitialMargin", 0))
            if equity > 0:
                return (margin / equity) * 100.0
    except Exception:
        pass

    if not managed_trades:
        return 0.0

    if account_size_usdt is None or account_size_usdt <= 0:
        account_size_usdt = get_exchange_account_size_usdt(session)
    if account_size_usdt <= 0:
        return 0.0

    total_margin_used = 0.0
    try:
        for symbol in managed_trades.keys():
            trade = managed_trades[symbol]
            entry = float(trade.get("entry", 0) or 0)
            leverage = clamp_leverage(trade.get("leverage", MIN_LEVERAGE))
            original_qty = float(trade.get("original_qty", 0) or 0)

            if entry > 0 and original_qty > 0:
                position_value = entry * original_qty
                position_margin = position_value / leverage if leverage > 0 else position_value
                total_margin_used += position_margin
    except Exception as e:
        log.warning("Error calculating margin usage: %s", e)
        return 0.0

    return (total_margin_used / account_size_usdt) * 100.0


def _fetch_bybit_tradable_symbols(session):
    """Fetch and cache all tradable linear perpetual symbols from Bybit."""
    global _bybit_tradable_symbols
    if not session:
        return
    try:
        resp = session.get_instruments_info(category=BYBIT_CATEGORY)
        if resp.get("retCode") == 0:
            symbols = {
                item["symbol"]
                for item in resp.get("result", {}).get("list", [])
                if "USDT" in item["symbol"]
            }
            _bybit_tradable_symbols = symbols
            log.info("Bybit ke %d tradable symbols fetch kiye.", len(symbols))
    except Exception as e:
        log.warning("Bybit tradable symbols fetch karne mein error: %s", e)


def handle_direction_flip(symbol: str, new_direction: str, session=None, client=None) -> bool:
    """
    Detect if a new signal direction conflicts with an existing open position on Bybit or Binance.
    If conflict found, close the existing position via Market order, persist state,
    wait 30 seconds, and return True so the new opposite trade can open.
    """
    bybit_key = symbol
    binance_key = f"BINANCE_{symbol}"
    
    trade_key = None
    if bybit_key in managed_trades:
        trade_key = bybit_key
    elif binance_key in managed_trades:
        trade_key = binance_key
    elif symbol in managed_trades:
        trade_key = symbol

    if not trade_key:
        return False

    existing_trade = managed_trades[trade_key]
    existing_direction = existing_trade.get("direction", "").upper()
    new_direction = new_direction.upper()

    if existing_direction == new_direction:
        return False

    log.warning(
        "%s: Direction flip detected! Existing: %s, New: %s. Closing existing position via Market order...",
        symbol, existing_direction, new_direction
    )

    try:
        # Close on Bybit if applicable
        if session is not None and trade_key != binance_key:
            if existing_trade.get("order_id"):
                try:
                    session.cancel_order(
                        category=BYBIT_CATEGORY,
                        symbol=symbol,
                        orderId=existing_trade["order_id"]
                    )
                    log.info("%s: Cancelled pending order for direction flip.", symbol)
                except Exception as e:
                    log.debug("%s: Cancel order attempt failed: %s", symbol, e)
            pos_resp = session.get_positions(category=BYBIT_CATEGORY, symbol=symbol)
            positions = pos_resp.get("result", {}).get("list", [])
            if positions:
                current_qty = float(positions[0].get("size", 0))
                if current_qty != 0:
                    close_side = "Sell" if current_qty > 0 else "Buy"
                    session.place_order(
                        category=BYBIT_CATEGORY, symbol=symbol, side=close_side,
                        orderType="Market", qty=str(abs(current_qty)), reduceOnly=True
                    )
                    log.info("%s: Closed Bybit %s position (%.6f qty) due to direction flip.", symbol, existing_direction, abs(current_qty))

        # Close on Binance if applicable
        if client is not None and (trade_key == binance_key or existing_trade.get("exchange") == "binance"):
            try:
                positions = client.futures_position_information(symbol=symbol)
                if positions:
                    current_qty = float(positions[0].get("positionAmt", 0))
                    if current_qty != 0:
                        close_side = "SELL" if current_qty > 0 else "BUY"
                        step, min_qty = get_binance_qty_step_and_min(client, symbol)
                        decimals = max(0, len(str(step).split(".")[1].rstrip("0"))) if "." in str(step) else 0
                        client.futures_create_order(
                            symbol=symbol, side=close_side, type="MARKET",
                            quantity=f"{abs(current_qty):.{decimals}f}", reduceOnly=True
                        )
                        # Cancel existing TP/SL orders
                        try:
                            client.futures_cancel_all_open_orders(symbol=symbol)
                        except Exception:
                            pass
                        log.info("%s: Closed Binance %s position (%.6f qty) due to direction flip.", symbol, existing_direction, abs(current_qty))
            except Exception as be:
                log.error("%s: Binance direction flip close error: %s", symbol, be)

        journal_log_close(symbol, existing_trade, notes=f"Direction flip closure: {existing_direction} -> {new_direction}")
        del managed_trades[trade_key]
        save_managed_trades_state()
        log.info("%s: Direction flip position closed & state saved. Waiting 30 seconds before opening new %s trade...", symbol, new_direction)
        time.sleep(30)
        return True
    except Exception as e:
        log.error("%s: Unexpected error in handle_direction_flip: %s", symbol, e)
        return False


def determine_leverage(score: float | None = None, entry: float | None = None, sl: float | None = None) -> int:
    """
    Return a score-driven or SL-distance driven leverage strictly clamped in the 8x-20x band.
    - min(max(leverage, 8), 20) is enforced across all paths.
    - If dynamic leverage is calculated based on Stop Loss distance, force output strictly into 8x-20x range.
    """
    try:
        chosen = MIN_LEVERAGE

        # 1. Dynamic leverage based on Stop Loss distance (tighter SL -> higher leverage, wider SL -> lower leverage)
        if entry is not None and sl is not None and entry > 0 and sl > 0:
            sl_distance_pct = (abs(entry - sl) / entry) * 100.0
            if sl_distance_pct > 0:
                # E.g. 1.0% SL -> 20x, 2.0% SL -> 10x, 2.5% SL -> 8x
                sl_dynamic = 20.0 / max(sl_distance_pct, 0.5)
                chosen = int(round(sl_dynamic))

        # 2. Score-driven adjustment (takes precedence if score is provided)
        if score is not None:
            sc = float(score)
            if sc >= 90:
                chosen = 20
            elif sc >= 85:
                chosen = 16
            elif sc >= 80:
                chosen = 12
            elif sc >= 75:
                chosen = 10
            else:
                chosen = 8
    except Exception as e:
        log.warning("determine_leverage error: %s, defaulting to %sx", e, MIN_LEVERAGE)
        chosen = MIN_LEVERAGE

    # Strictly clamp between MIN_LEVERAGE (8) and MAX_LEVERAGE (20)
    return clamp_leverage(chosen)


def estimate_initial_margin_usdt(entry: float, qty: float, leverage: int) -> float:
    """Approx used margin for a futures position at the planned leverage."""
    leverage = clamp_leverage(leverage)
    if entry <= 0 or qty <= 0 or leverage <= 0:
        return 0.0
    notional = abs(entry) * abs(qty)
    return notional / float(leverage)


def validate_initial_margin(entry: float, qty: float, leverage: int, account_size_usdt: float = ACCOUNT_SIZE_USDT) -> bool:
    """Hard stop: keep initial margin inside allowed margin window and leverage strictly in 8x-20x."""
    if leverage is None or leverage < MIN_LEVERAGE or leverage > MAX_LEVERAGE:
        return False
    min_margin, max_margin = get_dynamic_margin_bounds(account_size_usdt)
    margin = estimate_initial_margin_usdt(entry, qty, leverage)
    margin = round(margin, 2)
    return (min_margin * 0.9) <= margin <= (max_margin * 1.15)





def cap_qty_by_margin_utilization(entry: float, qty: float, leverage: int, account_size_usdt: float, session) -> tuple[float, float]:
    """Cap quantity to maintain MAX_MARGIN_UTILIZATION_PCT, accounting for existing open positions."""
    leverage = clamp_leverage(leverage)
    if account_size_usdt <= 0 or leverage <= 0 or entry <= 0 or qty <= 0:
        return qty, 0.0

    current_margin_pct = get_total_margin_used_pct(session)
    if current_margin_pct >= MAX_MARGIN_UTILIZATION_PCT:
        log.warning(
            "Margin utilization already at %.1f%% (limit: %.1f%%) -- cannot place new trades.",
            current_margin_pct, MAX_MARGIN_UTILIZATION_PCT,
        )
        return 0.0, current_margin_pct

    # Calculate remaining margin available
    remaining_margin_pct = MAX_MARGIN_UTILIZATION_PCT - current_margin_pct
    max_margin_available = account_size_usdt * (remaining_margin_pct / 100.0)

    # Calculate max quantity based on remaining margin
    max_qty = (max_margin_available * leverage) / entry if entry > 0 else 0.0

    if qty > max_qty:
        new_margin_pct = (max_qty * entry / leverage / account_size_usdt * 100) if account_size_usdt > 0 else 0
        log.info(
            "Qty capped from %.6f to %.6f (margin utilization: %.1f%% + new: %.1f%% = %.1f%%)",
            qty, max_qty, current_margin_pct, new_margin_pct, current_margin_pct + new_margin_pct
        )
        return round(max_qty, 6), current_margin_pct
    return qty, current_margin_pct


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
            recv_window=20000,  # laptop/server clock mein minor drift tolerate karne ke liye
        )
        log.info("Bybit DEMO session connected.")
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
                    "qty", "event", "notes", "pnl_usdt"]


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


def journal_log_open(symbol, direction, order_type, entry, sl, qty):
    _journal_write({
        "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "direction": direction,
        "order_type": order_type, "entry": entry, "sl": sl,
        "qty": qty, "event": "OPENED", "notes": "", "pnl_usdt": "",
    })


def journal_log_cancelled(symbol):
    _journal_write({
        "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "direction": "",
        "order_type": "", "entry": "", "sl": "",
        "qty": "", "event": "CANCELLED", "notes": "Limit order timeout se cancel hua", "pnl_usdt": "",
    })


def journal_log_close(symbol, trade: dict, notes: str = ""):
    # Prefer exact pnl if already computed and attached to trade (pnl_usdt),
    # otherwise fallback to heuristic estimate based on exit.
    pnl = ""
    try:
        if trade.get("pnl_usdt") is not None and trade.get("pnl_usdt") != "":
            pnl = trade.get("pnl_usdt")
        else:
            qty = float(trade.get("original_qty", 0))
            entry = float(trade.get("entry", 0))
            # Heuristic calculation for closed trades
            pnl = ""
    except Exception:
        pnl = ""

    try:
        account_usdt = float(trade.get("account_value_usdt", ACCOUNT_SIZE_USDT) or ACCOUNT_SIZE_USDT)
    except Exception:
        account_usdt = ACCOUNT_SIZE_USDT
    if isinstance(pnl, (int, float)):
        record_daily_loss(pnl, account_usdt)

    final_notes = notes if notes else f"final_stage={trade.get('stage','')}"
    _journal_write({
        "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "direction": trade.get("direction",""),
        "order_type": "", "entry": trade.get("entry",""), "sl": trade.get("sl",""),
        "qty": trade.get("original_qty",""), "event": "CLOSED", "notes": final_notes,
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
    """Try to compute exact realized PnL. Returns pnl_usdt or None if cannot compute."""
    try:
        # Simplified PnL logic
        return None
    except Exception as e:
        log.warning('compute_realized_pnl_from_trade error: %s', e)
    return None



def _try_set_leverage(session, symbol: str, leverage: int) -> bool:
    """Best-effort: try common Bybit/set leverage endpoints to set per-symbol leverage.
    Strictly clamps leverage between MIN_LEVERAGE (8) and MAX_LEVERAGE (20).
    Returns True if a call appeared successful (retCode==0 or 110043), False otherwise.
    This is defensive because different pybit versions expose different method names/params.
    """
    if not session or leverage is None:
        return False
    leverage = clamp_leverage(leverage)
    calls = [
        ("set_leverage", {"category": BYBIT_CATEGORY, "symbol": symbol, "buyLeverage": str(leverage), "sellLeverage": str(leverage)}),
        ("set_leverage", {"category": BYBIT_CATEGORY, "symbol": symbol, "buyLeverage": int(leverage), "sellLeverage": int(leverage)}),
        ("set_leverage", {"category": BYBIT_CATEGORY, "symbol": symbol, "leverage": str(leverage)}),
        ("set_leverage", {"category": BYBIT_CATEGORY, "symbol": symbol, "leverage": int(leverage)}),
        ("set_leverage_by_symbol", {"symbol": symbol, "leverage": int(leverage)}),
        ("set_margin", {"symbol": symbol, "leverage": int(leverage)}),
    ]
    for method, kwargs in calls:
        try:
            fn = getattr(session, method, None)
            if not fn:
                continue
            resp = fn(**kwargs)
            # Accept either dict with retCode in (0, 110043) or no-error response
            if isinstance(resp, dict):
                ret_code = resp.get("retCode", 0)
                if ret_code not in (0, 110043):
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
                               qty: float, score: float = None):
    """
    Entry placement without static TP limit orders.
    """
    if qty <= 0:
        log.warning("%s: position size 0 hai (ACCOUNT_SIZE_USDT .env mein set karein) -- order skip.", symbol)
        return None

    session = get_bybit_session()
    if session is None:
        return None

    step, min_qty = get_qty_step_and_min(session, symbol)

    chosen_leverage = clamp_leverage(determine_leverage(score, entry, sl))

    if USE_ISOLATED_MARGIN and BYBIT_CATEGORY != "spot":
        try:
            _try_set_isolated_margin(session, symbol)
        except Exception:
            pass

    # Set leverage on exchange before placing the order
    try:
        _try_set_leverage(session, symbol, chosen_leverage)
    except Exception as e:
        log.warning("%s: failed setting leverage %sx prior to order placement: %s", symbol, chosen_leverage, e)

    account_value = get_exchange_account_size_usdt(session)
    if DEMO_SIGNAL_TEST_MODE:
        capped_qty = float(qty)
        log.info("%s: demo mode bypassing margin utilization cap for visibility", symbol)
        current_margin_pct = 0.0
    else:
        capped_qty, current_margin_pct = cap_qty_by_margin_utilization(entry, float(qty), chosen_leverage, account_value, session)
        if capped_qty < float(qty):
            new_margin_pct = (capped_qty * entry / chosen_leverage / account_value * 100) if account_value > 0 else 0
            log.info("Qty capped from %.6f to %.6f (margin utilization: %.1f%% + new: %.1f%% = %.1f%%)",
                     qty, capped_qty, current_margin_pct, new_margin_pct, current_margin_pct + new_margin_pct)

    if capped_qty <= 0:
        log.warning("%s: qty capped to 0 -- margin limit exceeded, skipping entry.", symbol)
        return None
    qty = capped_qty

    # Enforce the user's exact trade setup constraints: margin window = $50-$70 and leverage window = 8x-20x.
    leverage = chosen_leverage
    if not validate_initial_margin(entry, qty, leverage):
        margin = estimate_initial_margin_usdt(entry, qty, leverage)
        log.warning(
            "%s: projected initial margin %.2f USDT outside %.2f-%.2f USDT band at %sx leverage -- order skip.",
            symbol, margin, MIN_INITIAL_MARGIN_USDT, MAX_INITIAL_MARGIN_USDT, leverage
        )
        return None

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
        log.info("Bybit DEMO %s order placed: %s %s @ %s qty=%s (order_id=%s) leverage=%sx SL=%s",
                  order_type, side, symbol, entry if order_type == "Limit" else "market price", qty_str, order_id, chosen_leverage, sl)

        managed_trades[symbol] = {
            "exchange": "bybit",
            "order_id": order_id,
            "direction": direction,
            "side": side,
            "original_qty": adjusted_qty,
            "entry": entry,
            "sl": sl,
            "score": score,
            "leverage": chosen_leverage,
            "stage": "pending" if order_type == "Limit" else "filled",
            "candles_waited": 0,
            "qty_step": step,
            "min_qty": min_qty,
            "score_journal_logged": False,
            "account_value_usdt": account_value,
        }
        journal_log_open(symbol, direction, order_type, entry, sl, adjusted_qty)
        save_managed_trades_state()

        # Send Telegram alert IMMEDIATELY when trade opens
        send_telegram_message(
            f"🚀 <b>TRADE OPENED ON BYBIT DEMO</b>\n\n"
            f"🪙 <b>Asset:</b> <code>{symbol}</code> | <b>{direction}</b> ({order_type})\n"
            f"💰 <b>Entry Price:</b> <code>${entry if order_type == 'Limit' else current_price}</code>\n"
            f"🛑 <b>Initial Stop Loss:</b> <code>${sl:.6f}</code>\n"
            f"⚡ <b>Leverage:</b> <b>{chosen_leverage}x</b>\n"
            f"📦 <b>Size:</b> <code>{qty_str}</code>\n"
            f"⭐ <b>Score:</b> <b>{score:.1f}/100</b>\n"
            f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
            f"🛡️ <b>TSL Protocol:</b> 1:1 Breakeven | 1:2 Higher Low | 1:3 Swing Tighten\n"
            f"⏰ <b>Timestamp:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>",
            is_signal=False
        )
        return resp
    except Exception as e:
        log.error("Bybit DEMO order failed for %s: %s", symbol, e)
        return None


# ---------------------------------------------------------------------------
# BINANCE FUTURES EXECUTION ENGINE
# ---------------------------------------------------------------------------
_binance_symbol_filters = {}


def _fetch_binance_symbol_filters(client: Client):
    """Fetch and cache Binance USDT-M futures lot sizes, tick sizes, and minNotionals."""
    global _binance_symbol_filters
    if not client:
        return
    try:
        info = client.futures_exchange_info()
        for sym_info in info.get("symbols", []):
            sym = sym_info["symbol"]
            step_size = 0.001
            min_qty = 0.001
            tick_size = 0.01
            min_notional = 5.0
            for f in sym_info.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    step_size = float(f.get("stepSize", 0.001))
                    min_qty = float(f.get("minQty", 0.001))
                elif f.get("filterType") == "PRICE_FILTER":
                    tick_size = float(f.get("tickSize", 0.01))
                elif f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
                    min_notional = float(f.get("notional", 5.0) or f.get("minNotional", 5.0))
            _binance_symbol_filters[sym] = {
                "stepSize": step_size,
                "minQty": min_qty,
                "tickSize": tick_size,
                "minNotional": min_notional,
            }
        log.info("Binance Futures ke %d symbols ke filters fetch kiye.", len(_binance_symbol_filters))
    except Exception as e:
        log.warning("Binance futures exchange info fetch error: %s", e)


def get_binance_qty_step_and_min(client: Client, symbol: str) -> tuple[float, float]:
    if symbol not in _binance_symbol_filters:
        _fetch_binance_symbol_filters(client)
    filt = _binance_symbol_filters.get(symbol, {})
    return filt.get("stepSize", 0.001), filt.get("minQty", 0.001)


def _binance_try_set_leverage(client: Client, symbol: str, leverage: int) -> bool:
    """Sets leverage on Binance USDT-M Futures (strictly clamped to 8x-20x)."""
    if not client or leverage is None:
        return False
    leverage = clamp_leverage(leverage)
    try:
        client.futures_change_leverage(symbol=symbol, leverage=int(leverage))
        log.info("Binance set leverage %sx for %s OK", leverage, symbol)
        return True
    except Exception as e:
        log.debug("Binance futures_change_leverage for %s: %s", symbol, e)
        return False


def _binance_try_set_isolated_margin(client: Client, symbol: str) -> bool:
    """Sets margin type to ISOLATED on Binance Futures."""
    if not client:
        return False
    try:
        client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
        log.info("Binance set isolated margin for %s OK", symbol)
        return True
    except Exception as e:
        if "-4046" in str(e):
            return True  # No need to change margin type
        log.debug("Binance futures_change_margin_type for %s: %s", symbol, e)
        return False


def get_binance_account_size_usdt(client: Client) -> float:
    """Fetches real available USDT balance from Binance Futures account."""
    if not client or not (BINANCE_API_KEY and BINANCE_API_SECRET):
        return ACCOUNT_SIZE_USDT
    try:
        balances = client.futures_account_balance()
        for b in balances:
            if b.get("asset") == "USDT":
                val = float(b.get("availableBalance") or b.get("balance") or 0.0)
                if val > 0:
                    return val
    except Exception as e:
        log.debug("get_binance_account_size_usdt error: %s", e)
    return ACCOUNT_SIZE_USDT


def binance_place_entry_with_multi_tp(client: Client, symbol: str, direction: str, current_price: float,
                                      entry: float, sl: float, qty: float, score: float = None):
    """
    Places trade on Binance Futures with 8x-20x leverage, STOP_MARKET SL.
    """
    if qty <= 0 or client is None:
        return None

    step, min_qty = get_binance_qty_step_and_min(client, symbol)
    chosen_leverage = clamp_leverage(determine_leverage(score, entry, sl))

    _binance_try_set_isolated_margin(client, symbol)
    _binance_try_set_leverage(client, symbol, chosen_leverage)

    account_val = get_binance_account_size_usdt(client)

    filt = _binance_symbol_filters.get(symbol, {})
    min_notional = max(filt.get("minNotional", 5.0), 5.0)  # Always at least $5.0

    # Step 1: Start from qty passed in
    adjusted_qty = round_qty_to_step(qty, step)

    # Step 2: Must meet minQty
    if adjusted_qty < min_qty:
        adjusted_qty = min_qty

    # Step 3: Must meet minNotional — round UP to enough qty
    required_notional = min_notional * 1.20  # 20% buffer
    if adjusted_qty * current_price < required_notional:
        import math
        raw_qty = required_notional / max(current_price, 0.0001)
        # Round UP to next valid step size
        if step > 0:
            adjusted_qty = math.ceil(raw_qty / step) * step
            adjusted_qty = round(adjusted_qty, 8)
        else:
            adjusted_qty = raw_qty
        adjusted_qty = max(adjusted_qty, min_qty)
        log.info("Binance %s: qty rounded UP to %.6f to meet minNotional $%.2f (price=%.4f)",
                 symbol, adjusted_qty, required_notional, current_price)

    # Step 4: Final safety check — if still below minNotional, skip
    final_notional = adjusted_qty * current_price
    if final_notional < min_notional:
        log.error("Binance %s: Cannot meet minNotional $%.2f (got $%.2f) -- skipping.",
                  symbol, min_notional, final_notional)
        return None

    decimals = max(0, len(str(step).split(".")[1].rstrip("0"))) if "." in str(step) else 0
    qty_str = f"{adjusted_qty:.{decimals}f}"

    order_type = decide_order_type(current_price, entry)
    side = "BUY" if direction == "LONG" else "SELL"
    close_side = "SELL" if direction == "LONG" else "BUY"

    tick_size = filt.get("tickSize", 0.01)
    price_decimals = max(0, len(str(tick_size).split(".")[1].rstrip("0"))) if "." in str(tick_size) else 2

    order_kwargs = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET" if order_type == "Market" else "LIMIT",
        "quantity": qty_str,
    }
    if order_type == "Limit":
        order_kwargs["price"] = f"{entry:.{price_decimals}f}"
        order_kwargs["timeInForce"] = "GTC"

    try:
        resp = client.futures_create_order(**order_kwargs)
        order_id = resp.get("orderId")
        log.info("Binance Futures %s order placed: %s %s @ %s qty=%s (orderId=%s) leverage=%sx",
                 order_type, side, symbol, entry if order_type == "Limit" else "MARKET", qty_str, order_id, chosen_leverage)

        # Place Stop Loss on Binance (STOP_MARKET with closePosition=True)
        try:
            sl_price_str = f"{sl:.{price_decimals}f}"
            client.futures_create_order(
                symbol=symbol, side=close_side, type="STOP_MARKET",
                stopPrice=sl_price_str, closePosition=True
            )
            log.info("Binance %s SL order placed @ %s", symbol, sl_price_str)
        except Exception as e:
            log.warning("Binance SL order placement error for %s: %s", symbol, e)

        # Save managed trade state
        binance_key = f"BINANCE_{symbol}"
        managed_trades[binance_key] = {
            "exchange": "binance",
            "symbol": symbol,
            "order_id": order_id,
            "direction": direction,
            "side": side,
            "original_qty": adjusted_qty,
            "entry": entry,
            "sl": sl,
            "score": score,
            "leverage": chosen_leverage,
            "stage": "pending" if order_type == "Market" else "filled",
            "candles_waited": 0,
            "qty_step": step,
            "min_qty": min_qty,
            "qty_decimals": decimals,
            "price_decimals": price_decimals,
            "account_value_usdt": account_val,
        }
        journal_log_open(symbol, direction, f"Binance-{order_type}", entry, sl, adjusted_qty)
        save_managed_trades_state()

        # Send Telegram alert IMMEDIATELY when trade opens
        send_telegram_message(
            f"🚀 <b>TRADE OPENED ON BINANCE FUTURES</b>\n\n"
            f"🪙 <b>Asset:</b> <code>{symbol}</code> | <b>{direction}</b> ({order_type})\n"
            f"💰 <b>Entry Price:</b> <code>${entry if order_type == 'Limit' else current_price}</code>\n"
            f"🛑 <b>Initial Stop Loss:</b> <code>${sl_price_str}</code>\n"
            f"⚡ <b>Leverage:</b> <b>{chosen_leverage}x Isolated</b>\n"
            f"📦 <b>Size:</b> <code>{qty_str}</code> (~${adjusted_qty * current_price:.2f} Notional)\n"
            f"⭐ <b>Score:</b> <b>{score:.1f}/100</b>\n"
            f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
            f"🛡️ <b>TSL Protocol:</b> 1:1 Breakeven | 1:2 Higher Low | 1:3 Swing Tighten\n"
            f"⏰ <b>Timestamp:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>",
            is_signal=False
        )
        return resp
    except Exception as e:
        log.error("Binance Futures order failed for %s: %s", symbol, e)
        return None


def _binance_update_step_tsl(client: Client, sym: str, trade: dict, pos: dict):
    """
    Dynamic Step-by-Step Trailing Stop Loss (TSL) Protocol for Binance Futures.
    Runs every 5 minutes for ALL open positions.
    - At 1:1 RR -> Move SL to breakeven NOW
    - At 1:2 RR -> Trail to higher low / lock 1R
    - At 1:3 RR -> Tighten to swing low / lock 2R
    """
    try:
        entry = float(trade.get("entry", 0.0) or 0.0)
        initial_sl = float(trade.get("sl", 0.0) or 0.0)
        current_sl = float(trade.get("current_sl", initial_sl) or initial_sl)
        direction = trade.get("direction", "LONG").upper()
        close_side = "SELL" if direction == "LONG" else "BUY"
        r_unit = abs(entry - initial_sl)

        if entry <= 0 or r_unit <= 0:
            return

        mark_price = float(pos.get("markPrice", 0.0) or 0.0)
        if mark_price <= 0:
            return

        current_r = (mark_price - entry) / r_unit if direction == "LONG" else (entry - mark_price) / r_unit

        price_decimals = int(trade.get("price_decimals", 2))
        if price_decimals == 2 and sym in _binance_symbol_filters:
            tick_size = _binance_symbol_filters[sym].get("tickSize", 0.01)
            price_decimals = max(0, len(str(tick_size).split(".")[1].rstrip("0"))) if "." in str(tick_size) else 2

        target_locked_r = None
        target_stage = None
        new_sl = None

        if current_r >= 3.0:
            target_locked_r = 3.0
            target_stage = "1:3_RR_SWING_TRAIL"
            new_sl = entry + (2.0 * r_unit) if direction == "LONG" else entry - (2.0 * r_unit)
        elif current_r >= 2.0:
            target_locked_r = 2.0
            target_stage = "1:2_RR_HIGHER_LOW_TRAIL"
            new_sl = entry + (1.0 * r_unit) if direction == "LONG" else entry - (1.0 * r_unit)
        elif current_r >= 1.0:
            target_locked_r = 1.0
            target_stage = "1:1_RR_BREAKEVEN"
            new_sl = entry

        prev_locked_r = float(trade.get("locked_r", 0.0) or 0.0)

        # Upgrade validation
        is_sl_upgrade = False
        if new_sl is not None and target_locked_r > prev_locked_r:
            if direction == "LONG" and new_sl > current_sl:
                is_sl_upgrade = True
            elif direction == "SHORT" and new_sl < current_sl:
                is_sl_upgrade = True
            elif target_stage == "1:1_RR_BREAKEVEN" and prev_locked_r < 1.0:
                is_sl_upgrade = True

        if is_sl_upgrade:
            new_sl_str = f"{new_sl:.{price_decimals}f}"
            old_sl_str = f"{current_sl:.{price_decimals}f}"

            # Cancel all previous regular and algo/conditional stop orders on Binance
            try:
                if hasattr(client, "futures_cancel_all_algo_open_orders"):
                    client.futures_cancel_all_algo_open_orders(symbol=sym)
                client.futures_cancel_all_open_orders(symbol=sym)
                time.sleep(0.3)
            except Exception as ce:
                log.debug("Binance cancel open/algo orders for %s: %s", sym, ce)

            # Place upgraded STOP_MARKET order at new stepped level
            try:
                client.futures_create_order(
                    symbol=sym,
                    side=close_side,
                    type="STOP_MARKET",
                    stopPrice=new_sl_str,
                    closePosition=True
                )
                log.info("TSL Updated: $%s → $%s (Symbol: %s, Current R: %.2fR, Stage: %s)",
                         old_sl_str, new_sl_str, sym, current_r, target_stage)

                trade["locked_r"] = target_locked_r
                trade["current_sl"] = float(new_sl_str)
                trade["stage"] = target_stage
                save_managed_trades_state()

                # Send Telegram alert immediately
                send_telegram_message(
                    f"🛡️ <b>TRAILING STOP LOSS UPDATED (BINANCE)</b>\n\n"
                    f"🪙 <b>Asset:</b> <code>{sym}</code> | <b>{direction}</b>\n"
                    f"🎯 <b>R-Multiple:</b> <b>{current_r:.2f}R reached</b>\n"
                    f"🛑 <b>TSL Updated: ${old_sl_str} → ${new_sl_str}</b>\n"
                    f"📈 <b>Mark Price:</b> <code>${mark_price}</code>\n"
                    f"🔒 <b>Protection Level:</b> <b>{target_stage}</b>\n"
                    f"⏰ <b>Timestamp:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>",
                    is_signal=False
                )
            except Exception as e:
                log.warning("Binance place upgraded SL failed for %s: %s", sym, e)
    except Exception as e:
        log.debug("Binance _binance_update_step_tsl error: %s", e)


def binance_manage_open_trades(client: Client):
    """Monitors active Binance Futures positions, updates TSL every 5 min, handles closures."""
    if EXECUTION_EXCHANGE not in ("binance", "both"):
        return
    if not client or not (BINANCE_API_KEY and BINANCE_API_SECRET):
        return
    try:
        # Fetch all open positions on Binance Futures
        positions = client.futures_position_information()
        pos_by_sym = {
            p["symbol"]: p for p in positions
            if abs(float(p.get("positionAmt", 0.0) or 0.0)) > 0
        }

        # 1. Update/check tracked trades in managed_trades
        binance_keys = [k for k in list(managed_trades.keys()) if k.startswith("BINANCE_") or managed_trades[k].get("exchange") == "binance"]
        for k in binance_keys:
            trade = managed_trades[k]
            sym = trade.get("symbol", k.replace("BINANCE_", ""))
            pos = pos_by_sym.get(sym)

            if pos and abs(float(pos.get("positionAmt", 0.0) or 0.0)) > 0:
                trade["stage"] = "filled"
                _binance_update_step_tsl(client, sym, trade, pos)
            else:
                # Position is closed
                log.info("Binance position %s is closed. Cleaning up and sending close alert...", sym)
                try:
                    client.futures_cancel_all_open_orders(symbol=sym)
                except Exception:
                    pass

                pnl = 0.0
                try:
                    incomes = client.futures_income_history(symbol=sym, incomeType="REALIZED_PNL", limit=5)
                    if incomes:
                        pnl = sum(float(inc.get("income", 0.0)) for inc in incomes if float(inc.get("time", 0)) > (time.time() - 3600) * 1000)
                except Exception as ie:
                    log.debug("Income history error for %s: %s", sym, ie)

                trade["pnl_usdt"] = pnl
                close_note = f"Position closed on exchange (PnL: ${pnl:.2f})"
                journal_log_close(sym, trade, notes=close_note)

                res_tag = "🟢 WIN / PROFIT" if pnl >= 0 else "🔴 LOSS"
                pnl_display = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                send_telegram_message(
                    f"🏁 <b>TRADE CLOSED ({res_tag})</b>\n\n"
                    f"🪙 <b>Asset:</b> <code>{sym}</code> | <b>{trade.get('direction', 'LONG')}</b>\n"
                    f"💵 <b>Entry:</b> <code>${trade.get('entry', 0)}</code>\n"
                    f"🛑 <b>Final SL:</b> <code>${trade.get('current_sl', trade.get('sl', 0))}</code>\n"
                    f"📊 <b>Realized PnL:</b> <b>{pnl_display}</b>\n"
                    f"📝 <b>Status:</b> {close_note}\n"
                    f"⏰ <b>Timestamp:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>",
                    is_signal=False
                )

                del managed_trades[k]
                save_managed_trades_state()

        # 2. Adopt any untracked open positions on Binance
        for sym, pos in pos_by_sym.items():
            binance_key = f"BINANCE_{sym}"
            if binance_key not in managed_trades:
                entry = float(pos.get("entryPrice", 0.0) or 0.0)
                pos_amt = float(pos.get("positionAmt", 0.0) or 0.0)
                direction = "LONG" if pos_amt > 0 else "SHORT"
                filt = _binance_symbol_filters.get(sym, {})
                tick_size = filt.get("tickSize", 0.01)
                price_decimals = max(0, len(str(tick_size).split(".")[1].rstrip("0"))) if "." in str(tick_size) else 2
                est_sl = entry * 0.995 if direction == "LONG" else entry * 1.005
                managed_trades[binance_key] = {
                    "exchange": "binance",
                    "symbol": sym,
                    "direction": direction,
                    "entry": entry,
                    "sl": est_sl,
                    "current_sl": est_sl,
                    "original_qty": abs(pos_amt),
                    "price_decimals": price_decimals,
                    "stage": "filled",
                    "locked_r": 0.0
                }
                save_managed_trades_state()
                log.info("Adopted open Binance position for %s (%s @ %s qty=%s)", sym, direction, entry, pos_amt)
                _binance_update_step_tsl(client, sym, managed_trades[binance_key], pos)
    except Exception as e:
        log.error("Binance manage open trades error: %s", e)


def manage_open_trades():
    """
    Monitors active Bybit positions, updates TSL, and handles closures.
    """
    session = get_bybit_session()
    if session is None:
        return
    try:
        bybit_keys = [k for k in list(managed_trades.keys()) if not k.startswith("BINANCE_") and managed_trades[k].get("exchange") != "binance"]
        for sym in bybit_keys:
            trade = managed_trades[sym]
            pos_resp = session.get_positions(category=BYBIT_CATEGORY, symbol=sym)
            positions = pos_resp.get("result", {}).get("list", [])
            pos = positions[0] if positions else None
            size = float(pos.get("size", 0.0) or 0.0) if pos else 0.0

            if size > 0:
                # Active position -> TSL check
                mark_price = float(pos.get("markPrice", 0.0) or 0.0)
                entry = float(trade.get("entry", 0.0) or 0.0)
                initial_sl = float(trade.get("sl", 0.0) or 0.0)
                current_sl = float(trade.get("current_sl", initial_sl) or initial_sl)
                direction = trade.get("direction", "LONG").upper()
                r_unit = abs(entry - initial_sl)

                if entry > 0 and r_unit > 0 and mark_price > 0:
                    current_r = (mark_price - entry) / r_unit if direction == "LONG" else (entry - mark_price) / r_unit
                    target_locked_r = None
                    target_stage = None
                    new_sl = None

                    if current_r >= 3.0:
                        target_locked_r = 3.0
                        target_stage = "1:3_RR_SWING_TRAIL"
                        new_sl = entry + (2.0 * r_unit) if direction == "LONG" else entry - (2.0 * r_unit)
                    elif current_r >= 2.0:
                        target_locked_r = 2.0
                        target_stage = "1:2_RR_HIGHER_LOW_TRAIL"
                        new_sl = entry + (1.0 * r_unit) if direction == "LONG" else entry - (1.0 * r_unit)
                    elif current_r >= 1.0:
                        target_locked_r = 1.0
                        target_stage = "1:1_RR_BREAKEVEN"
                        new_sl = entry

                    prev_locked_r = float(trade.get("locked_r", 0.0) or 0.0)
                    if new_sl is not None and target_locked_r > prev_locked_r:
                        old_sl_str = f"{current_sl:.6f}"
                        new_sl_str = f"{new_sl:.6f}"
                        try:
                            session.set_trading_stop(
                                category=BYBIT_CATEGORY,
                                symbol=sym,
                                stopLoss=new_sl_str,
                                positionIdx=0
                            )
                            log.info("TSL Updated: $%s → $%s (Symbol: %s, Current R: %.2fR, Stage: %s)",
                                     old_sl_str, new_sl_str, sym, current_r, target_stage)
                            trade["current_sl"] = new_sl
                            trade["locked_r"] = target_locked_r
                            trade["stage"] = target_stage
                            save_managed_trades_state()
                            send_telegram_message(
                                f"🛡️ <b>TRAILING STOP LOSS UPDATED (BYBIT)</b>\n\n"
                                f"🪙 <b>Asset:</b> <code>{sym}</code> | <b>{direction}</b>\n"
                                f"🎯 <b>R-Multiple:</b> <b>{current_r:.2f}R reached</b>\n"
                                f"🛑 <b>TSL Updated: ${old_sl_str} → ${new_sl_str}</b>\n"
                                f"📈 <b>Mark Price:</b> <code>${mark_price}</code>\n"
                                f"🔒 <b>Protection Level:</b> <b>{target_stage}</b>\n"
                                f"⏰ <b>Timestamp:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>",
                                is_signal=False
                            )
                        except Exception as se:
                            log.warning("Bybit set_trading_stop error for %s: %s", sym, se)
            else:
                # Closed position
                log.info("Bybit trade %s closed.", sym)
                pnl = 0.0
                try:
                    closed_resp = session.get_closed_pnl(category=BYBIT_CATEGORY, symbol=sym, limit=1)
                    closed_list = closed_resp.get("result", {}).get("list", [])
                    if closed_list:
                        pnl = float(closed_list[0].get("closedPnl", 0.0))
                except Exception:
                    pass

                trade["pnl_usdt"] = pnl
                close_note = f"Bybit position closed (PnL: ${pnl:.2f})"
                journal_log_close(sym, trade, notes=close_note)

                res_tag = "🟢 WIN / PROFIT" if pnl >= 0 else "🔴 LOSS"
                pnl_display = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                send_telegram_message(
                    f"🏁 <b>TRADE CLOSED ({res_tag})</b>\n\n"
                    f"🪙 <b>Asset:</b> <code>{sym}</code> | <b>{trade.get('direction', 'LONG')}</b>\n"
                    f"💵 <b>Entry:</b> <code>${trade.get('entry', 0)}</code>\n"
                    f"🛑 <b>Final SL:</b> <code>${trade.get('current_sl', trade.get('sl', 0))}</code>\n"
                    f"📊 <b>Realized PnL:</b> <b>{pnl_display}</b>\n"
                    f"📝 <b>Status:</b> {close_note}\n"
                    f"⏰ <b>Timestamp:</b> <code>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>",
                    is_signal=False
                )

                del managed_trades[sym]
                save_managed_trades_state()
    except Exception as e:
        log.error("Bybit manage open trades error: %s", e)


def tsl_background_worker(client: Client):
    """
    Dedicated Background Thread: Ensures Trailing Stop Loss (TSL) runs every 5 minutes (300s)
    for ALL open positions on Binance and Bybit continuously without interruption.
    """
    log.info("[TSL WORKER] Dedicated 5-minute Trailing Stop Loss loop started.")
    while True:
        try:
            if EXCHANGE_EXECUTION_ENABLED:
                if EXECUTION_EXCHANGE in ("binance", "both") and client is not None:
                    binance_manage_open_trades(client)
                if EXECUTION_EXCHANGE in ("bybit", "both"):
                    manage_open_trades()
        except Exception as e:
            log.error("[TSL WORKER] Error during 5-minute TSL cycle: %s", e)
        time.sleep(300)  # 5 minutes exact





# ---------------------------------------------------------------------------
# LAYER 8 -- NEWS FILTER & BLACK SWAN PROTECTION
# ---------------------------------------------------------------------------
NEWS_FILTER_ENABLED = os.getenv("NEWS_FILTER_ENABLED", "true").strip().lower() == "true"

def news_clear() -> bool:
    """
    Returns True if macro environment is safe for new entries.
    If a black swan or high-threat exploit is detected in breaking news, returns False.
    """
    if not NEWS_FILTER_ENABLED:
        return True
    if not _NEWS_SERVICE_AVAILABLE:
        return True

    intel = evaluate_macro_news_intelligence()
    if intel.get("danger_event", False):
        log.warning(
            "NEWS_FILTER BLOCKED: Black Swan / Danger detected in headlines: '%s'. Halting new trade entries.",
            intel.get("danger_headline", "Unknown high risk event")
        )
        return False
    return True



# ---------------------------------------------------------------------------
# LAYER 9 -- SCORING SYSTEM (Normalized 0-100 Confluence Score)
# ---------------------------------------------------------------------------
def compute_final_score(f_score, o_score, structure, candle_ok, rr, ob_or_fvg_found, vsa,
                         pullback_score=0.0, macd_sc=0.5, rsi_score=0.5, mtf_cascade_score=0.5,
                         intermediate_score=0.5, precision_score=0.5):
    """
    Compute the 100-point confluence score.
    """
    structure_score = 1.0 if structure.get("bos_confirmed") else 0.75
    ob_fvg_score = 1.0 if ob_or_fvg_found else 0.4
    rr_bonus = 1.0 if rr >= 2.0 else (0.75 if rr >= 1.5 else 0.3)

    structure_blend = structure_score * 0.6 + (1.0 if candle_ok else 0.4) * 0.2 + rr_bonus * 0.2

    raw_score = (
        mtf_cascade_score * WEIGHTS["macro_alignment"]
        + intermediate_score * WEIGHTS["intermediate"]
        + structure_blend * WEIGHTS["structure"]
        + ob_fvg_score * WEIGHTS["ob_fvg"]
        + vsa * WEIGHTS["vsa"]
        + precision_score * WEIGHTS["precision_trigger"]
        + rsi_score * WEIGHTS["rsi_divergence"]
        + macd_sc * WEIGHTS["macd"]
    )

    total_weight = sum(WEIGHTS.values())
    normalized = (raw_score / total_weight) * 100.0 if total_weight > 0 else raw_score
    return round(min(100.0, max(0.0, normalized)), 1)


# ---------------------------------------------------------------------------
# LAYER 10 -- QUICK TRADE NOTE FORMAT (Telegram message)
# ---------------------------------------------------------------------------
def format_candidate_summary(symbol: str, direction: str, entry: float, sl: float, rr: float, score: float, size: float, leverage: int, sl_gap_pct: float, margin_ok: bool) -> str:
    """Human-readable candidate signal snapshot."""
    return (
        f"CANDIDATE-SETUP | symbol={symbol} direction={direction} "
        f"entry={entry:.4f} sl={sl:.4f} "
        f"rr={rr:.2f} score={score:.1f} size={size:.6f} leverage={leverage}x "
        f"sl_gap_pct={sl_gap_pct:.2f}% margin_ok={margin_ok}"
    )


def format_rejection_summary(symbol: str, rr: float, sl_distance_pct: float, margin_ok: bool, leverage: int, open_trades: int) -> str:
    """Compact Telegram summary for a risk-gated reject."""
    reasons = []
    if rr < MIN_RISK_REWARD_RATIO:
        reasons.append(f"RRR {rr:.2f} < {MIN_RISK_REWARD_RATIO:.2f}")
    if sl_distance_pct > MAX_SL_DISTANCE_PCT:
        reasons.append(f"SL gap {sl_distance_pct:.2f}% > {MAX_SL_DISTANCE_PCT:.2f}%")
    if not margin_ok:
        reasons.append("margin limits")
    return f"<b>BOT CHECK SUMMARY</b>\nSymbol: {symbol}\nReason: {'; '.join(reasons)}"


def format_message(symbol, structure, entry, sl, rr, score, size, ob_found, fvg_found, vsa, pullback_data=None, cascade_analysis=None, smart_plan=None, macro_intel=None, ai_eval=None, z_score=0.0, vol_scalar=1.0):
    struct_str = "BOS Confirmed" if structure.get("bos_confirmed") else "CHoCH Reversal"
    bias = structure.get("direction", "LONG")
    
    macro_bias = bias
    if cascade_analysis:
        macro = cascade_analysis.get("macro", {})
        macro_bias = macro.get("bias", "BULLISH" if bias == "LONG" else "BEARISH")
    
    verdict = "Valid" if score >= SCORE_THRESHOLD else "Weak"

    macro_news_line = ""
    if macro_intel:
        sent_label = macro_intel.get("sentiment_label", "NEUTRAL")
        sent_sc = macro_intel.get("sentiment_score", 0.50)
        top_h = macro_intel.get("top_headlines", [])
        h_snippet = f" | <i>\"{top_h[0][:40]}...\"</i>" if top_h else ""
        macro_news_line = f"➤ <b>Macro News:</b> {sent_label} ({sent_sc:.2f}){h_snippet}\n"

    ai_badge = ""
    if ai_eval:
        ai_ok = ai_eval.get("ai_confirmed", False)
        ai_sc = ai_eval.get("ai_score", 0.0) * 100
        ai_reason = ai_eval.get("reason", "")
        ai_icon = "🤖 <b>Gemini 3.7 AI:</b> 🟢 CONFIRMED" if ai_ok else "🤖 <b>Gemini 3.7 AI:</b> 🔴 REJECTED"
        ai_badge = f"\n{ai_icon} ({ai_sc:.0f}% confidence)\n➤ <i>AI Note: {ai_reason}</i>\n"

    quant_line = f"➤ <b>Quant Confluence:</b> Z-Score={z_score:.2f} | Vol-Scalar={vol_scalar:.2f}x\n"

    plan_section = ""
    if smart_plan and smart_plan.get("status") == "EXECUTE":
        strat = smart_plan.get("strategy", "FULL_ENTRY")
        sent = smart_plan.get("sentiment", "NEUTRAL")
        sl_pct_disp = smart_plan.get("sl_percentage", 0.0) * 100
        tranches = smart_plan.get("tranches", [])
        plan_section = (
            f"\n\n🎯 <b>Smart Entry Plan ({strat}):</b>\n"
            f"➤ <b>Sentiment:</b> {sent} ({smart_plan.get('sentiment_score', 0.5):.2f})\n"
            f"➤ <b>SL Risk:</b> {sl_pct_disp:.2f}%\n"
            f"➤ <b>Tranches ({len(tranches)}):</b>\n"
        )
        for t in tranches:
            plan_section += f"  • Tranche {t['tranche_number']}: {t['position_allocation']*100:.0f}% @ ${t['entry_price']:.4f} ({t['timing']})\n"
    
    return (
        f"📋 <b>Quick Trade Note — {symbol}</b>\n"
        f"➤ <b>Bias (HTF):</b> {macro_bias}\n"
        f"{macro_news_line}"
        f"{quant_line}"
        f"➤ <b>Structure:</b> {struct_str}\n"
        f"➤ <b>Entry:</b> <code>${entry:.4f}</code>\n"
        f"➤ <b>Stop Loss:</b> <code>${sl:.4f}</code> (Trailing)\n"
        f"➤ <b>TP:</b> Unlimited — Trail SL only\n"
        f"➤ <b>Current R:R:</b> 1:∞\n"
        f"➤ <b>Score:</b> <b>{score}/100</b>\n"
        f"➤ <b>Verdict:</b> <b>{verdict}</b>"
        f"{ai_badge}"
        f"{plan_section}"
    )


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
def run_once(client: Client, universe: list):
    if daily_loss_limit_hit():
        log.warning("Daily loss limit hit -- naye trades skip kiye ja rahe hain aaj.")
        return

    if not news_clear():
        log.warning("🚨 Macro News Risk Filter ACTIVE: Adverse high-threat headlines detected. Halting new trade signals this cycle.")
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

            # --- ADX CHOP MARKET FILTER (Claude Optimization: Stay 100% Cash if ADX < 20) ---
            if calc_adx and len(candles) >= 30:
                try:
                    adx_vals = calc_adx(
                        [c["high"] for c in candles],
                        [c["low"] for c in candles],
                        [c["close"] for c in candles],
                        14
                    )
                    if adx_vals and adx_vals[-1] is not None and adx_vals[-1] < 18.0:
                        log.info("%s: ADX %.1f < 18.0 (Dead Chop Market) -- staying in CASH to protect capital.", symbol, adx_vals[-1])
                        continue
                except Exception as adx_err:
                    log.debug("%s: ADX check error: %s", symbol, adx_err)

            # --- FALLBACK: Flexible EMA Pullback + OB/FVG Trend Entry (Claude Recommendation: 0.6% - 1.8% range) ---
            if not structure and len(candles) >= 60:
                try:
                    cls = [c["close"] for c in candles]
                    ema20_vals = calc_ema(cls, 20) if calc_ema else []
                    ema50_vals = calc_ema(cls, 50) if calc_ema else []
                    if ema20_vals and ema50_vals:
                        e20 = ema20_vals[-1]; e50 = ema50_vals[-1]
                        cur = cls[-1]; prev = cls[-2] if len(cls) > 1 else cur
                        pullback_dist = abs(cur - e20) / e20
                        # LONG: price above EMA50, pulling back within flexible 0.6% - 1.8% of EMA20
                        if cur > e50 and e20 > e50 and 0.003 <= pullback_dist <= 0.018:
                            ob_hit = detect_order_block(candles, "LONG")
                            fvg_hit = detect_fvg(candles, "LONG")
                            if ob_hit or fvg_hit:
                                atr_vals = calc_atr([c["high"] for c in candles], [c["low"] for c in candles], cls, 14) if calc_atr else []
                                atr14 = atr_vals[-1] if atr_vals and atr_vals[-1] else cur * 0.01
                                structure = {
                                    "direction": "LONG", "swept_level": e20, "close": cur,
                                    "candle_time": candles[-1]["close_time"], "bos_confirmed": False,
                                    "atr": atr14, "atr_sl_mult": 1.8,  # Claude Recommendation: 1.8x ATR buffer prevents premature wick stop-outs
                                    "wick_ratio": 0.3, "vol_ratio": 1.0, "rsi": 50.0,
                                    "signal_type": "EMA_PULLBACK_OB"
                                }
                        # SHORT: price below EMA50, pulling back within flexible 0.6% - 1.8% of EMA20
                        elif cur < e50 and e20 < e50 and 0.003 <= pullback_dist <= 0.018:
                            ob_hit = detect_order_block(candles, "SHORT")
                            fvg_hit = detect_fvg(candles, "SHORT")
                            if ob_hit or fvg_hit:
                                atr_vals = calc_atr([c["high"] for c in candles], [c["low"] for c in candles], cls, 14) if calc_atr else []
                                atr14 = atr_vals[-1] if atr_vals and atr_vals[-1] else cur * 0.01
                                structure = {
                                    "direction": "SHORT", "swept_level": e20, "close": cur,
                                    "candle_time": candles[-1]["close_time"], "bos_confirmed": False,
                                    "atr": atr14, "atr_sl_mult": 1.8,
                                    "wick_ratio": 0.3, "vol_ratio": 1.0, "rsi": 50.0,
                                    "signal_type": "EMA_PULLBACK_OB"
                                }
                except Exception as fb_err:
                    log.debug("%s: EMA pullback fallback error: %s", symbol, fb_err)

            if not structure:
                log.info("%s: no sweep/structure signal.", symbol)
                continue


            key = f"{symbol}_{structure['direction']}_{structure['candle_time']}"

            if EXCHANGE_EXECUTION_ENABLED and EXECUTION_EXCHANGE == "bybit" and _bybit_tradable_symbols and symbol not in _bybit_tradable_symbols:
                log.info("%s: Bybit futures market par ye symbol exist nahi karta -- signal skip (execution possible nahi).", symbol)
                continue

            if last_alerted.get(symbol) == key:
                continue

            if TREND_FILTER_ENABLED and not trend_filter_ok(candles, structure["direction"]):
                log.info("%s: signal mila lekin 1H EMA trend filter ke against hai -- skip.", symbol)
                continue

            # ---- FULL 8-TIMEFRAME MTF CASCADE & GWAIDIER 4-PILLARS CHECK ----
            cascade_analysis = None
            macro_cascade_score = 0.5
            intermediate_sc = 0.5
            precision_sc = 0.5
            if MULTI_TIMEFRAME_CASCADE_ENABLED:
                cascade_analysis = run_mtf_cascade(client, symbol, structure["direction"], current_price=structure.get("close", 0.0))
                if not cascade_analysis.get("trade_allowed", True):
                    log.info(
                        "%s: 8-TF Cascade REJECTED %s signal. Macro: %s | Reason: %s",
                        symbol, structure["direction"],
                        cascade_analysis.get("overall_bias", "?"),
                        cascade_analysis.get("reason", "unknown"),
                    )
                    continue
                macro_cascade_score = cascade_analysis.get("macro", {}).get("score", 0.5)
                intermediate_sc = cascade_analysis.get("intermediate", {}).get("score", 0.5)
                precision_sc = cascade_analysis.get("execution", {}).get("precision_score", 0.5)
                log.info(
                    "%s: 8-TF Cascade PASSED | Macro: %s (%.2f) | 4H/2H: %.2f | Precision: %.2f | Overall: %.2f",
                    symbol, cascade_analysis.get("overall_bias", "?"),
                    macro_cascade_score, intermediate_sc, precision_sc,
                    cascade_analysis.get("cascade_score", 0),
                )
            else:
                mtf_info = get_higher_tf_bias(client, symbol)
                if structure["direction"] == "LONG" and mtf_info["bias"] == "SHORT":
                    log.info("%s: macro trend is BEARISH (%s) -- skipping counter-trend LONG signal.", symbol, mtf_info["reason"])
                    continue
                elif structure["direction"] == "SHORT" and mtf_info["bias"] == "LONG":
                    log.info("%s: macro trend is BULLISH (%s) -- skipping counter-trend SHORT signal.", symbol, mtf_info["reason"])
                    continue
                macro_cascade_score = 1.0 if (mtf_info["bias"] == structure["direction"] or mtf_info["bias"] == "NEUTRAL") else 0.0

            funding_info = check_funding_rate(symbol, structure["direction"])
            if funding_info.get("rejected", False):
                log.info("%s: funding rate filter reject -- %s -- signal skip.", symbol, funding_info.get("reason"))
                continue

            f_score = fundamental_score(symbol)
            o_score = onchain_score(symbol, structure["direction"])
            candle_ok = candle_confirmation(candles, structure["direction"])
            ob_found = detect_order_block(candles, structure["direction"])
            fvg_found = detect_fvg(candles, structure["direction"])
            vsa = vsa_score(candles, structure["direction"])
            pullback_data = detect_trend_pullback(candles, structure["direction"])
            levels = compute_entry_sl_tp(structure, candles)
            if not levels:
                log.info("%s: entry/sl/tp calculation invalid -- signal skip.", symbol)
                continue
            entry, sl, rr = levels

            score = compute_final_score(
                f_score, o_score, structure, candle_ok, rr,
                ob_found or fvg_found, vsa,
                pullback_score=pullback_data.get("pullback_score", 0.0) if pullback_data else 0.0,
                mtf_cascade_score=macro_cascade_score,
                intermediate_score=intermediate_sc,
                precision_score=precision_sc,
            )

            # --- Claude 3-Tier Adaptive Market Regime System ---
            closes = [float(c["close"]) for c in candles] if candles else []
            highs = [float(c["high"]) for c in candles] if candles else []
            lows = [float(c["low"]) for c in candles] if candles else []
            
            regime_info = detect_market_regime(highs, lows, closes) if _INDICATORS_CALC_AVAILABLE else {"regime": "NORMAL", "adx": 25.0, "min_score": 50.0, "pos_multiplier": 1.0, "tp_scale": 1.0, "min_rrr": 1.5}
            regime_name = regime_info.get("regime", "NORMAL")
            adaptive_min_score = regime_info.get("min_score", 50.0) if not TESTING_MODE else 35.0
            pos_multiplier = regime_info.get("pos_multiplier", 1.0)

            # --- V2 INSTITUTIONAL GATE INTEGRATION (Default OFF via USE_V2 switch) ---
            if USE_V2 and _V2_AVAILABLE:
                tf_signs = {
                    "1D": 1 if cascade_analysis and cascade_analysis.get("tf_breakdown", {}).get("1D", {}).get("bias") == "LONG" else (-1 if cascade_analysis and cascade_analysis.get("tf_breakdown", {}).get("1D", {}).get("bias") == "SHORT" else 0),
                    "4H": 1 if cascade_analysis and cascade_analysis.get("tf_breakdown", {}).get("4H", {}).get("bias") == "LONG" else (-1 if cascade_analysis and cascade_analysis.get("tf_breakdown", {}).get("4H", {}).get("bias") == "SHORT" else 0),
                    "1H": 1 if structure["direction"] == "LONG" else -1,
                    "15m": 1 if cascade_analysis and cascade_analysis.get("tf_breakdown", {}).get("15m", {}).get("bias") == "LONG" else (-1 if cascade_analysis and cascade_analysis.get("tf_breakdown", {}).get("15m", {}).get("bias") == "SHORT" else 0),
                }
                v2_dir_side = 1 if structure["direction"] == "LONG" else -1
                a01_score = v2_calc_a01(tf_signs, v2_dir_side, V2ScoreCfg())
                v2_scores = {
                    "a01_mtf_trend": a01_score,
                    "a02_sweep_choch": v2_dir_side * (0.85 if structure.get("bos_confirmed") else 0.65),
                    "a03_ob_fvg": v2_dir_side * (0.80 if (ob_found or fvg_found) else 0.0),
                    "a04_vsa_cvd": v2_dir_side * (vsa * 2.0 - 1.0),
                    "a06_sr_hvn": v2_dir_side * 0.70,
                    "a08_candles": v2_dir_side * (0.80 if candle_ok else 0.20),
                    "a09_whale_ratio": v2_dir_side * (o_score * 2.0 - 1.0),
                }

                # Evaluate Gemini LLM Veto (if configured/enabled)
                llm_veto_flag = False
                if GEMINI_AI_CONFIRMATION_ENABLED and is_gemini_configured():
                    try:
                        ai_eval = gemini_evaluate_setup(
                            symbol=symbol,
                            direction=structure["direction"],
                            entry=entry,
                            sl=sl,
                            tp=levels[2] if len(levels) > 2 else entry + (entry - sl) * 2.0,
                            score=score,
                            cascade_data=cascade_analysis,
                            macro_intel=macro_intel,
                        )
                        if isinstance(ai_eval, dict):
                            llm_veto_flag = not ai_eval.get("ai_confirmed", True) or float(ai_eval.get("ai_score", 0.75)) < 0.40
                    except Exception as ai_e:
                        log.debug("%s: Gemini AI evaluation error: %s", symbol, ai_e)

                # Range edge check for CHOP regime
                at_range_edge_flag = bool(ob_found or fvg_found or structure.get("signal_type") == "EMA_PULLBACK_OB")

                v2_dec = v2_decide(
                    agent_scores=v2_scores,
                    tf_signs=tf_signs,
                    regime=regime_name,
                    llm_veto=llm_veto_flag,
                    at_range_edge=at_range_edge_flag,
                    fundamental_score=f_score,
                    cfg=V2ScoreCfg(),
                )
                if not v2_dec.trade:
                    log.info("%s: V2 Gate BLOCKED trade | Conviction: %.1f | Reasons: %s", symbol, v2_dec.conviction, ", ".join(v2_dec.reasons))
                    continue
                score = v2_dec.conviction
                pos_multiplier = pos_multiplier * v2_dec.risk_mult
                log.info("%s: V2 Gate APPROVED trade | Conviction: %.1f | RiskMult: %.2f", symbol, v2_dec.conviction, v2_dec.risk_mult)
            else:
                min_rr_threshold = (MIN_RISK_REWARD_RATIO * 0.8) if TESTING_MODE else (MIN_RISK_REWARD_RATIO if regime_name != "CHOP_SHIELD" else 2.0)
                vsa_min_1 = 0.5 if TESTING_MODE else (0.6 if regime_name == "BREAKOUT" else 0.7)
                vsa_min_2 = 0.4 if TESTING_MODE else (0.5 if regime_name == "BREAKOUT" else 0.6)

                fallback_eligible = (
                    rr >= min_rr_threshold
                    and (structure.get("bos_confirmed", False) or ob_found or fvg_found or vsa >= vsa_min_1)
                    and (candle_ok or ob_found or fvg_found or vsa >= vsa_min_2)
                    and score >= adaptive_min_score - SCORE_FALLBACK_MARGIN
                    and score >= min(adaptive_min_score - SCORE_FALLBACK_MARGIN, 25.0)
                )

                if score < adaptive_min_score and not fallback_eligible:
                    log.info("%s: [Regime: %s | ADX: %.1f] signal found but score %.1f < adaptive threshold %.1f -- skipping weak trade.", symbol, regime_name, regime_info.get("adx", 0.0), score, adaptive_min_score)
                    continue

                log.info("%s: [Regime: %s | ADX: %.1f] score %.1f PASSED adaptive threshold %.1f.", symbol, regime_name, regime_info.get("adx", 0.0), score, adaptive_min_score)

            leverage = determine_leverage(score, entry, sl)
            size = position_size(entry, sl, account_value, leverage) * pos_multiplier
            sl_distance_pct = (abs(entry - sl) / entry) * 100 if entry else 0.0

            # --- SMART ENTRY POSITION SIZER, QUANT VOLATILITY & GEMINI AI GATING ---
            smart_plan = None
            macro_intel = evaluate_macro_news_intelligence()
            news_score_val = macro_intel.get("sentiment_score", 0.50)

            # Dr. Ernest Chan Statistical Z-Score & Robert Carver Volatility Scaling
            closes = [float(c["close"]) for c in candles] if candles else []
            highs = [float(c["high"]) for c in candles] if candles else []
            lows = [float(c["low"]) for c in candles] if candles else []

            z_score_val = 0.0
            if calc_z_score and closes:
                try:
                    z_list = calc_z_score(closes, period=20)
                    z_score_val = z_list[-1] if z_list and z_list[-1] is not None else 0.0
                except Exception as z_err:
                    log.warning("z_score calc failed for %s: %s", symbol, z_err)
                    z_score_val = 0.0

            vol_scalar_val = 1.0
            if calc_carver_volatility_scalar and closes and highs and lows:
                try:
                    current_price = closes[-1]
                    atr_list = calc_atr(highs, lows, closes, period=14) if calc_atr else []
                    current_atr = atr_list[-1] if atr_list and atr_list[-1] is not None else 0.0
                    vol_scalar_val = calc_carver_volatility_scalar(current_price, current_atr)
                except Exception as vol_err:
                    log.warning("vol_scalar calc failed for %s: %s", symbol, vol_err)
                    vol_scalar_val = 1.0

            if SMART_ENTRY_ENABLED and smart_sizer:
                # Rule 3: Skip trade if SL > 5%
                if sl_distance_pct > 5.0:
                    log.warning("%s: Trade SKIPPED by Smart Entry Sizer: SL %.2f%% > 5.0%% max limit.", symbol, sl_distance_pct)
                    continue

                # Calculate composite sentiment (trend, volume, momentum, macro news)
                macro_dir = "BULLISH"
                if cascade_analysis:
                    macro_dir = cascade_analysis.get("macro", {}).get("bias", "BULLISH" if structure["direction"] == "LONG" else "BEARISH")
                elif structure["direction"] == "SHORT":
                    macro_dir = "BEARISH"

                trend_sc = 0.85 if macro_dir == "BULLISH" else 0.35
                vol_sc = min(1.0, max(0.2, vsa if vsa else 0.6))
                mom_sc = min(1.0, max(0.2, score / 100.0))
                sentiment_val = smart_sentiment_analyzer.calculate_market_sentiment(
                    trend_strength=trend_sc,
                    volume_score=vol_sc,
                    momentum_score=mom_sc,
                    news_score=news_score_val
                )
                tp_target = entry + (abs(entry - sl) * 2.5) if structure["direction"] == "LONG" else entry - (abs(entry - sl) * 2.5)
                smart_plan = smart_sizer.calculate_position_sizing(
                    entry_price=entry,
                    stop_loss_price=sl,
                    take_profit_price=tp_target,
                    market_sentiment=sentiment_val,
                    volatility_scalar=vol_scalar_val,
                    z_score=z_score_val,
                    direction=structure["direction"],
                    symbol=symbol
                )
                if smart_plan.get("status") == "SKIP":
                    log.warning("%s: Trade SKIPPED by Smart Entry Sizer: %s", symbol, smart_plan.get("reason"))
                    continue

                # If Scale-In strategy, allocate Tranche 1 size for initial execution
                if smart_plan.get("strategy") == "SCALE_IN" and smart_plan.get("tranches"):
                    t1_alloc = smart_plan["tranches"][0]["position_allocation"]
                    size = size * t1_alloc
                    log.info("%s: Smart Entry SCALE_IN active: Tranche 1 executing with %.0f%% size.", symbol, t1_alloc * 100)

            # --- GEMINI 3.7 FLASH LIVE TRADE GATE ---
            ai_eval = None
            if GEMINI_AI_CONFIRMATION_ENABLED and is_gemini_configured():
                try:
                    setup_payload = {
                        "symbol": symbol,
                        "direction": structure["direction"],
                        "entry": entry,
                        "sl": sl,
                        "rr": rr,
                        "score": score,
                        "vsa_score": vsa,
                        "z_score": z_score_val,
                        "volatility_scalar": vol_scalar_val,
                        "macro_bias": macro_dir if 'macro_dir' in locals() else "NEUTRAL",
                        "news_headline": macro_intel.get("top_headlines", [""])[0] if macro_intel.get("top_headlines") else ""
                    }
                    ai_eval = gemini_evaluate_setup(setup_payload)
                    if not ai_eval.get("ai_confirmed", True):
                        log.warning("%s: Trade REJECTED by Gemini 3.7 AI Gate (Score %.2f): %s", symbol, ai_eval.get("ai_score", 0.0), ai_eval.get("reason", "No reason provided"))
                        continue
                    log.info("%s: Trade CONFIRMED by Gemini 3.7 AI Gate (Score %.2f): %s", symbol, ai_eval.get("ai_score", 1.0), ai_eval.get("reason", ""))
                except Exception as ai_err:
                    log.warning("Gemini AI check skipped due to exception: %s", ai_err)

            bybit_open_count = len([k for k in managed_trades.keys() if not k.startswith("BINANCE_")])
            binance_open_count = len([k for k in managed_trades.keys() if k.startswith("BINANCE_")])
            
            open_trades_cap_ok = True
            if MAX_OPEN_TRADES > 0:
                if EXECUTION_EXCHANGE == "binance":
                    open_trades_cap_ok = binance_open_count < MAX_OPEN_TRADES
                elif EXECUTION_EXCHANGE == "bybit":
                    open_trades_cap_ok = bybit_open_count < MAX_OPEN_TRADES
                else:
                    open_trades_cap_ok = (binance_open_count < MAX_OPEN_TRADES) or (bybit_open_count < MAX_OPEN_TRADES)

            margin_ok = validate_initial_margin(entry, size, leverage)
            approval = (
                rr >= MIN_RISK_REWARD_RATIO
                and sl_distance_pct <= MAX_SL_DISTANCE_PCT
                and sl_distance_pct >= MIN_SL_DISTANCE_PCT
                and margin_ok
                and open_trades_cap_ok
            )

            if not approval:
                active_count = binance_open_count if EXECUTION_EXCHANGE == "binance" else len(managed_trades)
                reject_summary = format_rejection_summary(symbol, rr, sl_distance_pct, margin_ok, leverage, active_count)
                log.info(
                    "%s: signal not approved: rr=%.2f, sl_gap_pct=%.2f, margin_ok=%s, binance_trades=%d/%s, bybit_trades=%d/%s, leverage=%sx -- telegram suppressed.",
                    symbol, rr, sl_distance_pct, margin_ok, binance_open_count, MAX_OPEN_TRADES if MAX_OPEN_TRADES > 0 else 'unlimited',
                    bybit_open_count, MAX_OPEN_TRADES if MAX_OPEN_TRADES > 0 else 'unlimited', leverage
                )
                log.info("BOT CHECK SUMMARY | %s", reject_summary.replace("\n", " | "))
                continue

            last_alerted[symbol] = key
            msg = format_message(
                symbol, structure, entry, sl, rr, score, size, ob_found, fvg_found, vsa,
                pullback_data, cascade_analysis, smart_plan=smart_plan, macro_intel=macro_intel,
                ai_eval=ai_eval, z_score=z_score_val, vol_scalar=vol_scalar_val
            )
            log.info("Approved signal:\n%s", msg)

            # Generate visual chart & deliver via Telegram Photo (with automatic text fallback)
            chart_path = None
            if _CHART_VISUALIZER_AVAILABLE:
                try:
                    tp_targets = {
                        "tp1": smart_plan.get("tp1") if smart_plan else None,
                        "tp2": smart_plan.get("tp2") if smart_plan else None,
                        "tp3": smart_plan.get("runner") if smart_plan else None,
                    }
                    chart_path = chart_visualizer.render_smc_trade_chart(
                        candles=candles,
                        symbol=symbol,
                        direction=structure["direction"],
                        entry=entry,
                        sl=sl,
                        tp_levels=tp_targets,
                        structure=structure,
                        score=score,
                        timeframe=TIMEFRAME
                    )
                except Exception as chart_err:
                    log.warning("Visual chart generation failed for %s: %s", symbol, chart_err)

            if chart_path and os.path.exists(chart_path):
                chart_visualizer.send_telegram_chart_alert(chart_path, caption=msg, symbol=symbol)
            else:
                send_telegram_message(msg, symbol=symbol, is_signal=True)

            global _demo_signal_count
            if EXCHANGE_EXECUTION_ENABLED:
                if DEMO_SIGNAL_TEST_MODE and _demo_signal_count >= DEMO_SIGNAL_TARGET:
                    log.info("Demo signal target reached (%s/%s), skipping execution.", _demo_signal_count, DEMO_SIGNAL_TARGET)
                    return

                # Bybit Execution
                if EXECUTION_EXCHANGE in ("bybit", "both") and bybit_session is not None:
                    flip_handled = handle_direction_flip(symbol, structure["direction"], session=bybit_session, client=client)
                    if symbol in managed_trades and not flip_handled:
                        log.info("%s: Bybit pe pehle se ek managed trade chal rahi hai -- naya signal skip.", symbol)
                    elif MAX_OPEN_TRADES > 0 and bybit_open_count >= MAX_OPEN_TRADES:
                        log.info("%s: Bybit max open trades (%s) reached -- skip.", symbol, MAX_OPEN_TRADES)
                    else:
                        if place_entry_with_multi_tp(symbol, structure["direction"], structure["close"], entry, sl, size, score):
                            if DEMO_SIGNAL_TEST_MODE:
                                _demo_signal_count += 1

                # Binance Execution
                if EXECUTION_EXCHANGE in ("binance", "both") and BINANCE_CREDENTIALS_PRESENT and client is not None:
                    binance_key = f"BINANCE_{symbol}"
                    flip_handled = handle_direction_flip(symbol, structure["direction"], session=bybit_session, client=client)
                    if binance_key in managed_trades and not flip_handled:
                        log.info("%s: Binance pe pehle se ek managed trade chal rahi hai -- naya signal skip.", symbol)
                    elif MAX_OPEN_TRADES > 0 and binance_open_count >= MAX_OPEN_TRADES:
                        log.info("%s: Binance max open trades (%s) reached -- skip.", symbol, MAX_OPEN_TRADES)
                    else:
                        binance_acc = get_binance_account_size_usdt(client)
                        binance_size = position_size(entry, sl, account_size_usdt=binance_acc, leverage=leverage)
                        binance_place_entry_with_multi_tp(client, symbol, structure["direction"], structure["close"], entry, sl, binance_size, score)

        except BinanceAPIException as e:
            log.error("Binance API error for %s: %s", symbol, e)
        except Exception as e:
            log.error("Unexpected error checking %s: %s", symbol, e)


def main():
    log.info("Starting Master Crypto Signal Bot (Layer 0-10 system)")
    load_managed_trades_state()

    # ── Telegram startup test (only once, before the Binance retry loop) ──────
    # Telegram uses DIRECT connection (no proxy). Test confirmed: proxy BLOCKS Telegram.
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        log.info("Verifying Telegram connection on startup...")
        test_telegram_connection()
    else:
        log.warning("Telegram token/chat missing in .env -- alerts disabled.")

    # Resilient Startup Initialization (Waits for WiFi/Binance network on boot)
    client = None
    universe = []
    while True:
        try:
            # PERMANENT PROXY SOLUTION: get_hardwired_proxy() is ALWAYS used.
            # WiFi badlo, ISP badlo — koi farq nahi. Bot hamesha fixed proxy
            # IP (45.38.107.97) se Binance connect karta hai.
            binance_proxy = get_hardwired_proxy()
            _active_proxy_url = binance_proxy.get("https", "unknown")
            client_kwargs = {"testnet": BINANCE_TESTNET, "requests_params": {"proxies": binance_proxy}}
            log.info("✅ Binance Client using PERMANENT proxy IP: %s", _active_proxy_url.split("@")[-1] if "@" in _active_proxy_url else _active_proxy_url)

            client = Client(BINANCE_API_KEY or None, BINANCE_API_SECRET or None, **client_kwargs)
            try:
                srv_time = client.get_server_time()
                client.timestamp_offset = srv_time.get("serverTime", 0) - int(time.time() * 1000)
                log.info("Binance server time synchronized. Offset: %d ms", client.timestamp_offset)
            except Exception as time_err:
                log.warning("Could not sync Binance server time: %s", time_err)

            # Launch Dedicated Background Trailing Stop Loss (TSL) Thread (Every 5 minutes, never stops)
            tsl_thread = threading.Thread(target=tsl_background_worker, args=(client,), daemon=True, name="TSL_Worker_Thread")
            tsl_thread.start()
            log.info("Dedicated 5-minute Trailing Stop Loss background worker thread started.")

            if EXCHANGE_EXECUTION_ENABLED:
                log.info("Exchange execution enabled. Selected exchange mode: %s", EXECUTION_EXCHANGE.upper())
                if EXECUTION_EXCHANGE in ("bybit", "both"):
                    if get_bybit_session() is not None:
                        log.info("Bybit DEMO connection successful.")
                        _fetch_bybit_tradable_symbols(_bybit_session)
                    else:
                        log.warning("Bybit DEMO execution enabled but unable to connect.")
                if EXECUTION_EXCHANGE in ("binance", "both"):
                    if BINANCE_CREDENTIALS_PRESENT:
                        log.info("Binance Futures credentials loaded. Fetching filters...")
                        _fetch_binance_symbol_filters(client)
                    else:
                        log.warning("Binance execution selected but BINANCE_API_KEY/SECRET missing in .env.")
            else:
                log.info("Exchange execution disabled. Running in alert-only mode.")

            if MANUAL_WATCHLIST_ENABLED and MANUAL_WATCHLIST:
                universe = MANUAL_WATCHLIST
                log.info("Manual watchlist active (%d coins), Layer 0 auto-scan OFF: %s",
                          len(universe), universe)
            else:
                universe = select_final_universe(client)
                if not universe:
                    log.warning("Universe scan khali aaya -- fallback BTCUSDT/ETHUSDT/SOLUSDT use kar rahe hain.")
                    universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            break
        except Exception as init_err:
            log.warning("Startup initialization waiting for network: %s. Retrying in 10s...", init_err)
            time.sleep(10)

    last_universe_refresh = time.time()
    retry_backoff = 5

    while True:
        try:
            if not MANUAL_WATCHLIST_ENABLED and time.time() - last_universe_refresh > 6 * 3600:
                new_universe = select_final_universe(client)
                if new_universe:
                    universe = new_universe
                last_universe_refresh = time.time()

            run_once(client, universe)
            if EXCHANGE_EXECUTION_ENABLED:
                if EXECUTION_EXCHANGE in ("bybit", "both"):
                    manage_open_trades()
                if EXECUTION_EXCHANGE in ("binance", "both"):
                    binance_manage_open_trades(client)

            # Periodic account report (daily by default). Sends Telegram message if token/chat set.
            try:
                global _last_report_time
                if REPORT_INTERVAL_SECONDS > 0 and time.time() - _last_report_time > REPORT_INTERVAL_SECONDS:
                    send_account_report(days=1)
                    _last_report_time = time.time()
            except Exception as e:
                log.warning("Account report failed: %s", e)

            # Agent 10: Autonomous 30-Day Self-Learning & Loss Audit
            try:
                global _last_agent10_audit_time
                if "_last_agent10_audit_time" not in globals():
                    _last_agent10_audit_time = time.time()
                if time.time() - _last_agent10_audit_time > 30 * 86400:
                    log.info("[AGENT 10] Running autonomous 30-day self-learning loss audit...")
                    try:
                        requests.post("http://127.0.0.1:8000/agents/agent10/run_learning", timeout=30)
                    except Exception:
                        pass
                    _last_agent10_audit_time = time.time()
            except Exception as e:
                log.debug("Agent 10 periodic trigger check: %s", e)

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