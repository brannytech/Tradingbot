"""Deterministic synthetic data for UI/testing. Never exchange validation."""
import math
import random
from .models import Candle, Context


def fixture_context(count=900, interval=300, now=1800000000, symbol="BTCUSDT", market="linear"):
    rng=random.Random(42)
    now=now//interval*interval
    candles=[]
    price=60000.0
    for i in range(count):
        drift=.0003*math.sin(i/60)+.0008*math.sin(i/11)
        close=price*(1+drift+rng.uniform(-.001,.001))
        high=max(price,close)*(1+rng.uniform(.0001,.001))
        low=min(price,close)*(1-rng.uniform(.0001,.001))
        candles.append(Candle(now-(count-1-i)*interval,price,high,low,close,rng.uniform(10,80)))
        price=close
    return Context(candles,symbol,market,interval,now)
