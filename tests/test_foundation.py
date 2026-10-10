import tempfile
import unittest
from pathlib import Path
from tradingbot.security import Config, Auth
from tradingbot.storage import Store


class FoundationTests(unittest.TestCase):
    def test_live_is_locked(self):
        with self.assertRaises(ValueError):
            Config(environment="live", password="long-password-example")

    def test_auth_and_csrf(self):
        auth = Auth("long-password-example")
        self.assertIsNone(auth.login("wrong", "client"))
        token, csrf = auth.login("long-password-example", "client")
        self.assertTrue(auth.check(token))
        self.assertFalse(auth.check(token, "wrong", True))
        self.assertTrue(auth.check(token, csrf, True))
        auth.logout(token)
        self.assertFalse(auth.check(token))

    def test_auth_rate_limit(self):
        auth = Auth("long-password-example")
        for _ in range(5):
            self.assertIsNone(auth.login("bad", "c"))
        self.assertIsNone(auth.login("long-password-example", "c"))

    def test_secret_repr(self):
        config = Config(password="long-password-example", demo_key="private-key", demo_secret="private-secret")
        self.assertNotIn("private", repr(config))
        self.assertNotIn(config.password, repr(config))

    def test_migration_restart_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"paper.sqlite3"
            db = Store(path)
            db.event("startup", {"environment": "paper"})
            db.put_setting("emergency_stop", True)
            self.assertTrue(db.audit_valid())
            db.close()
            db = Store(path)
            self.assertTrue(db.setting("emergency_stop"))
            self.assertTrue(db.audit_valid())
            self.assertEqual(db.db.execute("SELECT version FROM schema_version").fetchall(), [(1,)])
            db.db.execute("UPDATE events SET payload='{}'")
            self.assertFalse(db.audit_valid())
            db.close()

    def test_durable_duplicate_prevention(self):
        db = Store(":memory:")
        self.assertTrue(db.reserve_order("one", "paper", {}))
        self.assertFalse(db.reserve_order("one", "paper", {}))
        with self.assertRaises(ValueError):
            db.reserve_order("two", "live", {})
        db.close()
