"""Public read-only V5 adapter. Private adapter is restricted to demo GETs."""
import hashlib
import hmac
import json
import time
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from typing import Any
from .models import Candle, Context


class NoPrivateRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Private API redirect blocked", headers, fp)


def private_urlopen(request, timeout=12):
    # Preserve TLS verification and never forward keys/tokens to redirect targets.
    return build_opener(NoPrivateRedirect()).open(request, timeout=timeout)


class Bybit:
    PUBLIC = "https://api.bybitglobal.com"
    DEMO = "https://api-demo.bybitglobal.com"

    def __init__(self, opener=urlopen, sleeper=time.sleep):
        self.opener, self.sleeper = opener, sleeper

    def get(self, path, params=None):
        if not path.startswith("/v5/market/"):
            raise ValueError("Only public market GETs permitted")
        req = Request(self.PUBLIC+path+"?"+urlencode(params or {}), headers={"User-Agent": "StrategyIntelligence/0.1"})
        for attempt in range(3):
            try:
                with self.opener(req, timeout=12) as response:
                    data = json.load(response)
                if data.get("retCode") in (10006, 10016):
                    if attempt == 2:
                        raise RuntimeError("Bybit rate limit / service unavailable")
                    self.sleeper(2**attempt)
                    continue
                if data.get("retCode") != 0:
                    raise RuntimeError(f"Bybit market error code {data.get('retCode')}")
                return data
            except (URLError, TimeoutError, HTTPError):
                if attempt == 2:
                    raise
                self.sleeper(2**attempt)
        raise RuntimeError("Market request failed")

    def catalog(self, market="linear", symbol=None):
        if market not in ("spot", "linear", "inverse", "option"):
            raise ValueError("Unsupported market")
        params: dict[str, Any] = dict(category=market)
        if market != "spot":
            params["limit"] = 1000
        if market == "option":
            params["baseCoin"] = "All"
        if symbol:
            params["symbol"] = symbol
        result: list[dict[str,Any]] = []
        seen = set()
        while True:
            page = self.get("/v5/market/instruments-info", params)["result"]
            result.extend(x for x in page["list"] if x.get("status") == "Trading"
                          and (not symbol or x.get("symbol") == symbol))
            cursor = page.get("nextPageCursor")
            if not cursor:
                break
            if cursor in seen:
                raise ValueError("Repeated instrument cursor")
            seen.add(cursor)
            params["cursor"] = cursor
        for row in result:
            tick = Decimal(row["priceFilter"]["tickSize"])
            if not tick.is_finite() or tick <= 0:
                raise ValueError("Invalid instrument precision")
        unique: dict[str, dict[str, Any]] = {}
        for row in result:
            name = row["symbol"]
            if name in unique and unique[name] != row:
                raise ValueError("Conflicting instrument metadata")
            unique[name] = row
        return [unique[name] for name in sorted(unique)]

    def instruments(self, market="linear", symbol=None):
        if market not in ("spot", "linear"):
            raise ValueError("Unsupported analysis market")
        return [row for row in self.catalog(market, symbol)
                if market == "spot" or (row.get("quoteCoin") == "USDT"
                                       and row.get("contractType") == "LinearPerpetual")]

    def candles(self, symbol="BTCUSDT", market="linear", interval=300, count=1000, now=None):
        if market not in ("spot", "linear") or interval not in (60, 180, 300, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400):
            raise ValueError("Unsupported market / interval")
        if not 1 <= count <= 100000:
            raise ValueError("count outside supported bounds")
        now = int(time.time()) if now is None else now
        value = "D" if interval == 86400 else str(interval//60)
        end = now*1000
        rows: dict[int,Candle] = {}
        while len(rows) < count:
            page = self.get("/v5/market/kline", dict(category=market, symbol=symbol,
                       interval=value, limit=min(1000, count-len(rows)+1), end=end))["result"]["list"]
            if not page:
                break
            earliest = min(int(x[0]) for x in page)
            for r in page:
                close_time = int(r[0])//1000+interval
                if close_time <= now:
                    c = Candle(close_time, *map(float, r[1:6]))
                    if close_time in rows and rows[close_time] != c:
                        raise ValueError("Conflicting historical candles")
                    rows[close_time] = c
            if earliest > end:
                raise ValueError("Nonprogressing candle pagination")
            end = earliest-1
        candles = sorted(rows.values(), key=lambda x: x.timestamp)[-count:]
        return Context(candles, symbol, market, interval, now).checked()

    def orderflow(self, symbol, market):
        book = self.get("/v5/market/orderbook", dict(category=market, symbol=symbol, limit=50))["result"]
        trades = self.get("/v5/market/recent-trade", dict(category=market, symbol=symbol, limit=100))["result"]["list"]
        ticker = self.get("/v5/market/tickers", dict(category=market, symbol=symbol))["result"]["list"][0]
        result = dict(timestamp=int(book["ts"])//1000, instrument=symbol, market=market,
                      bids=[[float(p), float(q)] for p, q in book["b"]],
                      asks=[[float(p), float(q)] for p, q in book["a"]],
                      trades=[dict(timestamp=int(t["time"])//1000, side=t["side"],
                                   price=float(t["price"]), volume=float(t["size"])) for t in trades],
                      coverage="RECENT_WINDOW_ONLY", liquidation_data=None)
        if market == "linear":
            oi = self.get("/v5/market/open-interest", dict(category=market, symbol=symbol, intervalTime="5min", limit=2))["result"]["list"]
            result.update(funding_rate=float(ticker.get("fundingRate", 0)),
                          open_interest=[dict(value=float(x["openInterest"]), timestamp=int(x["timestamp"])//1000) for x in oi])
        return result


def round_down(value, step):
    step = Decimal(str(step))
    if step <= 0:
        raise ValueError("Invalid precision")
    return (Decimal(str(value))/step).to_integral_value(rounding=ROUND_DOWN)*step


class DemoAPIError(RuntimeError):
    def __init__(self, code):
        self.code = code if type(code) is int else None
        super().__init__("Demo API rejected request")


class DemoAccount:
    """Authenticated demo reads only. No production host / order submission path."""
    ALLOWED = {"/v5/account/wallet-balance", "/v5/position/list", "/v5/order/realtime", "/v5/order/history", "/v5/execution/list"}

    def __init__(self, key, secret, opener=private_urlopen):
        if not key or not secret:
            raise ValueError("Demo credentials unavailable")
        self.key, self.secret, self.opener = key, secret, opener

    def get(self, path, params):
        if path not in self.ALLOWED:
            raise ValueError("Demo read endpoint not authorised")
        query = urlencode(sorted(params.items()))
        stamp, window = str(int(time.time()*1000)), "5000"
        sig = hmac.new(self.secret.encode(), (stamp+self.key+window+query).encode(), hashlib.sha256).hexdigest()
        req = Request(Bybit.DEMO+path+"?"+query, headers={"X-BAPI-API-KEY": self.key,
                      "X-BAPI-TIMESTAMP": stamp, "X-BAPI-RECV-WINDOW": window, "X-BAPI-SIGN": sig})
        with self.opener(req, timeout=12) as response:
            data = json.load(response)
        if data.get("retCode") != 0:
            raise DemoAPIError(data.get("retCode"))
        return data["result"]


def stream_closed_candles(symbol, market, interval, on_candle, stop, on_status):
    """Optional public WebSocket feed: only confirm=true; caller detects gaps/backfills."""
    import websocket
    if market not in ("spot", "linear"):
        raise ValueError("Unsupported stream market")
    if interval not in (300, 900, 3600, 14400, 86400):
        raise ValueError("Unsupported stream interval")
    resolution = "D" if interval == 86400 else str(interval//60)
    attempts = 0
    while not stop.is_set():
        ws = None
        try:
            ws = websocket.create_connection(f"wss://stream.bybitglobal.com/v5/public/{market}", timeout=5)
            ws.send(json.dumps({"op": "subscribe", "args": [f"kline.{resolution}.{symbol}"]}))
            on_status("CONNECTED")
            last_ping = time.monotonic()
            while not stop.is_set():
                if time.monotonic()-last_ping > 15:
                    ws.send(json.dumps({"op": "ping"}))
                    last_ping = time.monotonic()
                try:
                    message = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if message.get("success") is False:
                    raise RuntimeError("Subscription rejected")
                for row in message.get("data", []) if message.get("topic", "").startswith("kline.") else []:
                    if row.get("confirm") is True:
                        on_candle(Candle(int(row["start"])//1000+interval,
                                        *[float(row[k]) for k in ("open", "high", "low", "close", "volume")]))
        except Exception as error:
            on_status("DISCONNECTED:"+type(error).__name__)
            attempts += 1
            stop.wait(min(30, 2**min(attempts, 5)))
        finally:
            if ws:
                ws.close()
