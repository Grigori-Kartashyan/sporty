import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080


STAGING = {
    "database": {
        "host": "staging-db.internal",
        "port": 7777,
        "password": "staging-secret-from-remote",
        "pool_size": 10,
    }
}

PRODUCTION = {
    "database": {
        "host": "prod-db.internal",
        "port": 5432,
        "password": "prod-secret-from-remote",
        "pool_size": 50,
    }
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.rstrip("/")
        if path == "/staging":
            self._send(200, STAGING)
        elif path == "/production":
            self._send(200, PRODUCTION)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "not found"}')

    def _send(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    server = HTTPServer(("localhost", PORT), _Handler)
    sys.stderr.write(f"mock_server listening on http://localhost:{PORT} (Ctrl-C to stop)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopping\n")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
