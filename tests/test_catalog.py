import unittest
from unittest.mock import patch
from tradingbot.bybit import Bybit
from tradingbot.fixtures import fixture_context
from tradingbot.server import Application
from tradingbot.security import Config
from tradingbot.storage import Store
from tradingbot.service import sync_instruments, refresh


def row(symbol, quote="USDT", status="Trading", contract="LinearPerpetual"):
    return dict(symbol=symbol, quoteCoin=quote, baseCoin="ETH", status=status,
                contractType=contract, priceFilter=dict(tickSize="0.01"))


class CatalogTests(unittest.TestCase):
    def test_full_pagination_and_deduplication(self):
        calls = []
        class Client(Bybit):
            def get(self, path, params=None):
                calls.append(dict(params))
                if "cursor" not in params:
                    return {"result": {"list": [row("ETHUSDT"), row("ETHUSDC", "USDC")], "nextPageCursor": "next"}}
                return {"result": {"list": [row("ETHUSDT"), row("SOLUSDT"), row("OLDUSDT", status="Settled")]}}
        self.assertEqual([r["symbol"] for r in Client().catalog()], ["ETHUSDC", "ETHUSDT", "SOLUSDT"])
        self.assertEqual(calls[1]["cursor"], "next")
        self.assertEqual([r["symbol"] for r in Client().instruments()], ["ETHUSDT", "SOLUSDT"])

    def test_spot_all_quotes_without_invalid_pagination_parameters(self):
        class Client(Bybit):
            def get(self, path, params=None):
                self.params = params
                return {"result": {"list": [row("ETHBTC", "BTC"), row("ETHUSDC", "USDC")]}}
        client = Client()
        self.assertEqual(len(client.instruments("spot")), 2)
        self.assertEqual(client.params, {"category": "spot"})
        fixture_context(symbol="ETHBTC", market="spot").checked()
        with self.assertRaises(ValueError):
            fixture_context(symbol="ETHBTC", market="linear").checked()

    def test_option_all_base_coins(self):
        class Client(Bybit):
            def get(self, path, params=None):
                self.params = params
                return {"result": {"list": [row("ETH-31DEC26-3000-C")]}}
        client = Client()
        self.assertEqual(len(client.catalog("option")), 1)
        self.assertEqual(client.params["baseCoin"], "All")

    def test_repeated_cursor_rejected(self):
        class Client(Bybit):
            def get(self, path, params=None):
                return {"result": {"list": [row("ETHUSDT")], "nextPageCursor": "same"}}
        with self.assertRaises(ValueError):
            Client().catalog()

    def test_exact_symbol_and_finite_precision(self):
        class Client(Bybit):
            def get(self, path, params=None):
                return {"result": {"list": [row("ETHUSDT")]}}
        self.assertEqual(Client().instruments("linear", "BTCUSDT"), [])
        class Invalid(Client):
            def get(self, path, params=None):
                r = row("ETHUSDT")
                r["priceFilter"]["tickSize"] = "NaN"
                return {"result": {"list": [r]}}
        with self.assertRaises(ValueError):
            Invalid().catalog()

    def test_sync_persistence_and_failed_refresh_retains_cache(self):
        store = Store(":memory:")
        app = Application(Config(), store)
        try:
            with patch("tradingbot.service.Bybit.catalog", return_value=[row("ETHUSDT")]):
                sync_instruments(app)
            first = store.setting("instrument_catalog")
            self.assertEqual(set(first), {"spot", "linear", "inverse", "option"})
            self.assertFalse(first["inverse"]["entries"][0]["analysis_supported"])
            with patch("tradingbot.service.Bybit.catalog", side_effect=OSError("sensitive details")):
                sync_instruments(app)
            second = store.setting("instrument_catalog")
            self.assertEqual(second["spot"]["entries"], first["spot"]["entries"])
            self.assertEqual(second["spot"]["fetched_at"], first["spot"]["fetched_at"])
            self.assertEqual(second["spot"]["status"], "FAILED")
            self.assertNotIn("sensitive details", str(app.state()))
        finally:
            app.close()

    def test_arbitrary_public_spot_pair_validated_by_exchange_metadata(self):
        app = Application(Config(), Store(":memory:"))
        ctx = fixture_context(symbol="ETHBTC", market="spot")
        try:
            with patch("tradingbot.service.time.time", return_value=ctx.now), patch("tradingbot.service.Bybit.instruments", return_value=[row("ETHBTC", "BTC")]) as metadata, patch("tradingbot.service.Bybit.candles", return_value=ctx), patch("tradingbot.service.Bybit.orderflow", side_effect=OSError()):
                refresh(app, dict(symbol="ETHBTC", market="spot"))
            metadata.assert_called_once_with("spot", "ETHBTC")
            self.assertEqual(app.snapshot["quote_currency"], "BTC")
            with patch("tradingbot.service.Bybit.instruments", return_value=[]):
                with self.assertRaises(ValueError):
                    refresh(app, dict(symbol="FAKEUSDT", market="spot"))
            with self.assertRaises(ValueError):
                refresh(app, dict(symbol="ETHBTC", market="spot", source="SYNTHETIC"))
        finally:
            app.close()
