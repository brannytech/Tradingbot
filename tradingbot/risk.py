import math
from dataclasses import dataclass, asdict
from decimal import Decimal
from .bybit import round_down


@dataclass(frozen=True)
class RiskLimits:
    risk_fraction: float = .005
    max_exposure_fraction: float = .10
    max_leverage: float = 1
    max_daily_loss_fraction: float = .02
    max_drawdown_fraction: float = .05
    max_positions: int = 2
    max_spread_bps: float = 10
    max_account_age: int = 15

    def __post_init__(self):
        values=asdict(self)
        if any(not math.isfinite(x) or x<=0 for x in values.values()):
            raise ValueError("Risk limits must be positive and finite")
        if self.risk_fraction>.02 or self.max_exposure_fraction>1 or self.max_leverage>3 or self.max_positions>10:
            raise ValueError("Risk configuration exceeds conservative limits")
        if self.max_daily_loss_fraction>.1 or self.max_drawdown_fraction>.5 or self.max_account_age>60 or self.max_spread_bps>50:
            raise ValueError("Risk protection cannot be disabled by extreme settings")
        if int(self.max_positions)!=self.max_positions or int(self.max_account_age)!=self.max_account_age:
            raise ValueError("Integer position and age limits required")


@dataclass
class Account:
    timestamp: int
    equity: float
    available_margin: float
    exposure: float = 0
    daily_pnl: float = 0
    drawdown: float = 0
    positions: int = 0
    reconciled: bool = False
    connected: bool = False


class RiskManager:
    def __init__(self,limits=RiskLimits()):
        self.limits=limits

    def approve(self,signal,account,now,instrument,*,emergency_stop=False,spread_bps=None,depth_notional=None,authorised=()):
        l=self.limits
        errors=[]
        if emergency_stop:
            errors.append("Emergency stop active")
        if signal.instrument not in authorised:
            errors.append("Instrument not authorised")
        if account is None:
            return dict(approved=False,reasons=errors+["Account state unavailable"],quantity=0)
        if not account.connected or not account.reconciled or not 0<=now-account.timestamp<=l.max_account_age:
            errors.append("Account disconnected, stale or unreconciled")
        if any(not math.isfinite(x) for x in (account.equity,account.available_margin,account.exposure,account.daily_pnl,account.drawdown)) or account.equity<=0 or account.available_margin<0 or account.exposure<0:
            errors.append("Invalid account values")
        if account.daily_pnl<=-account.equity*l.max_daily_loss_fraction:
            errors.append("Daily loss limit reached")
        if account.drawdown>=l.max_drawdown_fraction or account.positions>=l.max_positions:
            errors.append("Drawdown / position limit reached")
        if signal.direction not in ("LONG","SHORT") or signal.direction=="SHORT" and signal.market=="spot":
            errors.append("Direction not authorised")
        if not 0<=now-signal.timestamp<=signal.timeframe*2:
            errors.append("Signal stale or future")
        if spread_bps is None or not math.isfinite(spread_bps) or not 0<=spread_bps<=l.max_spread_bps:
            errors.append("Spread missing or excessive")
        if depth_notional is None or not math.isfinite(depth_notional) or depth_notional<=0:
            errors.append("Liquidity depth missing")
        if instrument.get("symbol")!=signal.instrument or instrument.get("status")!="Trading":
            errors.append("Instrument metadata mismatch")
        levels=(signal.entry,signal.stop,signal.target)
        if any(x is None or not math.isfinite(x) or x<=0 for x in levels):
            errors.append("Protective prices missing")
        else:
            sign=1 if signal.direction=="LONG" else -1
            if sign*(signal.entry-signal.stop)<=0 or sign*(signal.target-signal.entry)<=0:
                errors.append("Protective price direction invalid")
        if errors:
            return dict(approved=False,reasons=errors,quantity=0)
        try:
            risk_per_unit=abs(signal.entry-signal.stop)
            exposure_room=max(0,account.equity*l.max_exposure_fraction-account.exposure)
            maximum=min(account.equity*l.risk_fraction/risk_per_unit,
                        exposure_room/signal.entry,account.available_margin*l.max_leverage/signal.entry,
                        depth_notional*.01/signal.entry)
            lot=instrument["lotSizeFilter"]
            step=lot.get("qtyStep",lot.get("basePrecision"))
            quantity=round_down(maximum,step)
            minimum=Decimal(lot.get("minOrderQty","0"))
            min_notional=Decimal(lot.get("minNotionalValue",lot.get("minOrderAmt","0")))
            max_qty=Decimal(lot.get("maxMktOrderQty",lot.get("maxOrderQty","Infinity")))
            tick=instrument["priceFilter"]["tickSize"]
            stop,target=round_down(signal.stop,tick),round_down(signal.target,tick)
            sign=1 if signal.direction=="LONG" else -1
            if quantity<=0 or quantity<minimum or quantity>max_qty or quantity*Decimal(str(signal.entry))<min_notional:
                errors.append("Quantity fails exchange min/max constraints")
            if sign*(signal.entry-float(stop))<=0 or sign*(float(target)-signal.entry)<=0:
                errors.append("Rounded protective prices invalid")
            # Round-down can increase a long stop distance; recheck risk after precision.
            if float(quantity)*abs(signal.entry-float(stop))>account.equity*l.risk_fraction+1e-9:
                errors.append("Rounded stop exceeds risk budget")
            return dict(approved=not errors,reasons=errors,quantity=str(quantity) if not errors else "0",
                        stop=str(stop),target=str(target),leverage=l.max_leverage,
                        notional=float(quantity)*signal.entry,risk_amount=float(quantity)*abs(signal.entry-float(stop)))
        except Exception:
            return dict(approved=False,reasons=["Invalid exchange precision/limits"],quantity=0)
