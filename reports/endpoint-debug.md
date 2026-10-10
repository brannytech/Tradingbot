# Endpoint debugging ? 2026-10-10

User-requested runtime switch: all exchange website, REST, OAuth and optional WebSocket hosts now use bybitglobal.com. Legacy authorization launcher directs users to integrated OAuth rather than running the old bybit.com helper.

Credential-free external network probes on this PC:
- api-demo.bybit.com: DNS failed, Windows error 11001.
- api.bybitglobal.com/v5/market/time: verified TLS, HTTP 200, retCode 0, timeSecond/timeNano response.
- api-demo.bybitglobal.com/v5/market/time: TLS certificate hostname mismatch, verification code 62. No credentials used.
- api2.bybitglobal.com: HTTPS 200; Global OAuth page and token GET paths respond. This does not validate token exchange or user account authorization.
- www.bybitglobal.com: HTTPS 200.
- api-demo.bytick.com/v5/market/time: TLS certificate verification failure; no fallback enabled.

Corrections: Global runtime URLs; distinct DNS/TLS/API errors; private redirects blocked; full USDT linear position pagination with repeated-cursor guard; OAuth temporary credentials cleared on failure; Windows launcher uses installed Anaconda interpreter. Automated exchange orders remain disabled.

Official documentation still lists api-demo.bybit.com for demo; Global replacement is requested configuration, not confirmed demo compatibility. Sources: https://bybit-exchange.github.io/docs/v5/demo and https://bybit-exchange.github.io/docs/v5/guide .
