from tradingbot.security import Config
from tradingbot.storage import Store
from tradingbot.server import Application
import unittest


class SetupTests(unittest.TestCase):
    def test_only_hash_is_persisted(self):
        db=Store(":memory:")
        app=Application(Config(),db)
        self.assertIsNone(app.auth.digest)
        record=app.auth.configure("local-test-owner-password")
        db.put_setting("owner_auth",record)
        self.assertNotIn("local-test-owner-password",str(db.setting("owner_auth")))
        restored=Application(Config(),db)
        self.assertIsNotNone(restored.auth.login("local-test-owner-password","test"))
        with self.assertRaises(ValueError):
            restored.auth.configure("another-password")
        db.close()

    def test_short_setup_password_rejected(self):
        from tradingbot.security import Auth
        with self.assertRaises(ValueError):
            Auth("").configure("short")
