from dataclasses import dataclass, asdict
import math


@dataclass
class Profile:
    prices: list
    volumes: list
    poc: float
    vah: float
    val: float
    hvn: list
    lvn: list
    method: str
    start: int
    end: int
    bin_width: float
    total_volume: float
    market: str

    def to_dict(self):
        return asdict(self)


def volume_profile(candles, bins=48, area=.70, mode="rolling", start=None, end=None,
                   lookback=200, session_seconds=86400, trades=None, market="linear", source_interval=None):
    if bins < 2 or bins > 1000 or not 0 < area <= 1 or not candles:
        raise ValueError("Invalid profile parameters")
    if market not in ("spot", "linear"):
        raise ValueError("Separate Spot / USDT contract profiles required")
    if mode in ("fixed", "visible"):
        if start is None or end is None or start > end:
            raise ValueError("Explicit range required")
        rows = [c for c in candles if start < c.timestamp <= end]
    elif mode == "session":
        if session_seconds <= 0:
            raise ValueError("Invalid session duration")
        end = candles[-1].timestamp
        start = ((end-1)//session_seconds)*session_seconds
        rows = [c for c in candles if start < c.timestamp <= end]
    elif mode == "rolling":
        if lookback < 1:
            raise ValueError("Invalid rolling lookback")
        rows = candles[-lookback:]
    else:
        raise ValueError("Unknown profile mode")
    if not rows:
        raise ValueError("No candles in profile range")
    lo, hi = min(c.low for c in rows), max(c.high for c in rows)
    if hi == lo:
        lo, hi = lo*.999999, hi*1.000001
    width = (hi-lo)/bins
    prices = [lo+(i+.5)*width for i in range(bins)]
    volume = [0.0]*bins
    if trades is None:
        for c in rows:
            if c.high == c.low:
                volume[min(bins-1, max(0, int((c.close-lo)/width)))] += c.volume
            else:
                for i in range(bins):
                    overlap = max(0, min(c.high, lo+(i+1)*width)-max(c.low, lo+i*width))
                    volume[i] += c.volume*overlap/(c.high-c.low)
        method = "ESTIMATED_CANDLE_UNIFORM_ALLOCATION"
    else:
        interval = source_interval or (rows[1].timestamp-rows[0].timestamp if len(rows)>1 else None)
        if interval is None or interval<=0:
            raise ValueError("Trade-derived range requires source interval")
        for t in trades:
            if t.get("market") != market:
                raise ValueError("Trade market mismatch")
            if not all(math.isfinite(t[k]) for k in ("timestamp", "price", "volume")) or t["volume"] < 0:
                raise ValueError("Invalid trade record")
            if rows[0].timestamp-interval <= t["timestamp"] < rows[-1].timestamp:
                if not lo <= t["price"] <= hi:
                    raise ValueError("Trade price outside candle range")
                volume[min(bins-1, max(0, int((t["price"]-lo)/width)))] += t["volume"]
        method = "OBSERVED_TRADE_VOLUME_AT_PRICE_PARTIAL_COVERAGE"
    total = sum(volume)
    if total <= 0:
        raise ValueError("No positive volume")
    poc_index = max(range(bins), key=lambda i: (volume[i], -i))
    left = right = poc_index
    accumulated = volume[poc_index]
    while accumulated < area*total and (left > 0 or right < bins-1):
        l = volume[left-1] if left > 0 else -1
        r = volume[right+1] if right < bins-1 else -1
        if l >= r:
            left -= 1
            accumulated += volume[left]
        else:
            right += 1
            accumulated += volume[right]
    mean = total/bins
    hvn = [prices[i] for i in range(1, bins-1) if volume[i] >= 1.5*mean and volume[i] > volume[i-1] and volume[i] >= volume[i+1]]
    lvn = [prices[i] for i in range(1, bins-1) if volume[i] <= .5*mean and volume[i] < volume[i-1] and volume[i] <= volume[i+1]]
    return Profile(prices, volume, prices[poc_index], lo+(right+1)*width,
                   lo+left*width, hvn, lvn, method, rows[0].timestamp,
                   rows[-1].timestamp, width, total, market)


def distribution_change(previous, current):
    """Compare on a common grid via bin-overlap mass reallocation (TV distance)."""
    lo = min(previous.prices[0]-previous.bin_width/2, current.prices[0]-current.bin_width/2)
    hi = max(previous.prices[-1]+previous.bin_width/2, current.prices[-1]+current.bin_width/2)
    bins = max(len(previous.prices), len(current.prices))
    w = (hi-lo)/bins
    def align(p):
        result = [0.0]*bins
        for price, v in zip(p.prices, p.volumes):
            for i in range(bins):
                overlap = max(0, min(price+p.bin_width/2, lo+(i+1)*w)-max(price-p.bin_width/2, lo+i*w))
                result[i] += v*overlap/p.bin_width/p.total_volume
        return result
    return sum(abs(x-y) for x, y in zip(align(previous), align(current)))/2
