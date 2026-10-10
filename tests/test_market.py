import io
import json
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from tradingbot.bybit import Bybit, DemoAccount, round_down, private_urlopen
from tradingbot.models import Candle, validate_candles, resample


class MarketTests(unittest.TestCase):
    def test_unclosed_bar_removed(self):
        class Client(Bybit):
            def get(self, path, params=None):
                return {"result": {"list": [["600000", "10", "12", "9", "11", "2", "20"], ["300000", "10", "12", "9", "11", "2", "20"]]}}
        context = Client().candles(count=1, interval=300, now=800)
        self.assertEqual(context.candles[0].timestamp, 600)

    def test_invalid_and_missing_data(self):
        c = Candle(300, 10, 12, 9, 11, 2)
        for rows, now in [([c,c], 1000), ([c,Candle(900,10,12,9,11,2)],1000), ([c],299),
                          ([Candle(300,10,9,8,11,2)],1000), ([Candle(300,10,12,9,float('nan'),2)],1000)]:
            with self.assertRaises(ValueError):
                validate_candles(rows,300,now)

    def test_resample_only_complete(self):
        rows = [Candle(t,10,12,9,11,2) for t in (300,600,900,1200)]
        self.assertEqual([c.timestamp for c in resample(rows,300,900,1200)], [900])
        self.assertEqual(resample(rows[1:],300,900,1200), [])

    def test_public_adapter_cannot_order(self):
        with self.assertRaises(ValueError):
            Bybit().get("/v5/order/create")

    def test_demo_isolation_and_signing(self):
        requests = []
        def opener(req, timeout):
            requests.append(req)
            return io.BytesIO(json.dumps({"retCode":0,"result":{}}).encode())
        client = DemoAccount("key", "secret", opener)
        client.get("/v5/account/wallet-balance", {"accountType":"UNIFIED"})
        self.assertTrue(requests[0].full_url.startswith("https://api-demo.bybitglobal.com/"))
        self.assertTrue(requests[0].get_header("X-bapi-sign"))
        with self.assertRaises(ValueError):
            client.get("/v5/order/create", {})

    def test_private_redirect_is_not_followed(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                hits.append(self.path)
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/target")
                else:
                    self.send_response(200)
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            from urllib.request import Request
            request = Request(f"http://127.0.0.1:{server.server_port}/redirect", headers={"Authorization": "Bearer fixture-token"})
            with self.assertRaises(HTTPError) as error:
                private_urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 302)
            self.assertEqual(hits, ["/redirect"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_hmac_signs_exact_timestamp_window_and_encoded_query(self):
        requests = []
        def opener(req, timeout):
            requests.append(req)
            return io.BytesIO(b'{"retCode":0,"result":{}}')
        with patch("tradingbot.bybit.time.time", return_value=1658384314.791):
            DemoAccount("XXXXXXXXXX", "fixture-secret", opener).get("/v5/order/realtime", {"symbol":"BTCUSDT","category":"linear"})
        import hashlib, hmac
        expected = hmac.new(b"fixture-secret", b"1658384314791XXXXXXXXXX5000category=linear&symbol=BTCUSDT", hashlib.sha256).hexdigest()
        self.assertEqual(requests[0].get_header("X-bapi-sign"), expected)
        self.assertTrue(requests[0].full_url.endswith("category=linear&symbol=BTCUSDT"))

    def test_precision_rounds_down(self):
        self.assertEqual(str(round_down(1.2349, .001)), "1.234")

    def test_rate_limit_retries(self):
        answers = iter([{"retCode":10006}, {"retCode":0,"result":{}}])
        pauses = []
        client = Bybit(lambda *a, **kw: io.BytesIO(json.dumps(next(answers)).encode()), pauses.append)
        self.assertEqual(client.get("/v5/market/time")["retCode"],0)
        self.assertEqual(pauses,[1])
