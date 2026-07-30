"""Generate moon_engine.py (headless) from moon_tk.py.

language: Python 3.10+, file: build_engine.py, runtime: stdlib only

    python build_engine.py [project_dir]

moon_tk.py is READ, never written: the Tk app keeps working. What comes out
is moon_engine.py -- the same download engine with the Tk layer amputated and a
JSON-shaped API bolted on, which moon_bridge.py drives from the WebView2 GUI.

Kept byte-identical
───────────────────
    download_file, Telemetry, ProxyPool, FileRecord, App._run,
    App._browser_worker, App._do_dl, every tuning constant

Removed
───────
    tkinter import, every _build*/_label/_btn/_mbtn/_pulse_tick/_draw_bars,
    _ui_loop, _log_flush_loop, _set_status, the filedialog helpers, __main__

Added
─────
    Engine.start(cfg) / stop() / snapshot(cursor) / scan_tmp()
    FileRecord.done_bytes + live_mbs, published from download_file at ~4 Hz

*Run against a PRISTINE moon_tk.py. Every anchor is an exact string from that
file, so a hand-edited source fails on the first missing anchor instead of
producing a half-transformed engine.*
"""
from __future__ import annotations

import pathlib
import re
import sys

TARGET = "moon_engine.py"


# ── surgery helpers ──────────────────────────────────────────────────────────
def replace_once(src: str, old: str, new: str, what: str) -> str:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"[FAIL] {what}: anchor found {count} times, expected 1")
    return src.replace(old, new, 1)


def method_span(src: str, name: str, indent: str = "    ",
                after: int = 0) -> tuple[int, int]:
    """Span of one method: its `def` up to the next sibling member or a dedent.

    *`after` is not optional in practice: moon_tk.py has three `def __init__` at
    indent 4 (ProxyPool, Telemetry, App). Searching from position 0 rewrites the
    wrong class and leaves the intended one untouched -- silently, because the
    anchor still matched exactly once.*
    """
    head = re.search(rf"^{indent}def {re.escape(name)}\(", src[after:], re.M)
    if not head:
        raise SystemExit(f"[FAIL] method {name}: not found")
    start = after + head.start()
    # `async def` MUST be in the stop set. Without it, dropping _toggle runs to
    # the next sync sibling and takes _do_dl, _browser_worker and _run with it --
    # the whole engine, deleted by a regex that looked right.
    tail = re.compile(
        rf"^(?:{indent}(?:async def |def |@|[A-Za-z_][A-Za-z0-9_]*\s*[:=])|\S)", re.M)
    nxt = tail.search(src, after + head.end())
    return start, (nxt.start() if nxt else len(src))


def engine_at(src: str) -> int:
    """Offset of the Engine class body, recomputed after every edit."""
    return src.index("class Engine:")


def drop_methods(src: str, names: list[str]) -> str:
    for name in names:
        start, end = method_span(src, name, after=engine_at(src))
        src = src[:start] + src[end:]
    return src


def swap_method(src: str, name: str, body: str) -> str:
    start, end = method_span(src, name, after=engine_at(src))
    return src[:start] + body.rstrip("\n") + "\n\n" + src[end:]


# ── replacement bodies ───────────────────────────────────────────────────────
HEADER = '''"""
MoonDownloader v16 -- headless engine
════════════════════════════════════════
GENERATED FILE. Do not edit by hand: run `python build_engine.py` against a
pristine moon_tk.py and this file is rebuilt.

The download engine with no GUI attached. State leaves through
Engine.snapshot(), commands come in through Engine.start()/stop(), and both are
plain JSON-able dicts -- moon_bridge.py hands them straight to the WebView.

Thread model
────────────
    * the caller's thread (the WebView bridge) only ever touches start/stop/
      snapshot/scan_tmp
    * one worker thread runs asyncio.run(self._run(...))
    * every shared counter sits behind self._lock; the log ring behind
      self._log_lock

*snapshot() is called ~12x/second, so it copies counters under the lock and does
its arithmetic outside it -- holding the lock through the ETA maths would stall
every download worker that wants to bump a byte count.*
"""
'''

INIT = '''    def __init__(self):
        # Settings arrive from the GUI on start(); these are the fallbacks used
        # for the first paint and for a start() that omits a field.
        self._cfg = {
            "out_folder": DEFAULT_DL_FOLDER,
            "mode":       "download",
            "workers":    16,
            "dl_streams": 48,
            "retries":    3,
            # Defaults asked for by the operator, not by the library: 8 lanes
            # and the shortest manual-captcha wait the extractor accepts.
            "dn_pages":   8,
            "dn_captcha": 30,
            "dn_chrome":  _moon_extract.CHROME_PATH or (_moon_extract.find_chrome() or ""),
            "dn_apikey":  DN_API_KEY,
        }

        self._lock       = threading.Lock()
        self._running    = False
        self._stop_flag  = False
        self._state      = "idle"
        self._url_total  = 0; self._url_done = 0
        self._dl_total   = 0; self._dl_done  = 0
        self._ok         = 0; self._fail     = 0
        self._kills      = 0; self._browsers = 0
        self._dls        = 0
        self._bytes_acc  : collections.deque = collections.deque(maxlen=200000)
        self._t0         = 0.0
        self._proxies    = 0

        # Live FileRecord registry: the GUI reads these objects every snapshot,
        # so a row's speed and percentage come off the download loop itself
        # instead of a second copy that can go stale.
        self._tracked : dict[str, FileRecord] = {}

        # Bounded log ring + a monotonic cursor. The GUI asks for "everything
        # after N"; if it fell behind further than the ring, it gets the oldest
        # line still held instead of a gap it cannot detect.
        self._log_ring  : collections.deque = collections.deque(maxlen=6000)
        self._log_total = 0
        self._log_lock  = threading.Lock()

        self._alive  = True
        self._thread = None
'''

LOG = '''    def log(self, msg, tag=""):
        """Thread-safe: called from the asyncio worker, drained by snapshot()."""
        with self._log_lock:
            self._log_ring.append((str(msg), tag))
            self._log_total += 1
'''

ON_DONE = '''    def _on_done(self):
        with self._lock:
            self._running = False
            self._stop_flag = False
            self._state = "done"
'''

SCAN_TMP = '''    def scan_tmp(self) -> int:
        folder = self._cfg["out_folder"]
        if not os.path.isdir(folder):
            return 0
        try:
            return len([f for f in os.listdir(folder) if f.endswith(".tmp")])
        except OSError:
            return 0
'''

API = '''
    # ══ GUI-facing API ═════════════════════════════════════════════════════
    _CLAMP = {
        "workers":    (2, 32),
        "dl_streams": (2, 48),
        "retries":    (0, 5),
        "dn_pages":   (1, 8),
        "dn_captcha": (30, 600),
    }
    _FILE_UI_STATE = {
        "pending":     "queue",
        "extracting":  "extract",
        "downloading": "download",
        "ok":          "ok",
        "fail":        "fail",
    }
    # The GUI shows active transfers first and keeps a tail of finished ones.
    # 40 was too short to be honest on a 124-file batch: the badge read "40"
    # while 124 had gone through. 120 rows cost nothing with content-visibility.
    _ROWS_KEEP = 120

    def _track(self, rec):
        """Register a FileRecord so snapshot() can read its live fields."""
        with self._lock:
            self._tracked[rec.url] = rec

    def apply_cfg(self, cfg: dict) -> dict:
        """Validate and store settings. Returns the effective values.

        The GUI is a web page: everything it sends is untrusted input, so ints
        are coerced and clamped here rather than being fed to the semaphores raw.
        """
        cfg = cfg or {}
        for key, (lo, hi) in self._CLAMP.items():
            if key in cfg:
                try:
                    self._cfg[key] = max(lo, min(hi, int(cfg[key])))
                except (TypeError, ValueError):
                    pass
        if cfg.get("mode") in ("download", "links"):
            self._cfg["mode"] = cfg["mode"]
        for key in ("out_folder", "dn_chrome", "dn_apikey"):
            if isinstance(cfg.get(key), str):
                self._cfg[key] = cfg[key].strip() if key != "dn_apikey" else cfg[key]
        return dict(self._cfg)

    def start(self, cfg: dict) -> dict:
        if self._get("_running"):
            return {"error": "already running"}

        urls = [u.strip() for u in (cfg or {}).get("links", []) if str(u).strip()]
        if not urls:
            return {"error": "no links pasted"}
        eff = self.apply_cfg(cfg)

        try:
            os.makedirs(eff["out_folder"], exist_ok=True)
        except OSError as e:
            return {"error": f"cannot create folder: {e}"}

        with self._lock:
            self._running = True; self._stop_flag = False
            self._state = "running"
            self._url_total = len(urls); self._url_done = 0
            self._dl_total = len(urls);  self._dl_done  = 0
            self._ok = 0; self._fail = 0; self._kills = 0
            self._browsers = 0; self._dls = 0
            self._bytes_acc.clear(); self._t0 = time.monotonic()
            self._tracked.clear()
        with self._log_lock:
            self._log_ring.clear(); self._log_total = 0

        # What is on screen is what runs: push the per-host settings into the
        # extraction layer before any worker thread starts.
        applied = _moon_extract.configure(
            lanes=eff["dn_pages"],
            chrome_path=eff["dn_chrome"],
            api_key=eff["dn_apikey"],
            captcha_wait=eff["dn_captcha"])

        proxy_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxies.txt")
        self._proxies = _PROXY_POOL.load(proxy_path)

        n, d, r = eff["workers"], eff["dl_streams"], eff["retries"]
        self.log(f"▶  {len(urls)} links  ·  {n} extractors  ·  {d} streams  ·  {r} retries  ·  {VERSION}", "info")
        self.log(f"   fuckingfast: direct HTTP"
                 f"{'' if applied['curl_cffi'] else '  ✗ curl_cffi MISSING'}"
                 f"   ·   datanodes: {applied['lanes']} pages, captcha {applied['captcha_wait']}s"
                 f"{', API key' if applied['api_key'] else ''}", "dim")
        self.log(f"   chrome: {applied['chrome']}", "dim")
        if self._proxies:
            self.log(f"   proxies: {self._proxies} loaded — rotating per download", "info")
        self.log(f"   stall < {STALL_MIN_MBS} MB/s  ·  grace {STALL_GRACE_S}s  ·  max {STALL_MAX_KILL} kill", "dim")

        self._thread = threading.Thread(
            target=lambda: self._guarded_run(urls, n, d, r), daemon=True)
        self._thread.start()
        return {"ok": True, "proxies": self._proxies, "effective": applied}

    def _guarded_run(self, urls, n, d, r):
        """asyncio.run in a thread: an escaping exception would vanish silently."""
        try:
            asyncio.run(self._run(urls, n, d, r))
        except Exception:
            self.log(f"✗  engine crash: {traceback.format_exc(limit=3)}", "fail")
            self._on_done()

    def stop(self) -> dict:
        if not self._get("_running"):
            return {"ok": True}
        with self._lock:
            self._stop_flag = True
            self._state = "stopping"
        self.log("⏹  stop requested — finishing the downloads in flight...", "warn")
        return {"ok": True}

    def _files_payload(self) -> list[dict]:
        with self._lock:
            tracked = list(self._tracked.items())

        # Retire the oldest finished entries once the list is long. Active
        # transfers are never dropped, so a 400-file batch stays bounded.
        excess = len(tracked) - self._ROWS_KEEP
        if excess > 0:
            with self._lock:
                for url, rec in tracked:
                    if excess <= 0:
                        break
                    if rec.status in ("ok", "fail"):
                        self._tracked.pop(url, None)
                        excess -= 1
                tracked = list(self._tracked.items())

        out = []
        for url, rec in tracked:
            state = self._FILE_UI_STATE.get(rec.status, "queue")
            if rec.stall_kills and rec.status in ("pending", "extracting"):
                state = "kill"
            if rec.status == "downloading" and rec.file_bytes > 0:
                pct = min(1.0, rec.done_bytes / rec.file_bytes)
            elif rec.status == "ok":
                pct = 1.0
            else:
                pct = None
            if rec.status == "downloading":
                mbs = rec.live_mbs
            elif rec.status == "ok":
                mbs = rec.avg_mbs
            else:
                mbs = 0.0
            out.append({"key": url, "name": rec.filename, "state": state,
                        "mbs": round(mbs, 3), "pct": pct})
        return out

    def snapshot(self, cursor: int = 0) -> dict:
        with self._lock:
            state    = self._state
            running  = self._running
            t0       = self._t0
            url_done = self._url_done; url_tot = self._url_total
            dl_done  = self._dl_done;  dl_tot  = self._dl_total
            ok       = self._ok; fail = self._fail
            kills    = self._kills; dls = self._dls
            snap     = list(self._bytes_acc)

        now = time.monotonic()
        recent = [(t, b) for t, b in snap if t > now - 3.0]
        if len(recent) > 1:
            span = max(now - recent[0][0], 0.05)
            mbs = sum(b for _, b in recent) / span / 1_048_576
        else:
            mbs = 0.0

        total_downloaded = sum(b for _, b in snap)
        files_remaining  = dl_tot - dl_done
        if mbs > 0.1 and files_remaining > 0 and dl_done > 0:
            avg_file = total_downloaded / dl_done
            eta = min(files_remaining * avg_file / (mbs * 1_048_576), 7200)
        else:
            eta = 0.0

        el = (now - t0) if t0 else 0.0
        # No phase sentence here on purpose: the GUI owns wording and language,
        # so the engine ships numbers and a stage name instead of prose.
        if not running and state == "idle":
            stage = "idle"
        elif url_done < url_tot:
            stage = "extracting"
        elif dl_done < dl_tot:
            stage = "downloading"
        else:
            stage = "done"

        with self._log_lock:
            dropped = self._log_total - len(self._log_ring)
            begin = max(0, min(len(self._log_ring), cursor - dropped))
            lines = [list(pair) for pair in list(self._log_ring)[begin:]]
            new_cursor = self._log_total

        return {
            "state": state,
            "metrics": {
                "speed_mbs": round(mbs, 3),
                "dl_done": dl_done, "dl_total": dl_tot,
                "ok": ok, "fail": fail, "kills": kills,
                "eta_s": round(eta, 1),
                "bytes_total": total_downloaded,
                "extract_done": url_done, "extract_total": url_tot,
                "active": dls, "stage": stage, "elapsed_s": round(el, 1),
            },
            "files": self._files_payload(),
            "log": lines,
            "cursor": new_cursor,
            "proxies": self._proxies,
            "tmp": self.scan_tmp() if not running else None,
        }

    def clear_files(self) -> dict:
        with self._lock:
            for url in [u for u, r in self._tracked.items() if r.status in ("ok", "fail")]:
                self._tracked.pop(url, None)
        return {"ok": True}
'''

MAIN = '''
# ── entry point ─────────────────────────────────────────────────────────────
# There is no GUI in here. Start the app with:  python moon_bridge.py
if __name__ == "__main__":
    engine = Engine()
    print(json.dumps(engine.snapshot(0)["metrics"], indent=2))
    print(f"{VERSION}  ·  headless engine ok  ·  start the GUI with: python moon_bridge.py")
'''


def build(src: str) -> str:
    # 0 ── version + module docstring ----------------------------------------
    head_end = src.index('"""', src.index('"""') + 3) + 3
    src = HEADER + src[head_end:]

    # 1 ── imports: no Tk in a headless engine -------------------------------
    src = replace_once(
        src,
        "import os, re, ctypes, asyncio, threading, tkinter as tk\n"
        "import math, time, random, traceback, json, datetime, collections, io\n"
        "from tkinter import filedialog, scrolledtext\n",
        "import os, re, asyncio, threading\n"
        "import time, random, traceback, json, datetime, collections, io\n",
        "imports")
    src = replace_once(
        src,
        "try:\n    from PIL import Image, ImageTk\n    PIL_OK = True\nexcept ImportError:\n    PIL_OK = False\n\n",
        "",
        "drop Pillow import")

    # 2 ── FileRecord live fields --------------------------------------------
    src = replace_once(
        src,
        "    avg_mbs      : float = 0.0\n"
        "    queue_wait_s : float = 0.0\n"
        "    notes        : list  = field(default_factory=list)",
        "    avg_mbs      : float = 0.0\n"
        "    queue_wait_s : float = 0.0\n"
        "    done_bytes   : int   = 0      # live, published by download_file\n"
        "    live_mbs     : float = 0.0    # live, 3s window\n"
        "    notes        : list  = field(default_factory=list)",
        "FileRecord live fields")

    # 3 ── download_file publishes live progress ----------------------------
    src = replace_once(
        src,
        "                speed_win  : collections.deque = collections.deque(maxlen=8000)\n"
        "                downloaded = resume\n"
        "                last_check = dl_t0",
        "                speed_win  : collections.deque = collections.deque(maxlen=8000)\n"
        "                # Separate window for the UI: stall detection prunes\n"
        "                # speed_win on a 60s cutoff, so sharing one deque would\n"
        "                # let the row speed eat the stall detector's history.\n"
        "                pub_win    : collections.deque = collections.deque(maxlen=600)\n"
        "                last_pub   = dl_t0\n"
        "                downloaded = resume\n"
        "                last_check = dl_t0",
        "pub_win declaration")
    src = replace_once(
        src,
        "                        speed_win.append((now, len(chunk)))\n"
        "                        bytes_acc.append((now, len(chunk)))",
        "                        speed_win.append((now, len(chunk)))\n"
        "                        pub_win.append((now, len(chunk)))\n"
        "                        bytes_acc.append((now, len(chunk)))",
        "pub_win append")
    src = replace_once(
        src,
        "                        elapsed = now - dl_t0\n",
        "                        elapsed = now - dl_t0\n"
        "\n"
        "                        # Publish live progress for the GUI's rows at ~4 Hz.\n"
        "                        # Two attribute writes cost nothing against a 4 MB\n"
        "                        # socket read, and snapshot() reads rec directly.\n"
        "                        if now - last_pub >= 0.25:\n"
        "                            last_pub = now\n"
        "                            pub_cut  = now - 3.0\n"
        "                            while pub_win and pub_win[0][0] < pub_cut:\n"
        "                                pub_win.popleft()\n"
        "                            pub_span = max(now - pub_win[0][0], 0.25) if pub_win else 1.0\n"
        "                            rec.done_bytes = downloaded\n"
        "                            rec.live_mbs   = sum(b for _, b in pub_win) / pub_span / 1_048_576\n",
        "live publish block")

    # 4 ── App(tk.Tk) becomes a plain Engine ---------------------------------
    src = replace_once(src, "class App(tk.Tk):", "class Engine:", "class rename")
    src = swap_method(src, "__init__", INIT)
    src = swap_method(src, "log", LOG)
    src = swap_method(src, "_on_done", ON_DONE)
    src = swap_method(src, "_scan_tmp", SCAN_TMP)
    src = drop_methods(src, [
        "_on_close", "_load_logo", "_build", "_build_header", "_build_left",
        "_build_right", "_build_footer", "_label", "_btn", "_mbtn", "_pulse_tick",
        "_draw_bars", "_ui_loop", "_log_flush_loop", "_load_file", "_clear_links",
        "_upd_count", "_pick_folder", "_pick_chrome", "_clear_log", "_set_status",
        "_toggle",
    ])

    # 5 ── engine references that used to read tk variables -----------------
    src = replace_once(
        src,
        "        dest_folder  = self._out_folder.get()",
        '        dest_folder  = self._cfg["out_folder"]',
        "dest_folder")
    src = replace_once(
        src,
        "        mode         = self._mode.get()",
        '        mode         = self._cfg["mode"]',
        "mode")
    src = replace_once(
        src,
        "        self.after(0, self._on_done)",
        "        self._on_done()",
        "on_done call")

    # 6 ── registry feed in the worker paths --------------------------------
    src = replace_once(
        src,
        '                self.log(f"  → {short}{suffix}", "retry" if (is_re or is_retry) else "dim")',
        '                self.log(f"  → {short}{suffix}", "retry" if (is_re or is_retry) else "dim")\n'
        '                self._track(rec)',
        "track on extract")
    src = replace_once(
        src,
        '            rec.dl_start = time.monotonic(); rec.status = "downloading"',
        '            rec.dl_start = time.monotonic(); rec.status = "downloading"\n'
        '            self._track(rec)',
        "track on download")

    # 7 ── swap the Tk __main__ for the headless one, then append the API ---
    main_at = src.index('if __name__ == "__main__":')
    src = src[:main_at].rstrip("\n") + "\n"

    class_at = src.index("class Engine:")
    tail_marker = "\n    def scan_tmp(self) -> int:"
    if tail_marker not in src[class_at:]:
        raise SystemExit("[FAIL] scan_tmp not found for API insertion")
    src = src.rstrip("\n") + "\n" + API + MAIN
    return src


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).parent)
    source = root / "moon_tk.py"
    if not source.exists():
        raise SystemExit(f"[FAIL] {source} not found")
    original = source.read_text(encoding="utf-8")
    if "class Engine:" in original:
        raise SystemExit("[FAIL] moon_tk.py looks already transformed -- use a pristine copy")
    built = build(original)
    dest = root / TARGET
    dest.write_text(built, encoding="utf-8")
    print(f"[OK] {TARGET} generated  ·  {len(original.splitlines())} -> "
          f"{len(built.splitlines())} lines")
    print("[OK] moon_tk.py untouched (the Tk app still runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
