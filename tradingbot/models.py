from dataclasses import dataclass, field, asdict
from math import isfinite
import re


@dataclass(frozen=True)
class Candle:
    # Timestamp is the CLOSE of the interval, in Unix seconds (UTC).
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def validate_candles(candles, interval, now):
    if interval <= 0 or not candles:
        raise ValueError("Empty data or invalid interval")
    previous = None
    for c in candles:
        values = [c.open, c.high, c.low, c.close, c.volume, c.timestamp]
        if not all(isfinite(x) for x in values):
            raise ValueError("Nonfinite market data")
        if min(c.open, c.high, c.low, c.close) <= 0 or c.volume < 0:
            raise ValueError("Invalid price/volume")
        if c.low > min(c.open, c.close) or c.high < max(c.open, c.close) or c.low > c.high:
            raise ValueError("Invalid OHLC bounds")
        if c.timestamp > now or c.timestamp % interval != 0:
            raise ValueError("Future, unclosed or unaligned candle")
        if previous is not None and c.timestamp - previous != interval:
            raise ValueError("Duplicate, unordered or missing candle")
        previous = c.timestamp
    return candles


@dataclass
class Signal:
    agent: str
    instrument: str
    market: str
    timeframe: int
    timestamp: int
    direction: str = "NO_TRADE"
    version: str = "1.0.0"
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    horizon: int = 12
    evidence: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    status: str = "EXPERIMENTAL"
    validation: str = "UNVERIFIED"
    dependency_group: str = "price"
    probability: float | None = None
    uncertainty: float | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Context:
    candles: list[Candle]
    instrument: str = "BTCUSDT"
    market: str = "linear"
    interval: int = 300
    now: int = 0
    orderflow: dict | None = None
    timeframes: tuple = (300, 900, 3600, 14400, 86400)

    def checked(self):
        if (self.market not in ("spot", "linear")
                or not re.fullmatch(r"[A-Z0-9]{2,40}", self.instrument)
                or (self.market == "linear" and not self.instrument.endswith("USDT"))):
            raise ValueError("Only Spot and USDT linear markets are supported")
        validate_candles(self.candles, self.interval, self.now)
        return self


def resample(candles, base_interval, target_interval, now):
    """Aggregate only complete, aligned buckets; never forward-fill a missing bucket."""
    if target_interval < base_interval or target_interval % base_interval:
        raise ValueError("Timeframe must be an integer multiple of the source interval")
    groups: dict[int, list[Candle]] = {}
    for c in candles:
        end = ((c.timestamp - 1) // target_interval + 1) * target_interval
        groups.setdefault(end, []).append(c)
    result = []
    for end, rows in sorted(groups.items()):
        expected = list(range(end-target_interval+base_interval, end+1, base_interval))
        if end <= now and [x.timestamp for x in rows] == expected:
            result.append(Candle(end, rows[0].open, max(x.high for x in rows),
                                 min(x.low for x in rows), rows[-1].close,
                                 sum(x.volume for x in rows)))
    return result
