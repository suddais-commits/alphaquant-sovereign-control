# Sweep & Reclaim Bot — Setup (24/7 Laptop Method)

## 1. Folder banayein
Ek naya folder banayein (e.g. `C:\CryptoBot\`) aur ye 4 files usme daal dein:
- `sweep_reclaim_signal.py`
- `requirements.txt`
- `.env.example`
- `run_bot.bat`

## 2. Naya Telegram token lein
Purana token revoke ho chuka tha, isliye BotFather se naya token lein:
1. Telegram mein `@BotFather` open karein
2. `/mybots` -> apna bot select karein -> `API Token` -> `Revoke current token` (agar zaroorat ho) ya seedha naya token copy karein
3. `.env.example` ko rename karke `.env` banayein
4. `.env` file open karein aur `TELEGRAM_BOT_TOKEN=` ke aage apna naya token paste karein

**Important:** token kabhi bhi chat mein paste na karein — sirf `.env` file mein.

## 3. Python libraries install karein
Command Prompt kholein, folder mein jayein, phir:

```
cd C:\CryptoBot
pip install -r requirements.txt
```

## 4. Test run karein (pehle manually)

```
python sweep_reclaim_signal.py
```

Agar sahi chal raha hai, aapko console mein har symbol ke liye "no sweep+reclaim" ya signal lines dikhengi, aur `bot_log.txt` file bhi ban jayegi.
Ctrl+C dabaakar rok dein test ke baad.

## 5. Telegram connection test
Agar pehle wala `ConnectTimeoutError` (api.telegram.org tak connection) dobara aaye:
- Check karein Windows Firewall bot ke liye Python ko block to nahi kar raha
- Browser mein `https://api.telegram.org` khol ke dekhein load hota hai ya nahi
- VPN chal raha ho to disable karke try karein

## 6. 24/7 ke liye run_bot.bat use karein
Manual `python` command ki jagah, `run_bot.bat` ko double-click karke chalayein — ye crash hone par khud restart kar dega.

## 7. Laptop ko sona (sleep) na dein
Windows Settings -> System -> Power & Battery:
- "Screen and sleep" -> "When plugged in, put device to sleep" -> **Never**
- Laptop hamesha charger pe laga rehna chahiye

## 8. (Optional) Auto-start on boot
`run_bot.bat` ka shortcut bana kar is folder mein daal dein:
`shell:startup` (Win+R mein type karein, Enter dabayein)
Isse laptop restart hone par bot khud shuru ho jayega.

---
**Note:** Ye bot sirf *alerts* bhejta hai (pattern detect karke Telegram pe message) — khud se koi trade place nahi karta. Signal ko chart pe khud confirm karke hi trade lein.
