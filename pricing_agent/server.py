"""Zero-dependency HTTP server: serves the web UI and a small JSON API."""
import json
import mimetypes
import os
import threading
import traceback
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .dbview import DBView
from .engine import InputError, PricingAgent
from .narrator import Narrator
from .repricer import Repricer

mimetypes.add_type("image/webp", ".webp")   # not in every Linux mime table
mimetypes.add_type("text/javascript", ".js")

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
MAX_BODY = 1_000_000


class Handler(BaseHTTPRequestHandler):
    agent: PricingAgent = None
    repricer: Repricer = None
    narrator: Narrator = None
    dbview: DBView = None
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

    def _qs(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

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
                return self._json(200, dict(self.agent.meta(), llm=self.narrator.info()))
            if path == "/api/listings":
                qs = parse_qs(urlparse(self.path).query)
                with self.lock:
                    out = self.repricer.seller_listings((qs.get("seller_id") or [None])[0],
                                                        (qs.get("mode") or ["balanced"])[0])
                return self._json(200, out)
            if path == "/api/db":
                return self._json(200, {"tables": self.agent.market.db_overview()})
            if path == "/api/db/schema":
                return self._json(200, self.dbview.schema())
            if path == "/api/db/table":
                qs = self._qs()
                return self._json(200, self.dbview.page(qs.get("name", ""), qs.get("page", 1), qs.get("size", 25),
                                                        qs.get("q", ""), qs.get("filter_col", ""),
                                                        qs.get("filter_val", ""), qs.get("sort", ""),
                                                        qs.get("dir", "asc")))
            if path == "/api/db/export.csv":
                qs = self._qs()
                name = qs.get("name", "")
                data = self.dbview.csv(name, qs.get("q", ""), qs.get("filter_col", ""), qs.get("filter_val", ""),
                                       qs.get("sort", ""), qs.get("dir", "asc")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
                return
            if path == "/" or path == "/index.html":
                return self._static("index.html")
            if path in ("/prototype", "/prototype/"):
                return self._static("prototype.html")
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
            if path == "/api/listings/delist":
                with self.lock:
                    return self._json(200, self.agent.set_status(body, "delisted"))
            if path == "/api/listings/relist":
                with self.lock:
                    return self._json(200, self.agent.set_status(body, "active"))
            if path == "/api/demo/restore":
                with self.lock:
                    return self._json(200, self.agent.restore_examples())
            if path == "/api/narrate/pricing":
                rid = body.get("recommendation_id") if isinstance(body, dict) else None
                result = self.agent.recent.get(rid) if isinstance(rid, int) else None
                if result is None:
                    return self._json(200, {"source": "template", "why": "recommendation not in memory"})
                return self._json(200, self.narrator.narrate_pricing(result))   # slow call: outside the lock
            if path == "/api/narrate/listing":
                if not isinstance(body, dict):
                    raise InputError("Invalid request.")
                with self.lock:
                    found = self.repricer.find_variant(body.get("product_id"), body.get("mode") or "balanced")
                if found is None:
                    return self._json(200, {"source": "template", "why": "listing not found"})
                v, design, seller, goal = found
                return self._json(200, self.narrator.narrate_listing(v, design, seller, goal))
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
    Handler.narrator = Narrator()
    Handler.dbview = DBView(db_path)
    last_err = None
    for p in ([port] if exact_port else range(port, port + 20)):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            return httpd, p
        except OSError as e:
            last_err = e
    raise last_err
