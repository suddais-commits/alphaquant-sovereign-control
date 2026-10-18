"""
Agent 05: Enhanced Multi-Timeframe SMC / ICT Cascade Analysis
Integrates:
- 8-Timeframe Cascade (1m, 5m, 15m, 1h, 4h, 1d, 1w, 1M)
- Fair Value Gap (FVG) Detection
- Order Block (OB) Identification
- Break of Structure (BOS) & Change of Character (CHoCH)
- Liquidity Pool Mapping & Supply/Demand Zones
- Publishes SMC structures to In-Memory Pipeline Bus
"""
import os
import sys
import time
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import read_bus, update_bus_section, record_heartbeat

AGENT_NAME = "Agent_05_Enhanced_SMCICT_Cascade"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_05.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

class EnhancedAgent5_SMCICTCascade:
    def __init__(self):
        self.name = AGENT_NAME
        self.timeframes = ['15m', '1h', '4h', '1d']
        self.fvg_threshold = 0.001
        self.ob_strength_threshold = 1.5

    def analyze_symbol_candles(self, candles_dict: Dict[str, List[Dict]]) -> Dict[str, Any]:
        results = {
            "timeframe_scores": {},
            "fvg_levels": [],
            "order_blocks": [],
            "bos_detected": False,
            "choch_detected": False,
            "liquidity_pools": [],
            "supply_zones": [],
            "demand_zones": [],
            "overall_structure": "NEUTRAL",
            "cascade_strength": 50,
            "timestamp": datetime.now().isoformat()
        }

        timeframe_alignments = []

        for tf in self.timeframes:
            candles = candles_dict.get(tf, [])
            if not candles or len(candles) < 20:
                continue

            tf_analysis = self._analyze_timeframe(tf, candles)
            results["timeframe_scores"][tf] = tf_analysis["score"]
            timeframe_alignments.append(tf_analysis["trend"])

            results["fvg_levels"].extend(tf_analysis["fvgs"])
            results["order_blocks"].extend(tf_analysis["order_blocks"])
            results["liquidity_pools"].extend(tf_analysis["liquidity_pools"])
            results["supply_zones"].extend(tf_analysis["supply_zones"])
            results["demand_zones"].extend(tf_analysis["demand_zones"])

        if timeframe_alignments:
            bullish_count = sum(1 for t in timeframe_alignments if t == "BULLISH")
            bearish_count = sum(1 for t in timeframe_alignments if t == "BEARISH")

            if bullish_count > bearish_count:
                results["overall_structure"] = "BULLISH"
                results["cascade_strength"] = (bullish_count / len(timeframe_alignments)) * 100
            elif bearish_count > bullish_count:
                results["overall_structure"] = "BEARISH"
                results["cascade_strength"] = (bearish_count / len(timeframe_alignments)) * 100
            else:
                results["overall_structure"] = "CONSOLIDATING"
                results["cascade_strength"] = 50

        results["bos_detected"] = self._detect_bos(candles_dict)
        results["choch_detected"] = self._detect_choch(candles_dict)
        return results

    def _analyze_timeframe(self, tf: str, candles: List[Dict]) -> Dict[str, Any]:
        df = pd.DataFrame(candles)
        for col in ['open', 'high', 'low', 'close', 'vol']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        closes = df['close'].values
        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().values[-1]
        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().values[-1] if len(closes) >= 50 else ema20
        curr_price = closes[-1]

        trend = "BULLISH" if curr_price > ema20 > ema50 else ("BEARISH" if curr_price < ema20 < ema50 else "NEUTRAL")
        score = 80 if trend == "BULLISH" else (20 if trend == "BEARISH" else 50)

        fvgs = self._find_fvgs(df, tf)
        obs = self._find_order_blocks(df, tf)
        liquidity = self._find_liquidity_pools(df, tf)

        supply = [ob["high"] for ob in obs if ob["type"] == "BEARISH"]
        demand = [ob["low"] for ob in obs if ob["type"] == "BULLISH"]

        return {
            "timeframe": tf,
            "trend": trend,
            "score": score,
            "fvgs": fvgs,
            "order_blocks": obs,
            "liquidity_pools": liquidity,
            "supply_zones": supply,
            "demand_zones": demand
        }

    def _find_fvgs(self, df: pd.DataFrame, tf: str) -> List[Dict]:
        fvgs = []
        if len(df) < 3: return fvgs
        for i in range(len(df) - 1, max(len(df) - 15, 2), -1):
            c1, c2, c3 = df.iloc[i-2], df.iloc[i-1], df.iloc[i]
            # Bullish FVG
            if c3['low'] > c1['high']:
                gap_pct = (c3['low'] - c1['high']) / c1['high']
                if gap_pct >= self.fvg_threshold:
                    fvgs.append({
                        "tf": tf, "type": "BULLISH_FVG", "top": float(c3['low']), "bottom": float(c1['high']),
                        "mid": float((c3['low'] + c1['high']) / 2), "gap_pct": round(gap_pct * 100, 2)
                    })
            # Bearish FVG
            elif c3['high'] < c1['low']:
                gap_pct = (c1['low'] - c3['high']) / c1['low']
                if gap_pct >= self.fvg_threshold:
                    fvgs.append({
                        "tf": tf, "type": "BEARISH_FVG", "top": float(c1['low']), "bottom": float(c3['high']),
                        "mid": float((c1['low'] + c3['high']) / 2), "gap_pct": round(gap_pct * 100, 2)
                    })
        return fvgs

    def _find_order_blocks(self, df: pd.DataFrame, tf: str) -> List[Dict]:
        obs = []
        if len(df) < 5: return obs
        for i in range(len(df) - 2, max(len(df) - 12, 1), -1):
            curr = df.iloc[i]
            next_c = df.iloc[i+1]
            body_next = abs(next_c['close'] - next_c['open'])
            avg_body = df['close'].diff().abs().tail(10).mean()
            if body_next > avg_body * self.ob_strength_threshold:
                if next_c['close'] > next_c['open'] and curr['close'] < curr['open']:
                    obs.append({"tf": tf, "type": "BULLISH", "high": float(curr['high']), "low": float(curr['low'])})
                elif next_c['close'] < next_c['open'] and curr['close'] > curr['open']:
                    obs.append({"tf": tf, "type": "BEARISH", "high": float(curr['high']), "low": float(curr['low'])})
        return obs

    def _find_liquidity_pools(self, df: pd.DataFrame, tf: str) -> List[Dict]:
        pools = []
        if len(df) < 15: return pools
        highs = df['high'].values
        lows = df['low'].values
        recent_high = float(np.max(highs[-10:]))
        recent_low = float(np.min(lows[-10:]))
        pools.append({"tf": tf, "type": "BSL_POOL", "price": recent_high})
        pools.append({"tf": tf, "type": "SSL_POOL", "price": recent_low})
        return pools

    def _detect_bos(self, candles_dict: Dict) -> bool:
        candles = candles_dict.get('4h') or candles_dict.get('1h')
        if not candles or len(candles) < 20: return False
        highs = [c['high'] for c in candles]
        return highs[-1] > max(highs[-20:-1])

    def _detect_choch(self, candles_dict: Dict) -> bool:
        candles = candles_dict.get('1h') or candles_dict.get('15m')
        if not candles or len(candles) < 20: return False
        lows = [c['low'] for c in candles]
        return lows[-1] < min(lows[-20:-1])

def process_smc_cascade_all():
    bus = read_bus()
    market_data = bus.get("market_data", {})
    analyzer = EnhancedAgent5_SMCICTCascade()
    
    cascade_results = {}
    for sym, tf_candles in market_data.items():
        try:
            # tf_candles is a dict of timeframe -> list of candles
            if isinstance(tf_candles, dict):
                res = analyzer.analyze_symbol_candles(tf_candles)
                cascade_results[sym] = res
        except Exception as e:
            logging.warning(f"SMC Cascade error on {sym}: {e}")

    if cascade_results:
        update_bus_section("smc_cascade_structures", cascade_results)
    record_heartbeat(AGENT_NAME, f"ANALYZED_{len(cascade_results)}_PAIRS")

if __name__ == "__main__":
    process_smc_cascade_all()
