from math import isfinite
from .models import Signal, resample
from . import indicators as ind
from .profile import volume_profile, distribution_change


class Agent:
    name = "base"
    dependency_group = "price"
    warmup = 70

    def analyze(self,ctx):
        raise NotImplementedError("Agent analysis contract")

    def evaluate(self, ctx):
        signal = Signal(self.name, ctx.instrument, ctx.market, ctx.interval,
                        ctx.candles[-1].timestamp if ctx.candles else ctx.now,
                        dependency_group=self.dependency_group)
        try:
            ctx.checked()
            if ctx.now-signal.timestamp > ctx.interval*2:
                raise ValueError("Stale candle data")
            if len(ctx.candles) < self.warmup:
                signal.reasons = [f"WARMUP: requires {self.warmup} closed candles"]
                return signal
            direction, evidence = self.analyze(ctx)
            signal.evidence = evidence
            if direction not in ("LONG", "SHORT"):
                signal.reasons = ["No unambiguous entry setup"]
                return signal
            if direction == "SHORT" and ctx.market == "spot":
                signal.reasons = ["Spot shorting is not authorised"]
                return signal
            a = ind.atr(ctx.candles)[-1]
            if a is None or a <= 0:
                signal.reasons = ["Undefined or zero ATR"]
                return signal
            price, sign = ctx.candles[-1].close, 1 if direction == "LONG" else -1
            risk = 1.5*a
            # Liquidity sweep invalidation must include the actual wick.
            if "invalidation_price" in evidence:
                risk = max(risk, sign*(price-evidence["invalidation_price"])+.1*a)
            signal.direction = direction
            signal.entry, signal.stop, signal.target = price, price-sign*risk, price+sign*2*risk
            signal.evidence.update(entry_rule="Enter next bar open after confirmed setup",
                                   invalidation="Stop, opposite setup or 12-bar time exit",
                                   data_quality="VALID_CLOSED_CANDLES")
            if price-sign*risk <= 0 or price+sign*2*risk <= 0:
                raise ValueError("Invalid protective prices")
            return signal
        except Exception as error:
            signal.direction = "NO_TRADE"
            signal.entry = signal.stop = signal.target = None
            signal.status = "ERROR"
            signal.reasons = [f"Agent rejected data: {type(error).__name__}"]
            return signal


class VolumeProfileAgent(Agent):
    name = "volume_profile"
    dependency_group = "price_volume"
    def analyze(self, ctx):
        rows = ctx.candles
        p = volume_profile(rows[:-1], market=ctx.market)
        prev, last = rows[-2:]
        before = rows[-3]
        vol_mean = sum(c.volume for c in rows[-21:-1])/20
        volume_supported = last.volume > 1.5*vol_mean
        setups = []
        def add(test, direction, rule):
            if test:
                setups.append(dict(direction=direction, rule=rule))
        add(last.low < p.val < last.close, "LONG", "value_area_rejection")
        add(last.high > p.vah > last.close, "SHORT", "value_area_rejection")
        add(prev.close > p.poc and last.low <= p.poc < last.close, "LONG", "poc_retest")
        add(prev.close < p.poc and last.high >= p.poc > last.close, "SHORT", "poc_retest")
        up = before.close <= p.vah and prev.close > p.vah and last.close > p.vah
        down = before.close >= p.val and prev.close < p.val and last.close < p.val
        add(up, "LONG", "value_area_breakout_acceptance")
        add(down, "SHORT", "value_area_breakout_acceptance")
        add(prev.close > p.vah and last.close < p.vah, "SHORT", "failed_breakout")
        add(prev.close < p.val and last.close > p.val, "LONG", "failed_breakout")
        for node in p.hvn:
            add(prev.close > node and last.low <= node < last.close, "LONG", "hvn_support")
            add(prev.close < node and last.high >= node > last.close, "SHORT", "hvn_resistance")
        for node in p.lvn:
            add(prev.close < node < last.close and last.close > last.open, "LONG", "lvn_traversal")
            add(prev.close > node > last.close and last.close < last.open, "SHORT", "lvn_traversal")
        add(volume_supported and last.low < p.val < last.close, "LONG", "volume_supported_reversal")
        add(volume_supported and last.high > p.vah > last.close, "SHORT", "volume_supported_reversal")
        add(volume_supported and up, "LONG", "volume_supported_continuation")
        add(volume_supported and down, "SHORT", "volume_supported_continuation")
        directions = {x["direction"] for x in setups}
        previous = volume_profile(rows[:-2], market=ctx.market)
        return (next(iter(directions)) if len(directions) == 1 else "NO_TRADE"), dict(
            profile=p.to_dict(), setups=setups, volume_supported=volume_supported,
            distribution_change=distribution_change(previous,p))


class CipherAgent(Agent):
    name = "market_cipher_inspired"
    dependency_group = "price_momentum"
    def analyze(self, ctx):
        c = ctx.candles
        w1,w2,spread = ind.wavetrend(c)
        mf, rsi = ind.money_flow(c), ind.rsi([x.close for x in c])
        k,d = ind.stoch_rsi(c)
        stc = ind.schaff(c)
        cross = ind.cross(w1,w2)
        divs = {"wt":ind.divergences(c,w2), "wt_extra":ind.divergences(c,w2,15,-40),
                "wt_hidden":ind.divergences(c,w2,limits=False),
                "rsi":ind.divergences(c,rsi,74,28), "stoch":ind.divergences(c,k,limits=False)}
        current = [v for group in ("wt","wt_extra") for v in divs[group]
                   if v["timestamp"] == c[-1].timestamp]
        bull = cross == 1 and w2[-1] is not None and w2[-1] <= -57
        bear = cross == -1 and w2[-1] is not None and w2[-1] >= 64
        bull |= any(v["kind"] == "bullish" for v in current)
        bear |= any(v["kind"] == "bearish" for v in current)
        sommi = {"flag":None,"diamond":None,"htf_method":"COMPLETED_NATIVE_BUCKETS_CAUSAL_ADAPTATION"}
        high = resample(c,ctx.interval,43200,ctx.now) if 43200 % ctx.interval == 0 else []
        if len(high) >= 70:
            hspread = ind.wavetrend(high)[2][-1]
            if hspread is not None and mf[-1] is not None and w2[-1] is not None:
                sommi["flag"] = "LONG" if mf[-1]>0 and w2[-1]<0 and cross==1 and hspread>0 else "SHORT" if mf[-1]<0 and w2[-1]>0 and cross==-1 and hspread<0 else "NO_TRADE"
        h1 = resample(c,ctx.interval,3600,ctx.now) if 3600 % ctx.interval == 0 else []
        h4 = resample(c,ctx.interval,14400,ctx.now) if 14400 % ctx.interval == 0 else []
        if len(h1)>=2 and len(h4)>=2 and w2[-1] is not None:
            a,b = ind.heikin_ashi(h1)[-1],ind.heikin_ashi(h4)[-1]
            sommi["diamond"] = "LONG" if cross==1 and w2[-1]<=0 and a[1]>a[0] and b[1]>b[0] else "SHORT" if cross==-1 and w2[-1]>=0 and a[1]<=a[0] and b[1]<=b[0] else "NO_TRADE"
        gold = False
        for v in divs["wt"]:
            if v["timestamp"] == c[-1].timestamp and v["kind"] == "bullish":
                prior = v["previous_oscillator"]
                # Latest confirmed WT low existed at the current pivot (script lastRsi).
                j = v["previous_pivot_index"]
                gold = prior<=-75 and w2[-1] is not None and w2[-1]>-75 and prior-w2[-1]<=-7 and rsi[j] is not None and rsi[j]<25
        values = dict(wt1=w1[-1],wt2=w2[-1],wt_spread=spread[-1],money_flow=mf[-1],
                      money_flow_definition="SMA60(CCI-like OHLC4 SMA5/deviation5); NOT MFI",
                      rsi=rsi[-1],stoch_k=k[-1],stoch_d=d[-1],schaff=stc[-1],gold_buy=gold,
                      sommi=sommi,divergences=divs,parity="UNVERIFIED",cross=cross,
                      series=dict(timestamp=[x.timestamp for x in c],wt1=w1,wt2=w2,money_flow=mf,rsi=rsi))
        return ("LONG" if bull and not bear else "SHORT" if bear and not bull else "NO_TRADE"),values


class MultiTimeframeAgent(Agent):
    name = "multi_timeframe"
    dependency_group = "price_momentum"
    def analyze(self,ctx):
        table = []
        for tf in ctx.timeframes:
            if tf<ctx.interval or tf%ctx.interval:
                table.append(dict(timeframe=tf,direction="NO_TRADE",reason="Lower/incompatible timeframe source unavailable"))
                continue
            rows = resample(ctx.candles,ctx.interval,tf,ctx.now)
            if len(rows)<50:
                table.append(dict(timeframe=tf,direction="NO_TRADE",reason="50 completed candles required"))
                continue
            closes = [c.close for c in rows]
            e20,e50 = ind.ema(closes,20)[-1],ind.ema(closes,50)[-1]
            direction = "LONG" if closes[-1]>e50 and e20>e50 else "SHORT" if closes[-1]<e50 and e20<e50 else "NO_TRADE"
            table.append(dict(timeframe=tf,direction=direction,timestamp=rows[-1].timestamp,
                              support=min(c.low for c in rows[-20:]), resistance=max(c.high for c in rows[-20:])))
        directions = {x["direction"] for x in table}
        direction = next(iter(directions)) if len(directions)==1 and "NO_TRADE" not in directions else "NO_TRADE"
        return direction,dict(timeframes=table)


class StructureAgent(Agent):
    name = "market_structure"
    def analyze(self,ctx):
        c=ctx.candles
        highs,lows=[],[]
        # Exclude pivots confirmed on the entry bar; prior structure only.
        for i in range(2,len(c)-3):
            if all(c[i].high>c[j].high for j in (i-2,i-1,i+1,i+2)):
                highs.append(i)
            if all(c[i].low<c[j].low for j in (i-2,i-1,i+1,i+2)):
                lows.append(i)
        last,prev=c[-1],c[-2]
        hi=c[highs[-1]].high if highs else max(x.high for x in c[-21:-1])
        lo=c[lows[-1]].low if lows else min(x.low for x in c[-21:-1])
        long_sweep=last.low<lo and last.close>lo
        short_sweep=last.high>hi and last.close<hi
        long_bos=prev.close<=hi<last.close
        short_bos=prev.close>=lo>last.close
        long_retest=prev.close>hi and last.low<=hi<last.close
        short_retest=prev.close<lo and last.high>=lo>last.close
        a=ind.atr(c)[-1]
        expansion=abs(last.close-last.open)>1.5*a
        long_exp=expansion and last.close>max(x.high for x in c[-21:-1])
        short_exp=expansion and last.close<min(x.low for x in c[-21:-1])
        bull=long_sweep or long_bos or long_retest or long_exp
        bear=short_sweep or short_bos or short_retest or short_exp
        direction="LONG" if bull and not bear else "SHORT" if bear and not bull else "NO_TRADE"
        previous_break="NO_TRADE"
        if highs and lows:
            for row in c[max(highs[-1],lows[-1])+3:-1]:
                if row.close>hi:
                    previous_break="LONG"
                elif row.close<lo:
                    previous_break="SHORT"
        evidence=dict(swing_high=hi,swing_low=lo,sweep=long_sweep or short_sweep,
                      bos=long_bos or short_bos,choch=(long_bos and previous_break=="SHORT") or (short_bos and previous_break=="LONG"),
                      retest=long_retest or short_retest,range_expansion=expansion,
                      pivot_confirmation_delay=2,failed_breakout=long_sweep or short_sweep)
        if long_sweep and direction=="LONG":
            evidence["invalidation_price"]=last.low
        if short_sweep and direction=="SHORT":
            evidence["invalidation_price"]=last.high
        return direction,evidence


class MomentumAgent(Agent):
    name="momentum_trend"
    dependency_group="price_momentum"
    def analyze(self,ctx):
        c=ctx.candles
        close=[x.close for x in c]
        e20,e50=ind.ema(close,20)[-1],ind.ema(close,50)[-1]
        macd=ind.subtract(ind.ema(close,12),ind.ema(close,26))
        hist=ind.subtract(macd,ind.ema(macd,9))[-1]
        rsi,adx=ind.rsi(close)[-1],ind.adx(c)[-1]
        momentum=close[-1]/close[-6]-1
        a=ind.atr(c)
        evidence=dict(ema20=e20,ema50=e50,macd_histogram=hist,rsi=rsi,adx=adx,
                      price_momentum=momentum,atr=a[-1],volatility_expansion=a[-1]>a[-6])
        if rsi is None or adx is None:
            return "NO_TRADE",evidence
        return ("LONG" if e20>e50 and hist>0 and rsi>55 and adx>=20 and momentum>0 else
                "SHORT" if e20<e50 and hist<0 and rsi<45 and adx>=20 and momentum<0 else "NO_TRADE"),evidence


class OrderflowAgent(Agent):
    name="order_flow"
    dependency_group="microstructure"
    def analyze(self,ctx):
        f=ctx.orderflow
        if not f:
            return "NO_TRADE",dict(reason="Order flow unavailable")
        if f.get("market")!=ctx.market or f.get("instrument")!=ctx.instrument or not 0<=ctx.now-f["timestamp"]<=15:
            raise ValueError("Order flow stale, future or mismatched")
        bids,asks=f["bids"],f["asks"]
        if not bids or not asks or any(not isfinite(p) or not isfinite(q) or p<=0 or q<=0 for p,q in bids+asks):
            raise ValueError("Incomplete order book")
        if any(bids[i][0]<=bids[i+1][0] for i in range(len(bids)-1)) or any(asks[i][0]>=asks[i+1][0] for i in range(len(asks)-1)):
            raise ValueError("Unsorted order book")
        if bids[0][0]>=asks[0][0]:
            raise ValueError("Crossed order book")
        bid,ask=sum(p*q for p,q in bids),sum(p*q for p,q in asks)
        imbalance=(bid-ask)/(bid+ask)
        spread=(asks[0][0]-bids[0][0])/((asks[0][0]+bids[0][0])/2)*10000
        trades=[t for t in f["trades"] if 0<=ctx.now-t["timestamp"]<=60]
        if not trades or any(t["volume"]<=0 or not isfinite(t["volume"]) or t["side"] not in ("Buy","Sell") for t in trades):
            raise ValueError("Missing/invalid recent trade flow")
        flow=sum(t["volume"]*(1 if t["side"]=="Buy" else -1) for t in trades)/sum(t["volume"] for t in trades)
        evidence=dict(imbalance=imbalance,spread_bps=spread,trade_flow=flow,
                      coverage=f.get("coverage"),liquidation_data="UNAVAILABLE", timestamp=f["timestamp"])
        if ctx.market=="linear":
            oi=f.get("open_interest",[])
            if len(oi)<2 or any(not 0<=ctx.now-x["timestamp"]<=900 or not isfinite(x["value"]) or x["value"]<0 for x in oi) or not isfinite(f.get("funding_rate",float('nan'))):
                raise ValueError("Derivatives inputs missing or stale")
            evidence.update(funding_rate=f["funding_rate"],open_interest_change=oi[0]["value"]-oi[1]["value"])
        direction="LONG" if spread<=10 and imbalance>=.2 and flow>=.2 else "SHORT" if spread<=10 and imbalance<=-.2 and flow<=-.2 else "NO_TRADE"
        return direction,evidence


AGENTS = (VolumeProfileAgent,CipherAgent,MultiTimeframeAgent,StructureAgent,MomentumAgent,OrderflowAgent)


def evaluate_agents(ctx):
    # Isolated exceptions; no agent has an execution service reference.
    return [agent().evaluate(ctx) for agent in AGENTS]
