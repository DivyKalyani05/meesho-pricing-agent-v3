#!/usr/bin/env python3
"""
Start the Meesho Kurti Pricing Agent prototype.

    python3 run.py              # build the database if needed, then serve on http://127.0.0.1:8000
    python3 run.py --rebuild    # regenerate the synthetic marketplace first
    python3 run.py --port 9000 --no-browser
"""
import argparse
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pricing_agent import seed  # noqa: E402
from pricing_agent.server import serve  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # On a cloud host (e.g. Render) the platform sets $PORT and the app must listen on all interfaces.
    cloud = "PORT" in os.environ
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="0.0.0.0" if cloud else "127.0.0.1")
    ap.add_argument("--rebuild", action="store_true", help="regenerate the database")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if sys.version_info < (3, 9):
        sys.exit("Python 3.9 or newer is required.")
    if args.rebuild or seed.needs_rebuild(seed.DB_PATH):
        print("Building the synthetic Meesho kurti marketplace ...")
        seed.build()

    httpd, port = serve(seed.DB_PATH, args.host, args.port, exact_port=cloud)
    url = f"http://{args.host}:{port}/"
    print(f"\n  Kurti Pricing Agent is running at {url}\n  Press Ctrl+C to stop.\n")
    if not args.no_browser and not cloud:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
