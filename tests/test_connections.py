import json
import socket
import ssl
import threading
import time
import unittest
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
from unittest.mock import patch
from tradingbot.connections import Connections
from tradingbot.bybit import DemoAccount, DemoAPIError
from tradingbot.security import Config

WALLET = {"list": [{"totalEquity": "123.45", "coin": [{"coin": "USDT", "walletBalance": "120"}]}]}


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.connections = Connections(Config(), resolver=lambda *args: [])

    def tearDown(self):
        self.connections.close()

    def test_demo_balance_positions_and_secret_redaction(self):
        def read(path, params):
            if "wallet-balance" in path:
                return WALLET
            return {"list": [{"symbol": "BTCUSDT", "side": "Buy", "size": "0.1", "avgPrice": "50000", "unrealisedPnl": "5"}]}
        with patch("tradingbot.connections.DemoAccount.get", side_effect=read):
            self.connections.connect_demo("fixture-key-private", "fixture-secret-private")
        view = self.connections.view()
        self.assertEqual(view["demo"]["balance"]["equity_usd"], 123.45)
        self.assertEqual(view["demo"]["positions"][0]["size"], .1)
        self.assertFalse(view["execution_enabled"])
        self.assertNotIn("private", json.dumps(view))
        self.connections.disconnect("demo")
        self.assertIsNone(self.connections.demo)
        self.assertNotIn("balance", self.connections.view()["demo"])

    def test_demo_failure_never_retains_stale_balance(self):
        with patch("tradingbot.connections.DemoAccount.get", return_value=WALLET):
            self.connections.connect_demo("fixture-key", "fixture-secret")
        with patch("tradingbot.connections.DemoAccount.get", side_effect=RuntimeError("fixture-secret")):
            self.connections.refresh_demo()
        view = self.connections.view()
        self.assertEqual(view["demo"]["status"], "FAILED")
        self.assertNotIn("balance", view["demo"])
        self.assertNotIn("fixture-secret", json.dumps(view))

    def test_demo_dns_failure_is_distinguished_from_invalid_key(self):
        with patch("tradingbot.connections.DemoAccount.get", side_effect=URLError(socket.gaierror(11001, "fixture-secret"))):
            self.connections.connect_demo("fixture-key", "fixture-secret")
        view = self.connections.view()["demo"]
        self.assertEqual(view["error_code"], "DNS_BLOCKED")
        self.assertIn("keys have not been validated", view["message"])
        self.assertNotIn("fixture-secret", json.dumps(view))

    def test_demo_tls_failure_never_claims_invalid_credentials(self):
        error = URLError(ssl.SSLCertVerificationError(1, "fixture-secret"))
        with patch("tradingbot.connections.DemoAccount.get", side_effect=error):
            self.connections.connect_demo("fixture-key", "fixture-secret")
        view = self.connections.view()["demo"]
        self.assertEqual(view["error_code"], "TLS_CERTIFICATE_INVALID")
        self.assertNotIn("fixture-secret", json.dumps(view))
        self.assertNotIn("balance", view)

    def test_demo_reads_all_position_pages(self):
        calls = []
        def read(path, params):
            calls.append((path, dict(params)))
            if "wallet-balance" in path:
                return WALLET
            if "cursor" not in params:
                return {"list": [{"symbol": "BTCUSDT", "size": "1"}], "nextPageCursor": "page2"}
            return {"list": [{"symbol": "ETHUSDT", "size": "2"}]}
        with patch("tradingbot.connections.DemoAccount.get", side_effect=read):
            self.connections.connect_demo("fixture-key", "fixture-secret")
        self.assertEqual([r["symbol"] for r in self.connections.view()["demo"]["positions"]], ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(calls[-1][1]["cursor"], "page2")

    def test_position_pagination_failure_does_not_present_partial_exposure(self):
        def read(path, params):
            return WALLET if "wallet-balance" in path else {"list": [{"symbol": "BTCUSDT", "size": "1"}], "nextPageCursor": "repeated"}
        with patch("tradingbot.connections.DemoAccount.get", side_effect=read):
            self.connections.connect_demo("fixture-key", "fixture-secret")
        view = self.connections.view()["demo"]
        self.assertEqual(view["positions"], [])
        self.assertTrue(view["warning"])

    def test_demo_provider_error_is_numeric_and_redacted(self):
        class Response:
            def __enter__(self):
                import io
                return io.StringIO(json.dumps(dict(retCode=10003, retMsg="fixture-secret")))
            def __exit__(self, *args):
                pass
        account = DemoAccount("fixture-key", "fixture-secret", opener=lambda *args, **kwargs: Response())
        with self.assertRaises(DemoAPIError) as error:
            account.get("/v5/account/wallet-balance", dict(accountType="UNIFIED"))
        with patch("tradingbot.connections.DemoAccount.get", side_effect=error.exception):
            self.connections.connect_demo("fixture-key", "fixture-secret")
        view = self.connections.view()["demo"]
        self.assertEqual(view["error_code"], 10003)
        self.assertIn("mainnet Demo Trading", view["message"])
        self.assertNotIn("fixture-secret", json.dumps(view))

    def test_dns_failure_does_not_offer_broken_authorization_link(self):
        self.connections.resolver = lambda *args: (_ for _ in ()).throw(socket.gaierror())
        self.connections.prepare_live()
        self.assertEqual(self.connections.view()["live"]["status"], "DNS_BLOCKED")
        self.assertNotIn("authorize_url", self.connections.view()["live"])
        self.assertIsNone(self.connections.server)

    def test_callback_state_and_expiry_validation(self):
        self.connections.prepare_live()
        port = self.connections.server.server_port
        with self.assertRaises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{port}/callback?state=wrong&code=fixture", timeout=3)
        self.assertEqual(error.exception.code, 403)
        self.assertNotIn("verifier", json.dumps(self.connections.view()))
        self.connections.deadline = time.time()-1
        self.assertEqual(self.connections.view()["live"]["status"], "EXPIRED")
        self.connections.expire_live(self.connections.generation)
        self.assertIsNone(self.connections.server)

    def test_valid_callback_lists_accounts_without_automatic_selection(self):
        with patch.object(self.connections, "request_oauth", side_effect=[{"access_token": "fixture-token"}, [{"sub_member_id": "42", "nickname": "Bot"}]]):
            self.connections.prepare_live()
            port = self.connections.server.server_port
            state = self.connections.state_token
            with urlopen(f"http://127.0.0.1:{port}/callback?state={state}&code=fixture-code", timeout=3) as response:
                self.assertEqual(response.status, 200)
            end = time.time()+3
            while self.connections.view()["live"]["status"] == "EXCHANGING" and time.time() < end:
                time.sleep(.01)
        self.assertEqual(self.connections.view()["live"]["status"], "CHOOSE_ACCOUNT")
        self.assertIsNone(self.connections.live_credentials)
        self.assertNotIn("fixture-token", json.dumps(self.connections.view()))
        with self.assertRaises(ValueError):
            self.connections.select_live("unlisted")
        with patch.object(self.connections, "request_oauth", return_value={"sub_member_id": "42", "api_key": "fixture-key", "api_secret": "fixture-secret"}):
            self.connections.select_live("42")
        self.assertEqual(self.connections.view()["live"]["status"], "AUTHORIZED")
        self.assertFalse(self.connections.view()["execution_enabled"])
        self.assertNotIn("fixture-secret", json.dumps(self.connections.view()))
        self.connections.disconnect("live")
        self.assertIsNone(self.connections.live_credentials)
        self.assertIsNone(self.connections.token)

    def test_disconnect_cancels_inflight_token_exchange(self):
        started, release = threading.Event(), threading.Event()
        def request(path, **kwargs):
            started.set()
            release.wait(2)
            return {"access_token": "fixture-token"} if "access_token" in path else []
        with patch.object(self.connections, "request_oauth", side_effect=request):
            thread = threading.Thread(target=self.connections.exchange, args=("fixture-code", "fixture-verifier", self.connections.generation))
            thread.start()
            self.assertTrue(started.wait(1))
            self.connections.disconnect("live")
            release.set()
            thread.join(2)
        self.assertIsNone(self.connections.token)
        self.assertEqual(self.connections.view()["live"]["status"], "NOT_CONNECTED")

    def test_token_exchange_failure_is_redacted(self):
        with patch.object(self.connections, "request_oauth", side_effect=RuntimeError("private-token")):
            self.connections.exchange("fixture-code", "fixture-verifier", self.connections.generation)
        self.assertEqual(self.connections.view()["live"]["status"], "FAILED")
        self.assertNotIn("private-token", json.dumps(self.connections.view()))
        with self.assertRaises(ValueError):
            self.connections.request_oauth("/v5/order/create")

    def test_account_creation_requires_valid_explicit_selection_session(self):
        with self.assertRaises(ValueError):
            self.connections.select_live(create=True)
        self.connections.token = dict(access="fixture-token", expires_at=time.time()+60)
        self.connections.live_state = dict(status="CHOOSE_ACCOUNT", accounts=[])
        with patch.object(self.connections, "request_oauth", return_value={"sub_member_id": "43", "api_key": "fixture-key", "api_secret": "fixture-secret"}) as provider:
            self.connections.select_live(create=True)
        self.assertIn("is_create=true", provider.call_args.args[0])
        self.assertEqual(self.connections.view()["live"]["account_id"], "43")
        self.assertFalse(self.connections.view()["execution_enabled"])
