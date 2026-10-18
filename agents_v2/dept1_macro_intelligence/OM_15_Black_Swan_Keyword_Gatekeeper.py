"""
Agent 23: News Sentiment Gatekeeper
Single Responsibility:
- Polls CoinDesk and Cointelegraph RSS feeds every 10 minutes.
- Scores headlines using keyword-based BULLISH / BEARISH / NEUTRAL classification.
- If CRITICAL BEARISH news detected (e.g. "hack", "exploit", "SEC", "ban", "crash"):
    → Blocks new entries immediately.
- Provides a macro sentiment score (0-100) to Gemini Conviction Scorer.
- Writes news_sentiment section to Pipeline Bus.
"""
import os
import sys
import time
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_bus import update_bus_section, record_heartbeat, push_notification

AGENT_NAME = "Agent_23_NewsSentimentGatekeeper"
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "agent_23.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

# Keywords that indicate critical bearish events
CRITICAL_BEARISH_KEYWORDS = [
    "hack", "exploit", "breach", "stolen", "rug pull", "scam",
    "sec charges", "sec lawsuit", "ban", "regulate", "arrest",
    "crash", "collapse", "bankrupt", "insolvent", "emergency",
    "systemic risk", "contagion", "margin call", "liquidation crisis"
]

BULLISH_KEYWORDS = [
    "etf approved", "etf launch", "institutional", "adoption", "partnership",
    "upgrade", "mainnet", "bullish", "rally", "breakout", "accumulation",
    "spot etf", "halving", "treasury", "reserve", "all-time high", "ath"
]

BEARISH_KEYWORDS = [
    "regulation", "warning", "risk", "decline", "drop", "fall",
    "bearish", "sell-off", "outflow", "fear", "uncertainty", "delay"
]

_NEWS_CACHE = {"articles": [], "timestamp": 0}
NEWS_CACHE_TTL = 600  # 10 minutes


def fetch_rss(url: str, max_items: int = 10) -> list:
    """Fetch and parse RSS feed, return list of {'title': ..., 'pubDate': ...}."""
    articles = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 CryptoBotNewsReader/1.0"}
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            return articles

        root = ET.fromstring(r.content)
        channel = root.find("channel")
        if channel is None:
            return articles

        for item in channel.findall("item")[:max_items]:
            title = item.findtext("title", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            articles.append({
                "title": title.lower(),
                "description": description.lower()[:200],
                "pubDate": pub_date,
                "source": url.split("/")[2]
            })
    except Exception as e:
        logging.warning(f"RSS fetch error [{url}]: {e}")
    return articles


def score_headline(title: str, description: str = "") -> dict:
    """Score a headline as BULLISH/BEARISH/NEUTRAL/CRITICAL_BEARISH."""
    text = f"{title} {description}".lower()

    # Check critical bearish first (highest priority)
    for kw in CRITICAL_BEARISH_KEYWORDS:
        if kw in text:
            return {"sentiment": "CRITICAL_BEARISH", "score": 0, "keyword": kw}

    bullish_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bearish_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in text)

    if bullish_hits > bearish_hits:
        score = min(100, 55 + bullish_hits * 8)
        return {"sentiment": "BULLISH", "score": score}
    elif bearish_hits > bullish_hits:
        score = max(0, 45 - bearish_hits * 8)
        return {"sentiment": "BEARISH", "score": score}
    else:
        return {"sentiment": "NEUTRAL", "score": 50}


def process_news_sentiment():
    global _NEWS_CACHE
    now = time.time()

    # Use cache if fresh
    if _NEWS_CACHE["articles"] and (now - _NEWS_CACHE["timestamp"] < NEWS_CACHE_TTL):
        all_articles = _NEWS_CACHE["articles"]
    else:
        all_articles = []
        for feed in RSS_FEEDS:
            articles = fetch_rss(feed)
            all_articles.extend(articles)
            time.sleep(0.5)
        _NEWS_CACHE = {"articles": all_articles, "timestamp": now}

    if not all_articles:
        update_bus_section("news_sentiment", {
            "overall_sentiment": "NEUTRAL",
            "macro_score": 50,
            "critical_bearish": False,
            "new_entries_allowed": True,
            "articles_analyzed": 0
        })
        record_heartbeat(AGENT_NAME, "IDLE_NO_ARTICLES")
        return

    # Score all articles
    scored = []
    critical_bearish_detected = False
    critical_keyword = None

    for art in all_articles:
        result = score_headline(art["title"], art.get("description", ""))
        result["title"] = art["title"][:80]
        result["source"] = art.get("source", "")
        scored.append(result)

        if result["sentiment"] == "CRITICAL_BEARISH":
            critical_bearish_detected = True
            critical_keyword = result.get("keyword", "unknown")

    # Aggregate sentiment
    scores = [s["score"] for s in scored]
    macro_score = round(sum(scores) / len(scores), 1) if scores else 50.0

    sentiments = [s["sentiment"] for s in scored]
    bullish_count = sentiments.count("BULLISH")
    bearish_count = sentiments.count("BEARISH")
    critical_count = sentiments.count("CRITICAL_BEARISH")

    if critical_bearish_detected:
        overall_sentiment = "CRITICAL_BEARISH"
        new_entries_allowed = False
        push_notification(
            "CRITICAL BEARISH NEWS",
            f"⚠️ DANGER: Critical bearish news detected!\nKeyword: '{critical_keyword}'\nNew entries BLOCKED.",
            level="CRITICAL"
        )
    elif macro_score >= 65:
        overall_sentiment = "BULLISH"
        new_entries_allowed = True
    elif macro_score <= 35:
        overall_sentiment = "BEARISH"
        new_entries_allowed = True  # Still allow but score will be lower
    else:
        overall_sentiment = "NEUTRAL"
        new_entries_allowed = True

    result_data = {
        "overall_sentiment": overall_sentiment,
        "macro_score": macro_score,
        "critical_bearish": critical_bearish_detected,
        "critical_keyword": critical_keyword,
        "new_entries_allowed": new_entries_allowed,
        "articles_analyzed": len(scored),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "critical_count": critical_count,
        "top_headlines": [s["title"] for s in scored[:5]],
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S UTC")
    }

    update_bus_section("news_sentiment", result_data)
    record_heartbeat(AGENT_NAME, f"HEALTHY | {overall_sentiment} | Score: {macro_score}")
    logging.info(
        f"News Sentiment: {overall_sentiment} | Score: {macro_score} | "
        f"Bullish: {bullish_count} | Bearish: {bearish_count} | Critical: {critical_count}"
    )


def main():
    logging.info(f"{AGENT_NAME} started.")
    while True:
        try:
            process_news_sentiment()
        except Exception as e:
            logging.error(f"Error: {e}")
            record_heartbeat(AGENT_NAME, f"ERROR: {e}")
        time.sleep(600)  # Run every 10 minutes

if __name__ == "__main__":
    main()
