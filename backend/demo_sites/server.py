"""
demo_sites/server.py
=====================
Run this to serve all 3 demo websites locally.
Nova Bridge will automate these sites during the demo.

Usage:
  cd demo_sites
  python server.py

Then open:
  http://localhost:3000/book      ← Apollo Hospital booking
  http://localhost:3000/pharmacy  ← 1mg medicine order
  http://localhost:3000/bill      ← BESCOM bill payment
"""

import http.server
import socketserver
import os
import webbrowser

PORT = 3000
DIR  = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        # clean URL routing
        routes = {
            '/':          '/book.html',
            '/book':      '/book.html',
            '/pharmacy':  '/pharmacy.html',
            '/bill':      '/bill.html',
        }
        if self.path in routes:
            self.path = routes[self.path]
        return super().do_GET()

    def log_message(self, format, *args):
        # clean logging
        print(f"  [Demo Server] {args[0]} {args[1]}")

if __name__ == "__main__":
    os.chdir(DIR)
    print(f"""
╔══════════════════════════════════════════════════╗
║         Nova Bridge — Demo Sites Server          ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  🏥  Apollo Hospital:                            ║
║      http://localhost:{PORT}/book                   ║
║                                                  ║
║  💊  1mg Pharmacy:                               ║
║      http://localhost:{PORT}/pharmacy               ║
║                                                  ║
║  ⚡  BESCOM Bill Payment:                        ║
║      http://localhost:{PORT}/bill                   ║
║                                                  ║
║  Press Ctrl+C to stop                           ║
╚══════════════════════════════════════════════════╝
""")
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()