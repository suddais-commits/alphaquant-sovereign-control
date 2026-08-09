import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()
key = os.getenv('BYBIT_API_KEY','')
secret = os.getenv('BYBIT_API_SECRET','')
print('KEY_PRESENT', bool(key), 'SECRET_PRESENT', bool(secret))
session = HTTP(demo=True, api_key=key, api_secret=secret, recv_window=120000, max_retries=2)
print('server_time', session.get_server_time())
try:
    print('wallet_balance', session.get_wallet_balance(accountType='UNIFIED'))
except Exception as e:
    print('wallet_balance_error', repr(e))
