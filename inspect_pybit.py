import inspect
from pybit.unified_trading import HTTP
import pybit.unified_trading.http as http_mod

print('HTTP class:', HTTP)
print('Module:', http_mod.__file__)
for name in ['_prepare_headers','_auth','_auth_binary','get_server_time','_request']:
    if hasattr(HTTP, name):
        print('\n===', name, '===')
        try:
            print(inspect.getsource(getattr(HTTP, name)))
        except Exception as e:
            print('SOURCE ERROR', e)
