import json
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from tradingbot.security import Config
from tradingbot.storage import Store
from tradingbot.server import Application, make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(Config(password="long-password-example"), Store(":memory:"))
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()

    def request(self, path, body=None, headers=None):
        req = Request(self.url+path, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as e:
            response = e
        with response:
            data = response.read().decode()
            return response.code, response.headers, data

    def login(self):
        code, headers, text = self.request("/api/login", {"password": "long-password-example"})
        self.assertEqual(code, 200)
        return {"Cookie": headers["Set-Cookie"].split(";")[0], "X-CSRF-Token": json.loads(text)["csrf"]}

    def test_health_and_page(self):
        self.assertEqual(self.request("/health")[0], 200)
        self.assertIn("Strategy Intelligence", self.request("/")[2])

    def test_auth_no_secret_leak(self):
        self.assertEqual(self.request("/api/state")[0], 401)
        headers = self.login()
        code, _, data = self.request("/api/state", headers=headers)
        self.assertEqual(code, 200)
        self.assertNotIn(self.app.config.password, data)
        self.assertFalse(json.loads(data)["live_enabled"])

    def test_stop_persists_and_requires_csrf(self):
        headers = self.login()
        self.assertEqual(self.request("/api/emergency-stop", {"active": True})[0], 403)
        self.assertEqual(self.request("/api/emergency-stop", {"active": True}, headers)[0], 200)
        self.assertTrue(self.app.store.setting("emergency_stop"))

    def test_live_and_gate_mutation_locked(self):
        headers = self.login()
        self.assertEqual(self.request("/api/live-activate", {}, headers)[0], 423)
        self.assertEqual(self.request("/api/gates", {"status": "PASS"}, headers)[0], 404)

    def test_origin_rejected(self):
        self.assertEqual(self.request("/api/login", {"password": "long-password-example"}, {"Origin": "https://evil.example"})[0], 403)

    def test_worker_failure_clears_snapshot(self):
        self.app.snapshot = {"consensus": "APPROVE"}
        def fail():
            raise RuntimeError("private-key")
        self.app.launch_job("test", fail)
        self.app.worker.join(2)
        self.assertEqual(self.app.worker_status, "FAILED")
        self.assertIsNone(self.app.snapshot)
        self.assertNotIn("private-key", str(self.app.state()))

    def test_catalog_sync_requires_csrf_and_exposes_cached_state(self):
        from unittest.mock import patch
        from tests.test_catalog import row
        self.assertEqual(self.request("/api/instruments/refresh", {})[0], 403)
        headers = self.login()
        with patch("tradingbot.service.Bybit.catalog", return_value=[row("SOLUSDT")]):
            self.assertEqual(self.request("/api/instruments/refresh", {}, headers)[0], 202)
            self.app.worker.join(2)
        state = json.loads(self.request("/api/state", headers=headers)[2])
        self.assertEqual(state["instrument_catalog"]["spot"]["entries"][0]["symbol"], "SOLUSDT")
        self.assertFalse(state["live_enabled"])

    def test_demo_setup_owner_csrf_and_secret_redaction(self):
        from unittest.mock import patch
        from tests.test_connections import WALLET
        body = dict(key="fixture-api-key", secret="fixture-api-secret")
        self.assertEqual(self.request("/api/account/demo", body)[0], 403)
        headers = self.login()
        with patch("tradingbot.connections.DemoAccount.get", return_value=WALLET):
            self.assertEqual(self.request("/api/account/demo", body, headers)[0], 202)
            self.app.worker.join(2)
        state = self.request("/api/state", headers=headers)[2]
        self.assertEqual(json.loads(state)["connections"]["demo"]["status"], "CONNECTED")
        self.assertNotIn("fixture-api", state)
        self.assertNotIn("fixture-api", str(self.app.store.events()))
        self.assertNotIn("fixture-api", str(self.app.store.setting("owner_auth")))
        self.assertEqual(self.request("/api/account/disconnect", dict(mode="demo"), headers)[0], 200)
        self.assertIsNone(self.app.connections.demo)
        self.assertEqual(self.request("/api/live-activate", {}, headers)[0], 423)

    def test_reload_can_recover_csrf_only_with_owner_cookie(self):
        self.assertEqual(self.request("/api/session")[0], 401)
        headers = self.login()
        cookie_only = {"Cookie": headers["Cookie"]}
        code, _, data = self.request("/api/session", headers=cookie_only)
        self.assertEqual(code, 200)
        restored = dict(cookie_only, **{"X-CSRF-Token": json.loads(data)["csrf"]})
        self.assertEqual(self.request("/api/emergency-stop", dict(active=True), restored)[0], 200)
        self.assertEqual(self.request("/api/account/live/create", dict(confirmed=False), restored)[0], 400)
