"""
finanzamt.ui.server
~~~~~~~~~~~~~~~~~~~
Uvicorn launcher for the finanzamt web UI.

Called by the CLI via ``finanzamt ui`` or directly::

    python -m finanzamt.ui.server
    python -m finanzamt.ui.server --port 8080 --no-browser

The server serves:
  - /api/*            — FastAPI routes (health, receipts, tax)
  - /assets/*         — Vite-compiled JS/CSS bundles
  - /*                — index.html (SPA catch-all)

Building the frontend
---------------------
    cd frontend/
    npm install
    npm run build
    cp -r dist/* ../src/finanzamt/ui/static/

After copying, restart the server — static files are picked up automatically.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

STATIC_DIR = Path(__file__).parent / "static"


def _open_browser(url: str, delay: float = 1.2) -> None:
    """Open the browser after a short delay so the server is ready."""
    def _open():
        time.sleep(delay)
        webbrowser.open(url)
    t = threading.Thread(target=_open, daemon=True)
    t.start()


def launch(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    reload: bool = False,
    open_browser: bool = True,
    log_level: str = "warning",
) -> None:
    """
    Start the finanzamt API + UI server.

    Args:
        host:         Bind address (default 127.0.0.1).
        port:         TCP port (default 8000).
        reload:       Enable uvicorn hot-reload (dev mode only).
        open_browser: Automatically open the browser on start.
        log_level:    Uvicorn log level.
    """
    try:
        import uvicorn
    except ImportError:
        print(
            "[error] uvicorn is not installed.\n"
            "        Install the UI extras:  pip install finanzamt[ui]",
            file=sys.stderr,
        )
        sys.exit(1)

    url = f"http://{host}:{port}"

    # Show static build status
    has_static = STATIC_DIR.exists() and any(STATIC_DIR.glob("*.html"))
    if has_static:
        print(f"  ✓  Frontend found at {STATIC_DIR}")
    else:
        print(
            f"  ⚠  No built frontend found in {STATIC_DIR}\n"
            f"     API will work but the UI will show a placeholder.\n"
            f"     Build: cd frontend && npm run build && "
            f"cp -r dist/* src/finanzamt/ui/static/"
        )

    print(f"\n  finanzamt UI  →  {url}")
    print(f"  API docs      →  {url}/docs")
    print(f"  Press Ctrl+C to stop.\n")

    if open_browser:
        _open_browser(url)

    uvicorn.run(
        "finanzamt.ui.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Start the finanzamt web UI server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host",       default=DEFAULT_HOST,
                   help="Bind address.")
    p.add_argument("--port", "-p", default=DEFAULT_PORT, type=int,
                   help="TCP port.")
    p.add_argument("--reload",     action="store_true",
                   help="Enable hot-reload (development mode).")
    p.add_argument("--no-browser", action="store_true",
                   help="Do not open the browser automatically.")
    p.add_argument("--log-level",  default="warning",
                   choices=["debug", "info", "warning", "error"],
                   help="Uvicorn log level.")
    return p


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(level=logging.WARNING)
    launch(
        host=args.host,
        port=args.port,
        reload=args.reload,
        open_browser=not args.no_browser,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()