from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json, os
from .orders import Kitchen, Conflict


def serve():
    kitchen = Kitchen(os.environ.get("KITCHEN_DATABASE", "data/kitchen.sqlite3"))
    if not kitchen.menu():
        kitchen.add_item(
            "bowl", "Roasted vegetable bowl", "Mains", 1250, 40, ("sesame",)
        )
        kitchen.add_item("soup", "Seasonal soup", "Mains", 750, 30)
        kitchen.add_item("tea", "Iced tea", "Drinks", 300, 80)
    web = Path(__file__).resolve().parents[1] / "web"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/menu":
                return self.send_json(200, kitchen.menu())
            path = {
                "/": "index.html",
                "/app.js": "app.js",
                "/style.css": "style.css",
            }.get(self.path)
            if path is None:
                return self.send_json(404, {"error": "not found"})
            body = (web / path).read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                {
                    "index.html": "text/html; charset=utf-8",
                    "app.js": "text/javascript",
                    "style.css": "text/css",
                }[path],
            )
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/api/orders":
                return self.send_json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 20000:
                    raise ValueError("invalid body length")
                body = json.loads(self.rfile.read(length))
                result = kitchen.create_order(
                    self.headers.get("Idempotency-Key", ""),
                    body["items"],
                    body["pickup"],
                )
                self.send_json(201, result)
            except Conflict as error:
                self.send_json(409, {"error": str(error)})
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"error": "invalid order"})

        def send_json(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(
        ("127.0.0.1", int(os.environ.get("PORT", "8081"))), Handler
    ).serve_forever()


if __name__ == "__main__":
    serve()
