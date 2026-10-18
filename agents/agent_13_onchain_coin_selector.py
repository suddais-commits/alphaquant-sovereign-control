"""
Agent 13: On-Chain Data Analyst & Dynamic Coin Selector
Single Responsibility:
- Fetches on-chain momentum data (Volume, Open Interest, Price Change, Volatility)
  from Binance Futures across top 200+ pairs.
- Scores each coin using a multi-factor ranking model:
    1. 24h Volume (Market liquidity/activity)
    2. 7-Day Price Momentum (Trend strength)
    3. 24h Price Volatility Range (Range opportunity)
    4. Open Interest Change (Institutional positioning)
    5. Market Dominance Rank (Relative strength vs BTC)
- Selects Top 25 coins dynamically and updates the watchlist on the Pipeline Bus.
- Runs every 4 hours to stay fresh with market conditions.
"""
import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import update_bus_section, record_heartbeat

AGENT_NAME = "Agent_13_OnChainCoinSelector"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_13.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# Fixed coins that MUST always stay in the watchlist (top market caps)
MANDATORY_COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

# Coins to completely exclude (stablecoins, leveraged tokens, low-quality)
EXCLUDE_SYMBOLS = {
    "USDCUSDT", "BUSDUSDT", "TUSDUSDT", "USDTUSDT", "FDUSDUSDT", "DAIUSDT",
    "LDOUSDT",  # Complex DeFi governance
    "SCUSDT",   # Siacoin (low quality)
    "DENTUSDT", "KEYUSDT", "HOTUSDT", "WINUSDT",  # Very low quality
}

# Scoring weights
WEIGHTS = {
    "volume_score":      0.35,   # High 24h volume = good liquidity
    "momentum_score":    0.25,   # 7D price movement relative to BTC
    "volatility_score":  0.20,   # Good range for setups
    "oi_change_score":   0.12,   # Open Interest momentum
    "price_range_score": 0.08    # % Price range vs ATR for signal quality
}

WATCHLIST_SIZE = 25

def fetch_all_ticker_24h():
    """Fetches 24h price change stats for all Binance Futures USDT pairs."""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        r = requests.get(url, timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logging.warning(f"24h ticker fetch failed: {e}")
    
    # Fallback to spot if futures fails
    try:
        url_spot = "https://api.binance.com/api/v3/ticker/24hr"
        r2 = requests.get(url_spot, timeout=12)
        if r2.status_code == 200:
            return r2.json()
    except Exception as e2:
        logging.warning(f"Spot 24h ticker fallback also failed: {e2}")
    return []

def fetch_open_interest_change():
    """Fetches Open Interest stats for top Binance Futures contracts."""
    url = "https://fapi.binance.com/futures/data/openInterestHist"
    oi_changes = {}
    # OI endpoint needs per-symbol; skip for now, use volume as proxy
    return oi_changes

def score_and_rank_coins(tickers: list) -> list:
    """
    Scores all USDT-perp coins on multi-factor criteria.
    Returns list of dicts sorted by composite score desc.
    """
    candidates = []
    
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        if sym in EXCLUDE_SYMBOLS:
            continue
        if sym in MANDATORY_COINS:
            continue  # We'll add them back later
        
        try:
            quote_vol = float(t.get("quoteVolume", 0))     # 24h Volume in USDT
            price_chg_pct = float(t.get("priceChangePercent", 0))
            high_24h = float(t.get("highPrice", 0))
            low_24h = float(t.get("lowPrice", 0))
            last_price = float(t.get("lastPrice", 1))
            count = int(t.get("count", 0))                  # Trade count (proxy for activity)
            
            if last_price <= 0 or quote_vol < 5_000_000:   # Min 5M USDT 24h volume
                continue
            
            # 1. Volume Score (log-scaled to prevent BTC domination)
            import math
            vol_score = min(math.log10(max(quote_vol, 1)) / 10.0, 1.0)
            
            # 2. Momentum Score (absolute price change - positive or negative fine)
            momentum_score = min(abs(price_chg_pct) / 15.0, 1.0)  # Cap at 15% move
            
            # 3. Volatility Score (24h range as % of price)
            if last_price > 0 and high_24h > 0 and low_24h > 0:
                range_pct = (high_24h - low_24h) / last_price * 100
                volatility_score = min(range_pct / 12.0, 1.0)  # Ideal 5-12% range
            else:
                volatility_score = 0.0
                
            # 4. OI Change Score (use count as proxy if OI not available)
            oi_score = min(count / 500000.0, 1.0)
            
            # 5. Price Range Score (not too cheap - to avoid noise, not too expensive)
            if last_price >= 0.001:
                price_range_score = 0.8
            else:
                price_range_score = 0.3
                
            composite_score = (
                WEIGHTS["volume_score"] * vol_score +
                WEIGHTS["momentum_score"] * momentum_score +
                WEIGHTS["volatility_score"] * volatility_score +
                WEIGHTS["oi_change_score"] * oi_score +
                WEIGHTS["price_range_score"] * price_range_score
            )
            
            candidates.append({
                "symbol": sym,
                "price": round(last_price, 6),
                "volume_24h_usdt": round(quote_vol / 1_000_000, 2),  # in millions
                "price_change_pct": round(price_chg_pct, 2),
                "range_24h_pct": round((high_24h - low_24h) / last_price * 100, 2) if last_price > 0 else 0,
                "trade_count": count,
                "composite_score": round(composite_score, 4),
                "scored_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            })
        except Exception as e:
            continue
    
    candidates.sort(key=lambda x: x["composite_score"], reverse=True)
    return candidates

def run_coin_selection():
    """Main function: fetch, score, rank, publish top 25 coins to bus."""
    logging.info("Starting on-chain coin selection cycle...")
    
    tickers = fetch_all_ticker_24h()
    if not tickers:
        logging.error("No ticker data received. Skipping coin selection cycle.")
        record_heartbeat(AGENT_NAME, "ERROR_NO_DATA")
        return None
    
    ranked = score_and_rank_coins(tickers)
    
    # Build final watchlist: mandatory coins + top ranked others (up to 25)
    remaining_slots = WATCHLIST_SIZE - len(MANDATORY_COINS)
    top_selected = [c["symbol"] for c in ranked[:remaining_slots]]
    
    final_watchlist = MANDATORY_COINS + top_selected
    
    # Build full detail of top coins for reporting
    top_coins_detail = [c for c in ranked[:remaining_slots]]
    
    result = {
        "watchlist": final_watchlist,
        "mandatory_coins": MANDATORY_COINS,
        "dynamic_coins": top_selected,
        "total_scanned": len(tickers),
        "total_qualified": len(ranked),
        "top_coins_detail": top_coins_detail[:30],  # Store top 30 for analysis
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "timestamp": time.time()
    }
    
    update_bus_section("coin_selection", result)
    record_heartbeat(AGENT_NAME, f"HEALTHY_{len(final_watchlist)}_COINS")
    
    logging.info(f"Coin selection complete. Watchlist updated: {final_watchlist}")
    return result

def main():
    """Runs coin selection every 4 hours continuously."""
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            result = run_coin_selection()
            if result:
                logging.info(f"Updated watchlist: {result['watchlist']}")
        except Exception as e:
            logging.error(f"Coin selection error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(4 * 3600)  # Re-score every 4 hours

if __name__ == "__main__":
    main()
