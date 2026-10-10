# Gate 0 — repository discovery

Status: PASS. Inspected 2026-10-09, Africa/Lagos.

The original repository was an unborn Git main branch containing only the
26,289-byte `MCB_indicator.txt`. No frontend, backend, database, tests, CI,
credentials, Bybit service, execution service or risk manager existed.
`python -m unittest discover -v` executed successfully and found zero baseline
tests; this is inventory evidence, not evidence of application correctness.
Python and Node were available. No dependency installation is needed for the
core Python application. Optional WebSocket support uses websocket-client.

Plan: establish authentication, SQLite migrations, local server, health checks,
durable audit and worker contracts; verify these before enabling strategy work.
Then validate public ingestion independently of source research. Implement
specified experimental agents, cost-aware backtests, conservative calibration,
consensus and risk gates. Develop dashboard views independently when an exchange
gate is blocked. Authenticated demo and live activation stay blocked until all
required evidence exists.

Initial risk register:

| Risk | Control / remaining work |
|---|---|
| Unconfirmed/future market data | Closed aligned candles, strict timestamp checks |
| Pine HTF lookahead and backdated plots | Completed HTF buckets, confirmation-time signals |
| Unsupported 95% claims | Separate OOS calibration and lower confidence bound |
| Correlated agents | Dependency groups; no vote-based probability |
| Missing execution infrastructure | Fail closed; no production order adapter |
| Missing credentials / transcripts | Explicit BLOCKED evidence records |
| Candle profile approximation | Method labels and mass-conservation tests |
| Local HTTP deployment | Loopback only; production TLS/auth review still required |

Progression: foundation development authorised. No trading gate passed.
