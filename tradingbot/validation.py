"""Outcome-based cohort calibration. Agreement scores are never probabilities."""
import math
from collections import Counter
from statistics import NormalDist, mean, stdev
from dataclasses import dataclass, asdict


def wilson(wins, count, alpha=.05, tests=1):
    if count <= 0 or tests < 1 or not 0 <= wins <= count:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(1-alpha/(2*tests))
    p, z2 = wins/count, z*z
    center = (p+z2/(2*count))/(1+z2/count)
    half = z*math.sqrt(p*(1-p)/count+z2/(4*count*count))/(1+z2/count)
    return max(0, center-half), min(1, center+half)


@dataclass
class CalibrationEvidence:
    cohort: str
    instrument: str
    market: str
    timeframe: int
    direction: str
    horizon: int
    outcome: str
    probability: float
    lower: float
    upper: float
    expected_net_return: float
    expected_return_lower: float
    observations: int
    calibration_observations: int
    calibration_error: float
    drift: float
    regimes: dict
    regime_lower: dict
    folds: int
    valid_until: int
    data_source: str
    selection_tests: int
    issues: list

    def to_dict(self):
        return asdict(self)


def calibrate_cohort(rows, *, cohort, instrument, market, timeframe, direction,
                     horizon, training_end, data_source, selection_tests, valid_until):
    """Separate early calibration from chronological held-out evaluation.

    Each observation has start/end, net_return, fold, regime. No overlapping
    trades, synthetic sources, training overlap or caller-provided confidence.
    Independence is a research assumption requiring external review.
    """
    if selection_tests < 1 or timeframe <= 0 or horizon < 1:
        raise ValueError("Invalid calibration configuration")
    if direction not in ("LONG", "SHORT") or market not in ("spot", "linear"):
        raise ValueError("Invalid cohort direction or market")
    if not rows:
        raise ValueError("No outcome observations")
    previous_end = training_end
    for r in rows:
        if not all(math.isfinite(r[k]) for k in ("start","end","net_return")):
            raise ValueError("Nonfinite observation")
        if r["start"] <= previous_end or r["end"] <= r["start"] or r["end"]-r["start"] > horizon*timeframe:
            raise ValueError("Overlapping/future/leaked outcome observation")
        if not isinstance(r.get("regime"), str) or not isinstance(r.get("fold"), int):
            raise ValueError("Missing regime or walk-forward fold")
        if r.get("costs_included") is not True:
            raise ValueError("Net costs not accounted for")
        previous_end = r["end"]
    if valid_until <= rows[-1]["end"]:
        raise ValueError("Invalid evidence expiry")
    split = len(rows)//2
    calibration, evaluation = rows[:split], rows[split:]
    if not calibration or not evaluation:
        raise ValueError("Independent calibration/evaluation required")
    p_cal = mean(r["net_return"]>0 for r in calibration)
    wins = sum(r["net_return"]>0 for r in evaluation)
    p_eval = wins/len(evaluation)
    low, high = wilson(wins,len(evaluation),tests=selection_tests)
    returns = [r["net_return"] for r in evaluation]
    ev = mean(returns)
    z = NormalDist().inv_cdf(1-.05/(2*selection_tests))
    ev_lower = ev-z*stdev(returns)/math.sqrt(len(returns)) if len(returns)>1 else -1
    third = max(1,len(evaluation)//3)
    drift = abs(mean(r["net_return"]>0 for r in evaluation[-third:])-mean(r["net_return"]>0 for r in evaluation[:third]))
    regimes = Counter(r["regime"] for r in evaluation)
    regime_lower = {regime:wilson(sum(r["net_return"]>0 for r in evaluation if r["regime"]==regime),n,tests=selection_tests*len(regimes))[0]
                    for regime,n in regimes.items()}
    folds = len({r["fold"] for r in evaluation})
    issues = []
    if data_source in ("SYNTHETIC", "FIXTURE", "UNKNOWN"):
        issues.append("Synthetic/unknown data cannot support trade probability")
    if len(evaluation)<200 or len(calibration)<200:
        issues.append("At least 200 calibration and 200 held-out observations required")
    if folds<3:
        issues.append("Three held-out walk-forward folds required")
    if len(regimes)<3 or min(regimes.values())<30:
        issues.append("Insufficient evaluation across three market regimes")
    if abs(p_cal-p_eval)>.03:
        issues.append("Calibration error exceeds .03")
    if drift>.05:
        issues.append("Calibration drift exceeds .05")
    return CalibrationEvidence(cohort,instrument,market,timeframe,direction,horizon,
        "positive_net_return_within_horizon",p_cal,low,high,ev,ev_lower,
        len(evaluation),len(calibration),abs(p_cal-p_eval),drift,dict(regimes),regime_lower,
        folds,valid_until,data_source,selection_tests,issues)


def statistics(trades):
    returns=[t["net_return"] for t in trades]
    wins=sum(x>0 for x in returns)
    gains=sum(x for x in returns if x>0)
    losses=-sum(x for x in returns if x<0)
    equity,peak,drawdown=1.0,1.0,0.0
    curve=[]
    for t in trades:
        equity*=max(0,1+t["net_return"])
        peak=max(peak,equity)
        drawdown=max(drawdown,1-equity/peak)
        curve.append(dict(timestamp=t["end"],equity=equity,drawdown=1-equity/peak))
    return dict(trade_count=len(trades),win_rate=wins/len(trades) if trades else None,
                win_rate_interval=list(wilson(wins,len(trades))),average_net_return=mean(returns) if returns else None,
                expected_value=mean(returns) if returns else None,net_return=equity-1,
                profit_factor=gains/losses if losses else None,profit_factor_note="undefined without losses" if not losses else None,
                maximum_drawdown=drawdown,average_holding_bars=mean(t["bars"] for t in trades) if trades else None,
                average_cost=mean(t["cost"] for t in trades) if trades else None,equity=curve,
                by_regime={r:dict(count=sum(t["regime"]==r for t in trades),mean_net_return=mean(t["net_return"] for t in trades if t["regime"]==r)) for r in {t["regime"] for t in trades}})
