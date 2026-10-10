# Bybit Strategy Intelligence

A functioning local research web app, built from the supplied Pine source.
Exchange execution remains locked. Start with Python3.10 or newer:

```powershell
cd C:\Users\OLWOLU024\Documents\TradingBot
python -m tradingbot serve
```

Open http://127.0.0.1:8765 and create an owner password (12+ characters) on
first launch. Only a salted PBKDF2 hash is persisted. Alternatively set
`TRADINGBOT_PASSWORD` in the backend environment before starting. This override
does not modify the persisted owner hash. Keep passwords and API secrets out
of committed files. `TRADINGBOT_ENV` supports paper/demo only; live is rejected.
The app binds exclusively to loopback. It is not a reviewed public deployment.

Choose **Load synthetic example** to exercise the dashboard without network
access. These fixtures are prominently labeled and never count as exchange,
historical or demo validation. **Refresh Bybit data** uses public V5 GETs.
Choose **Sync all Bybit pairs** to fetch the full active V5 catalog across Spot,
linear, inverse and options (all option base coins, all pagination pages).
Search by symbol, base or quote currency. All Spot quotes and USDT perpetuals
support analysis; USDC/delivery/inverse/options are visible as catalog only
until their strategy and accounting support is implemented. Quotes and returns
for non-USDT Spot research are in the pair quote currency, not dollar balances.
Catalogs persist with fetch timestamps; a failed sync retains dated cached rows.
Public market data and instrument lists require no API credentials.
Without connectivity the app shows only explicitly labeled BTC/ETH synthetic
examples. Select 5m/15m/1h/4h/D. Analysis is on-demand;
the browser polls app state every3 seconds. The backend does not yet run an
autonomous scanner or place demo/live orders.

The app opens at **Connect Bybit**. Main navigation is Home, Connect Bybit,
Signals, Positions and Risk; research and readiness views are under Advanced tools.

On Connect Bybit, enter a demo key and secret, then select Connect demo account.
The owner-authenticated loopback endpoint keeps keys in backend memory until
disconnect/restart, never in SQLite, logs, browser storage or returned state.
Successful reads display demo equity and USDT linear positions with timestamps.
Connection failures clear the previous account data. No demo orders are sent.

Live AI authorization is integrated with in-memory PKCE/state, a loopback callback,
OAuth token exchange and explicit selection from returned AI sub-accounts.
No account is auto-selected or created. Creating a new AI sub-account requires
the owner to check an explicit mainnet consent box and submit the creation form. Secrets are not persisted; provider
revocation is separate from local disconnect. Runtime endpoints use the requested Bybit Global hosts: api.bybitglobal.com
(public), api-demo.bybitglobal.com (demo), www.bybitglobal.com/oauth and
api2.bybitglobal.com (OAuth). The public time API was verified; authenticated
Global demo/OAuth compatibility remains unverified. The Global demo hostname
currently fails TLS certificate hostname validation; this is a provider/network
blocker, not proof of an invalid key. Certificate verification stays enabled.
DNS failure prevents generating an unusable link. Successful OAuth means
AUTHORIZED, not ready to trade; no live order adapter or reconciled live
account dashboard is enabled.

Dashboard views cover overview, scanner, strategy intelligence, agent monitor,
consensus, positions, orders, trades, backtesting, analytics, risk controls,
alerts, settings and implementation readiness. Click agent rows and gate cards
for evidence. Emergency stop and risk limits persist across restarts.

Run reproducible checks with the interpreter that has the developer tools:

```powershell
python -m pip install mypy==1.8.0 pyflakes==3.2.0
python scripts/verify.py
python -m unittest discover -v
python -m tradingbot backtest --fixture --agent momentum_trend
python -m tradingbot probe
python -m tradingbot demo-check
```

The core runtime has no third-party dependencies. Optional public WebSocket
support requires `websocket-client`; the closed-candle streaming helper is
available in `tradingbot.bybit`, but public stream integration is not validated
or enabled in the dashboard. Do not interpret the optional module as a passed
connectivity gate.

For historical research, provide a chronological CSV with
`timestamp,open,high,low,close,volume`, using candle CLOSE timestamps in Unix UTC
seconds. Duplicates, gaps, invalid OHLC and future/unclosed bars are rejected:

```powershell
python -m tradingbot backtest --csv data\btc-5m.csv --interval 300 --market linear --agent volume_profile
```

Reports include next-open fills, adverse spread/slippage, fees, assumed funding,
stop-first same-bar exits, nonoverlapping trades, exploratory walk-forward
folds, final holdout and slippage sensitivity. Constant costs are assumptions;
historical funding and spread reconstruction remain outstanding. Strategy
parameter stability is not validated. Source versions are recorded, and no
backtest grants live eligibility automatically.

Outcome calibration is a separate cohort API. It needs chronological,
nonoverlapping profitable-after-cost observations, independent calibration and
evaluation samples, regime labels, multiple-testing correction, walk-forward
folds and drift checks. Both the estimated probability and conservative bound
must meet95%; net expected value has a separate positive-bound requirement.
No calibration cohort is loaded by this app. Unanimous agents cannot authorize
execution without it. Historical statistical assumptions need review.

For demo account **read checks**, set `BYBIT_DEMO_KEY` and `BYBIT_DEMO_SECRET`
in the backend environment and run `demo-check`. Keys generated in Bybit's
demo environment uses the configured `api-demo.bybitglobal.com`; testnet is distinct.
Bybit official documentation still names `api-demo.bybit.com`, so the requested
Global demo host must not be treated as validated merely because its DNS resolves.
The app never accepts or displays API secrets in the browser. Balance reads
alone cannot pass the full demo gate. Production and demo order submission
are deliberately unavailable while mandatory gates are incomplete.

Browser test infrastructure:

```powershell
npm install --ignore-scripts
npx playwright install chromium
npm run test:e2e
```

This suite uses an isolated in-memory server on8767, not the owner's database.
CI runs Python verification, desktop/mobile browser tests and npm advisory
checks, preserving reports as artifacts. CI does not activate live trading or
turn exchange-blocked gates into PASS. Lockfile installation and optional
dependency advisory review remain deployment work.

Architecture:

- `models.py`: closed-candle, timeframe and signal contracts.
- `agents.py`, `indicators.py`, `profile.py`: six isolated experimental agents.
- `backtest.py`, `validation.py`, `consensus.py`: independent research and approval.
- `risk.py`, `execution.py`: independent sizing and durable paper execution boundary.
- `bybit.py`: public reads, optional closed-candle stream, authenticated demo reads.
- `security.py`, `storage.py`, `server.py`: owner auth, SQLite migration, audit, workers.
- `gates.py`, `scripts/verify.py`: source-bound evidence and dependency enforcement.

The source audit, inventory, specifications and live-readiness limitations are
in `research/`. Machine-readable evidence is in `reports/`. See
`research/readiness.md` for each agent's actual validation state.
