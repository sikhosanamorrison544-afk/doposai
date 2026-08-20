#!/usr/bin/env python3
"""Reproduce / validate mobile boot: no GLB preload, load event completes quickly."""
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

UA_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)
UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
UA_DESKTOP = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PROBE = r"""
<script id="boot-probe">
(function () {
  var t0 = performance.now();
  var requested = [];
  var origFetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      var u = typeof input === 'string' ? input : (input && input.url) || '';
      requested.push(u);
    } catch (e) {}
    return origFetch.apply(this, arguments);
  };
  window.addEventListener('load', function () {
    report({ event: 'load' });
  });
  // Fallback if 'load' already happened before this script ran.
  if (document.readyState === 'complete') {
    report({ event: 'already-complete' });
  } else {
    setTimeout(function () {
      if (!window.__bootProbeSent) report({ event: 'timeout' });
    }, 5000);
  }
  function report(extra) {
    if (window.__bootProbeSent) return;
    window.__bootProbeSent = true;
    var payload = Object.assign({
      readyState: document.readyState,
      loadMs: Math.round(performance.now() - t0),
      hasLogin: !!document.getElementById('login-screen'),
      loginActive: !!(document.getElementById('login-screen') &&
        document.getElementById('login-screen').classList.contains('active')),
      glbRequested: requested.some(function (u) { return /butterflies\.glb/.test(u); }),
      threeRequested: requested.some(function (u) { return /three\.min\.js|GLTFLoader/.test(u); }),
      preloadGlb: !!document.querySelector('link[rel="preload"][href*="butterflies.glb"]'),
      ua: navigator.userAgent.slice(0, 80),
      requestedSample: requested.filter(function (u) {
        return /butterflies|three|app\.js|auth\/me|background/.test(u);
      }).slice(0, 20)
    }, extra || {});
    fetch('/beacon', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).catch(function () {});
  }
})();
</script>
"""


def build_fixture(outdir: Path) -> None:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{ store_name }}", "Boot Test Store")
    html = html.replace("{{ platform_motto or 'Pecunia Non Olet' }}", "Pecunia Non Olet")
    # Neutralize auth redirect/bootstrap side effects for fixture
    html = html.replace(
        "window.location.replace(landing);",
        "console.log('skip landing', landing);",
    )
    html = html.replace("</body>", PROBE + "\n</body>")
    (outdir / "index.html").write_text(html, encoding="utf-8")
    static = outdir / "static"
    if not static.exists():
        static.symlink_to(ROOT / "static")


def main() -> int:
    outdir = Path(tempfile.mkdtemp(prefix="pos-mobile-boot-"))
    build_fixture(outdir)
    beacons: list[dict] = []
    lock = Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(outdir), **kwargs)

        def log_message(self, *args):
            return

        def do_POST(self):
            if urlparse(self.path).path == "/beacon":
                n = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(n)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {"error": "bad json"}
                with lock:
                    beacons.append(payload)
                self.send_response(204)
                self.end_headers()
                return
            self.send_error(404)

        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                body = b'{"detail":"fixture"}'
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.1)

    profiles = [
        ("android-390", UA_ANDROID, 390, 844),
        ("iphone-390", UA_IPHONE, 390, 844),
        ("android-360", UA_ANDROID, 360, 640),
        ("desktop", UA_DESKTOP, 1280, 800),
    ]
    results = []
    try:
        for label, ua, w, h in profiles:
            with lock:
                beacons.clear()
            url = f"http://127.0.0.1:{port}/index.html"
            subprocess.run(
                [
                    "chromium",
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-gpu",
                    f"--user-agent={ua}",
                    f"--window-size={w},{h}",
                    "--virtual-time-budget=12000",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            deadline = time.time() + 3
            payload = None
            while time.time() < deadline:
                with lock:
                    if beacons:
                        payload = beacons[-1]
                        break
                time.sleep(0.1)
            row = {"profile": label, **(payload or {"error": "no beacon"})}
            results.append(row)
            print(
                f"{label}: loadMs={row.get('loadMs')} ready={row.get('readyState')} "
                f"loginActive={row.get('loginActive')} preloadGlb={row.get('preloadGlb')} "
                f"glbReq={row.get('glbRequested')} threeReq={row.get('threeRequested')} "
                f"event={row.get('event')}"
            )
    finally:
        server.shutdown()

    report = ROOT / "mobile_boot_report.json"
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")

    bad = [
        r
        for r in results
        if r.get("error")
        or r.get("preloadGlb")
        or r.get("glbRequested")
        or r.get("threeRequested")
        or not r.get("loginActive")
        or r.get("readyState") != "complete"
    ]
    # classic theme must not request three/glb
    if bad:
        print("MOBILE_BOOT_ISSUES", len(bad), file=sys.stderr)
        for r in bad:
            print(r, file=sys.stderr)
        return 1
    print("MOBILE_BOOT_OK", len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
