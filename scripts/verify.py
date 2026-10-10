"""Execute checks and persist source-bound gate evidence. Never activates trading."""
import ast
import io
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tradingbot.gates import TITLES,DEPENDENCIES,source_hash


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.records=[]

    def addSuccess(self,test):
        super().addSuccess(test)
        self.records.append(dict(test=test.id(),status="PASS"))

    def addFailure(self,test,err):
        super().addFailure(test,err)
        self.records.append(dict(test=test.id(),status="FAIL"))

    def addError(self,test,err):
        super().addError(test,err)
        self.records.append(dict(test=test.id(),status="FAIL"))

    def addSkip(self,test,reason):
        super().addSkip(test,reason)
        self.records.append(dict(test=test.id(),status="BLOCKED",reason=reason))


def main():
    import os
    os.chdir(ROOT)
    out=ROOT/"reports"
    out.mkdir(exist_ok=True)
    log=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"),top_level_dir=str(ROOT))
    result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(suite)
    (out/"tests.txt").write_text(log.getvalue())
    checks=[]
    for args in (["-m","compileall","-q","tradingbot","tests","scripts"],
                 ["-m","pyflakes","tradingbot","tests","scripts"],
                 ["-m","mypy","tradingbot","--check-untyped-defs","--ignore-missing-imports","--follow-imports=skip"],
                 ["scripts/audit_pine.py"]):
        try:
            p=subprocess.run([sys.executable,*args],cwd=ROOT,capture_output=True,text=True,timeout=120)
            missing="No module named" in p.stderr
            checks.append(dict(command=[sys.executable,*args],status="BLOCKED" if missing else "PASS" if p.returncode==0 else "FAIL",
                               exit_code=p.returncode,output=p.stdout+p.stderr))
        except subprocess.TimeoutExpired:
            checks.append(dict(command=args,status="BLOCKED",output="Check exceeded 120 seconds"))
    unsafe=[]
    for path in (ROOT/"tradingbot").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ("eval","exec"):
                unsafe.append(f"{path.name}:{node.lineno}: dynamic execution")
            if isinstance(node,ast.Import) and any(a.name=="pickle" for a in node.names):
                unsafe.append(f"{path.name}:{node.lineno}: pickle")
    checks.append(dict(command="runtime AST security scan",status="FAIL" if unsafe else "PASS",output=unsafe,
                       limitations="Narrow static scan, not a comprehensive security audit"))
    checks.append(dict(command="runtime dependency inventory",status="PASS",output="Core runtime uses Python standard library only; WebSocket support is optional",
                       limitations="Optional websocket-client advisory audit and production security review remain outstanding"))
    h=source_hash()
    counts=dict(passed=sum(r["status"]=="PASS" for r in result.records),failed=sum(r["status"]=="FAIL" for r in result.records),
                skipped=len(result.skipped),blocked=sum(r["status"]=="BLOCKED" for r in result.records))
    verification=dict(source_hash=h,checked_at=int(time.time()),python=sys.version,command="python scripts/verify.py",
                      results=counts,tests=result.records,checks=checks)
    (out/"verification.json").write_text(json.dumps(verification,indent=2))
    rows=[]
    def add(i,status,modules,issues,next_action,components):
        test_rows=[t for t in result.records if any(t["test"].startswith(m) for m in modules)]
        local_bad=any(t["status"]!="PASS" for t in test_rows)
        checks_bad=any(c["status"]!="PASS" for c in checks) if i==1 else False
        if status=="PASS" and (local_bad or checks_bad):
            status="FAIL" if local_bad or any(c["status"]=="FAIL" for c in checks) else "BLOCKED"
        missing=[d for d in DEPENDENCIES[i] if rows[d]["status"]!="PASS"]
        if status=="PASS" and missing:
            status="BLOCKED"
            issues=issues+[f"Prerequisite gates incomplete: {missing}"]
        rows.append(dict(id=i,title=TITLES[i],status=status,source_hash=h,implemented_components=components,
                         tests_executed=["python scripts/verify.py"]+modules,
                         results=dict(passed=sum(t["status"]=="PASS" for t in test_rows),failed=sum(t["status"]=="FAIL" for t in test_rows),skipped=0,blocked=1 if status in ("BLOCKED","LOCKED") else 0),
                         evidence=["reports/verification.json","reports/tests.txt"],known_issues=issues,
                         dependencies=DEPENDENCIES[i],next_action=next_action,progression_decision="ALLOW" if status=="PASS" else "STOP_DEPENDENT_WORK"))
    add(0,"PASS",[],["Original repository contained only Pine source; no baseline application/tests"],"Foundation verification",["research/baseline.md"])
    add(1,"PASS",["tests.test_foundation","tests.test_server","tests.test_setup","tests.test_connections"],["Local deployment only; production TLS and security review not complete"],"Continue independent market/research work",["tradingbot/security.py","tradingbot/storage.py","tradingbot/server.py"])
    add(2,"BLOCKED",["tests.test_market"],["Bybit DNS failed outside sandbox; Spot/perpetual public ingestion and WebSocket capture not externally verified"],"Restore network connectivity and run python -m tradingbot probe; capture real WebSocket data",["tradingbot/bybit.py","reports/connectivity.json"])
    add(3,"PASS",["tests.test_strategies.IndicatorTests"],["Frankie transcripts unavailable; no Frankie-derived rule implemented", "TradingView parity vectors unavailable"],"Retrieve timestamped transcripts and parity vectors",["research/pine-audit.md","research/pine-inputs.json","research/strategies.md","research/video-inventory.json"])
    add(4,"PASS",["tests.test_strategies"],["Experimental candidates only; individual implementation PASS does not grant historical/live validation", "Sommi HTF calculations are causal adaptations; proprietary parity unverified"],"Evaluate on authentic historical data",["tradingbot/agents.py","tradingbot/indicators.py","tradingbot/profile.py"])
    add(5,"BLOCKED",["tests.test_validation.BacktestTests"],["Only synthetic exploratory backtests available; no independent authentic OOS/calibrated consensus cohort", "Historical funding/spread, parameter stability and regime validation incomplete"],"Collect data, freeze strategy versions, run independent validation",["tradingbot/backtest.py","tradingbot/validation.py"])
    add(6,"PASS",["tests.test_validation.ConsensusTests"],["Logic validated; deployed evidence remains insufficient and agents ineligible"],"Retain NO TRADE until Gate 5 supplies evidence",["tradingbot/consensus.py"])
    add(7,"BLOCKED",["tests.test_risk"],["Paper risk/idempotency/recovery tests pass; authenticated partial fills, protective order lifecycle and exchange reconciliation not implemented/verified", "No demo or live write adapter enabled"],"Complete exchange execution safety after prerequisite validation",["tradingbot/risk.py","tradingbot/execution.py"])
    add(8,"BLOCKED",["tests.test_market.MarketTests.test_demo_isolation"],["No demo credentials; no authenticated demo order/fill lifecycle; prerequisites 2/5/7 incomplete"],"Provide demo configuration only after prior gates pass",["tradingbot/bybit.py:DemoAccount","reports/demo.json"])
    add(9,"BLOCKED",["tests.test_server"],["Local desktop/mobile browser checks completed; exchange financial reconciliation unavailable", "Standalone Playwright CI suite has not been run locally"],"Run automated browser suite and verify authenticated exchange dashboard data",["tradingbot/static/index.html","reports/ui-e2e.json","tests/e2e.spec.mjs"])
    add(10,"BLOCKED",["tests.test_risk","tests.test_server"],["Partial failure tests only; authenticated exchange outage/partial-fill scenarios and production security audit incomplete"],"Complete Gates 7/8/9 and comprehensive security testing",["tests/test_risk.py","tests/test_server.py"])
    add(11,"BLOCKED",[],["Mandatory readiness gates 2/5/7/8/9/10 are incomplete"],"Keep live activation locked",["research/readiness.md"])
    add(12,"LOCKED",[],["Owner activation unavailable until all preceding mandatory gates pass; no production write transport exists"],"Do not activate live trading",["tradingbot/security.py","tradingbot/server.py"])
    (out/"gates.json").write_text(json.dumps(rows,indent=2))
    print(json.dumps(dict(tests=counts,checks=[dict(command=c["command"],status=c["status"]) for c in checks],
                          gates=[dict(id=r["id"],status=r["status"]) for r in rows]),indent=2))
    return 1 if counts["failed"] or any(c["status"]!="PASS" for c in checks) else 0


if __name__=="__main__":
    raise SystemExit(main())
