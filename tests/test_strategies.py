import unittest
from dataclasses import replace
from tradingbot.fixtures import fixture_context
from tradingbot.models import Candle
from tradingbot.agents import AGENTS,OrderflowAgent
from tradingbot.profile import volume_profile,distribution_change
from tradingbot import indicators as ind


class IndicatorTests(unittest.TestCase):
    def test_known_averages_and_rsi(self):
        self.assertEqual(ind.sma([1,2,3,4],3),[None,None,2,3])
        self.assertEqual(ind.ema([1,2,3],3),[1,1.5,2.25])
        self.assertEqual(ind.rsi(list(range(1,31)))[-1],100)
        self.assertEqual(ind.rsi(list(range(31,1,-1)))[-1],0)

    def test_flat_data_undefined_without_division(self):
        c=[Candle(i*300,10,10,10,10,1) for i in range(1,101)]
        self.assertIsNone(ind.wavetrend(c)[1][-1])
        self.assertIsNone(ind.money_flow(c)[-1])
        self.assertIsNone(ind.stoch_rsi(c)[0][-1])
        self.assertIsNone(ind.rsimfi_helper(c)[-1])
        self.assertEqual(ind.schaff(c)[-1],0)

    def test_indicator_prefix_invariance(self):
        c=fixture_context(count=140).candles
        for fn in (ind.money_flow,ind.schaff,ind.atr,ind.adx):
            self.assertEqual(fn(c[:100]),fn(c)[:100])
        for fn in (ind.wavetrend,ind.stoch_rsi):
            for short,long in zip(fn(c[:100]),fn(c)):
                self.assertEqual(short,long[:100])

    def test_actual_money_flow_formula(self):
        c=fixture_context(count=100).candles
        src=[(x.open+x.high+x.low+x.close)/4 for x in c]
        means=ind.sma(src,5)
        deviation=ind.sma([None if y is None else abs(x-y) for x,y in zip(src,means)],5)
        expected=ind.sma([None if y is None or z is None or z==0 else (x-y)/(.015*z) for x,y,z in zip(src,means,deviation)],60)
        self.assertEqual(ind.money_flow(c),expected)
        self.assertNotEqual(ind.money_flow(c)[-1],ind.rsimfi_helper(c)[-1])

    def test_divergence_available_at_confirmation(self):
        osc=[-10,-20,-80,-30,-10,-20,-75,-30,-10]
        c=[Candle((i+1)*300,100,110,30 if i==2 else 20 if i==6 else 40,100,1) for i in range(9)]
        events=ind.divergences(c,osc)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["kind"],"bullish")
        self.assertEqual(events[0]["pivot_index"],6)
        self.assertEqual(events[0]["confirmation_index"],8)
        self.assertEqual(ind.divergences(c[:8],osc[:8]),[])

    def test_cross_direction(self):
        self.assertEqual(ind.cross([0,2],[1,1]),1)
        self.assertEqual(ind.cross([2,0],[1,1]),-1)
        self.assertEqual(ind.cross([None,2],[1,1]),0)


class ProfileTests(unittest.TestCase):
    def test_uniform_allocation_conserves_mass(self):
        c=[Candle(300,11,12,10,11,100)]
        p=volume_profile(c,bins=2)
        self.assertEqual(p.volumes,[50,50])
        self.assertEqual(p.poc,10.5)
        self.assertEqual(p.val,10)
        self.assertEqual(p.vah,12)
        self.assertIn("ESTIMATED",p.method)

    def test_point_volume_and_trade_mass(self):
        c=[Candle(300,10,10,10,10,100),Candle(600,11,12,10,11,200)]
        p=volume_profile(c,bins=10)
        self.assertAlmostEqual(sum(p.volumes),300)
        trades=[dict(timestamp=150,price=10,volume=25,market="spot"),dict(timestamp=500,price=11,volume=30,market="spot")]
        p=volume_profile(c,bins=10,trades=trades,market="spot")
        self.assertEqual(p.total_volume,55)
        self.assertIn("PARTIAL_COVERAGE",p.method)
        with self.assertRaises(ValueError):
            volume_profile(c,trades=trades,market="linear")

    def test_range_modes_and_common_grid(self):
        c=fixture_context(count=100).candles
        p=volume_profile(c,mode="visible",start=c[20].timestamp,end=c[50].timestamp)
        self.assertEqual(p.end,c[50].timestamp)
        self.assertEqual(p.start,c[21].timestamp)
        self.assertAlmostEqual(distribution_change(p,p),0)
        self.assertTrue(0<=distribution_change(p,volume_profile(c))<=1.0000001)
        self.assertTrue(volume_profile(c,mode="session").total_volume>0)
        with self.assertRaises(ValueError):
            volume_profile(c,mode="visible")


class AgentTests(unittest.TestCase):
    def test_each_agent_reproducible_and_abstains_on_bad_data(self):
        ctx=fixture_context(count=120)
        for cls in AGENTS:
            agent=cls()
            self.assertEqual(agent.evaluate(ctx).to_dict(),agent.evaluate(ctx).to_dict())
            result=agent.evaluate(replace(ctx,candles=[]))
            self.assertEqual(result.direction,"NO_TRADE")
            self.assertEqual(result.status,"ERROR")
            result=agent.evaluate(replace(ctx,now=ctx.now-300))
            self.assertEqual(result.direction,"NO_TRADE")

    def test_warmup_and_no_future_influence(self):
        ctx=fixture_context(count=120)
        short=replace(ctx,candles=ctx.candles[:100],now=ctx.candles[99].timestamp)
        for cls in AGENTS:
            self.assertEqual(cls().evaluate(replace(ctx,candles=ctx.candles[:10])).direction,"NO_TRADE")
            first=cls().evaluate(short)
            altered=replace(ctx,candles=ctx.candles[:100]+[replace(c,close=c.close*1.001,high=c.high*1.002) for c in ctx.candles[100:]])
            replay=replace(altered,candles=altered.candles[:100],now=short.now)
            self.assertEqual(first.to_dict(),cls().evaluate(replay).to_dict())

    def test_no_spot_short(self):
        ctx=fixture_context(count=120,market="spot")
        for cls in AGENTS:
            self.assertNotEqual(cls().evaluate(ctx).direction,"SHORT")

    def test_orderflow_missing_stale_and_crossed(self):
        ctx=fixture_context(count=100)
        self.assertEqual(OrderflowAgent().evaluate(ctx).direction,"NO_TRADE")
        f=dict(timestamp=ctx.now,instrument=ctx.instrument,market=ctx.market,bids=[[100,1]],asks=[[99,1]],trades=[])
        self.assertEqual(OrderflowAgent().evaluate(replace(ctx,orderflow=f)).status,"ERROR")
        f["timestamp"]=ctx.now-30
        self.assertEqual(OrderflowAgent().evaluate(replace(ctx,orderflow=f)).status,"ERROR")
