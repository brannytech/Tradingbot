"""Owner-only account reads and OAuth onboarding. No exchange order transport."""
import base64
import hashlib
import hmac
import json
import math
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request
from typing import Any
from urllib.error import HTTPError, URLError
from .bybit import DemoAccount, DemoAPIError, private_urlopen


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def demo_failure(error):
    result = dict(status="FAILED", message="Demo read failed. Check the demo key permissions and API connectivity.",
                  error_type=type(error).__name__, checked_at=int(time.time()))
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        result.update(error_code="DNS_BLOCKED", message="Cannot resolve api-demo.bybitglobal.com. The request could not reach Bybit; your keys have not been validated. Check DNS/network access or ask Bybit support for a supported demo API endpoint for Bybit Global.")
    elif isinstance(reason, ssl.SSLCertVerificationError):
        result.update(error_code="TLS_CERTIFICATE_INVALID", message="The HTTPS certificate for api-demo.bybitglobal.com could not be verified. The request stopped before sending credentials; your keys have not been validated. Ask Bybit support for the supported Global demo API endpoint with a valid certificate.")
    elif isinstance(error, DemoAPIError):
        messages = {
            10002: "Request timestamp rejected. Sync the Windows clock and retry.",
            10003: "Key invalid for the demo API. Create a key inside mainnet Demo Trading, rather than live or testnet.",
            10004: "Signature rejected. Check that the API key and secret belong to the same system-generated demo key.",
            10005: "API permissions denied. Check balance and position read permissions.",
            10010: "IP restriction mismatch. Check the key's allowed public IP addresses.",
            10009: "Bybit reports regional service restrictions. Contact Bybit support.",
            10028: "This read requires a Unified Trading Account. Check your demo account mode.",
            10006: "Bybit rate limit reached. Wait before retrying.",
            -2015: "Demo API key expired. Create a new demo key.",
            33004: "Demo API key expired. Create a new demo key.",
        }
        result.update(error_code=error.code, message=messages.get(error.code if error.code is not None else 0, "Bybit rejected the demo read. Check the numeric error code with Bybit support."))
    elif isinstance(error, HTTPError):
        result.update(error_code=error.code, message="Bybit demo API returned an HTTP error. Check network access and account availability with Bybit support.")
    elif isinstance(reason, TimeoutError):
        result.update(error_code="TIMEOUT", message="Bybit demo API timed out. Check your connection and retry.")
    elif isinstance(error, URLError):
        result.update(error_code="NETWORK_ERROR", message="Could not reach the Bybit demo API securely. Check connectivity; do not disable certificate verification.")
    return result


def wallet_view(result):
    rows = result.get("list", [])
    if not rows or not isinstance(rows[0], dict):
        raise ValueError("Missing account balance")
    row = rows[0]
    return dict(equity_usd=numeric(row.get("totalEquity")),
                coins=[dict(coin=c.get("coin"), wallet_balance=numeric(c.get("walletBalance")))
                       for c in row.get("coin", [])[:50]])


class Connections:
    OAUTH = "https://www.bybitglobal.com/oauth"
    API = "https://api2.bybitglobal.com"

    def __init__(self, config, resolver=socket.getaddrinfo, opener=private_urlopen):
        self.lock = threading.RLock()
        self.resolver, self.opener = resolver, opener
        self.demo = DemoAccount(config.demo_key, config.demo_secret) if config.demo_key and config.demo_secret else None
        self.demo_state: dict[str, Any] = dict(status="NOT_TESTED" if self.demo else "NOT_CONNECTED", message="Connect a demo key to read its account.")
        self.live_state: dict[str, Any] = dict(status="NOT_CONNECTED", message="Authorize a mainnet AI sub-account on Bybit. Trading stays locked.")
        self.token: dict[str, Any] | None = None
        self.live_credentials: dict[str, Any] | None = None
        self.server: ThreadingHTTPServer | None = None
        self.deadline = 0.0
        self.generation = 0
        self.state_token = ""
        self.verifier = ""
        self.closed = False

    def view(self):
        with self.lock:
            if self.live_state.get("status") == "AWAITING_AUTHORIZATION" and time.time() > self.deadline:
                self.live_state = dict(status="EXPIRED", message="Authorization link expired. Start a new connection.")
            # Explicit public projection: never serialize instance fields or secrets.
            return dict(demo=dict(self.demo_state), live=dict(self.live_state), execution_enabled=False,
                        account_website="https://www.bybitglobal.com/", credentials_storage="BACKEND_MEMORY_ONLY")

    def connect_demo(self, key, secret):
        if not isinstance(key, str) or not isinstance(secret, str) or not key.strip() or not secret.strip() or max(len(key), len(secret)) > 512:
            raise ValueError("Demo key and secret required")
        with self.lock:
            if self.closed:
                raise ValueError("Connection manager closed")
            self.demo = DemoAccount(key.strip(), secret.strip())
        self.refresh_demo()

    def refresh_demo(self):
        with self.lock:
            client = self.demo
            if client is None:
                raise ValueError("Demo credentials missing")
            self.demo_state = dict(status="CHECKING", message="Checking demo account reads...")
        try:
            balance = wallet_view(client.get("/v5/account/wallet-balance", {"accountType": "UNIFIED"}))
            try:
                rows: list[dict[str, Any]] = []
                seen: set[str] = set()
                params = {"category": "linear", "settleCoin": "USDT"}
                while True:
                    page = client.get("/v5/position/list", params)
                    rows.extend(page.get("list", []))
                    cursor = page.get("nextPageCursor")
                    if not cursor:
                        break
                    if not isinstance(cursor, str) or cursor in seen or len(seen) >= 100:
                        raise ValueError("Invalid or nonprogressing position pagination")
                    seen.add(cursor)
                    params = dict(category="linear", settleCoin="USDT", cursor=cursor)
                positions = [dict(symbol=r.get("symbol"), side=r.get("side"), size=numeric(r.get("size")),
                                  entry=numeric(r.get("avgPrice")), unrealised_pnl=numeric(r.get("unrealisedPnl")))
                             for r in rows if (numeric(r.get("size")) or 0) > 0]
                warning = None
            except Exception:
                positions, warning = [], "Position read unavailable; no exposure validation claimed."
            result = dict(status="CONNECTED", message="Demo account reads verified. Automated orders remain disabled.",
                          checked_at=int(time.time()), balance=balance, positions=positions, warning=warning,
                          position_scope="USDT linear positions only")
        except Exception as error:
            result = demo_failure(error)
        with self.lock:
            if self.demo is client and not self.closed:
                self.demo_state = result

    def disconnect(self, mode):
        if mode not in ("demo", "live"):
            raise ValueError("Invalid account mode")
        with self.lock:
            if mode == "demo":
                self.demo = None
                self.demo_state = dict(status="NOT_CONNECTED", message="Demo credentials removed from backend memory.")
            else:
                self.generation += 1
                self.token = None
                self.live_credentials = None
                self.verifier = self.state_token = ""
                self.live_state = dict(status="NOT_CONNECTED", message="Local OAuth session cleared. Revoke provider access separately on Bybit.")
        if mode == "live":
            self.stop_callback()

    def stop_callback(self, generation=None):
        with self.lock:
            if generation is not None and generation != self.generation:
                return
            server, self.server = self.server, None
        if server:
            server.shutdown()
            server.server_close()

    def request_oauth(self, path, token=None, body=None):
        # Only OAuth token and AI-account endpoints; never production trading.
        if path.split("?")[0] not in ("/oauth/v1/public/access_token", "/oauth/v1/resource/restrict/ai_accounts"):
            raise ValueError("OAuth endpoint denied")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(self.API + path, data=urlencode(body).encode() if body else None, headers=headers)
        with self.opener(req, timeout=12) as response:
            data = json.load(response)
        if data.get("retCode", data.get("ret_code", 0)) != 0:
            raise RuntimeError("OAuth provider rejected request")
        return data.get("result", data)

    def prepare_live(self):
        self.disconnect("live")
        with self.lock:
            if self.closed:
                raise ValueError("Connection manager closed")
            generation = self.generation
        try:
            for host in ("www.bybitglobal.com", "api2.bybitglobal.com"):
                self.resolver(host, 443)
        except OSError:
            with self.lock:
                if self.closed or generation != self.generation:
                    return
                self.live_state = dict(status="DNS_BLOCKED", message="Bybit Global is your account website, but the configured OAuth hosts www.bybitglobal.com / api2.bybitglobal.com cannot be resolved. Check network access and ask Bybit support for the supported Global OAuth endpoints.")
            return
        with self.lock:
            if self.closed or generation != self.generation:
                return
            self.verifier = secrets.token_urlsafe(32)
            self.state_token = secrets.token_urlsafe(32)
            self.deadline = time.time() + 300
            verifier, state_token = self.verifier, self.state_token
        owner = self
        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                parsed = urlsplit(self.path)
                args = parse_qs(parsed.query)
                with owner.lock:
                    valid = (parsed.path == "/callback" and generation == owner.generation
                             and not owner.closed and time.time() < owner.deadline
                             and hmac.compare_digest(args.get("state", [""])[0], owner.state_token)
                             and owner.live_state.get("status") == "AWAITING_AUTHORIZATION")
                    code = args.get("code", [""])[0]
                    if valid and code and len(code) < 8192:
                        owner.live_state = dict(status="EXCHANGING", message="Checking OAuth authorization...")
                        verifier = owner.verifier
                    else:
                        valid = False
                self.send_response(200 if valid else 403)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(b"Return to the bot to choose your AI sub-account." if valid else b"Authorization callback rejected or expired. Start again in the bot.")
                if valid:
                    threading.Thread(target=owner.exchange, args=(code, verifier, generation), daemon=True).start()
        server = None
        for port in range(9876, 9887):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), Callback)
                break
            except OSError:
                continue
        if server is None:
            with self.lock:
                self.live_state = dict(status="FAILED", message="Local callback ports unavailable. Close another authorization session and retry.")
            return
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        url = self.OAUTH + "?" + urlencode(dict(client_id="ai-agent", response_type="code", scope="ai-account",
              state=state_token, redirect_uri=f"http://127.0.0.1:{server.server_port}/callback",
              code_challenge=challenge, code_challenge_method="S256"))
        with self.lock:
            if self.closed or generation != self.generation:
                server.server_close()
                return
            self.server = server
            self.live_state = dict(status="AWAITING_AUTHORIZATION", message="Open the authorization link on this computer and approve on Bybit yourself.",
                                   authorize_url=url, expires_at=int(self.deadline))
            threading.Thread(target=server.serve_forever, daemon=True).start()
        timer = threading.Timer(300, self.expire_live, args=(generation,))
        timer.daemon = True
        timer.start()

    def expire_live(self, generation):
        with self.lock:
            if generation != self.generation or self.live_state.get("status") not in ("AWAITING_AUTHORIZATION", "EXPIRED"):
                return
            self.verifier = self.state_token = ""
            self.live_state = dict(status="EXPIRED", message="Authorization link expired. Start a new connection.")
        self.stop_callback(generation)

    def exchange(self, code, verifier, generation):
        try:
            token = self.request_oauth("/oauth/v1/public/access_token", body=dict(client_id="ai-agent", code=code, code_verifier=verifier))
            if not token.get("access_token"):
                raise ValueError("Missing token")
            result = self.request_oauth("/oauth/v1/resource/restrict/ai_accounts", token=token["access_token"])
            rows = result if isinstance(result, list) else result.get("accounts")
            if not isinstance(rows, list):
                raise ValueError("Provider did not return explicit account choices")
            choices = [dict(id=str(r["sub_member_id"]), name=str(r.get("nickname", "AI sub-account"))) for r in rows]
            with self.lock:
                if generation != self.generation or self.closed:
                    return
                self.token = dict(access=token["access_token"], expires_at=time.time()+int(token.get("expires_in", 86400)))
                self.live_state = dict(status="CHOOSE_ACCOUNT", accounts=choices, message="Choose an existing AI sub-account. No account is automatically selected or created.")
                self.verifier = self.state_token = ""
        except Exception as error:
            with self.lock:
                if generation == self.generation and not self.closed:
                    self.token = None
                    self.verifier = self.state_token = ""
                    self.live_state = dict(status="FAILED", error_type=type(error).__name__, message="OAuth exchange failed. Check API connectivity, account eligibility and 2FA, then start again.")
        finally:
            self.stop_callback(generation)

    def select_live(self, account_id=None, create=False):
        with self.lock:
            if (self.live_state.get("status") != "CHOOSE_ACCOUNT" or not self.token
                    or time.time() >= self.token["expires_at"]
                    or (not create and account_id not in [r["id"] for r in self.live_state.get("accounts", [])])
                    or (create and len(self.live_state.get("accounts", [])) >= 5)):
                raise ValueError("Select a listed account from a valid authorization session")
            generation, access = self.generation, self.token["access"]
        try:
            query = dict(is_create="true") if create else dict(sub_member_id=account_id)
            result = self.request_oauth("/oauth/v1/resource/restrict/ai_accounts?" + urlencode(query), token=access)
            if not isinstance(result, dict) or not result.get("sub_member_id") or (not create and str(result.get("sub_member_id")) != account_id) or not result.get("api_key") or not result.get("api_secret"):
                raise ValueError("Selected account credentials unavailable")
            account_id = str(result["sub_member_id"])
            with self.lock:
                if generation == self.generation and not self.closed:
                    self.live_credentials = dict(key=result["api_key"], secret=result["api_secret"], account_id=account_id)
                    self.token = None
                    self.live_state = dict(status="AUTHORIZED", account_id=account_id, message="AI sub-account authorization received. Live trading remains locked; balances and fills are not yet reconciled.")
        except Exception as error:
            with self.lock:
                if generation == self.generation:
                    self.token = None
                    self.live_credentials = None
                    self.live_state = dict(status="FAILED", error_type=type(error).__name__, message="Could not retrieve credentials for the selected AI account. Reconnect to retry.")

    def close(self):
        with self.lock:
            self.closed = True
        self.disconnect("demo")
        self.disconnect("live")
