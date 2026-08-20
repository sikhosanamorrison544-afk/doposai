#!/usr/bin/env python3
"""Validate pos-client-boot upgrade reload without wiping business localStorage keys."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BUILD = "mobile-cache-fix-v1"

HTML = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<script>
// Seed BEFORE boot script (simulates an existing normal browser profile).
(function () {{
  try {{
    if (!sessionStorage.getItem('fixture_seeded')) {{
      localStorage.setItem('pos_client_build', 'old-build-before-fix');
      localStorage.setItem('pos_token', 'keep-me-token');
      localStorage.setItem('pos_user', '{{"username":"admin"}}');
      localStorage.setItem('pos_offline_mutations', '[{{"id":1}}]');
      localStorage.setItem('pos-theme', 'classic');
      sessionStorage.setItem('fixture_seeded', '1');
    }}
  }} catch (e) {{}}
}})();
</script>
<meta name="pos-build" content="{BUILD}">
<script>window.__POS_BUILD__={json.dumps(BUILD)};</script>
<script src="/static/js/pos-client-boot.js?v={BUILD}"></script>
</head>
<body>
<pre id="out">boot</pre>
<script>
(function(){{
  function report(extra) {{
    var payload = Object.assign({{
      build: localStorage.getItem('pos_client_build'),
      token: localStorage.getItem('pos_token'),
      user: localStorage.getItem('pos_user'),
      offline: localStorage.getItem('pos_offline_mutations'),
      theme: localStorage.getItem('pos-theme'),
      href: location.href,
      reloadKey: sessionStorage.getItem('pos_client_build_reload'),
      navigations: performance.navigation ? performance.navigation.type : null
    }}, extra || {{}});
    fetch('/beacon', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}});
  }}
  // After upgrade reload, boot should have set the new build.
  setTimeout(function(){{ report({{phase:'after'}}); }}, 1200);
}})();
</script>
</body></html>
"""


def main() -> int:
    outdir = Path(tempfile.mkdtemp(prefix="pos-cache-bust-"))
    profile = Path(tempfile.mkdtemp(prefix="pos-chrome-profile-"))
    (outdir / "index.html").write_text(HTML, encoding="utf-8")
    static = outdir / "static"
    if not static.exists():
        static.symlink_to(ROOT / "static")

    beacons: list[dict] = []
    lock = Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(outdir), **k)

        def log_message(self, *a):
            return

        def do_POST(self):
            if urlparse(self.path).path != "/beacon":
                self.send_error(404)
                return
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n)
            with lock:
                beacons.append(json.loads(raw.decode("utf-8")))
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.1)

    url = f"http://127.0.0.1:{port}/index.html"
    try:
        subprocess.run(
            [
                "chromium",
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=15000",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        deadline = time.time() + 5
        while time.time() < deadline and len(beacons) < 1:
            time.sleep(0.1)
    finally:
        server.shutdown()

    if not beacons:
        print("NO_BEACON", file=sys.stderr)
        return 1
    # Prefer the last beacon (post-reload if it happened)
    last = beacons[-1]
    print("beacons", len(beacons))
    print(json.dumps(last, indent=2))
    ok = (
        last.get("build") == BUILD
        and last.get("token") == "keep-me-token"
        and last.get("offline") == '[{"id":1}]'
        and last.get("theme") == "classic"
        and "admin" in (last.get("user") or "")
    )
    if not ok:
        print("CACHE_BUST_FAIL", file=sys.stderr)
        return 1
    print("CACHE_BUST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
