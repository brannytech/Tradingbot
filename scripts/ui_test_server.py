"""Disposable in-memory UI test instance, isolated from the owner's database."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from tradingbot.server import Application,make_server
from tradingbot.security import Config
from tradingbot.storage import Store
from tradingbot.service import refresh

app=Application(Config(password="UI-test-only-8766"),Store(":memory:"))
refresh(app,{"source":"SYNTHETIC"})
server=make_server(app,8766)
print("Disposable UI test server at http://127.0.0.1:8766; isolated in-memory database",flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
    app.close()
