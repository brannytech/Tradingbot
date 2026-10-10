import unittest
from dataclasses import replace
from tradingbot.models import Signal,Candle
from tradingbot.consensus import decide,Policy,cohort_key
from tradingbot.validation import calibrate_cohort,wilson,statistics
from tradingbot.backtest import simulate_trade,Costs,backtest,walk_forward
from tradingbot.fixtures import fixture_context


def signals():
    return [Signal(n,"BTCUSDT","linear",300,120000,direction="LONG",entry=100,stop=98,target=104,
                   validation="VALIDATED",dependency_group="price_momentum") for n in Policy().required]


def evidence(negative=False,source="UNIT_TEST"):
    rows=[dict(start=i*100+1,end=i*100+51,net_return=(-.8 if negative and i%100==0 else .001),
               regime=("UPTREND","DOWNTREND","RANGE")[i%3],fold=i//100,costs_included=True) for i in range(1200)]
    return calibrate_cohort(rows,cohort=cohort_key(signals(),Policy().required),instrument="BTCUSDT",market="linear",
                            timeframe=300,direction="LONG",horizon=12,training_end=0,data_source=source,
                            selection_tests=6,valid_until=999999)


class ConsensusTests(unittest.TestCase):
    def test_unanimity_cannot_make_95_percent(self):
        s=signals()
        for x in s:
            x.probability=.99
        result=decide(s,120000)
        self.assertEqual(result["status"],"INSUFFICIENT_EVIDENCE")
        self.assertIsNone(result["probability"])
        self.assertFalse(result["agreement_is_probability"])

    def test_sufficient_test_evidence_candidate_and_correlation(self):
        result=decide(signals(),120000,calibration=evidence())
        self.assertEqual(result["status"],"APPROVED_CANDIDATE",result["reasons"])
        self.assertEqual(len(result["dependency_groups"]),1)
        self.assertTrue(result["risk_approval_required"])

    def test_missing_opposing_stale_failed_unvalidated(self):
        scenarios=[signals()[:-1]]
        for field,value in (("direction","SHORT"),("timestamp",100000),("timestamp",120001),("status","ERROR"),("validation","UNVERIFIED"),("market","spot"),("version","2.0.0")):
            s=signals()
            s[-1]=replace(s[-1],**{field:value})
            scenarios.append(s)
        for s in scenarios:
            self.assertNotEqual(decide(s,120000,calibration=evidence())["status"],"APPROVED_CANDIDATE")

    def test_high_win_negative_expectancy_rejected(self):
        e=evidence(negative=True)
        self.assertGreater(e.probability,.95)
        self.assertLess(e.expected_net_return,0)
        self.assertEqual(decide(signals(),120000,calibration=e)["status"],"INSUFFICIENT_EVIDENCE")

    def test_synthetic_and_expired_calibration_rejected(self):
        self.assertNotEqual(decide(signals(),120000,calibration=evidence(source="SYNTHETIC"))["status"],"APPROVED_CANDIDATE")
        e=evidence()
        e.valid_until=100000
        self.assertNotEqual(decide(signals(),120000,calibration=e)["status"],"APPROVED_CANDIDATE")

    def test_point_estimate_not_enough(self):
        e=evidence()
        e.probability=.99
        e.lower=.94
        self.assertNotEqual(decide(signals(),120000,calibration=e)["status"],"APPROVED_CANDIDATE")

    def test_duplicate_agents_and_negative_prices(self):
        s=signals()
        self.assertNotEqual(decide(s+[s[0]],120000,calibration=evidence())["status"],"APPROVED_CANDIDATE")
        s[0].stop=-1
        self.assertNotEqual(decide(s,120000,calibration=evidence())["status"],"APPROVED_CANDIDATE")


class BacktestTests(unittest.TestCase):
    def test_next_open_stop_first_and_costs(self):
        c=[Candle(i*300,100,106,94,100,10) for i in range(1,15)]
        s=signals()[0]
        s.timestamp=300
        result=simulate_trade(c,0,s,300,"linear",Costs())
        self.assertEqual(result["reason"],"STOP")
        self.assertEqual(result["start"],300)
        self.assertGreater(result["entry"],100)
        self.assertLess(result["net_return"],-.02)

    def test_gap_stop_and_truncated_horizon(self):
        c=[Candle(i*300,100,101,99,100,10) for i in range(1,15)]
        c[1]=Candle(600,95,99,94,98,10)
        r=simulate_trade(c,0,signals()[0],300,"linear",Costs())
        self.assertIsNone(r)  # Gap opens beyond stop: entry setup invalidated.
        self.assertIsNone(simulate_trade(c[:5],0,signals()[0],300,"linear",Costs()))

    def test_independent_walk_forward_no_overlaps(self):
        ctx=fixture_context(count=360)
        report=backtest(ctx,"momentum_trend")
        for a,b in zip(report["trades"],report["trades"][1:]):
            self.assertLess(a["end"],b["start"])
        result=walk_forward(ctx,"momentum_trend")
        self.assertEqual(len(result["folds"]),3)
        self.assertEqual(result["research_verdict"],"UNVERIFIED")

    def test_profit_factor_and_drawdown(self):
        t=[dict(net_return=x,end=i,bars=1,cost=.001,regime="RANGE") for i,x in enumerate([.1,-.2])]
        s=statistics(t)
        self.assertAlmostEqual(s["profit_factor"],.5)
        self.assertAlmostEqual(s["maximum_drawdown"],.2)

    def test_multiple_testing_widens_interval(self):
        self.assertLess(wilson(99,100,tests=100)[0],wilson(99,100,tests=1)[0])

    def test_overlap_rejected(self):
        rows=[dict(start=1,end=50,net_return=.1,regime="RANGE",fold=1,costs_included=True),
              dict(start=49,end=70,net_return=.1,regime="RANGE",fold=2,costs_included=True)]
        with self.assertRaises(ValueError):
            calibrate_cohort(rows,cohort="x",instrument="BTCUSDT",market="linear",timeframe=300,direction="LONG",
                             horizon=12,training_end=0,data_source="UNIT_TEST",selection_tests=1,valid_until=100)
