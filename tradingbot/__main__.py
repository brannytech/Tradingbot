import argparse
import json
import os
from pathlib import Path
from typing import Any
from .security import Config
from .server import Application,make_server


def main():
    parser=argparse.ArgumentParser(description="Bybit strategy research dashboard. Live trading locked.")
    parser.add_argument("command",choices=["serve","probe","backtest","demo-check"],nargs="?",default="serve")
    parser.add_argument("--fixture",action="store_true",help="Load clearly labelled synthetic development data")
    parser.add_argument("--csv",help="CSV of closed candles: timestamp,open,high,low,close,volume; timestamps in UTC seconds")
    parser.add_argument("--agent",default="volume_profile")
    parser.add_argument("--market",choices=["spot","linear"],default="linear")
    parser.add_argument("--symbol",default="BTCUSDT")
    parser.add_argument("--interval",type=int,default=300)
    args=parser.parse_args()
    if args.command=="serve":
        config=Config.from_env()
        app=Application(config)
        from .execution import ExecutionService
        ExecutionService(app.store).recover()
        if args.fixture:
            from .service import refresh
            refresh(app,dict(source="SYNTHETIC",symbol=args.symbol,market=args.market,interval=args.interval))
        server=make_server(app,config.port)
        print(f"Strategy Intelligence: http://127.0.0.1:{config.port} — {config.environment}, live LOCKED",flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            app.close()
    elif args.command=="probe":
        from .bybit import Bybit
        from .storage import Store
        import time
        report: dict[str,Any]=dict(status="BLOCKED",source="AUTHENTIC_PUBLIC_REQUEST",checked_at=int(time.time()),production_orders_sent=0,checks=[])
        try:
            client=Bybit()
            client.get("/v5/market/time")
            report["checks"].append("server_time")
            with_store=Store("data/public.sqlite3")
            for market in ("spot","linear"):
                metadata=client.instruments(market,args.symbol)
                if not metadata:
                    raise ValueError("Instrument missing")
                ctx=client.candles(args.symbol,market,args.interval,count=300)
                with_store.save_candles(ctx)
                report["checks"].append(dict(market=market,instruments=len(metadata),candles=len(ctx.candles)))
            with_store.close()
            report["status"]="PARTIAL"
            report["limitations"]=["WebSocket capture and reconnection verification outstanding"]
        except Exception as error:
            report["error_type"]=type(error).__name__
            report["limitations"]=["External public connectivity failed; no validation claimed"]
        Path("reports").mkdir(exist_ok=True)
        Path("reports/connectivity.json").write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    elif args.command=="backtest":
        from .fixtures import fixture_context
        from .backtest import backtest,walk_forward
        from .models import Candle,Context
        import csv,time
        if args.csv:
            with open(args.csv,newline="") as f:
                rows=[Candle(int(r["timestamp"]),*[float(r[k]) for k in ("open","high","low","close","volume")]) for r in csv.DictReader(f)]
            ctx=Context(rows,args.symbol,args.market,args.interval,int(time.time())).checked()
            source="USER_CSV_UNVERIFIED_PROVENANCE"
        elif args.fixture:
            ctx=fixture_context()
            source="SYNTHETIC"
        else:
            parser.error("Provide --csv or --fixture")
        result=backtest(ctx,args.agent)
        result.update(source=source,walk_forward=walk_forward(ctx,args.agent),eligible_for_live=False)
        Path("reports").mkdir(exist_ok=True)
        path=Path("reports")/f"backtest-{args.agent}.json"
        path.write_text(json.dumps(result,indent=2,allow_nan=False))
        print(f"Saved {path}; {result['metrics']['trade_count']} trades; validation remains UNVERIFIED")
    else:
        from .bybit import DemoAccount
        key,secret=os.getenv("BYBIT_DEMO_KEY",""),os.getenv("BYBIT_DEMO_SECRET","")
        report=dict(status="BLOCKED",orders_sent=0,reason="Demo credentials missing; full lifecycle not validated")
        if key and secret:
            try:
                DemoAccount(key,secret).get("/v5/account/wallet-balance",{"accountType":"UNIFIED"})
                report=dict(status="PARTIAL",orders_sent=0,reason="Authenticated balance read only; full lifecycle not validated")
            except Exception as error:
                report["reason"]="Demo read failed: "+type(error).__name__
        Path("reports").mkdir(exist_ok=True)
        Path("reports/demo.json").write_text(json.dumps(report,indent=2))
        print(json.dumps(report))


if __name__=="__main__":
    main()
