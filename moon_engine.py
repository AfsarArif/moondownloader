"""
MoonDownloader v16 -- headless engine
════════════════════════════════════════
GENERATED FILE. Do not edit by hand: run `python apply_web_v16.py` against a
pristine gen_1.py and this file is rebuilt.

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

import os, re, asyncio, threading
import time, random, traceback, json, datetime, collections, io
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict

import aiohttp

# ── THEME ──────────────────────────────────────────────────────────────────────
BG      = "#080b12"
BG2     = "#0c1018"
BG3     = "#111520"
SURFACE = "#161c2a"
BORDER  = "#1e2840"
ACC     = "#00d4ff"
ACC2    = "#0099cc"
ACC3    = "#00ffb3"
GOLD    = "#f5a623"
TEXT    = "#e8f0ff"
TEXT2   = "#8899bb"
TEXT3   = "#3d506e"
OK      = "#00e676"
ERR     = "#ff4d6d"
WARN    = "#ffb547"
VERSION = "v16.0"

# ── TUNING ─────────────────────────────────────────────────────────────────────
DEFAULT_DL_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads", "datanodes")
RECV_CHUNK        = 4  * 1024 * 1024
WRITE_BUF         = 16 * 1024 * 1024
READ_BUFSZ        = 1  << 19
UI_HZ             = 8
LOG_HZ            = 10

# Stall detection — near-disabled. datanodes.to CDN assigns lanes per session:
# re-extracting returns the same slow lane. A slow file WILL finish. Only kill
# files genuinely stuck at < 0.5 MB/s, once, then let them complete regardless.
STALL_MIN_MBS          = 0.5
STALL_GRACE_S          = 90
STALL_CHECK_S          = 20
STALL_WIN_S            = 60
STALL_MAX_KILL         = 1
STALL_SAFE_PCT         = 0.80
STALL_MIN_BYTES_IN_WIN = 30 * 1024 * 1024
STALL_MIN_FILE_BYTES   = 50 * 1024 * 1024

# Inner connection retries — separate from the user-facing extraction retry count.
# Handles transient network errors (drops, timeouts) before giving up on a download.
DL_INNER_RETRIES       = 4

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]

LAUNCH_ARGS = [
    "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
    "--disable-gpu", "--disable-extensions", "--disable-background-networking",
    "--disable-default-apps", "--disable-sync", "--no-first-run", "--no-zygote",
    "--mute-audio", "--hide-scrollbars", "--disable-breakpad",
    "--disable-component-update", "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
]

_WIN_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def _sanitize_filename(name: str) -> str:
    """Strip characters that are invalid in Windows filenames."""
    name = _WIN_INVALID.sub("_", name).strip(". ")
    return name or "download"

# ── SHARED RESOURCES ───────────────────────────────────────────────────────────
_SESSION : aiohttp.ClientSession | None = None
_POOL    = ThreadPoolExecutor(max_workers=12, thread_name_prefix="dl_write")

def _sess() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, force_close=False,
                                    enable_cleanup_closed=True, ttl_dns_cache=600,
                                    keepalive_timeout=30)
        _SESSION = aiohttp.ClientSession(
            connector=conn, read_bufsize=READ_BUFSZ,
            timeout=aiohttp.ClientTimeout(total=7200, connect=20, sock_read=90))
    return _SESSION

async def _close_sess():
    global _SESSION
    if _SESSION and not _SESSION.closed:
        await _SESSION.close(); _SESSION = None

# ── PROXY POOL ────────────────────────────────────────────────────────────────
# Loaded from proxies.txt (same folder as gen.py).
# Format per line: ip:port:user:pass  OR  http://user:pass@ip:port
# Proxy sessions are kept per-proxy for connection reuse.

class ProxyPool:
    def __init__(self):
        self.proxies : list[dict] = []   # [{url, auth}]
        self._idx    = 0
        self._lock   = threading.Lock()
        self._sessions : dict[str, aiohttp.ClientSession] = {}

    def load(self, path: str) -> int:
        if not os.path.exists(path):
            return 0
        loaded = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    if line.startswith("http://") or line.startswith("https://") or line.startswith("socks"):
                        loaded.append({"url": line, "auth": None})
                    else:
                        parts = line.split(":")
                        if len(parts) == 4:
                            # ip:port:user:pass  OR  user:pass:ip:port
                            if re.match(r'^\d+\.\d+\.\d+\.\d+$', parts[0]):
                                # ip:port:user:pass
                                ip, port, user, passwd = parts
                            else:
                                # user:pass:ip:port (less common)
                                user, passwd, ip, port = parts
                            url  = f"http://{ip}:{port}"
                            auth = aiohttp.BasicAuth(user, passwd)
                            loaded.append({"url": url, "auth": auth})
                        elif len(parts) == 2:
                            # ip:port (no auth)
                            ip, port = parts
                            loaded.append({"url": f"http://{ip}:{port}", "auth": None})
                except Exception:
                    continue
        self.proxies = loaded
        return len(loaded)

    def next(self) -> dict | None:
        """Round-robin proxy selection."""
        if not self.proxies:
            return None
        with self._lock:
            p = self.proxies[self._idx % len(self.proxies)]
            self._idx += 1
        return p

    def get_session(self, proxy: dict) -> aiohttp.ClientSession:
        """Get or create a dedicated aiohttp session for this proxy."""
        key = proxy["url"]
        if key not in self._sessions or self._sessions[key].closed:
            conn = aiohttp.TCPConnector(
                limit=0, limit_per_host=0, force_close=True,
                enable_cleanup_closed=True, ttl_dns_cache=300,
            )
            self._sessions[key] = aiohttp.ClientSession(
                connector=conn, read_bufsize=READ_BUFSZ,
                timeout=aiohttp.ClientTimeout(total=7200, connect=30, sock_read=120),
            )
        return self._sessions[key]

    async def close_all(self):
        for s in self._sessions.values():
            if not s.closed:
                try: await s.close()
                except Exception: pass
        self._sessions.clear()

_PROXY_POOL = ProxyPool()


# ── TELEMETRY ─────────────────────────────────────────────────────────────────

@dataclass
class FileRecord:
    url          : str
    filename     : str
    worker_id    : int   = -1
    stall_kills  : int   = 0
    queued_at    : float = 0.0
    extract_s    : float = 0.0
    dl_start     : float = 0.0
    dl_s         : float = 0.0
    file_bytes   : int   = 0
    status       : str   = "pending"
    error        : str   = ""
    avg_mbs      : float = 0.0
    queue_wait_s : float = 0.0
    done_bytes   : int   = 0      # live, published by download_file
    live_mbs     : float = 0.0    # live, 3s window
    notes        : list  = field(default_factory=list)

class Telemetry:
    def __init__(self, cfg: dict):
        self.cfg          = cfg
        self.t0           = time.monotonic()
        self.t_end        = 0.0
        self.files        : dict[str, FileRecord] = {}
        self.snapshots    : list[dict] = []
        self.stall_events : list[dict] = []
        self._lock        = threading.Lock()

    def reg(self, url: str, filename: str) -> FileRecord:
        rec = FileRecord(url=url, filename=filename, queued_at=time.monotonic())
        with self._lock: self.files[url] = rec
        return rec

    def snap(self, browsers, dls, qsize, ok, fail):
        self.snapshots.append({"ts": round(time.monotonic()-self.t0, 1),
            "browsers": browsers, "downloads": dls,
            "queue": qsize, "ok": ok, "fail": fail})

    def stall(self, filename, speed, done_bytes, action):
        self.stall_events.append({"ts": round(time.monotonic()-self.t0, 1),
            "file": filename, "speed_mbs": round(speed, 2),
            "done_mb": round(done_bytes/1e6, 1), "action": action})

    def finish(self): self.t_end = time.monotonic()

    def save(self, out_dir: str) -> tuple[str, str]:
        os.makedirs(out_dir, exist_ok=True)
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        lp   = os.path.join(out_dir, f"moontech_{ts}.log")
        jp   = os.path.join(out_dir, f"moontech_{ts}.json")
        el   = self.t_end - self.t0
        recs = list(self.files.values())
        ok_r = [r for r in recs if r.status == "ok"]
        dt   = sorted(r.dl_s for r in ok_r if r.dl_s > 0)
        med  = dt[len(dt)//2] if dt else 0.0
        # FIX: use id-based set — FileRecord is not hashable
        slow_ids = {id(r) for r in ok_r if r.dl_s > med * 2}

        buf = io.StringIO()
        def W(*parts): buf.write(" ".join(str(p) for p in parts) + "\n")

        W("="*72); W(f"MOONTECH {VERSION}  —  PERFORMANCE LOG"); W("="*72)
        W(f"Session  : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        W(f"Duration : {int(el//60)}m {int(el%60)}s  ({el:.1f}s)"); W()
        W("── CONFIG ──────────────────────────────────────────────────────────")
        for k, v in self.cfg.items(): W(f"  {k:<28} {v}")
        W()
        W("── SUMMARY ─────────────────────────────────────────────────────────")
        W(f"  Total links    : {len(recs)}")
        W(f"  Completed OK   : {len(ok_r)}")
        W(f"  Failed         : {len(recs)-len(ok_r)}")
        W(f"  Stall kills    : {sum(r.stall_kills for r in recs)}")
        if ok_r:
            tb = sum(r.file_bytes for r in ok_r)
            W(f"  Total data     : {tb/1e9:.2f} GB")
            W(f"  Session speed  : {tb/el/1e6:.1f} MB/s")
        if dt:
            W(f"  Median DL time : {med:.1f}s")
            W(f"  Slowest file   : {max(dt):.1f}s")
            W(f"  Fastest file   : {min(dt):.1f}s")
        W(f"  Slow (>2x median): {len(slow_ids)}"); W()
        W("── STALL EVENTS ────────────────────────────────────────────────────")
        if self.stall_events:
            for e in self.stall_events:
                W(f"  t={e['ts']:>6.1f}s  {e['file'][:44]:<44}  "
                  f"{e['speed_mbs']:.2f} MB/s  {e['done_mb']:.0f}MB  → {e['action']}")
        else: W("  None.")
        W()
        W("── PER-FILE TIMING ─────────────────────────────────────────────────")
        W(f"  {'#':<4} {'Filename':<48} {'Wkr':>3} {'Kll':>3} "
          f"{'QWait':>6} {'Extr':>6} {'DL':>7} {'Speed':>10} {'Status'}")
        W("  "+"-"*4+" "+"-"*48+" "+"-"*3+" "+"-"*3+" "+"-"*6+" "+"-"*6+" "+"-"*7+" "+"-"*10+" "+"-"*8)
        for i, r in enumerate(recs, 1):
            spd  = f"{r.avg_mbs:.1f} MB/s" if r.avg_mbs > 0 else "—"
            flag = " ⚠SLOW" if id(r) in slow_ids else ""
            W(f"  {i:<4} {r.filename[:48]:<48} {r.worker_id:>3} {r.stall_kills:>3} "
              f"{r.queue_wait_s:>6.1f} {r.extract_s:>6.1f} {r.dl_s:>7.1f} {spd:>10} {r.status}{flag}")
            for n in r.notes: W(f"       → {n}")
        W()
        W("── LAST 10 FILES ───────────────────────────────────────────────────")
        for r in recs[-10:]:
            spd = f"{r.avg_mbs:.1f} MB/s" if r.avg_mbs > 0 else "—"
            W(f"  {r.filename[:52]:<52}  DL={r.dl_s:.1f}s  {spd}"
              f"{'  ← SLOW' if id(r) in slow_ids else ''}")
        W()
        W("── CONCURRENCY ─────────────────────────────────────────────────────")
        W(f"  {'Time':>7}  {'Browsers':>8}  {'Downloads':>9}  {'Queue':>5}  {'OK':>5}  {'Fail':>5}")
        step = max(1, len(self.snapshots)//45)
        for s in self.snapshots[::step]:
            W(f"  {s['ts']:>6.1f}s  {s['browsers']:>8}  {s['downloads']:>9}  "
              f"{s['queue']:>5}  {s['ok']:>5}  {s['fail']:>5}")
        W()
        W("── ERRORS ──────────────────────────────────────────────────────────")
        errs = [r for r in recs if r.error]
        if errs:
            for r in errs: W(f"  {r.filename[:52]:<52}  {r.error}")
        else: W("  None.")
        W("="*72)

        with open(lp, "w", encoding="utf-8") as f: f.write(buf.getvalue())
        with open(jp, "w", encoding="utf-8") as f:
            json.dump({
                "session": {"start": datetime.datetime.now().isoformat(),
                            "duration_s": round(el, 2), "config": self.cfg,
                            "total": len(recs), "ok": len(ok_r),
                            "fail": len(recs)-len(ok_r),
                            "stall_kills": sum(r.stall_kills for r in recs),
                            "median_dl_s": round(med, 2)},
                "files": [{k: round(v, 3) if isinstance(v, float) else v
                           for k, v in asdict(r).items()} for r in recs],
                "stall_events": self.stall_events,
                "concurrency": self.snapshots,
            }, f, indent=2)
        return lp, jp

# ── EXTRACTION ────────────────────────────────────────────────────────────────
# Both host front-ends changed in 2026; the extraction layer now lives in
# moon_extract.py so gen_1.py and gen_cli.py share one implementation.
import sys                                       # noqa: E402  (gen_1.py has no top-level `import sys`)
from moon_extract import (                       # noqa: E402
    extract_fuckingfast,
    extract_datanodes,
    BrowserGate,
    close_ff_session,
    referer_for,
    HAVE_CURL_CFFI,
    DN_API_KEY,
    DN_LANES,
)
import moon_extract as _moon_extract            # noqa: E402

# The degraded no-curl_cffi fuckingfast path, and the lane pool's per-context user
# agent, both reuse this module's own HTTP/UA plumbing.
_moon_extract._sess = _sess
_moon_extract.USER_AGENTS = USER_AGENTS

if DN_API_KEY:
    print("datanodes: MOON_DN_API_KEY set - trying the API first "
          "(direct_link requires a premium account; free keys get 403 "
          "and fall back to the browser)")

if not HAVE_CURL_CFFI:
    print("WARNING: curl_cffi is not installed. fuckingfast.co will fail with "
          "Cloudflare 403 on every link \u2014 run: pip install curl_cffi",
          file=sys.stderr)

print(f"datanodes: up to {DN_LANES} persistent browser window(s) "
      "(set MOON_DN_LANES to change)")

# ── DOWNLOAD ──────────────────────────────────────────────────────────────────

class _StallKill(Exception): pass


async def download_file(
    proxy_url    : str,
    cookies      : str,
    dest         : str,
    rec          : FileRecord,
    bytes_acc    : collections.deque,
    telem        : Telemetry,
    kill_evt     : asyncio.Event,
    kills_so_far : int,
) -> tuple[bool, str, int]:
    """Download a single file with resume support, stall detection, and proxy rotation."""
    tmp    = dest + ".tmp"
    loop   = asyncio.get_running_loop()
    detect = kills_so_far < STALL_MAX_KILL

    def _write(f, data: bytes): f.write(data)

    for att in range(DL_INNER_RETRIES):
        resume = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        ref = referer_for(proxy_url)
        hdrs = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer":    ref,
            "Connection": "keep-alive",
        }
        if cookies: hdrs["Cookie"] = cookies
        if resume > 0: hdrs["Range"] = f"bytes={resume}-"

        # Pick proxy for this attempt — new proxy on each retry for variety
        proxy_cfg  = _PROXY_POOL.next()
        if proxy_cfg:
            dl_session  = _PROXY_POOL.get_session(proxy_cfg)
            dl_proxy    = proxy_cfg["url"]
            dl_proxy_auth = proxy_cfg["auth"]
        else:
            dl_session  = _sess()
            dl_proxy    = None
            dl_proxy_auth = None

        try:
            dl_t0 = time.monotonic()
            req_kwargs = dict(headers=hdrs)
            if dl_proxy:
                req_kwargs["proxy"]      = dl_proxy
                req_kwargs["proxy_auth"] = dl_proxy_auth

            async with dl_session.get(proxy_url, **req_kwargs) as r:
                if r.status == 416:
                    if os.path.exists(tmp): os.replace(tmp, dest)
                    rec.file_bytes = os.path.getsize(dest) if os.path.exists(dest) else 0
                    return True, "ok", 0
                if r.status not in (200, 206):
                    return False, f"HTTP {r.status}", resume
                if r.status == 200 and resume > 0: resume = 0

                file_size = int(r.headers.get("Content-Length", 0)) + resume
                if file_size > 0: rec.file_bytes = file_size

                effective_detect = detect and (file_size == 0 or file_size >= STALL_MIN_FILE_BYTES)
                mode = "ab" if resume > 0 else "wb"
                f = open(tmp, mode)
                speed_win  : collections.deque = collections.deque(maxlen=8000)
                # Separate window for the UI: stall detection prunes
                # speed_win on a 60s cutoff, so sharing one deque would
                # let the row speed eat the stall detector's history.
                pub_win    : collections.deque = collections.deque(maxlen=600)
                last_pub   = dl_t0
                downloaded = resume
                last_check = dl_t0

                try:
                    buf: list[bytes] = []; bufsz = 0
                    async for chunk in r.content.iter_chunked(RECV_CHUNK):
                        if not chunk: break
                        if kill_evt.is_set(): raise _StallKill()
                        now         = time.monotonic()
                        downloaded += len(chunk)
                        speed_win.append((now, len(chunk)))
                        pub_win.append((now, len(chunk)))
                        bytes_acc.append((now, len(chunk)))
                        buf.append(chunk); bufsz += len(chunk)
                        if bufsz >= WRITE_BUF:
                            data  = b"".join(buf); buf = []; bufsz = 0
                            await loop.run_in_executor(_POOL, _write, f, data)

                        elapsed = now - dl_t0

                        # Publish live progress for the GUI's rows at ~4 Hz.
                        # Two attribute writes cost nothing against a 4 MB
                        # socket read, and snapshot() reads rec directly.
                        if now - last_pub >= 0.25:
                            last_pub = now
                            pub_cut  = now - 3.0
                            while pub_win and pub_win[0][0] < pub_cut:
                                pub_win.popleft()
                            pub_span = max(now - pub_win[0][0], 0.25) if pub_win else 1.0
                            rec.done_bytes = downloaded
                            rec.live_mbs   = sum(b for _, b in pub_win) / pub_span / 1_048_576

                        # ── Stall detection ──────────────────────────────────
                        if effective_detect and (now - last_check) >= STALL_CHECK_S:
                            last_check = now
                            if elapsed >= STALL_GRACE_S:
                                pct    = downloaded / file_size if file_size > 0 else 0.0
                                cutoff = now - STALL_WIN_S
                                while speed_win and speed_win[0][0] < cutoff:
                                    speed_win.popleft()
                                win_bytes = sum(b for _, b in speed_win)
                                if win_bytes >= STALL_MIN_BYTES_IN_WIN and pct < STALL_SAFE_PCT:
                                    win_s = max(now - speed_win[0][0], 1.0)
                                    spd   = win_bytes / win_s / 1e6
                                    if spd < STALL_MIN_MBS:
                                        telem.stall(rec.filename, spd, downloaded,
                                            f"slow ({spd:.2f} MB/s, {pct*100:.0f}%) → kill")
                                        kill_evt.set()
                                        raise _StallKill()

                    if buf:
                        bytes_acc.append((time.monotonic(), sum(len(b) for b in buf)))
                        await loop.run_in_executor(_POOL, _write, f, b"".join(buf))
                finally:
                    f.close()

            os.replace(tmp, dest)
            dl_s = max(time.monotonic() - dl_t0, 0.001)
            net  = downloaded - resume
            if net > 0: rec.avg_mbs = net / dl_s / 1e6
            rec.file_bytes = rec.file_bytes or downloaded
            return True, "ok", 0

        except _StallKill:
            return False, "stall_killed", downloaded
        except (aiohttp.ClientPayloadError, aiohttp.ServerDisconnectedError):
            rec.notes.append(f"connection dropped att {att+1}")
            if att < DL_INNER_RETRIES - 1: await asyncio.sleep(0.5*(att+1)); continue
            return False, "connection dropped", downloaded
        except asyncio.TimeoutError:
            rec.notes.append(f"timeout att {att+1}")
            if att < DL_INNER_RETRIES - 1: await asyncio.sleep(1+att); continue
            return False, "timeout", downloaded
        except Exception as e:
            err = str(e)
            rec.notes.append(f"error att {att+1}: {err}")
            if att < DL_INNER_RETRIES - 1 and ("ContentLengthError" in err or "not enough data" in err.lower()):
                await asyncio.sleep(0.5*(att+1)); continue
            return False, err, downloaded

    return False, "max retries", 0


class Engine:

    def __init__(self):
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

    def _inc(self, attr, delta=1):
        with self._lock: setattr(self, attr, getattr(self, attr) + delta)

    def _get(self, attr):
        with self._lock: return getattr(self, attr)

    _LOG_MAX_LINES = 2000

    def log(self, msg, tag=""):
        """Thread-safe: called from the asyncio worker, drained by snapshot()."""
        with self._log_lock:
            self._log_ring.append((str(msg), tag))
            self._log_total += 1

    async def _do_dl(self, proxy_url, cookies, filename, orig_url, rec,
                     kill_counts, dl_sem, dest_folder, telem, mark_done_fn,
                     failed_urls, q):
        async with dl_sem:
            self._inc("_dls")
            rec.dl_start = time.monotonic(); rec.status = "downloading"
            self._track(rec)
            dest = os.path.join(dest_folder, filename)

            if os.path.exists(dest):
                self._inc("_ok")
                self.log(f"    ✓  Exists: {filename}", "ok")
                rec.status="ok"; rec.dl_s=0.0
                mark_done_fn(); self._inc("_dl_done"); self._inc("_dls",-1); return

            kc       = kill_counts.get(orig_url, 0)
            kill_evt = asyncio.Event()
            ok, msg, bytes_done = await download_file(
                proxy_url, cookies, dest, rec, self._bytes_acc, telem, kill_evt, kc)
            rec.dl_s = max(time.monotonic()-rec.dl_start, 0.001)

            if ok:
                self._inc("_ok")
                spd = f"  ({rec.avg_mbs:.1f} MB/s)" if rec.avg_mbs > 0 else ""
                self.log(f"    ✓  Saved: {filename}{spd}", "ok")
                rec.status="ok"; mark_done_fn(); self._inc("_dl_done")
            elif msg == "stall_killed":
                done_mb = bytes_done//(1<<20)
                new_kc = kc + 1; kill_counts[orig_url] = new_kc
                self._inc("_kills"); rec.stall_kills += 1
                if new_kc <= STALL_MAX_KILL:
                    self.log(f"    ⚡  Kill #{new_kc}: {filename}  ({done_mb}MB) → re-extract", "kill")
                else:
                    self.log(f"    ⚡  Kill #{new_kc}: {filename}  ({done_mb}MB) → continue", "warn")
                rec.queued_at=time.monotonic(); rec.status="pending"
                await q.put((orig_url, 1, rec))
                self._inc("_dls",-1); return
            else:
                self._inc("_fail"); failed_urls.append(orig_url)
                rec.status="fail"; rec.error=msg
                self.log(f"    ✗  {filename}: {msg}", "fail")
                mark_done_fn(); self._inc("_dl_done")

            self._inc("_dls",-1)

    async def _browser_worker(self, get_browser, wid, q, dl_sem, all_done, mark_done_fn,
                               kill_counts, all_tasks, tasks_lock,
                               output_links, failed_urls, dest_folder, mode, max_retries, telem):
        my_tasks = []
        try:
            while not self._get("_stop_flag"):
                if all_done.is_set() and q.empty(): break
                try:
                    url, attempt, rec = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError: continue

                rec.worker_id    = wid
                t_start          = time.monotonic()
                rec.queue_wait_s = t_start - rec.queued_at
                rec.status       = "extracting"
                filename = rec.filename
                short    = filename[:44]+("…" if len(filename)>44 else "")
                is_re    = rec.stall_kills > 0
                is_retry = attempt > 1
                suffix   = (" [re-extract]" if is_re else "")+(" [retry]" if is_retry else "")
                self.log(f"  → {short}{suffix}", "retry" if (is_re or is_retry) else "dim")
                self._track(rec)

                success = False
                try:
                    parsed = urlparse(url)
                    if "fuckingfast.co" in parsed.netloc:
                        link = await extract_fuckingfast(url)
                        rec.extract_s = time.monotonic()-t_start
                        if not link:
                            self.log("    ✗  No link found", "fail")
                        elif mode == "links":
                            output_links.append(link); self._inc("_ok")
                            self.log(f"    ✓  {link[:70]}", "ok")
                            rec.status="ok"; success=True; mark_done_fn()
                        else:
                            self.log(f"    ↓  {filename}", "dim")
                            async def _task(pu=link, fn=filename, ou=url, r=rec):
                                await self._do_dl(pu, "", fn, ou, r, kill_counts,
                                                   dl_sem, dest_folder, telem, mark_done_fn,
                                                   failed_urls, q)
                            t = asyncio.create_task(_task())
                            my_tasks.append(t)
                            async with tasks_lock: all_tasks.append(t)
                            success = True
                    elif "datanodes.to" in parsed.netloc:
                        # API key set -> single JSON GET, no browser, no captcha.
                        # get_browser() is where Chrome is actually launched, so a
                        # batch with no datanodes link never opens one. After that
                        # extract_datanodes() re-validates the shared Chrome
                        # (respawning it if it died) and checks out one window from
                        # the persistent lane pool internally.
                        proxy_url, cookies = await extract_datanodes(await get_browser(), url)
                        rec.extract_s = time.monotonic()-t_start
                        if not proxy_url:
                            rec.notes.append("extraction failed")
                            self.log("    ✗  No URL extracted", "fail")
                        elif mode == "links":
                            output_links.append(proxy_url); self._inc("_ok")
                            self.log(f"    ✓  {proxy_url[:70]}", "ok")
                            rec.status="ok"; success=True; mark_done_fn()
                        else:
                            self.log(f"    ↓  {filename}", "dim")
                            async def _task(pu=proxy_url, co=cookies, fn=filename, ou=url, r=rec):
                                await self._do_dl(pu, co, fn, ou, r, kill_counts,
                                                   dl_sem, dest_folder, telem, mark_done_fn,
                                                   failed_urls, q)
                            t = asyncio.create_task(_task())
                            my_tasks.append(t)
                            async with tasks_lock: all_tasks.append(t)
                            success = True
                except Exception as e:
                    rec.notes.append(f"exception: {e}")
                    self.log(f"    ✗  {e}", "fail")

                if not success and not is_re and attempt < max_retries and not self._get("_stop_flag"):
                    backoff = min(2**(attempt-1), 6)
                    self.log(f"    ↻  retry in {backoff}s", "warn")
                    await asyncio.sleep(backoff)
                    rec.queued_at = time.monotonic()
                    await q.put((url, attempt+1, rec))
                    q.task_done(); continue

                if not success and not is_re:
                    self._inc("_fail"); failed_urls.append(url)
                    rec.status="fail"; mark_done_fn()

                self._inc("_url_done"); q.task_done()

            if my_tasks:
                await asyncio.gather(*my_tasks, return_exceptions=True)
        finally:
            pass

    async def _run(self, urls, n_workers, max_dl, max_retries):
        t0           = time.monotonic()
        q            = asyncio.Queue()
        dl_sem       = asyncio.Semaphore(max_dl)
        output_links : list[str] = []
        failed_urls  : list[str] = []
        all_tasks    : list      = []
        tasks_lock   = asyncio.Lock()
        kill_counts  : dict[str,int] = {}
        dest_folder  = self._cfg["out_folder"]
        mode         = self._cfg["mode"]
        n_done       = 0
        all_done     = asyncio.Event()

        def mark_done():
            nonlocal n_done
            n_done += 1
            if n_done >= len(urls): all_done.set()

        cfg = {"browsers": n_workers, "dl_streams": max_dl, "retries": max_retries,
               "stall_min_mbs": STALL_MIN_MBS, "stall_grace_s": STALL_GRACE_S,
               "stall_max_kill": STALL_MAX_KILL, "stall_safe_pct": STALL_SAFE_PCT,
               "stall_win_guard_MB": STALL_MIN_BYTES_IN_WIN//(1<<20),
               "recv_chunk_MB": RECV_CHUNK//(1<<20), "write_buf_MB": WRITE_BUF//(1<<20),
               "socket_buf_KB": READ_BUFSZ//1024, "mode": mode, "total_links": len(urls)}
        telem = Telemetry(cfg)

        for url in urls:
            p = urlparse(url)
            raw_name = unquote(p.fragment or p.path.split("/")[-1]) or url
            rec = telem.reg(url, _sanitize_filename(raw_name))
            await q.put((url, 1, rec))

        snap_stop = asyncio.Event()
        async def snap_task():
            while not snap_stop.is_set():
                with self._lock:
                    b, d, ok, fail = self._browsers, self._dls, self._ok, self._fail
                telem.snap(b, d, q.qsize(), ok, fail)
                await asyncio.sleep(1.0)

        snap_t = asyncio.create_task(snap_task())

        # fuckingfast is pure HTTP: no browser, no profile, not even the Playwright
        # driver. Chrome opens on the first datanodes link and not before - a
        # fuckingfast-only batch never launches one.
        def _chrome_starting():
            self._inc("_browsers")
            self.log("   datanodes: starting Chrome...", "dim")

        gate = BrowserGate(LAUNCH_ARGS, on_open=_chrome_starting)

        async def _launch(wid):
            await self._browser_worker(
                gate.get, wid, q, dl_sem, all_done, mark_done,
                kill_counts, all_tasks, tasks_lock,
                output_links, failed_urls, dest_folder, mode, max_retries, telem)

        try:
            await asyncio.gather(*[asyncio.create_task(_launch(i)) for i in range(n_workers)])
        finally:
            if gate.opened:
                self._inc("_browsers", -1)
            await gate.aclose()

        async with tasks_lock:
            stragglers = [t for t in all_tasks if not t.done()]
        if stragglers:
            self.log(f"  ⚠  {len(stragglers)} straggler tasks finishing...", "warn")
            await asyncio.gather(*stragglers, return_exceptions=True)

        snap_stop.set()
        await _close_sess()
        await close_ff_session()
        await _PROXY_POOL.close_all()
        telem.finish()

        base = os.path.dirname(os.path.abspath(__file__))
        try:
            lp, jp = telem.save(base)
            self.log(f"📊  {os.path.basename(lp)}", "info")
            self.log(f"📊  {os.path.basename(jp)}", "info")
        except Exception as e:
            self.log(f"⚠  Log save error: {e}", "warn")

        if output_links and mode == "links":
            with open(os.path.join(base,"output_links.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(output_links)+"\n")
            self.log("✓  Links → output_links.txt", "info")
        if failed_urls:
            with open(os.path.join(base,"failed_links.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(failed_urls)+"\n")
            self.log(f"⚠  {len(failed_urls)} failed → failed_links.txt", "warn")

        el = time.monotonic()-t0; m, s = divmod(int(el), 60)
        with self._lock: ok, fail, kills = self._ok, self._fail, self._kills
        self.log(f"\n✓  Done in {m}m {s}s  ·  ✓ {ok}  ✗ {fail}  ⚡ {kills} kills", "ok")
        self._on_done()

    def _on_done(self):
        with self._lock:
            self._running = False
            self._stop_flag = False
            self._state = "done"

    def scan_tmp(self) -> int:
        folder = self._cfg["out_folder"]
        if not os.path.isdir(folder):
            return 0
        try:
            return len([f for f in os.listdir(folder) if f.endswith(".tmp")])
        except OSError:
            return 0

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

# ── entry point ─────────────────────────────────────────────────────────────
# There is no GUI in here. Start the app with:  python moon_bridge.py
if __name__ == "__main__":
    engine = Engine()
    print(json.dumps(engine.snapshot(0)["metrics"], indent=2))
    print(f"{VERSION}  ·  headless engine ok  ·  start the GUI with: python moon_bridge.py")
