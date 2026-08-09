import os
from dotenv import load_dotenv
import requests
from proxy_manager import get_proxy

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PROXIES = get_proxy()

if not TOKEN or not CHAT_ID:
    print("Token ya Chat ID .env file mein missing hai.")
else:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    if PROXIES:
        print("Using proxy for Telegram request.")
    try:
        resp = requests.post(url, json={"chat_id": CHAT_ID, "text": "Test message: bot connected successfully!"}, timeout=15, proxies=PROXIES)
        if resp.status_code == 200:
            print("Success! Apna Telegram app check karo.")
        else:
            print(f"Telegram error: {resp.status_code} - {resp.text}")
    except requests.exceptions.ConnectTimeout:
        print("ConnectTimeout - internet/firewall check karo.")
    except requests.exceptions.ProxyError as e:
        print(f"Proxy error: {e}")
    except Exception as e:
        print(f"Error: {e}")