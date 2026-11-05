#!/usr/bin/env python3
"""
VaultStock Development Server Launcher
Starts both:
  1. FastAPI Backend API (http://localhost:8000)
  2. Frontend Web Server (http://localhost:3000)
"""

import os
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(PROJECT_DIR, "web")

# Default to demo mode for local presentation runs
os.environ.setdefault("VAULTSTOCK_DEMO_MODE", "1")


class StaticRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def list_directory(self, path):
        self.send_error(404, "Directory listing disabled")
        return None

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "connect-src http://localhost:8000 http://127.0.0.1:8000; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def start_web_server(port=3000):
    server = HTTPServer(("127.0.0.1", port), StaticRequestHandler)
    print(f"[+] Frontend UI:  http://localhost:{port}")
    server.serve_forever()


def main():
    print("=" * 60)
    print(" VaultStock — Local Development Server")
    print("=" * 60)

    web_thread = threading.Thread(target=start_web_server, args=(3000,), daemon=True)
    web_thread.start()

    def open_browser():
        time.sleep(1.0)
        webbrowser.open("http://localhost:3000")

    threading.Thread(target=open_browser, daemon=True).start()

    demo_mode = os.environ.get("VAULTSTOCK_DEMO_MODE") == "1"
    reload_mode = os.environ.get("VAULTSTOCK_RELOAD") == "1"
    print(f"[+] Backend API:  http://localhost:8000 (Demo Mode: {demo_mode})")
    if demo_mode:
        print("[+] Swagger Docs: http://localhost:8000/docs")
        print("[+] Demo Logins:  admin / vault-admin-2026  |  staff / vault-staff-2026")
    print("=" * 60)

    try:
        import uvicorn
        os.chdir(PROJECT_DIR)
        uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=reload_mode)
    except KeyboardInterrupt:
        print("\n[+] Server stopped.")


if __name__ == "__main__":
    main()
