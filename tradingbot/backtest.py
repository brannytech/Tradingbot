from dataclasses import dataclass, replace
from .agents import AGENTS
from .validation import statistics


@dataclass(frozen=True)
class Costs:
    fee_bps: float = 10  # per side, conservative configurable assumption
    spread_bps: float = 2
    slippage_bps: float = 3
    funding_bps_per_8h: float = 1

    def validate(self):
        if min(self.fee_bps,self.spread_bps,self.slippage_bps,self.funding_bps_per_8h)<0:
            raise ValueError("Negative assumed cost")


def simulate_trade(candles, decision_index, signal, interval, market, costs):
    """Next-open fill, adverse slippage, stop-first ambiguous bar, gap stops.

    No leverage; unit return of committed notional. Funding charges are a
    conservative constant assumption, not historical funding reconstruction.
    """
    costs.validate()
    start=decision_index+1
    if start>=len(candles) or signal.direction not in ("LONG","SHORT"):
        return None
    sign=1 if signal.direction=="LONG" else -1
    adverse=(costs.spread_bps/2+costs.slippage_bps)/10000
    entry=candles[start].open*(1+sign*adverse)
    if signal.stop is None or signal.target is None or not sign*(entry-signal.stop)>0 or not sign*(signal.target-entry)>0:
        return None
    end=min(len(candles)-1,start+signal.horizon-1)
    # Do not label truncated outcomes as full-horizon independent evidence.
    if end-start+1<signal.horizon:
        return None
    exit_price,reason=candles[end].close,"TIME_EXIT"
    for j in range(start,end+1):
        c=candles[j]
        stopped=c.low<=signal.stop if sign==1 else c.high>=signal.stop
        target=c.high>=signal.target if sign==1 else c.low<=signal.target
        if stopped:
            exit_price=min(c.open,signal.stop) if sign==1 else max(c.open,signal.stop)
            end,reason=j,"STOP"  # conservative if both touched
            break
        if target:
            exit_price=signal.target
            end,reason=j,"TARGET"
            break
    exit_price*=1-sign*adverse
    bars=end-start+1
    funding=costs.funding_bps_per_8h*(bars*interval/28800)/10000 if market=="linear" else 0
    fees=costs.fee_bps/10000*(1+exit_price/entry)
    # Slippage/spread are already in fill prices; report their estimated cost.
    net=sign*(exit_price-entry)/entry-fees-funding
    return dict(start=candles[start].timestamp-interval,end=candles[end].timestamp,
                entry=entry,exit=exit_price,stop=signal.stop,target=signal.target,
                direction=signal.direction,net_return=net,bars=bars,
                cost=fees+funding+2*adverse,costs_included=True,reason=reason,
                signal_timestamp=signal.timestamp,regime="UNKNOWN",fold=0)


def regime(rows):
    if len(rows)<50:
        return "UNKNOWN"
    ret=rows[-1].close/rows[-50].close-1
    return "UPTREND" if ret>.015 else "DOWNTREND" if ret<-.015 else "RANGE"


def backtest(ctx, agent_name, costs=Costs(), start_index=70, end_index=None):
    ctx.checked()
    cls=next((a for a in AGENTS if a.name==agent_name),None)
    if cls is None:
        raise ValueError("Unknown strategy")
    if agent_name=="order_flow":
        return dict(agent=agent_name,version="1.0.0",status="BLOCKED",reason="Historical timestamped book/trade/OI replay unavailable",trades=[],metrics=statistics([]))
    trades=[]
    end_index=min(len(ctx.candles),end_index or len(ctx.candles))
    i=max(start_index,cls.warmup-1)
    while i<end_index-1:
        rows=ctx.candles[:i+1]
        past=replace(ctx,candles=rows,now=rows[-1].timestamp,orderflow=None)
        signal=cls().evaluate(past)
        trade=simulate_trade(ctx.candles[:end_index],i,signal,ctx.interval,ctx.market,costs)
        if trade:
            trade["regime"]=regime(rows)
            # Wait one decision bar after exit to keep observations nonoverlapping.
            i=next(j for j in range(i+1,end_index) if ctx.candles[j].timestamp==trade["end"])+1
            trades.append(trade)
        else:
            i+=1
    return dict(agent=agent_name,version="1.0.0",status="EXPERIMENTAL",instrument=ctx.instrument,
                market=ctx.market,timeframe=ctx.interval,horizon=12,trades=trades,metrics=statistics(trades),
                cost_assumptions=costs.__dict__,limitations=["Assumed constant fees, spread, slippage and funding", "Unit-notional returns; no portfolio leverage", "Opposite-setup exits are not simulated in version 1.0.0" ])


def walk_forward(ctx,agent_name,costs=Costs()):
    n=len(ctx.candles)
    if n<350:
        return dict(status="BLOCKED",reason="At least 350 bars needed for exploratory walk-forward")
    folds=[]
    holdout_start=int(n*.8)
    # Fixed, predeclared parameters: no tuning on evaluation folds.
    for fold in range(3):
        start=int(n*(.5+fold*.1))
        end=int(n*(.6+fold*.1))
        r=backtest(ctx,agent_name,costs,start_index=start,end_index=end)
        for t in r["trades"]:
            t["fold"]=fold+1
        folds.append(dict(fold=fold+1,training_end=ctx.candles[start-13].timestamp,
                          evaluation_start=ctx.candles[start].timestamp,report=r))
    holdout=backtest(ctx,agent_name,costs,start_index=holdout_start)
    sensitivity=[dict(slippage_bps=s,metrics=backtest(ctx,agent_name,replace(costs,slippage_bps=s),start_index=holdout_start)["metrics"])
                 for s in (1,3,10)]
    return dict(status="EXPLORATORY_ONLY",folds=folds,holdout=holdout,sensitivity=sensitivity,
                parameter_stability="NOT_VALIDATED",calibration="INSUFFICIENT_EVIDENCE",
                research_verdict="UNVERIFIED",note="These runs do not grant strategy eligibility. No calibrated consensus cohort exists.")
