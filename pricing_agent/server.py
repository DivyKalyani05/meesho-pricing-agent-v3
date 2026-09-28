"""Zero-dependency HTTP server: serves the web UI and a small JSON API."""
import json
import mimetypes
import os
import threading
import traceback
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import InputError, PricingAgent
from .repricer import Repricer

mimetypes.add_type("image/webp", ".webp")   # not in every Linux mime table
mimetypes.add_type("text/javascript", ".js")

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
MAX_BODY = 1_000_000


class Handler(BaseHTTPRequestHandler):
    agent: PricingAgent = None
    repricer: Repricer = None
    lock = threading.Lock()

    def log_message(self, fmt, *args):  # quieter console
        first = str(args[0]) if args else ""
        if "/api/" in first or not first.startswith(("GET", "POST", "HEAD")):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ responses
    def _send(self, status, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise InputError("Request too large.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise InputError("Request body must be valid JSON.")

    # ------------------------------------------------------------ routes
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/health":
                return self._json(200, {"ok": True})
            if path == "/api/meta":
                return self._json(200, self.agent.meta())
            if path == "/api/listings":
                qs = parse_qs(urlparse(self.path).query)
                with self.lock:
                    out = self.repricer.seller_listings((qs.get("seller_id") or [None])[0],
                                                        (qs.get("mode") or ["balanced"])[0])
                return self._json(200, out)
            if path == "/api/db":
                return self._json(200, {"tables": self.agent.market.db_overview()})
            if path == "/" or path == "/index.html":
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            return self._json(404, {"error": "Not found"})
        except InputError as e:
            return self._json(400, {"error": str(e)})
        except Exception:
            traceback.print_exc()
            return self._json(500, {"error": "Something went wrong on our side. Please try again."})

    def do_HEAD(self):   # uptime checkers and link previews send HEAD requests
        self.do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self._read_json()
            if path == "/api/recommend":
                with self.lock:  # sqlite writes + shared caches: one at a time
                    result = self.agent.recommend(body)
                return self._json(200, result)
            if path == "/api/list":
                with self.lock:
                    return self._json(200, self.agent.list_product(body))
            if path == "/api/listings/apply":
                with self.lock:
                    return self._json(200, self.agent.apply_price(body))
            if path == "/api/detect":
                text = body.get("text", "") if isinstance(body, dict) else ""
                return self._json(200, {"detected": self.agent.detect(str(text)[:5000])})
            return self._json(404, {"error": "Not found"})
        except InputError as e:
            return self._json(400, {"error": str(e)})
        except Exception:
            traceback.print_exc()
            return self._json(500, {"error": "Something went wrong on our side. Please try again."})

    def _static(self, rel):
        full = os.path.realpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.realpath(WEB_DIR) + os.sep) or not os.path.isfile(full):
            return self._json(404, {"error": "Not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8000, exact_port: bool = False):
    Handler.agent = PricingAgent(db_path)
    Handler.repricer = Repricer(Handler.agent)
    last_err = None
    for p in ([port] if exact_port else range(port, port + 20)):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            return httpd, p
        except OSError as e:
            last_err = e
    raise last_err
