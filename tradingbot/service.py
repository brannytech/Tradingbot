import time
import re
from dataclasses import asdict
from .bybit import Bybit
from .agents import evaluate_agents
from .consensus import decide
from .fixtures import fixture_context
from .backtest import backtest,walk_forward


def make_snapshot(ctx,source,warnings=()):
    signals=evaluate_agents(ctx)
    decision=decide(signals,ctx.now,warnings=warnings)
    return dict(source=source,instrument=ctx.instrument,market=ctx.market,timeframe=ctx.interval,
                data_timestamp=ctx.candles[-1].timestamp,decision_timestamp=ctx.now,
                candles=[asdict(c) for c in ctx.candles[-200:]],agents=[s.to_dict() for s in signals],
                consensus=decision,research=dict(implemented=True,historically_validated=False,demo_validated=False,live_eligible=False),
                execution=dict(status="DISABLED",reason="No statistically validated candidate or exchange execution gate"))


def sync_instruments(app):
    """Replace complete categories only; retain dated cache after network failure."""
    catalog = app.store.setting("instrument_catalog", {})
    client = Bybit()
    for market in ("spot", "linear", "inverse", "option"):
        if app.stop_event.is_set():
            return
        previous = catalog.get(market, {})
        try:
            rows = client.catalog(market)
            if not rows:
                raise ValueError("Empty instrument catalog")
            entries = [dict(symbol=r["symbol"], base=r.get("baseCoin"), quote=r.get("quoteCoin"),
                            contract=r.get("contractType", "Option" if market == "option" else "Spot"),
                            analysis_supported=market == "spot" or (market == "linear"
                                and r.get("quoteCoin") == "USDT" and r.get("contractType") == "LinearPerpetual"))
                       for r in rows]
            catalog[market] = dict(status="READY", fetched_at=int(time.time()), entries=entries)
        except Exception as error:
            catalog[market] = dict(previous, status="FAILED", error_type=type(error).__name__,
                                   attempted_at=int(time.time()))
        app.store.put_setting("instrument_catalog", catalog)
    app.store.event("instrument_catalog_sync", {m: catalog[m]["status"] for m in catalog})


def refresh(app,body):
    symbol=body.get("symbol","BTCUSDT")
    market=body.get("market","linear")
    interval=int(body.get("interval",300))
    if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{2,40}", symbol)
            or market not in ("spot","linear") or interval not in (300,900,3600,14400,86400)):
        raise ValueError("Unsupported scanner selection")
    source=body.get("source","BYBIT_PUBLIC")
    now=int(time.time())
    warnings=[]
    if source=="SYNTHETIC":
        if symbol not in ("BTCUSDT", "ETHUSDT"):
            raise ValueError("Synthetic examples only cover BTCUSDT and ETHUSDT")
        ctx=fixture_context(now=now,interval=interval,symbol=symbol,market=market)
        warnings=["SYNTHETIC FIXTURE: not exchange data; not historical/demo validation"]
    elif source=="BYBIT_PUBLIC":
        client=Bybit()
        metadata=client.instruments(market,symbol)
        if not metadata:
            raise ValueError("Instrument unavailable")
        ctx=client.candles(symbol,market,interval,count=1000,now=now)
        try:
            ctx.orderflow=client.orderflow(symbol,market)
        except Exception:
            warnings.append("Order flow unavailable; cannot influence approval")
        ctx.now=int(time.time())
    else:
        raise ValueError("Unsupported data source")
    if app.stop_event.is_set():
        return
    ctx.checked()
    app.store.save_candles(ctx)
    snapshot=make_snapshot(ctx,source,warnings)
    if source == "BYBIT_PUBLIC":
        snapshot["quote_currency"] = metadata[0].get("quoteCoin")
    with app.lock:
        app.context=ctx
        app.snapshot=snapshot
    app.store.event("analysis",dict(source=source,instrument=symbol,market=market,
                                   timestamp=ctx.candles[-1].timestamp,consensus=snapshot["consensus"]))


def run_backtest(app,body):
    name=body.get("agent","volume_profile")
    with app.lock:
        ctx=getattr(app,"context",None)
        source=app.snapshot["source"] if app.snapshot else "UNKNOWN"
    if ctx is None:
        raise ValueError("Load market data before running backtests")
    result=backtest(ctx,name)
    result["source"]=source
    result["walk_forward"]=walk_forward(ctx,name)
    result["eligible_for_live"]=False
    app.store.save_report("BACKTEST",result)
    app.store.event("backtest_complete",dict(agent=name,source=source,trades=result["metrics"]["trade_count"]))
