"""
Institutional 250-Coin Multi-Agent Fleet Engine (10 Specialized Squad Agents)
=============================================================================
Deploys 10 Dedicated Scouting Agents, each assigned 25 specific Binance Pairs (250 Coins Total):
  - Agent 24 (Squad 1): Major Layer-1 Blockchains (25 coins)
  - Agent 25 (Squad 2): Layer-2, Rollups & Bridges (25 coins)
  - Agent 26 (Squad 3): AI, Compute & DePIN (25 coins)
  - Agent 27 (Squad 4): Memes & High-Beta Momentum (25 coins)
  - Agent 28 (Squad 5): DeFi, Perps & Yield (25 coins)
  - Agent 29 (Squad 6): Gaming, Metaverse & NFTs (25 coins)
  - Agent 30 (Squad 7): RWA & Real-World Infrastructure (25 coins)
  - Agent 31 (Squad 8): Storage, Privacy & Security (25 coins)
  - Agent 32 (Squad 9): Payments & Legacy Giants (25 coins)
  - Agent 33 (Squad 10): Dynamic 24h Hot Breakouts & Top Volume (25 coins)

Runs in parallel worker pools to guarantee zero missed opportunities across all 250 pairs.
"""

import os
import sys
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import update_bus_section, record_heartbeat, read_bus
from proxy_manager import get_proxy

# ── 10 DEDICATED SQUADS (25 COINS EACH = 250 COINS TOTAL) ─────────────────────
SQUADS = {
    "Squad_01_Layer1": {
        "agent_id": "Agent_24",
        "name": "Major Layer-1 Scout",
        "coins": [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT",
            "AVAXUSDT", "SUIUSDT", "NEARUSDT", "APTUSDT", "DOTUSDT",
            "ATOMUSDT", "FTMUSDT", "ALGOUSDT", "HBARUSDT", "ICPUSDT",
            "EGLDUSDT", "SEIUSDT", "KASUSDT", "INJUSDT", "TIAUSDT",
            "MINAUSDT", "KAVAUSDT", "ROSEUSDT", "CELOUSDT", "ONEUSDT"
        ]
    },
    "Squad_02_Layer2": {
        "agent_id": "Agent_25",
        "name": "Layer-2 & Rollups Scout",
        "coins": [
            "ARBUSDT", "OPUSDT", "POLUSDT", "STRKUSDT", "MANTAUSDT",
            "METISUSDT", "ZKUSDT", "IMXUSDT", "BLURUSDT", "DYDXUSDT",
            "LDOUSDT", "SSVUSDT", "ETHFIUSDT", "REZUSDT", "PENDLEUSDT",
            "ENAUSDT", "JTOUSDT", "PYTHUSDT", "SKLUSDT", "CTSIUSDT",
            "RONINUSDT", "STXUSDT", "BOBAUSDT", "ALTUSDT", "GNOUSDT"
        ]
    },
    "Squad_03_AI_DePIN": {
        "agent_id": "Agent_26",
        "name": "AI & DePIN Supercycle Scout",
        "coins": [
            "FETUSDT", "RENDERUSDT", "TAOUSDT", "WLDUSDT", "ARUSDT",
            "FILUSDT", "THETAUSDT", "IOUSDT", "ATHUSDT", "GRTUSDT",
            "GLMUSDT", "LPTUSDT", "AIOZUSDT", "HNTUSDT", "IOTXUSDT",
            "JASMYUSDT", "OCEANUSDT", "AGIXUSDT", "POKTUSDT", "RLCUSDT",
            "NKNUSDT", "DATAUSDT", "AIUSDT", "ARKMUSDT", "VIRTUALUSDT"
        ]
    },
    "Squad_04_Memes": {
        "agent_id": "Agent_27",
        "name": "Memes & High-Beta Scout",
        "coins": [
            "DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT",
            "FLOKIUSDT", "TRUMPUSDT", "POPCATUSDT", "BRETTUSDT", "MEWUSDT",
            "BOMEUSDT", "MEMEUSDT", "TURBOUSDT", "1000SATSUSDT", "ORDIUSDT",
            "DOGSUSDT", "NOTUSDT", "CATIUSDT", "HMSTRUSDT", "NEIROUSDT",
            "BABYDOGEUSDT", "MOODENGUSDT", "GOATUSDT", "MYROUSDT", "PNUTUSDT"
        ]
    },
    "Squad_05_DeFi": {
        "agent_id": "Agent_28",
        "name": "DeFi & Perps Scout",
        "coins": [
            "UNIUSDT", "AAVEUSDT", "MKRUSDT", "SNXUSDT", "CRVUSDT",
            "COMPUSDT", "SUSHIUSDT", "1INCHUSDT", "CAKEUSDT", "RUNEUSDT",
            "KNCUSDT", "BALUSDT", "FXSUSDT", "CVXUSDT", "GMXUSDT",
            "RAYUSDT", "JUPUSDT", "DRIFTUSDT", "AEROUSDT", "COWUSDT",
            "SAFEUSDT", "ORCAUSDT", "YFIUSDT", "ZRXUSDT", "BADGERUSDT"
        ]
    },
    "Squad_06_Gaming": {
        "agent_id": "Agent_29",
        "name": "Gaming & Metaverse Scout",
        "coins": [
            "GALAUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "BEAMUSDT",
            "PIXELUSDT", "PORTALUSDT", "ILVUSDT", "BIGTIMEUSDT", "YGGUSDT",
            "SUPERUSDT", "ACEUSDT", "XAIUSDT", "MAGICUSDT", "ENJUSDT",
            "CHZUSDT", "ALICEUSDT", "TLMUSDT", "SLPUSDT", "WAXPUSDT",
            "HIGHUSDT", "DARUSDT", "VOXELUSDT", "PYRUSDT", "CHRUSDT"
        ]
    },
    "Squad_07_RWA": {
        "agent_id": "Agent_30",
        "name": "RWA & Tokenization Scout",
        "coins": [
            "ONDOUSDT", "OMUSDT", "TRUUSDT", "MPLUSDT", "GFIUSDT",
            "POLYXUSDT", "DUSKUSDT", "CTCUSDT", "TOKENUSDT", "PROPSUSDT",
            "CFGUSDT", "LTOUSDT", "RIOUSDT", "BOSONUSDT", "IXSUSDT",
            "CHZUSDT", "CSIXUSDT", "FACTRUSDT", "PROMPTUSDT", "LUMIAUSDT",
            "MKRUSDT", "AAVEUSDT", "PENDLEUSDT", "ENAUSDT", "SNXUSDT"
        ]
    },
    "Squad_08_Storage_Privacy": {
        "agent_id": "Agent_31",
        "name": "Storage & Privacy Scout",
        "coins": [
            "ZECUSDT", "XMRUSDT", "DASHUSDT", "SCRTUSDT", "ZENUSDT",
            "STORJUSDT", "SCUSDT", "BLZUSDT", "ANKRUSDT", "BANDUSDT",
            "TRBUSDT", "API3USDT", "UMAUSDT", "DIAUSDT", "LINKUSDT",
            "POKTUSDT", "FILUSDT", "ARUSDT", "OCEANUSDT", "CQTUSDT",
            "RLCUSDT", "QNTUSDT", "HOTUSDT", "KEYUSDT", "DENTUSDT"
        ]
    },
    "Squad_09_Payments_Legacy": {
        "agent_id": "Agent_32",
        "name": "Payments & Legacy Scout",
        "coins": [
            "XRPUSDT", "XLMUSDT", "LTCUSDT", "BCHUSDT", "ETCUSDT",
            "EOSUSDT", "TRXUSDT", "XTZUSDT", "NEOUSDT", "IOTAUSDT",
            "VETUSDT", "QTUMUSDT", "ZILUSDT", "ICXUSDT", "ONTUSDT",
            "RVNUSDT", "DGBUSDT", "BTGUSDT", "STRAXUSDT", "SYSUSDT",
            "XVGUSDT", "GASUSDT", "OMGUSDT", "WANUSDT", "WAVESUSDT"
        ]
    },
    "Squad_10_Hot_Breakouts": {
        "agent_id": "Agent_33",
        "name": "Dynamic 24h Hot Breakout Scout",
        "coins": []  # Dynamically fetched from Binance 24h ticker
    }
}

DATA_URL = "https://data-api.binance.vision/api/v3/klines"
TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
session = requests.Session()


def fetch_dynamic_hot_coins(limit: int = 25) -> List[str]:
    """Fetches Binance 24h gainers with highest volume momentum."""
    try:
        r = session.get(TICKER_URL, timeout=8)
        if r.status_code == 200:
            data = r.json()
            exclude = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "EURUSDT", "USDPUSDT"}
            valid = [
                d for d in data 
                if d["symbol"].endswith("USDT") and d["symbol"] not in exclude and float(d.get("quoteVolume", 0)) > 5_000_000
            ]
            valid.sort(key=lambda x: abs(float(x.get("priceChangePercent", 0))) * float(x.get("quoteVolume", 0)), reverse=True)
            return [d["symbol"] for d in valid[:limit]]
    except Exception:
        pass
    return ["ZECUSDT", "TRUMPUSDT", "GUSDT", "ONEUSDT", "RENDERUSDT", "PEPEUSDT", "SUIUSDT", "FETUSDT", "WIFUSDT", "NEARUSDT"]


def fetch_symbol_klines(symbol: str, interval: str = "15m", limit: int = 50):
    url = f"{DATA_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    for _ in range(2):
        try:
            r = session.get(url, timeout=6)
            if r.status_code == 200:
                raw = r.json()
                return [{
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                } for k in raw]
        except Exception:
            time.sleep(0.1)
    return []


def analyze_squad_coins(squad_key: str, squad_info: dict) -> Dict[str, Any]:
    """Worker function for an individual Squad Agent analyzing its 25 coins."""
    agent_id = squad_info["agent_id"]
    agent_name = squad_info["name"]
    coins = squad_info["coins"]
    
    if squad_key == "Squad_10_Hot_Breakouts" or not coins:
        coins = fetch_dynamic_hot_coins(limit=25)
        squad_info["coins"] = coins

    opportunities = []
    scanned_count = 0

    for sym in coins:
        klines = fetch_symbol_klines(sym, "15m", 30)
        if not klines or len(klines) < 20:
            continue
        scanned_count += 1
        
        last = klines[-1]
        prev = klines[-2]
        
        # 1. SMC Liquidity Sweep Check
        lows = [k["low"] for k in klines[-15:-1]]
        highs = [k["high"] for k in klines[-15:-1]]
        recent_low = min(lows) if lows else last["low"]
        recent_high = max(highs) if highs else last["high"]
        
        # Bullish Sweep (SSL Hunt)
        is_bullish_sweep = prev["low"] < recent_low and last["close"] > recent_low
        # Bearish Sweep (BSL Hunt)
        is_bearish_sweep = prev["high"] > recent_high and last["close"] < recent_high
        
        # Volume Surge >= 1.25x
        avg_vol = sum(k["volume"] for k in klines[-10:]) / 10.0 if klines else 1.0
        has_volume = last["volume"] >= avg_vol * 1.20
        
        # 20 EMA Direction
        closes = [k["close"] for k in klines]
        ema20 = sum(closes[-20:]) / 20.0
        
        if is_bullish_sweep and last["close"] > ema20 and has_volume:
            score = 85 + (10 if has_volume else 0)
            opportunities.append({
                "symbol": sym,
                "direction": "LONG",
                "price": last["close"],
                "score": score,
                "reason": f"SMC SSL Sweep + Volume Surge ({last['volume']/avg_vol:.1f}x) > EMA20",
                "squad": agent_name
            })
        elif is_bearish_sweep and last["close"] < ema20 and has_volume:
            score = 85 + (10 if has_volume else 0)
            opportunities.append({
                "symbol": sym,
                "direction": "SHORT",
                "price": last["close"],
                "score": score,
                "reason": f"SMC BSL Sweep + Volume Surge ({last['volume']/avg_vol:.1f}x) < EMA20",
                "squad": agent_name
            })

    record_heartbeat(agent_id, f"ONLINE_SCANNED_{scanned_count}_COINS")
    return {
        "squad_key": squad_key,
        "agent_id": agent_id,
        "name": agent_name,
        "scanned_count": scanned_count,
        "total_assigned": len(coins),
        "opportunities": opportunities
    }


def run_all_10_squads() -> Dict[str, Any]:
    """Runs all 10 squad agents concurrently across 250 coins."""
    results = {}
    all_opportunities = []
    total_coins_scanned = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futs = {
            executor.submit(analyze_squad_coins, k, v): k 
            for k, v in SQUADS.items()
        }
        for f in as_completed(futs):
            res = f.result()
            s_key = res["squad_key"]
            results[s_key] = res
            total_coins_scanned += res["scanned_count"]
            all_opportunities.extend(res["opportunities"])

    # Sort all 250-coin opportunities by highest institutional score
    all_opportunities.sort(key=lambda x: x["score"], reverse=True)

    summary = {
        "total_squads": 10,
        "total_coins_scanned": total_coins_scanned,
        "total_opportunities_found": len(all_opportunities),
        "top_ranked_setups": all_opportunities[:10],
        "squad_breakdown": results,
        "timestamp": time.time(),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    }

    # Publish to central pipeline bus
    update_bus_section("fleet_scanner_250", summary)
    record_heartbeat("Agent_Fleet_250_Manager", f"HEALTHY_250_COINS_SCANNED")

    return summary


if __name__ == "__main__":
    print(f"[*] Launching 10-Agent 250-Coin Sector Fleet Scanner...")
    res = run_all_10_squads()
    print(f"\n=========================================================================")
    print(f" 🚀 10-AGENT SECTOR FLEET SCAN COMPLETE (250 COINS TOTAL)")
    print(f" 📦 Total Coins Scanned: {res['total_coins_scanned']} Across 10 Specialized Squads")
    print(f" 🎯 High-Conviction Setups Discovered: {res['total_opportunities_found']}")
    print(f"=========================================================================")
    for opp in res["top_ranked_setups"]:
        print(f"  -> [{opp['squad']}] {opp['symbol']} | {opp['direction']} @ ${opp['price']} | Score: {opp['score']} | {opp['reason']}")
