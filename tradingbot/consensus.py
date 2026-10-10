import math
from dataclasses import dataclass
from .validation import CalibrationEvidence


@dataclass(frozen=True)
class Policy:
    required: tuple = ("volume_profile","market_cipher_inspired","multi_timeframe")
    threshold: float = .95
    max_age_bars: int = 2
    max_uncertainty: float = .05
    minimum_reward_risk: float = 1.5

    def __post_init__(self):
        if not self.required or len(set(self.required))!=len(self.required) or not .5<=self.threshold<1:
            raise ValueError("Invalid consensus policy")


def cohort_key(signals, required):
    return "|".join(sorted(f"{s.agent}@{s.version}" for s in signals if s.agent in required))


def decide(signals,now,policy=Policy(),calibration=None,warnings=()):
    reasons=list(warnings)
    by_name={s.agent:s for s in signals}
    if len(by_name)!=len(signals):
        reasons.append("Duplicate agent identities")
    missing=[name for name in policy.required if name not in by_name]
    if missing:
        reasons.append("Missing mandatory agents: "+", ".join(missing))
    required=[by_name[n] for n in policy.required if n in by_name]
    if not required:
        reasons.append("No mandatory signals")
    direction=None
    if required:
        first=required[0]
        identities={(s.instrument,s.market,s.timeframe,s.horizon) for s in required}
        if len(identities)!=1:
            reasons.append("Instrument, market, timeframe or outcome horizon mismatch")
        for s in required:
            if not 0<=now-s.timestamp<=s.timeframe*policy.max_age_bars:
                reasons.append(f"Stale or future signal: {s.agent}")
            if s.status=="ERROR" or s.direction=="NO_TRADE":
                reasons.append(f"Mandatory agent abstained/failed: {s.agent}")
            if s.validation!="VALIDATED":
                reasons.append(f"Unvalidated strategy: {s.agent}@{s.version}")
        directions={s.direction for s in required}
        if len(directions)!=1 or "NO_TRADE" in directions:
            reasons.append("Mandatory agents do not agree")
        else:
            direction=required[0].direction
        if direction:
            if direction=="SHORT" and first.market=="spot":
                reasons.append("Spot short prohibited")
            for s in required:
                levels=(s.entry,s.stop,s.target)
                if any(x is None or not math.isfinite(x) or x<=0 for x in levels):
                    reasons.append(f"Missing/invalid protective prices: {s.agent}")
                    continue
                sign=1 if direction=="LONG" else -1
                risk=sign*(s.entry-s.stop)
                reward=sign*(s.target-s.entry)
                if risk<=0 or reward<=0 or reward/risk<policy.minimum_reward_risk:
                    reasons.append(f"Protective prices / reward-risk invalid: {s.agent}")
    evidence_reasons=[]
    if calibration is None or not isinstance(calibration,CalibrationEvidence):
        evidence_reasons.append("No independently calibrated outcome estimate")
    elif required:
        first=required[0]
        if calibration.cohort!=cohort_key(signals,policy.required) or (calibration.instrument,calibration.market,calibration.timeframe,calibration.direction,calibration.horizon)!=(first.instrument,first.market,first.timeframe,direction,first.horizon):
            evidence_reasons.append("Calibration cohort/version/outcome mismatch")
        evidence_reasons.extend(calibration.issues)
        if calibration.outcome!="positive_net_return_within_horizon":
            evidence_reasons.append("Outcome definition unsupported")
        if now>calibration.valid_until:
            evidence_reasons.append("Calibration expired")
        numeric=(calibration.probability,calibration.lower,calibration.upper,calibration.expected_net_return,calibration.expected_return_lower)
        if not all(math.isfinite(x) for x in numeric) or not 0<=calibration.lower<=calibration.upper<=1 or not 0<=calibration.probability<=1:
            evidence_reasons.append("Malformed statistical estimate")
        if calibration.observations<200 or calibration.calibration_observations<200 or calibration.folds<3 or len(calibration.regimes)<3 or min(calibration.regimes.values(),default=0)<30:
            evidence_reasons.append("Insufficient independent validation observations")
        if calibration.data_source in ("SYNTHETIC","FIXTURE","UNKNOWN") or calibration.selection_tests<1:
            evidence_reasons.append("Calibration provenance / selection correction invalid")
        if calibration.lower<policy.threshold or calibration.probability<policy.threshold:
            evidence_reasons.append("Probability lower confidence bound below threshold")
        if calibration.upper-calibration.lower>policy.max_uncertainty:
            evidence_reasons.append("Statistical uncertainty too high")
        if any(x<policy.threshold for x in calibration.regime_lower.values()) or set(calibration.regime_lower)!=set(calibration.regimes):
            evidence_reasons.append("Regime validation below threshold / incomplete")
        if calibration.calibration_error>.03 or calibration.drift>.05:
            evidence_reasons.append("Calibration error or drift exceeds limits")
        if calibration.expected_net_return<=0 or calibration.expected_return_lower<=0:
            evidence_reasons.append("Nonpositive net expected value or uncertainty bound")
    reasons+=evidence_reasons
    result="INSUFFICIENT_EVIDENCE" if evidence_reasons else "REJECT" if reasons else "APPROVED_CANDIDATE"
    groups={g:[s.agent for s in signals if s.dependency_group==g] for g in {s.dependency_group for s in signals}}
    return dict(status=result,direction=direction if result=="APPROVED_CANDIDATE" else "NO_TRADE",
                reasons=reasons,threshold=policy.threshold,probability=calibration.probability if isinstance(calibration,CalibrationEvidence) else None,
                uncertainty=[calibration.lower,calibration.upper] if isinstance(calibration,CalibrationEvidence) else None,
                dependency_groups=groups,agreement_is_probability=False,cohort=cohort_key(signals,policy.required),
                risk_approval_required=True)
