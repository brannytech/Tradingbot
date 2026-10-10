# Experimental strategy specifications — version 1.0.0

These research designs are independently defined, not attributed to Frankie
Candles. Source-derived indicator formulas are from the supplied Pine file.
Frankie source reconstruction remains blocked without accessible transcripts.
All entries use the next bar open in historical simulation; decision time is the
last completed candle. Default horizon12 bars. Common stop distance1.5 ATR14,
target2 stop distances; invalidate at stop, with
time exit at horizon. Long/short symmetric except Spot cannot short.

| Agent | Explicit candidate conditions | Required inputs / limitations |
|---|---|---|
| Volume Profile | Prior200 candles,48 bins,70% contiguous value area. POC retest: last low<=POC and close>POC, previous close>POC (inverse short). VAL rejection: low<VAL and close>VAL (VAH inverse). Acceptance: two closes>VAH with preceding close<=VAH (inverse VAL). HVN support: touch node and close on same prior side. LVN traversal: previous close below node, current above, bullish body (inverse). Failed breakout: previous close>VAH, current<VAH (inverse). Reversal: value rejection and volume>1.5 prior20 mean. Continuation: acceptance and volume>1.5 mean. | Profile ends BEFORE the proposed entry candle; candle allocation estimated uniform across high-low; no exact reconstruction claim. Fixed/visible/session/rolling range APIs available. Candidate chosen by deterministic priority. |
| MCB-inspired | Oversold upward WT cross or default enabled WT regular divergence => long; overbought downward cross or regular bear divergence => short. Conflicting triggers abstain. | Source defaults; money-flow formula above; all additional indicators returned as evidence. Completed HTF flags and diamonds are experimental causal variants. |
| Multi-timeframe | Configurable5m/15m/1h/4h/D. Every timeframe needs50 completed candles. Close>EMA50 and EMA20>EMA50 across all => long (inverse short); disagreement abstains. | OHLC aggregation must be complete; EMA trend is our confirmation rule, not source-verified Frankie rule. |
| Structure / liquidity | Prior confirmed 2-left/2-right swing; sweep beyond last swing and close back inside => reversal. Close crosses last swing => BOS; opposite previous BOS => CHoCH. Retest touches level after prior close beyond. Expansion body>1.5ATR and close outside prior20 range. | Pivots recorded at confirmation time; no discretionary liquidity claim. Stop must lie beyond sweep extreme. |
| Momentum / trend | EMA20>EMA50, MACD12/26 histogram>0, RSI14>55, ADX14>=20 and positive5-bar return => long; inverse RSI<45 => short. | Shared price/momentum dependencies with MCB; not independent probabilistic evidence. ATR and volatility expansion returned. |
| Order flow | Book imbalance>=.2 and recent signed trade-volume ratio>=.2 => long; both<=-.2=>short. Spread<=10bps; source age<=15s. Futures OI and funding required and timestamped. | Book/trades support only; recent window is incomplete, no institutional flow claim. Liquidation data unavailable. No execution alone. |

Any missing warmup, invalid OHLC, unconfirmed bar, future timestamp or agent
exception produces NO_TRADE with a reason. An agent has no order API.
Each portfolio candidate gets an independent risk verdict after consensus.

Calibration must describe instrument, market, exact strategy/version cohort,
direction, horizon, regime and profitable-after-costs outcome. Nonoverlapping
chronological OOS observations, separate calibration/evaluation splits, purged
walk-forward folds, selection-corrected confidence bounds and drift checks are
required. Agent votes are never converted into probability.

Public API definitions: https://bybit-exchange.github.io/docs/v5/market/kline,
https://bybit-exchange.github.io/docs/v5/market/orderbook,
https://bybit-exchange.github.io/docs/v5/market/open-interest.
Demo isolation: https://bybit-exchange.github.io/docs/v5/demo.
