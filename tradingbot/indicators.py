"""Causal indicators with explicit None warmup / undefined values.

Pine parity remains unverified without exported reference vectors.
"""
import math
from typing import Any


def sma(xs, period):
    if period <= 0:
        raise ValueError("period must be positive")
    out = []
    for i in range(len(xs)):
        window = xs[max(0, i-period+1):i+1]
        out.append(sum(window)/period if len(window) == period and all(x is not None for x in window) else None)
    return out


def ema(xs, period, wilder=False):
    if period <= 0:
        raise ValueError("period must be positive")
    alpha = 1/period if wilder else 2/(period+1)
    state: float | None = None
    seed: list[float] = []
    out: list[float | None] = []
    for x in xs:
        if x is None:
            out.append(None)
            continue
        if state is None and wilder:
            seed.append(x)
            if len(seed) < period:
                out.append(None)
                continue
            state = sum(seed)/period
        state = x if state is None else state + alpha*(x-state)
        out.append(state)
    return out


def subtract(a, b):
    return [None if x is None or y is None else x-y for x, y in zip(a, b)]


def rsi(xs, period=14):
    change = [None] + subtract(xs[1:], xs[:-1])
    gain = ema([None if x is None else max(x, 0) for x in change], period, True)
    loss = ema([None if x is None else max(-x, 0) for x in change], period, True)
    return [None if g is None or l is None or (g == 0 and l == 0)
            else 100 if l == 0 else 100-100/(1+g/l) for g, l in zip(gain, loss)]


def stochastic(xs, period):
    out: list[float | None] = []
    for i, x in enumerate(xs):
        window = xs[max(0, i-period+1):i+1]
        if len(window) != period or any(v is None for v in window):
            out.append(None)
        else:
            lo, hi = min(window), max(window)
            out.append(100*(x-lo)/(hi-lo) if hi > lo else None)
    return out


def wavetrend(candles, channel=9, average=12, smooth=3):
    src = [(c.open+c.high+c.low+c.close)/4 for c in candles]
    esa = ema(src, channel)
    de = ema([abs(x-y) for x, y in zip(src, esa)], channel)
    ci = [(x-y)/(0.015*d) if d > 0 else None for x, y, d in zip(src, esa, de)]
    wt1 = ema(ci, average)
    wt2 = sma(wt1, smooth)
    return wt1, wt2, subtract(wt1, wt2)


def money_flow(candles):
    # The actual plotted script uses mf, not f_rsimfi(65, 280, tf).
    src = [(c.open+c.high+c.low+c.close)/4 for c in candles]
    mean = sma(src, 5)
    deviation = sma([None if m is None else abs(s-m) for s, m in zip(src, mean)], 5)
    ci = [None if m is None or d is None or d == 0 else (s-m)/(0.015*d)
          for s, m, d in zip(src, mean, deviation)]
    return sma(ci, 60)


def rsimfi_helper(candles, period=65, multiplier=280, offset=1):
    values = [None if c.high == c.low else (c.close-c.open)/(c.high-c.low)*multiplier for c in candles]
    return [None if x is None else x-offset for x in sma(values, period)]


def stoch_rsi(candles, period=14, rsi_period=14, k_smooth=3, d_smooth=3, use_log=True, average=False):
    src = [math.log(c.close) if use_log else c.close for c in candles]
    k = sma(stochastic(rsi(src, rsi_period), period), k_smooth)
    d = sma(k, d_smooth)
    return ([None if a is None or b is None else (a+b)/2 for a, b in zip(k, d)] if average else k), d


def schaff(candles, length=10, fast=23, slow=50, factor=.5):
    src = [c.close for c in candles]
    macd = subtract(ema(src, fast), ema(src, slow))
    def normalize(values):
        out: list[float | None] = []
        previous = 0.0
        for i, x in enumerate(values):
            window = values[max(0, i-length+1):i+1]
            if any(v is None for v in window):
                out.append(None)
                continue
            lo, hi = min(window), max(window)
            previous = 100*(x-lo)/(hi-lo) if hi > lo else previous
            out.append(previous)
        return out
    def smooth(values):
        state, out = None, []
        for x in values:
            if x is not None:
                state = x if state is None else state + factor*(x-state)
            out.append(state if x is not None else None)
        return out
    return smooth(normalize(smooth(normalize(macd))))


def atr(candles, period=14):
    tr = [max(c.high-c.low, abs(c.high-candles[i-1].close), abs(c.low-candles[i-1].close))
          if i else c.high-c.low for i, c in enumerate(candles)]
    return ema(tr, period, True)


def adx(candles, period=14):
    plus, minus = [0], [0]
    for prev, c in zip(candles, candles[1:]):
        up, down = c.high-prev.high, prev.low-c.low
        plus.append(up if up > down and up > 0 else 0)
        minus.append(down if down > up and down > 0 else 0)
    a = atr(candles, period)
    p, m = ema(plus, period, True), ema(minus, period, True)
    dx = []
    for av, pv, mv in zip(a, p, m):
        dx.append(None if av is None or pv is None or mv is None or av == 0 or pv+mv == 0
                  else 100*abs(pv-mv)/(pv+mv))
    return ema(dx, period, True)


def divergences(candles, oscillator, top=45, bottom=-69, limits=True):
    """Strict five-bar fractals; emit at confirmation, two bars after the pivot.

    Previous limited pivot is taken from confirmation history t-2, matching
    valuewhen(...,0)[2]. Hidden no-limit detections use a separate invocation.
    """
    out: list[dict[str, Any]] = []
    highs: list[tuple[int,float,float,int]] = []
    lows: list[tuple[int,float,float,int]] = []
    for i in range(4, len(candles)):
        j = i-2
        window = oscillator[i-4:i+1]
        if any(x is None for x in window):
            continue
        v = oscillator[j]
        top_pivot = all(v > window[k] for k in (0, 1, 3, 4)) and (not limits or v >= top)
        bot_pivot = all(v < window[k] for k in (0, 1, 3, 4)) and (not limits or v <= bottom)
        for detected, history, price, regular, hidden in (
            (top_pivot, highs, candles[j].high, "bearish", "hidden_bearish"),
            (bot_pivot, lows, candles[j].low, "bullish", "hidden_bullish")):
            if not detected:
                continue
            eligible = [h for h in history if h[0] <= i-2]
            if eligible:
                _, old_v, old_price, old_j = eligible[-1]
                delta_p, delta_v = price-old_price, v-old_v
                kind = (regular if (delta_p > 0 and delta_v < 0 if top_pivot else delta_p < 0 and delta_v > 0)
                        else hidden if (delta_p < 0 and delta_v > 0 if top_pivot else delta_p > 0 and delta_v < 0) else None)
                if kind:
                    out.append(dict(kind=kind, pivot_index=j, confirmation_index=i,
                                    pivot_timestamp=candles[j].timestamp,
                                    timestamp=candles[i].timestamp, previous_oscillator=old_v,
                                    previous_pivot_index=old_j))
            history.append((i, v, price, j))
    return out


def heikin_ashi(candles):
    result: list[tuple[float,float]] = []
    previous: tuple[float,float] | None = None
    for c in candles:
        close = (c.open+c.high+c.low+c.close)/4
        op = (c.open+c.close)/2 if previous is None else (previous[0]+previous[1])/2
        result.append((op, close))
        previous = (op, close)
    return result


def cross(a, b):
    if len(a) < 2 or any(x is None for x in (a[-2], a[-1], b[-2], b[-1])):
        return 0
    return 1 if a[-2] <= b[-2] and a[-1] > b[-1] else -1 if a[-2] >= b[-2] and a[-1] < b[-1] else 0
