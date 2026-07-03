"""Browser control panel for Lamuel.

Serves a single-page console at ``http://<box-ip>:<port>/`` that:

* shows a live MJPEG feed from Lamuel's camera,
* streams a running log of what Lamuel hears and says (server-sent events),
* toggles hearing, speech, and head tracking on/off,
* and can power the whole box down.

The portal is optional: if Flask isn't installed it logs a warning and does
nothing, so the robot still runs. It only *reads* frames and *flips* switches;
all the real work stays in the subsystems.
"""

from __future__ import annotations

import json
import logging
import queue
import shlex
import subprocess
import threading
import time

try:
    from flask import Flask, Response, jsonify, request
except ImportError:  # pragma: no cover - portal is optional
    Flask = None

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None
    np = None

from .config import WebConfig
from .control import EventBus, Switches

log = logging.getLogger(__name__)


def _placeholder_jpeg() -> bytes:
    """A 'NO SIGNAL' frame shown before the first camera frame arrives."""
    if cv2 is None or np is None:
        return b""
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[:] = (12, 8, 6)  # match the console background (BGR)
    cv2.putText(img, "NO SIGNAL", (200, 190), cv2.FONT_HERSHEY_SIMPLEX,
                1.1, (56, 132, 168), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes() if ok else b""


class WebPortal:
    def __init__(self, cfg: WebConfig, vision, switches: Switches, bus: EventBus):
        self.cfg = cfg
        self.vision = vision
        self.switches = switches
        self.bus = bus
        self._thread = None
        self._placeholder = _placeholder_jpeg()
        self._app = self._build_app() if Flask is not None else None

    # -- lifecycle ----------------------------------------------------------

    def start(self):
        if Flask is None:
            log.warning("flask not installed - web portal disabled (pip install flask)")
            return
        if not self.cfg.enabled:
            log.info("Web portal disabled by config")
            return
        # Quiet the dev-server request log; our own logging is enough.
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        self._thread = threading.Thread(target=self._serve, name="web", daemon=True)
        self._thread.start()
        log.info("Web portal on http://%s:%d", self.cfg.host, self.cfg.port)

    def _serve(self):
        try:
            self._app.run(host=self.cfg.host, port=self.cfg.port,
                          threaded=True, use_reloader=False)
        except Exception as exc:  # noqa: BLE001
            log.error("web portal stopped: %s", exc)

    # -- routes -------------------------------------------------------------

    def _build_app(self):
        app = Flask(__name__)

        @app.route("/")
        def index():
            return Response(_PAGE, mimetype="text/html")

        @app.route("/stream.mjpg")
        def stream():
            return Response(self._mjpeg(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.route("/events")
        def events():
            return Response(self._sse(), mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache",
                                     "X-Accel-Buffering": "no"})

        @app.route("/api/state", methods=["GET", "POST"])
        def state():
            if request.method == "POST":
                payload = request.get_json(silent=True) or {}
                for name in Switches.NAMES:
                    if name in payload:
                        self.switches.set(name, bool(payload[name]))
                        log.info("Portal set %s -> %s", name, bool(payload[name]))
            return jsonify(self.switches.state())

        @app.route("/api/shutdown", methods=["POST"])
        def shutdown():
            log.warning("Portal requested system shutdown")
            try:
                subprocess.Popen(shlex.split(self.cfg.poweroff_command))
            except Exception as exc:  # noqa: BLE001
                log.error("shutdown command failed: %s", exc)
                return jsonify({"ok": False, "error": str(exc)}), 500
            return jsonify({"ok": True})

        return app

    # -- streams ------------------------------------------------------------

    def _mjpeg(self):
        period = 1.0 / max(1, self.cfg.stream_fps)
        while True:
            frame = self.vision.jpeg_frame() or self._placeholder
            if frame:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + frame + b"\r\n")
            time.sleep(period)

    def _sse(self):
        q = self.bus.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"  # keep the connection warm
        finally:
            self.bus.unsubscribe(q)


# ---------------------------------------------------------------------------
# The control panel: one self-contained page. Amber-CRT console styling to suit
# Lamuel's classic-sci-fi character; no external fonts or scripts so it loads
# even when the box is offline.
# ---------------------------------------------------------------------------
_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LAMUEL // control</title>
<style>
  :root {
    --bg:#0a0806; --panel:#151009; --panel-edge:#2a1f10;
    --amber:#ffb638; --amber-dim:#a8722a; --heard:#5cd6e0;
    --text:#e6dccb; --muted:#8a7c66; --danger:#e5484d; --ok:#4ec46a;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Roboto Mono",monospace;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; }
  body {
    background:var(--bg); color:var(--text); font-family:var(--mono);
    font-size:15px; line-height:1.5; padding:20px;
    background-image:repeating-linear-gradient(
      to bottom, transparent 0 3px, rgba(0,0,0,.18) 3px 4px);
  }
  a { color:var(--amber); }
  header {
    display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
    border-bottom:1px solid var(--panel-edge); padding-bottom:12px; margin-bottom:18px;
  }
  .wordmark { font-size:26px; font-weight:700; letter-spacing:.5em;
    color:var(--amber); text-shadow:0 0 14px rgba(255,182,56,.35); }
  .tag { color:var(--muted); letter-spacing:.28em; font-size:11px; text-transform:uppercase; }
  .link { margin-left:auto; display:flex; align-items:center; gap:8px; font-size:12px; color:var(--muted); }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--danger); box-shadow:0 0 8px currentColor; }
  .dot.live { background:var(--ok); animation:pulse 2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity:.4; } }

  .grid { display:grid; grid-template-columns:minmax(0,1.4fr) minmax(0,1fr); gap:18px; }
  @media (max-width:820px){ .grid { grid-template-columns:1fr; } }

  .panel { background:var(--panel); border:1px solid var(--panel-edge); border-radius:4px; }
  .panel h2 { margin:0; padding:10px 14px; font-size:11px; letter-spacing:.28em;
    text-transform:uppercase; color:var(--amber-dim); border-bottom:1px solid var(--panel-edge); }

  /* camera viewport with corner brackets + crosshair */
  .viewport { position:relative; aspect-ratio:16/9; background:#000; overflow:hidden; }
  .viewport img { width:100%; height:100%; object-fit:cover; display:block;
    filter:saturate(1.05) contrast(1.03); }
  .bracket { position:absolute; width:22px; height:22px; border:2px solid var(--amber);
    opacity:.7; pointer-events:none; }
  .bracket.tl { top:10px; left:10px; border-right:0; border-bottom:0; }
  .bracket.tr { top:10px; right:10px; border-left:0; border-bottom:0; }
  .bracket.bl { bottom:10px; left:10px; border-right:0; border-top:0; }
  .bracket.br { bottom:10px; right:10px; border-left:0; border-top:0; }
  .cross { position:absolute; inset:0; pointer-events:none; opacity:.35; }
  .cross::before,.cross::after { content:""; position:absolute; background:var(--amber); }
  .cross::before { left:50%; top:calc(50% - 10px); width:1px; height:20px; }
  .cross::after { top:50%; left:calc(50% - 10px); height:1px; width:20px; }
  .rec { position:absolute; top:12px; left:44px; font-size:11px; letter-spacing:.2em;
    color:var(--amber); text-shadow:0 0 8px rgba(255,182,56,.5); }

  /* controls */
  .controls { padding:8px 6px; }
  .switch { display:flex; align-items:center; justify-content:space-between;
    padding:12px 12px; border-bottom:1px solid rgba(42,31,16,.6); }
  .switch:last-child { border-bottom:0; }
  .switch .name { display:flex; flex-direction:column; }
  .switch .name b { font-weight:600; letter-spacing:.04em; }
  .switch .name small { color:var(--muted); font-size:11px; }
  .toggle { position:relative; width:52px; height:28px; flex:none; }
  .toggle input { position:absolute; opacity:0; width:100%; height:100%; margin:0; cursor:pointer; }
  .track { position:absolute; inset:0; border-radius:16px; background:#241a0d;
    border:1px solid var(--panel-edge); transition:background .15s; }
  .knob { position:absolute; top:3px; left:3px; width:20px; height:20px; border-radius:50%;
    background:var(--muted); transition:transform .15s,background .15s; }
  .toggle input:checked ~ .track { background:rgba(255,182,56,.22); border-color:var(--amber-dim); }
  .toggle input:checked ~ .knob { transform:translateX(24px); background:var(--amber);
    box-shadow:0 0 10px rgba(255,182,56,.6); }
  .toggle input:focus-visible ~ .track { outline:2px solid var(--amber); outline-offset:2px; }

  .danger-zone { padding:14px; border-top:1px solid var(--panel-edge); }
  button.power { width:100%; padding:12px; font-family:var(--mono); font-size:13px;
    letter-spacing:.18em; text-transform:uppercase; color:var(--danger);
    background:transparent; border:1px solid var(--danger); border-radius:4px; cursor:pointer;
    transition:background .15s,color .15s; }
  button.power:hover { background:var(--danger); color:#160404; }
  button.power:focus-visible { outline:2px solid var(--danger); outline-offset:2px; }

  /* feed */
  .feed { height:340px; overflow-y:auto; padding:10px 14px; font-size:13.5px; }
  .feed .empty { color:var(--muted); font-style:italic; }
  .line { padding:3px 0; display:flex; gap:10px; }
  .line .who { flex:none; width:64px; text-transform:uppercase; font-size:11px;
    letter-spacing:.1em; padding-top:2px; }
  .line.heard .who { color:var(--heard); }
  .line.said .who { color:var(--amber); }
  .line.said .msg { color:var(--text); }
  .line.heard .msg { color:#cfe9ec; }
  .line .t { flex:none; color:var(--muted); font-size:11px; padding-top:2px; }

  .overlay { position:fixed; inset:0; background:rgba(5,3,2,.92); display:none;
    align-items:center; justify-content:center; flex-direction:column; gap:14px; z-index:10; }
  .overlay.show { display:flex; }
  .overlay .big { color:var(--danger); font-size:22px; letter-spacing:.3em; }

  @media (prefers-reduced-motion: reduce){ *{ animation:none !important; } }
</style>
</head>
<body>
  <header>
    <span class="wordmark">LAMUEL</span>
    <span class="tag">remote console</span>
    <span class="link"><span id="dot" class="dot"></span><span id="conn">connecting…</span></span>
  </header>

  <div class="grid">
    <section class="panel">
      <h2>Camera</h2>
      <div class="viewport">
        <img id="cam" src="/stream.mjpg" alt="Live camera feed from Lamuel">
        <span class="rec">● LIVE</span>
        <span class="bracket tl"></span><span class="bracket tr"></span>
        <span class="bracket bl"></span><span class="bracket br"></span>
        <span class="cross"></span>
      </div>
    </section>

    <section class="panel">
      <h2>Systems</h2>
      <div class="controls" id="controls">
        <label class="switch">
          <span class="name"><b>Conversation</b><small>Listen and respond aloud</small></span>
          <span class="toggle"><input type="checkbox" data-sw="conversation"><span class="track"></span><span class="knob"></span></span>
        </label>
        <label class="switch">
          <span class="name"><b>Head tracking</b><small>Follow faces and motion</small></span>
          <span class="toggle"><input type="checkbox" data-sw="tracking"><span class="track"></span><span class="knob"></span></span>
        </label>
      </div>
      <div class="danger-zone">
        <button class="power" id="power">Shut down box</button>
      </div>
    </section>
  </div>

  <section class="panel" style="margin-top:18px;">
    <h2>Hears &amp; says</h2>
    <div class="feed" id="feed"><div class="empty">Waiting for activity…</div></div>
  </section>

  <div class="overlay" id="overlay">
    <div class="big">POWERING OFF</div>
    <div style="color:var(--muted)">Lamuel is shutting down. This console will go dark.</div>
  </div>

<script>
  const feed = document.getElementById('feed');
  const dot = document.getElementById('dot');
  const conn = document.getElementById('conn');

  function ts(sec){ const d=new Date(sec*1000);
    return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}); }

  function addLine(ev){
    const empty = feed.querySelector('.empty'); if (empty) empty.remove();
    const near = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
    const row = document.createElement('div');
    row.className = 'line ' + (ev.kind === 'heard' ? 'heard' : 'said');
    row.innerHTML = `<span class="t"></span><span class="who"></span><span class="msg"></span>`;
    row.querySelector('.t').textContent = ts(ev.ts);
    row.querySelector('.who').textContent = ev.kind === 'heard' ? 'heard' : 'lamuel';
    row.querySelector('.msg').textContent = ev.text;
    feed.appendChild(row);
    if (near) feed.scrollTop = feed.scrollHeight;
  }

  // --- toggles ---
  async function loadState(){
    try {
      const r = await fetch('/api/state');
      const s = await r.json();
      document.querySelectorAll('[data-sw]').forEach(el => { el.checked = !!s[el.dataset.sw]; });
    } catch(e){ /* leave defaults */ }
  }
  document.querySelectorAll('[data-sw]').forEach(el => {
    el.addEventListener('change', async () => {
      const body = {}; body[el.dataset.sw] = el.checked;
      try {
        const r = await fetch('/api/state', {method:'POST',
          headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const s = await r.json();
        document.querySelectorAll('[data-sw]').forEach(x => { x.checked = !!s[x.dataset.sw]; });
      } catch(e){ el.checked = !el.checked; }  // revert on failure
    });
  });

  // --- shutdown ---
  document.getElementById('power').addEventListener('click', async () => {
    if (!confirm('Shut down the entire box? Lamuel will power off and this console will stop responding.')) return;
    document.getElementById('overlay').classList.add('show');
    try { await fetch('/api/shutdown', {method:'POST'}); } catch(e){ /* box is going down */ }
  });

  // --- live feed ---
  function connect(){
    const es = new EventSource('/events');
    es.onopen = () => { dot.classList.add('live'); conn.textContent = 'online'; };
    es.onmessage = (m) => { try { addLine(JSON.parse(m.data)); } catch(e){} };
    es.onerror = () => { dot.classList.remove('live'); conn.textContent = 'reconnecting…'; };
  }

  loadState();
  connect();
</script>
</body>
</html>"""

