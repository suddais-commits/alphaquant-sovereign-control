#!/bin/bash
# Oracle Cloud / Ubuntu 22.04 deployment helper (copy to server and run as ubuntu user)
# Usage: paste on the Ubuntu VM terminal after SSH and adjust GIT_REPO_URL and APP_DIR

GIT_REPO_URL="https://github.com/YOUR_USERNAME/YOUR_REPO.git"  # <-- change
APP_DIR="$HOME/CryptoBot"

set -e

# 1) System update
sudo apt update && sudo apt upgrade -y

# 2) Install required packages
sudo apt install -y python3 python3-venv python3-pip git tmux
sudo apt install -y build-essential

# 3) Clone your repo (or pull if already exists)
if [ -d "$APP_DIR" ]; then
  echo "Repo exists, pulling latest"
  cd "$APP_DIR"
  git pull
else
  git clone "$GIT_REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi

# 4) Create virtualenv and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pybit

# 5) Create .env (edit values below or use an editor to paste)
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
# Example .env - UPDATE with your keys before running
BINANCE_API_KEY=
BINANCE_API_SECRET=
BYBIT_API_KEY=YOUR_BYBIT_DEMO_KEY
BYBIT_API_SECRET=YOUR_BYBIT_DEMO_SECRET
BYBIT_CATEGORY=linear
EXCHANGE_EXECUTION_ENABLED=false
ACCOUNT_SIZE_USDT=5962
RISK_PER_TRADE_PCT=1.0
SCORE_THRESHOLD=70
TIMEFRAME=1h
LOOP_INTERVAL_SECONDS=900
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
MANUAL_WATCHLIST_ENABLED=false
EOF
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE - edit it with your secrets (vim/nano)"
else
  echo "$ENV_FILE already exists - edit it if needed"
fi

# 6) Run once to test (interactive)
echo "To test now run: source venv/bin/activate && python master_bot.py"

echo "If you want to create systemd service, run the instructions in cryptobot.service.template as sudo"
