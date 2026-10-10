"""Durable execution boundary. No production write transport exists."""
import hashlib
import threading
from .consensus import decide
from .risk import RiskManager,RiskLimits


class ExecutionService:
    def __init__(self,store,risk=None):
        self.store=store
        self.risk=risk
        self.lock=threading.Lock()

    def submit(self,signals,calibration,account,instrument,now,*,environment="paper",policy=None,
               spread_bps=None,depth_notional=None,authorised=(),transport=None):
        from .consensus import Policy
        policy=policy or Policy()
        with self.lock:
            if environment!="paper":
                # Demo adapter integration/protective fill lifecycle still needs Gate 7.
                return dict(status="BLOCKED",reasons=["Exchange execution gates incomplete; live and demo orders disabled"])
            if any(o["state"] in ("UNKNOWN","PENDING") for o in self.store.orders()):
                self.store.put_setting("emergency_stop",True)
                return dict(status="RECONCILIATION_REQUIRED",reasons=["Outstanding ambiguous execution state"])
            decision=decide(signals,now,policy,calibration)
            self.store.event("consensus",decision)
            if decision["status"]!="APPROVED_CANDIDATE":
                return decision
            signal=next(s for s in signals if s.agent==policy.required[0])
            risk=self.risk or RiskManager(RiskLimits(**self.store.setting("risk_limits",{})))
            verdict=risk.approve(signal,account,now,instrument,
                emergency_stop=self.store.setting("emergency_stop",False),spread_bps=spread_bps,
                depth_notional=depth_notional,authorised=authorised)
            self.store.event("risk_verdict",verdict)
            if not verdict["approved"]:
                return dict(status="REJECT",reasons=verdict["reasons"])
            key=hashlib.sha256(f"{environment}|{decision['cohort']}|{signal.instrument}|{signal.market}|{signal.timestamp}|{signal.direction}".encode()).hexdigest()[:32]
            payload=dict(instrument=signal.instrument,market=signal.market,direction=signal.direction,
                         quantity=verdict["quantity"],stop=verdict["stop"],target=verdict["target"])
            # Persistence fails => no transport called. Unique index handles concurrency/restart.
            if not self.store.reserve_order(key,environment,payload):
                return dict(status="DUPLICATE_BLOCKED",order_id=key)
            try:
                # A paper transport may fail ambiguously; NEVER retry automatically.
                ack=transport(key,payload) if transport else dict(order_id=key,simulated=True,state="ACKNOWLEDGED")
                self.store.update_order(key,"ACKNOWLEDGED",dict(**payload,ack=ack))
                return dict(status="PAPER_ACKNOWLEDGED",order_id=key,payload=payload)
            except Exception as error:
                self.store.update_order(key,"UNKNOWN",payload)
                self.store.put_setting("emergency_stop",True)
                self.store.event("execution_unknown",dict(order_id=key,error_type=type(error).__name__))
                return dict(status="RECONCILIATION_REQUIRED",order_id=key)

    def recover(self):
        pending=[o for o in self.store.orders() if o["state"] in ("UNKNOWN","PENDING")]
        if pending:
            self.store.put_setting("emergency_stop",True)
            self.store.event("recovery_blocked",dict(order_ids=[o["id"] for o in pending]))
        return dict(status="RECONCILIATION_REQUIRED" if pending else "CLEAR",orders=pending)
