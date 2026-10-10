import json
import threading
from dataclasses import asdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .security import Auth
from .storage import Store
from .gates import gate_records
from .risk import RiskLimits


class Application:
    def __init__(self, config, store=None):
        self.config = config
        self.store = store or Store(f"data/{config.environment}.sqlite3")
        self.auth = Auth(config.password)
        owner = self.store.setting("owner_auth")
        if not config.password and owner:
            self.auth.restore(owner)
        from .connections import Connections
        self.connections = Connections(config)
        self.lock = threading.RLock()
        self.snapshot = None
        self.worker_status = "IDLE"
        self.alerts = []
        self.stop_event = threading.Event()
        self.worker = None
        self.store.event("startup", {"environment": config.environment, "live_enabled": False})

    def state(self):
        with self.lock:
            return dict(environment=self.config.environment, live_enabled=False,
                        emergency_stop=self.store.setting("emergency_stop", False),
                        worker=self.worker_status, alerts=list(self.alerts),
                        snapshot=self.snapshot, orders=self.store.orders(),
                        reports=self.store.reports(), gates=gate_records(),events=self.store.events(),
                        risk_limits=self.store.setting("risk_limits",asdict(RiskLimits())),
                        connections=self.connections.view(),
                        instrument_catalog=self.store.setting("instrument_catalog", {}),
                        settings=dict(interval=300, threshold=.95,
                                      demo_credentials_present=self.connections.demo is not None))

    def launch_job(self, name, job, clear_snapshot=True):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("A worker job is already running")
            self.worker_status = f"RUNNING: {name}"
        def run():
            try:
                job()
                with self.lock:
                    self.worker_status = "IDLE"
            except Exception as error:
                # Log exception class only; HTTP exceptions may contain secrets.
                with self.lock:
                    self.worker_status = "FAILED"
                    self.alerts.append(f"{name} failed: {type(error).__name__}. No execution permitted.")
                    if clear_snapshot:
                        self.snapshot = None
                self.store.event("worker_failed", {"job": name, "error_type": type(error).__name__})
        self.worker = threading.Thread(target=run, name=name, daemon=True)
        self.worker.start()

    def close(self):
        self.stop_event.set()
        self.connections.close()
        if self.worker:
            self.worker.join(timeout=30)
            if self.worker.is_alive():
                raise RuntimeError("Worker did not stop; database kept open")
        self.store.close()


def make_server(app, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Request bodies, cookies, API keys and passwords are never logged.
            pass

        def send(self, code, payload, headers=None, html=False):
            data = payload.encode() if html else json.dumps(payload, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def token(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                return cookie["session"].value if "session" in cookie else ""
            except Exception:
                return ""

        def origin_ok(self):
            host = self.headers.get("Host", "")
            actual_port=server.server_port
            valid = {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"}
            return host in valid and self.headers.get("Origin", f"http://{host}") == f"http://{host}"

        def do_GET(self):
            if not self.origin_ok():
                return self.send(403, {"error": "Origin rejected"})
            path = urlsplit(self.path).path
            if path == "/health":
                return self.send(200, {"status": "ok", "environment": app.config.environment, "live_enabled": False,"setup_required":app.auth.digest is None})
            if path == "/":
                p = Path(__file__).parent/"static"/"index.html"
                return self.send(200, p.read_text(encoding="utf-8") if p.exists() else "<h1>Strategy Intelligence</h1><p>Foundation ready.</p>", html=True)
            if not app.auth.check(self.token()):
                return self.send(401, {"error": "Authentication required"})
            if path == "/api/session":
                csrf = app.auth.session_csrf(self.token())
                return self.send(200, {"csrf": csrf}) if csrf else self.send(401, {"error": "Authentication required"})
            if path == "/api/state":
                return self.send(200, app.state())
            return self.send(404, {"error": "Not found"})

        def do_POST(self):
            if not self.origin_ok():
                return self.send(403, {"error": "Origin rejected"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 4096:
                    return self.send(413, {"error": "Request too large"})
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("Object body required")
                path = urlsplit(self.path).path
                if path == "/api/setup":
                    with app.lock:
                        record=app.auth.configure(body.get("password"))
                        app.store.put_setting("owner_auth",record)
                        app.store.event("owner_setup",{"configured":True})
                    return self.send(200,{"ok":True})
                if path == "/api/login":
                    password = body.get("password", "")
                    if not isinstance(password, str):
                        raise ValueError("Invalid password")
                    session = app.auth.login(password, self.client_address[0])
                    if not session:
                        return self.send(401, {"error": "Invalid credentials or rate limit"})
                    token, csrf = session
                    return self.send(200, {"csrf": csrf}, {"Set-Cookie": f"session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600"})
                if not app.auth.check(self.token(), self.headers.get("X-CSRF-Token"), True):
                    return self.send(403, {"error": "Authentication / CSRF rejected"})
                if path == "/api/logout":
                    app.auth.logout(self.token())
                    return self.send(200, {"ok": True}, {"Set-Cookie": "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
                if path == "/api/emergency-stop":
                    if not isinstance(body.get("active"), bool):
                        raise ValueError("Boolean active required")
                    app.store.put_setting("emergency_stop", body["active"])
                    app.store.event("emergency_stop", {"active": body["active"]})
                    return self.send(200, {"active": body["active"]})
                if path == "/api/risk-limits":
                    from .risk import RiskLimits
                    from dataclasses import asdict
                    limits=RiskLimits(**body)
                    app.store.put_setting("risk_limits",asdict(limits))
                    app.store.event("risk_limits_changed",asdict(limits))
                    return self.send(200,{"ok":True})
                if path == "/api/account/demo":
                    key, secret = body.get("key"), body.get("secret")
                    if not all(isinstance(v, str) and 0 < len(v.strip()) <= 512 for v in (key, secret)):
                        raise ValueError("Demo credentials required")
                    app.launch_job("demo-connect", lambda: app.connections.connect_demo(key, secret), clear_snapshot=False)
                    return self.send(202, {"ok": True})
                if path == "/api/account/demo/refresh":
                    app.launch_job("demo-read", app.connections.refresh_demo, clear_snapshot=False)
                    return self.send(202, {"ok": True})
                if path == "/api/account/live":
                    app.launch_job("live-authorization", app.connections.prepare_live, clear_snapshot=False)
                    return self.send(202, {"ok": True})
                if path == "/api/account/live/select":
                    account_id = body.get("account_id")
                    if not isinstance(account_id, str):
                        raise ValueError("Account selection required")
                    app.launch_job("live-account-selection", lambda: app.connections.select_live(account_id), clear_snapshot=False)
                    return self.send(202, {"ok": True})
                if path == "/api/account/live/create":
                    if body.get("confirmed") is not True:
                        raise ValueError("Explicit account creation consent required")
                    app.launch_job("live-account-creation", lambda: app.connections.select_live(create=True), clear_snapshot=False)
                    return self.send(202, {"ok": True})
                if path == "/api/account/disconnect":
                    app.connections.disconnect(body.get("mode"))
                    return self.send(200, {"ok": True})
                if path == "/api/refresh":
                    from .service import refresh
                    app.launch_job("market-refresh", lambda: refresh(app, body))
                    return self.send(202, {"worker": "RUNNING"})
                if path == "/api/instruments/refresh":
                    from .service import sync_instruments
                    app.launch_job("instrument-sync", lambda: sync_instruments(app))
                    return self.send(202, {"worker": "RUNNING"})
                if path == "/api/backtest":
                    from .service import run_backtest
                    app.launch_job("backtest", lambda: run_backtest(app, body))
                    return self.send(202, {"worker": "RUNNING"})
                if path == "/api/live-activate":
                    return self.send(423, {"error": "LOCKED: mandatory readiness and owner activation gates incomplete"})
                return self.send(404, {"error": "Not found"})
            except (ValueError, TypeError, KeyError):
                return self.send(400, {"error": "Invalid request"})
            except Exception as error:
                app.store.event("api_failed", {"error_type": type(error).__name__})
                return self.send(503, {"error": "Operation failed; execution disabled"})
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
