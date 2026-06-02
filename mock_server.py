from __future__ import annotations

import http.server
import socketserver
from pathlib import Path

PORT = 8000
ROOT = Path(__file__).resolve().parent / "mock_site"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)


if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving mock site from {ROOT} at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
