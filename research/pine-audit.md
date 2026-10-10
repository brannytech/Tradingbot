# Supplied Pine source audit

Reference: `MCB_indicator.txt`, Pine v5, `indicator(title='Market cipher B')`.
This is a user-supplied inspired implementation, not verified proprietary parity.
All inputs are extracted to `research/pine-inputs.json` by `scripts/audit_pine.py`.

WaveTrend uses OHLC4, channel EMA 9, EMA absolute deviation 9, CI divisor
0.015, CI EMA 12 and WT1 SMA 3. WT spread is WT1 minus WT2; the plot named
VWAP is not price-volume VWAP. OS=-57, OB=64; extra levels -65,-75,75,103.
Buy: WT crosses upward with WT2 <= -57. Sell: crosses downward with WT2 >=64.

The plotted `rsiMFI` is assigned `mf`: SMA(CCI-like normalization,60), where
the OHLC4 mean is SMA5 and deviation is SMA(abs(OHLC4-SMA5),5). It uses no
volume. It is not standard Money Flow Index. The helper `f_rsimfi` instead
computes SMA((close-open)/(high-low)*280,65)-1, used for MACD colors. These
definitions must remain separate; the MFI settings do not govern the main area.

RSI: close,14, OS28/OB74. Stoch RSI: logarithmic close, RSI14, stochastic14,
K SMA3, D SMA3; optional K/D averaging false. Schaff: fast23/slow50, cycle10,
recursive factor .5 and prior-value fallback on zero range.

Divergences: strict five-bar fractals centered two bars back; regular lower
oscillator high / higher price high and higher oscillator low / lower price
low; hidden comparisons reversed. Limited WT ranges 45/-69 and15/-40;
RSI74/28; hidden limits optional. `valuewhen(...,0)[2]` refers to pivot
history two confirmation bars ago. Offsets -2 at lines398–460 backdate
plots; signals become available at the later confirmation candle.

Gold: (enabled regular WT bull div or enabled RSI bull div), prior WT low<=-75,
current WT2>-75, prior WT low-current WT2<=-7, last RSI at WT low<25.
The executable candidate uses the confirmation timestamp, never plot timestamp.

Sommi Flag: bullish main mf>0, WT2<0, upward cross, HTF WT spread>0; bearish
inverse, default HTF720 minutes. Nested security/EMA contexts may differ from
plain native HTF recomputation. Our closed HTF candidate is an intentional
causal adaptation, not claimed numerical parity. Diamond: WT2<=0 with upward
cross and both HTF Heikin-Ashi bodies up (60/240); bearish inverse with WT2>=0.

Critical: `f_getTFCandle` lines241–244 requests unshifted OHLC with
`barmerge.lookahead_on`. It leaks the eventual HTF candle into historical
lower-timeframe bars. Replace executable use with fully completed HTF candles.
Other security calls lack confirmed-bar selection and may repaint intrabar.
Signals in this app require closed candles and completed HTF buckets.

Alerts (lines468–477): oversold buy, divergence buy, gold, Sommi flag/diamond,
small upward dot, bearish Sommi, overbought sell, divergence sell, small down
dot. Several messages mistakenly say overbought/buy on bullish/bearish alerts;
alert text is not a strategy definition. Visibility switches also gate some
divergence signals; executable options must distinguish computation and display.

Zero divisors: WT deviation, CCI deviation, high-low helper, stochastic range,
Schaff ranges. Log source must be positive. Warmup/missing values are undefined;
do not coerce them to directional evidence. Strict OHLC validation rejects NaN.
Trailing `message.txt` and `27 KB` are attachment metadata, not valid Pine code.
The reference is preserved byte-for-byte. No TradingView exported vectors are
available: numerical parity is BLOCKED, not PASS. Native indicators have formula
and causal-prefix tests; matching those does not establish Pine parity.
