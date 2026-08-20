#!/usr/bin/env python3
"""Viewport checks for Settings via Chromium screenshots + HTTP beacon metrics."""
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

VIEWPORTS = [
    (360, 640),
    (390, 844),
    (412, 915),
    (768, 1024),
    (1024, 768),
    (1440, 900),
]

PROBE_JS = r"""
<script id="viewport-probe">
(function () {
  // Prevent auth/bootstraps from navigating away during viewport capture.
  try {
    var _assign = window.location.assign.bind(window.location);
    var _replace = window.location.replace.bind(window.location);
    window.location.assign = function (u) { if (String(u).indexOf('store-settings') === -1 && String(u) !== '.') console.log('blocked assign', u); };
    window.location.replace = function (u) { if (String(u).indexOf('store-settings') === -1) console.log('blocked replace', u); };
  } catch (e) {}

  function run() {
    try {
      if (typeof switchSettingsPage === 'function') switchSettingsPage(1);
      if (window.PosPasswordToggle && window.PosPasswordToggle.scan) {
        window.PosPasswordToggle.scan(document);
      }
      // Enhance password fields on page 2 as well
      if (typeof switchSettingsPage === 'function') switchSettingsPage(2);
      if (window.PosPasswordToggle && window.PosPasswordToggle.scan) {
        window.PosPasswordToggle.scan(document);
      }
      var body = document.body;
      var html = document.documentElement;
      var main = document.querySelector('.settings-page-container, #settings-main');
      var probe = document.createElement('div');
      probe.className = 'break-long';
      probe.textContent = 'VeryLongBusinessName_ExampleTrading and https://script.google.com/macros/s/example/exec';
      probe.style.maxWidth = '100%';
      (main || body).appendChild(probe);
      var intended = (function () {
        var m = /[?&]vp=(\d+)x(\d+)/.exec(location.search || '');
        return m ? { w: parseInt(m[1], 10), h: parseInt(m[2], 10) } : null;
      })();
      if (intended) {
        document.documentElement.style.maxWidth = intended.w + 'px';
        document.body.style.maxWidth = intended.w + 'px';
        document.body.style.overflowX = 'clip';
      }
      var scrollW = Math.max(body.scrollWidth, html.scrollWidth);
      var clientW = Math.max(body.clientWidth, html.clientWidth, window.innerWidth);
      var mainW = main ? main.scrollWidth : scrollW;
      var mainClient = main ? main.clientWidth : clientW;
      var forcedMax = parseInt(getComputedStyle(document.body).maxWidth, 10) || 0;
      var overflowX = (mainW > mainClient + 2) || (forcedMax > 0 && mainW > forcedMax + 2);
      var title = document.querySelector('.settings-page-title');
      var input = document.querySelector('#store-name');
      var tab = document.querySelector('.settings-page-btn');
      var card = document.querySelector('details.settings-section');
      var kids = main ? Array.prototype.slice.call(main.querySelectorAll('*')) : [];
      var wide = kids.map(function (el) {
        return { tag: el.tagName, id: el.id || '', cls: (el.className || '').toString().slice(0, 60), w: el.scrollWidth };
      }).filter(function (x) { return x.w > mainClient + 2; }).sort(function (a, b) { return b.w - a.w; }).slice(0, 8);
      var payload = {
        overflowX: overflowX,
        scrollW: scrollW,
        clientW: clientW,
        mainScrollW: mainW,
        mainClientW: mainClient,
        forcedMax: forcedMax || null,
        intendedW: intended ? intended.w : null,
        wide: wide,
        innerWidth: window.innerWidth,
        hasContainer: !!main,
        hasSettingsCss: !!document.querySelector('link[href*="settings.css"]'),
        titleFont: title ? getComputedStyle(title).fontSize : null,
        inputMinH: input ? getComputedStyle(input).minHeight : null,
        tabMinH: tab ? getComputedStyle(tab).minHeight : null,
        hasPassword: !!document.querySelector('#cashier-password'),
        hasPwToggle: !!document.querySelector('.pw-field .pw-toggle'),
        cardPad: card ? getComputedStyle(card).padding : null
      };
      fetch('/beacon', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      }).catch(function () {});
    } catch (e) {
      fetch('/beacon', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({error: String(e)})
      }).catch(function () {});
    }
  }
  window.addEventListener('load', function () { setTimeout(run, 700); });
})();
</script>
"""


def build_fixture(outdir: Path, width: int) -> None:
    html = (ROOT / "templates" / "store-settings.html").read_text(encoding="utf-8")
    html = html.replace("{{ store_name }}", "Viewport Test Store")
    html = html.replace("{{ platform_motto or 'Pecunia Non Olet' }}", "Pecunia Non Olet")
    html = html.replace(
        '<script src="/static/js/admin.js?v=30"></script>',
        '<script>window.loadStoreSettings=function(){};window.loadCashiers=function(){};window.loadBackupStatus=function(){};</script>',
    )
    force = (
        f'<style id="vp-force">html,body,#app{{max-width:{width}px!important;'
        f"width:{width}px!important;overflow-x:clip!important}}"
        f".store-settings-page-content,.settings-page-container{{width:min(100% - 1rem,{width - 8}px)!important;"
        f"max-width:{width - 8}px!important}}</style>"
    )
    html = html.replace("</head>", force + "\n</head>")
    html = html.replace("</body>", PROBE_JS + "\n</body>")
    (outdir / "store-settings.html").write_text(html, encoding="utf-8")
    static_link = outdir / "static"
    if not static_link.exists():
        static_link.symlink_to(ROOT / "static")


def main() -> int:
    outdir = Path(tempfile.mkdtemp(prefix="pos-settings-vp-"))
    shots = ROOT / "settings_viewport_shots"
    shots.mkdir(exist_ok=True)
    build_fixture(outdir, 360)

    beacons: list[dict] = []
    lock = Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(outdir), **kwargs)

        def log_message(self, fmt, *args):
            return

        def _json(self, code: int, payload):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                if path.endswith("/store-settings"):
                    return self._json(200, {
                        "store_name": "Viewport Test Store",
                        "store_phone": "0770000000",
                        "store_location": "123 Long Street",
                        "notification_email": "ops@example.com",
                        "low_stock_email_enabled": True,
                        "default_low_stock_threshold": 10,
                    })
                if path.endswith("/users"):
                    return self._json(200, [])
                if path.endswith("/backup/status"):
                    return self._json(200, {"enabled": False, "pending": 0, "online": True})
                if path.endswith("/platform-info"):
                    return self._json(200, {"motto": "Pecunia Non Olet"})
                return self._json(200, {})
            return super().do_GET()

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/beacon":
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {"error": "bad json"}
                with lock:
                    beacons.append(payload)
                self.send_response(204)
                self.end_headers()
                return
            if path.startswith("/api/"):
                return self._json(200, {"ok": True})
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.15)

    results = []
    try:
        for w, h in VIEWPORTS:
            build_fixture(outdir, w)
            with lock:
                beacons.clear()
            shot = shots / f"settings_{w}x{h}.png"
            url = f"http://127.0.0.1:{port}/store-settings.html?vp={w}x{h}"
            subprocess.run(
                [
                    "chromium",
                    "--headless=new",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--force-device-scale-factor=1",
                    f"--window-size={max(w, 500)},{h}",
                    f"--screenshot={shot}",
                    "--virtual-time-budget=12000",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            deadline = time.time() + 4
            payload = None
            while time.time() < deadline:
                with lock:
                    if beacons:
                        payload = beacons[-1]
                        break
                time.sleep(0.1)
            row = {"width": w, "height": h, "screenshot": str(shot), **(payload or {"error": "no beacon"})}
            results.append(row)
            print(
                f"{w}x{h}: overflowX={row.get('overflowX')} "
                f"scrollW={row.get('scrollW')} clientW={row.get('clientW')} "
                f"inner={row.get('innerWidth')} css={row.get('hasSettingsCss')} "
                f"pwToggle={row.get('hasPwToggle')} titleFont={row.get('titleFont')} "
                f"inputMinH={row.get('inputMinH')} tabMinH={row.get('tabMinH')} "
                f"shot={shot.name} bytes={shot.stat().st_size if shot.exists() else 0}"
            )
    finally:
        server.shutdown()

    report = ROOT / "settings_viewport_report.json"
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    bad = [
        r
        for r in results
        if r.get("error")
        or r.get("overflowX")
        or not r.get("hasSettingsCss")
        or not r.get("hasContainer")
        or not r.get("hasPwToggle")
    ]
    if bad:
        print("VIEWPORT_ISSUES", len(bad), file=sys.stderr)
        return 1
    print("VIEWPORT_OK", len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
