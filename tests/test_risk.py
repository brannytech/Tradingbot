import unittest
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dataclasses import replace
from tradingbot.risk import RiskManager,Account
from tradingbot.storage import Store
from tradingbot.execution import ExecutionService
from tests.test_validation import signals,evidence


META=dict(symbol="BTCUSDT",status="Trading",priceFilter=dict(tickSize="0.01"),
          lotSizeFilter=dict(qtyStep="0.001",minOrderQty="0.001",minNotionalValue="5",maxMktOrderQty="100"))


class RiskTests(unittest.TestCase):
    def account(self):
        return Account(120000,10000,10000,reconciled=True,connected=True)

    def verdict(self,a=None,**kw):
        options=dict(spread_bps=2,depth_notional=1e6,authorised=("BTCUSDT",))
        options.update(kw)
        return RiskManager().approve(signals()[0],a or self.account(),120000,META,**options)

    def test_size_capped_without_vote_multiplier(self):
        result=self.verdict()
        self.assertTrue(result["approved"],result)
        self.assertLessEqual(result["notional"],1000)
        self.assertLessEqual(result["risk_amount"],50)

    def test_limits_fail_closed(self):
        for a in (replace(self.account(),timestamp=100000),replace(self.account(),equity=float('nan')),
                  replace(self.account(),daily_pnl=-300),replace(self.account(),drawdown=.06),
                  replace(self.account(),positions=2),replace(self.account(),reconciled=False),
                  replace(self.account(),available_margin=0),replace(self.account(),exposure=1000)):
            self.assertFalse(self.verdict(a)["approved"])
        for kw in (dict(emergency_stop=True),dict(spread_bps=None),dict(spread_bps=11),dict(depth_notional=None),dict(authorised=())):
            self.assertFalse(self.verdict(**kw)["approved"])

    def submit(self,service,**kw):
        return service.submit(signals(),evidence(),self.account(),META,120000,
                              spread_bps=2,depth_notional=1e6,authorised=("BTCUSDT",),**kw)

    def test_no_exchange_environment_can_submit(self):
        db=Store(":memory:")
        service=ExecutionService(db)
        for env in ("live","demo"):
            self.assertEqual(self.submit(service,environment=env)["status"],"BLOCKED")
        self.assertEqual(db.orders(),[])
        db.close()

    def test_concurrent_duplicate_orders(self):
        db=Store(":memory:")
        service=ExecutionService(db)
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda _: self.submit(service)["status"],range(2)))
        self.assertEqual(sorted(statuses),["DUPLICATE_BLOCKED","PAPER_ACKNOWLEDGED"])
        self.assertEqual(len(db.orders()),1)
        db.close()

    def test_timeout_unknown_no_retry_restart_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"paper.sqlite3"
            db=Store(path)
            calls=[]
            def timeout(key,payload):
                calls.append(key)
                raise TimeoutError()
            service=ExecutionService(db)
            self.assertEqual(self.submit(service,transport=timeout)["status"],"RECONCILIATION_REQUIRED")
            self.assertEqual(self.submit(service,transport=timeout)["status"],"RECONCILIATION_REQUIRED")
            self.assertEqual(len(calls),1)
            db.close()
            db=Store(path)
            self.assertEqual(ExecutionService(db).recover()["status"],"RECONCILIATION_REQUIRED")
            self.assertTrue(db.setting("emergency_stop"))
            db.close()
