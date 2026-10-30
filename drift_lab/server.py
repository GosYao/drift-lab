"""Local stateless preview. No cloud credentials, writes, shell execution or model calls."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .engine import compare, replay
from .github_view import TRIGGERS, preview
from .scenarios import SCENARIOS, scenario

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 4096


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value, status=200):
        self.send_bytes(json.dumps(value).encode(), "application/json; charset=utf-8", status)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/health":
            return self.send_json({"status": "ok", "mode": "fixture", "cloud_connected": False})
        if url.path == "/api/scenarios":
            return self.send_json(SCENARIOS)
        if url.path == "/api/triggers":
            return self.send_json(TRIGGERS)
        if url.path == "/api/github":
            identifier = parse_qs(url.query).get("trigger", ["pr"])[0]
            try:
                return self.send_json(preview(identifier))
            except ValueError as error:
                return self.send_json({"error": str(error)}, 400)
        if url.path == "/api/report":
            identifier = parse_qs(url.query).get("scenario", ["iam"])[0]
            try:
                expected, observed = scenario(identifier)
                report = compare(expected, observed)
            except ValueError as error:
                return self.send_json({"error": str(error)}, 400)
            return self.send_json(report)
        files = {"/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css"}
        if url.path not in files:
            return self.send_json({"error": "Not found"}, 404)
        file = STATIC / files[url.path]
        types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}
        self.send_bytes(file.read_bytes(), types[file.suffix] + "; charset=utf-8")

    def do_POST(self):
        if self.path != "/api/replay":
            return self.send_json({"error": "Not found"}, 404)
        # No CORS; reject browser cross-origin requests even though replay is stateless.
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            return self.send_json({"error": "Cross-origin request rejected"}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > MAX_BODY:
                return self.send_json({"error": "Invalid request size"}, 413)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Expected an object")
            expected, observed = scenario(payload.get("scenario", "iam"))
            if payload.get("baseline", False):
                observed = expected
            return self.send_json(replay(expected, observed))
        except (ValueError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)


def serve(host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, port), Handler)
    print("Drift Lab: http://{}:{} (synthetic fixtures; no AWS connection)".format(host, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
