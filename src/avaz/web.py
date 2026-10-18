"""The phone web app in ``web/``: export scales for it and serve it locally.

The web app is plain static files. It reads its scale positions from
``web/scales.json``, which is written here from ``config/scales.yaml`` so both
apps always use the same calibration.
"""

from __future__ import annotations

import functools
import json
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import config_dir
from .scales import load_scales


def web_dir() -> Path:
    return config_dir().parent / "web"


def scales_json(scales_path: Path | None = None) -> dict:
    """``{name: {"positions": [...], "labels": [...]}}`` for every scale in scales.yaml."""
    return {name: {"positions": s.positions, "labels": s.labels}
            for name, s in load_scales(scales_path).items()}


def export_scales(out: Path | None = None, scales_path: Path | None = None) -> Path:
    out = out or (web_dir() / "scales.json")
    text = json.dumps(scales_json(scales_path), indent=2, ensure_ascii=False) + "\n"
    out.write_text(text, encoding="utf-8")
    return out


class _Handler(SimpleHTTPRequestHandler):
    # Windows' registry sometimes maps .js to text/plain, and browsers refuse to run
    # modules served that way.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".json": "application/json",
                      ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def lan_address() -> str | None:
    """This computer's address on the local network, or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # no packet is sent; it only picks a route
            return s.getsockname()[0]
    except OSError:
        return None


def serve(port: int = 8765, host: str = "127.0.0.1") -> None:
    handler = functools.partial(_Handler, directory=str(web_dir()))
    with ThreadingHTTPServer((host, port), handler) as httpd:
        httpd.serve_forever()
