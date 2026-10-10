# Bybit official trading CLI compatibility

Reviewed https://github.com/bybit-exchange/trading-cli on 2026-10-09.
Its README identifies `bybit-official-trading-cli`, Node20.6+, structured V5
JSON output, HMAC/RSA credentials, mainnet confirmation, order caps, kill-switch,
deterministic orderLinkId, and manifest verification. It states v1 targets
macOS/Linux, with Windows deferred to v2. Documented output envs are mainnet
and testnet; demo support was not established by this review.

This Windows app therefore uses the native read-only Python V5 transport.
No CLI package was installed or executed. Mainnet defaults cannot be used as
demo equivalence. Future adapters must verify actual package support, pin and
audit it, use the app's risk/consensus boundary, preserve stable order IDs and
fail closed on environment mismatch. CLI safety flags complement, rather than
replace, app risk controls. No CLI order path is enabled.
