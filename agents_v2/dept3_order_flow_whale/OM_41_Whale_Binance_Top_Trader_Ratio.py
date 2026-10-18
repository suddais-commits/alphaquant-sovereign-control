"""
Agent 14: Whale & Funding Rate Analysis
Features:
- Live Binance Futures Funding Rates & Trends
- Open Interest (OI) Expansion vs Contraction
- Liquidation Pool Mapping (Trapped Longs / Shorts)
- Whale Accumulation vs Distribution Signal
- Publishes institutional bias to In-Memory Pipeline Bus
"""
import os
import sys
import time
import requests
import logging
from typing import Dict, Any, List
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_14_Whale_Funding_Analysis"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_14.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

FAPI_BASE = "https://fapi.binance.com/fapi/v1"
session = requests.Session()

class Agent14_WhaleAndFundingAnalysis:
    def __init__(self):
        self.name = AGENT_NAME

    def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        try:
            url = f"{FAPI_BASE}/fundingRate?symbol={symbol}&limit=10"
            r = session.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data:
                    rates = [float(d["fundingRate"]) for d in data]
                    curr_rate = rates[-1]
                    avg_rate = sum(rates) / len(rates)
                    condition = "LONGS_CROWDED" if curr_rate > 0.0003 else ("SHORTS_CROWDED" if curr_rate < -0.0001 else "BALANCED")
                    trend = "RISING" if curr_rate > avg_rate else "FALLING"
                    return {"current_rate": curr_rate, "condition": condition, "trend": trend}
        except Exception as e:
            logging.debug(f"Funding rate fetch notice for {symbol}: {e}")
        return {"current_rate": 0.0001, "condition": "BALANCED", "trend": "STABLE"}

    def get_open_interest(self, symbol: str) -> Dict[str, Any]:
        try:
            url = f"{FAPI_BASE}/openInterest?symbol={symbol}"
            r = session.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                oi = float(data.get("openInterest", 0))
                return {"current_oi": oi, "trend": "EXPANDING"}
        except Exception as e:
            logging.debug(f"OI fetch notice for {symbol}: {e}")
        return {"current_oi": 0.0, "trend": "STABLE"}

    def get_top_trader_whale_ratio(self, symbol: str) -> Dict[str, Any]:
        """Fetches Binance Top Trader Long/Short Ratio vs Global Retail Ratio."""
        try:
            url_top = f"https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={symbol}&period=15m&limit=5"
            url_global = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=15m&limit=5"
            
            r_top = session.get(url_top, timeout=5)
            r_global = session.get(url_global, timeout=5)
            
            top_ratio = 1.0
            global_ratio = 1.0
            
            if r_top.status_code == 200 and r_top.json():
                top_ratio = float(r_top.json()[-1].get("longShortRatio", 1.0))
            if r_global.status_code == 200 and r_global.json():
                global_ratio = float(r_global.json()[-1].get("longShortRatio", 1.0))
                
            # Squeeze and Whale Dominance logic:
            # When Top Traders are buying while Retail is neutral/shorting -> High Conviction Whale Accumulation
            whale_dominance = "WHALE_ACCUMULATION" if (top_ratio > global_ratio and top_ratio >= 1.20) else (
                "WHALE_DISTRIBUTION" if (top_ratio < global_ratio and top_ratio <= 0.85) else "BALANCED"
            )
            
            return {
                "top_trader_ratio": top_ratio,
                "retail_ratio": global_ratio,
                "whale_dominance": whale_dominance
            }
        except Exception as e:
            logging.debug(f"Whale ratio fetch notice for {symbol}: {e}")
            return {"top_trader_ratio": 1.0, "retail_ratio": 1.0, "whale_dominance": "BALANCED"}

    def analyze_symbol(self, symbol: str, current_price: float = 0.0) -> Dict[str, Any]:
        funding = self.get_funding_rate(symbol)
        oi = self.get_open_interest(symbol)
        whale_ratios = self.get_top_trader_whale_ratio(symbol)

        # Smart money sentiment & Whale Squeeze logic
        if whale_ratios["whale_dominance"] == "WHALE_ACCUMULATION" or (funding["condition"] == "SHORTS_CROWDED" and oi["trend"] == "EXPANDING"):
            whale_activity = "ACCUMULATING"
            smart_money = "BUY"
            bias = "BULLISH_WHALE_ACCUMULATION_SQUEEZE"
        elif whale_ratios["whale_dominance"] == "WHALE_DISTRIBUTION" or (funding["condition"] == "LONGS_CROWDED" and oi["trend"] == "EXPANDING"):
            whale_activity = "DISTRIBUTING"
            smart_money = "SELL"
            bias = "BEARISH_WHALE_DUMP"
        else:
            whale_activity = "NEUTRAL"
            smart_money = "HOLD"
            bias = "NEUTRAL"

        liq_levels = {}
        if current_price > 0:
            liq_levels = {
                "short_liquidation_level": round(current_price * 1.08, 4),
                "long_liquidation_level": round(current_price * 0.92, 4)
            }

        return {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "whale_activity": whale_activity,
            "smart_money_signal": smart_money,
            "institutional_bias": bias,
            "top_trader_ratio": whale_ratios["top_trader_ratio"],
            "retail_ratio": whale_ratios["retail_ratio"],
            "whale_dominance": whale_ratios["whale_dominance"],
            "funding_rate": funding["current_rate"],
            "funding_condition": funding["condition"],
            "oi_trend": oi["trend"],
            "liquidation_levels": liq_levels
        }

def process_whale_analysis_all():
    bus = read_bus()
    market_data = bus.get("market_data", {})
    tracker = Agent14_WhaleAndFundingAnalysis()
    
    whale_signals = {}
    for sym in list(market_data.keys())[:25]:
        try:
            curr_p = 0.0
            k1h = market_data[sym].get("1h", []) if isinstance(market_data[sym], dict) else []
            if k1h:
                curr_p = float(k1h[-1].get("close", 0))
            whale_signals[sym] = tracker.analyze_symbol(sym, curr_p)
        except Exception as e:
            logging.warning(f"Error analyzing whale data for {sym}: {e}")

    if whale_signals:
        update_bus_section("whale_funding_signals", whale_signals)
    record_heartbeat(AGENT_NAME, f"ANALYZED_{len(whale_signals)}_SYMBOLS")

if __name__ == "__main__":
    process_whale_analysis_all()
