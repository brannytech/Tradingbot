import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from tradingbot.server import Application,make_server
from tradingbot.security import Config
from tradingbot.storage import Store
from tradingbot.service import refresh

app=Application(Config(password="E2E-test-only-8767"),Store(":memory:"))
refresh(app,{"source":"SYNTHETIC"})
server=make_server(app,8767)
try:
    server.serve_forever()
finally:
    server.server_close()
    app.close()
