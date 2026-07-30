# Changelog

All notable changes to Moon Downloader will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [16.0]

The GUI moved off tkinter. Both extraction methods were rebuilt in the 14.2–14.8 line
and no longer share a mechanism, so the interface stopped pretending they do.

### Added
- **New GUI on Edge WebView2** (`web/index.html`, `web/styles.css`, `web/app.js`) — Chromium
  rendering: real anti-aliasing, real alpha, gradients, blur, GPU transitions
- `moon_bridge.py` — loopback HTTP host with a per-run token; launches Edge/Chrome with `--app`
  (a window with no tabs and no address bar), OS file dialogs, atomic `settings.json`
- `moon_engine.py` — the download engine with no GUI attached: `start()` / `stop()` /
  `snapshot(cursor)` / `scan_tmp()`, all JSON-able
- `build_engine.py` — generator that produces `moon_engine.py` from a pristine `moon_tk.py`,
  so there is one source of truth for the engine
- **Live transfer rows** — progress ring, state, percentage and instantaneous speed per file,
  fed by live `FileRecord`s (`done_bytes` / `live_mbs`, published ~4 Hz on their own window,
  kept separate from the stall detector's 60 s history)
- **English / Italian** switch, English by default; the engine ships numbers and a stage name,
  the page writes the sentence
- Fluid type scale (`clamp()`): the interface scales with the window instead of staying at an
  8 px ink height on a 2560×1440 screen
- `test_no_chrome.py`, `integration_http.py`, `integration_web.py`, `render_gui.py` — the verification suite.
  `test_no_chrome.py` stubs Chrome and the network at the `moon_extract` boundary, so it needs no
  browser, no display and no Playwright install, and covers the engine, the CLI and (statically)
  `moon_tk.py`
- `moon_extract.BrowserGate` — the deferred launch: `get()` opens Playwright and Chrome on first
  demand, collapses concurrent first calls onto one instance, and tears both down in order
- Byte-based ETA, host split of the pasted links, per-host colouring in the link editor,
  `proxies.txt` count and `.tmp` resume count in the status bar

### Changed
- **Chrome is opened lazily** — on the first datanodes link, never before. The decision lives in
  `moon_extract.BrowserGate` and is shared by the WebView engine, the Tk GUI and the CLI
- `Captcha` default 240 s → **30 s**, `Pages` default 3 → **8**
- Settings and pasted links persist across restarts in `settings.json`
- Every value the GUI sends is coerced and clamped in `Engine.apply_cfg()` before it reaches
  a semaphore
- `moon_tk.py` (the tkinter GUI) still runs unchanged from `start_tk.bat`; the only edit it took is
  the lazy launch, so the two GUIs and the CLI cannot drift apart on it
- `moon_cli.py --browsers` is documented as what it always was: parallel extraction workers, not
  one browser each
- CI byte-compiles every module, runs `test_no_chrome.py`, and regenerates `moon_engine.py` from
  `moon_tk.py` to prove the two have not drifted
- **Files renamed** so every name is English and says what it is:
  `avvia.bat` → `start.bat`, `avvia_tk.bat` → `start_tk.bat`, `gen_1.py` → `moon_tk.py`,
  `gen_cli.py` → `moon_cli.py`, `apply_web_v16.py` → `build_engine.py`
- **The repository is English throughout** — launcher output, engine warnings, Tk labels, OS dialog
  titles, module docstrings and test assertions. The GUI's runtime EN/IT switch is unaffected
- Documentation restructured: the two Italian guides became
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
  [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) and
  [`docs/ENGINEERING_NOTES.md`](docs/ENGINEERING_NOTES.md), and the README carries a documentation
  index

### Fixed
- **fuckingfast batches launched Chrome.** Every front-end called `open_browser()` once per worker
  at the top of the run, before reading a single URL, so a pure-HTTP batch paid ~1.5 s of Playwright
  driver boot and put a Chrome window on screen — visible, because Turnstile issues no token to a
  headless build, so datanodes forces `headless=False` and every launch is therefore seen
- On the fallback path (no real Chrome found) each worker got its **own** Playwright Chromium while
  the extraction layer only ever used one shared context — N browsers, one of them used
- Transfer count showed the row cap (40) instead of the transfers in flight — a 124-file
  session reported "40 active"
- The Log tab rendered the transfer list on top of the log: `.files { display: grid }` outranks
  the user-agent `[hidden]` rule
- Progress rings always rendered empty: a CSS declaration beats an SVG presentation attribute,
  so `setAttribute("stroke-dasharray")` lost to the stylesheet
- Loopback API replied 403 without draining the request body, so the next keep-alive request on
  that connection was parsed as garbage and answered 501

### Removed
- `apply_patch.py` — the v14.1 → v14.8 migration patcher. Against the current tree it
  half-applies instead of failing: in testing it silently reverted `moon_cli.py`'s imports
  to the pre-`BrowserGate` API
- `prep_assets.py` — one-shot asset builder whose inputs (the raw renders) were never in
  the repo; the assets it produced are committed
- Three orphan v14 screenshots in the repo root that nothing linked

## [15.0]

### Added
- `moon_ui.py` — the tkinter layer rebuilt from scratch: canvas-drawn cards, sliders, progress
  lanes, sparkline, status pill and per-file rows
- `apply_ui_v15.py` — exact-string patch that swaps the GUI layer and leaves the async engine
  byte-identical
- Generated brand assets (`assets/mark.png`, `assets/backdrop.png`) with `prep_assets.py`

### Known limits (the reason v16 exists)
- Tk's canvas has no anti-aliasing and no alpha channel: arcs, rounded corners and glows
  render as steps and bands
- Absolute type and geometry: on a large monitor the interface stays small and the layout
  does not redistribute

## [14.8]

### Changed
- **GUI settings split per method.** One "Browsers" slider described an architecture that no
  longer existed: fuckingfast opens no browser at all, datanodes is Chrome + Turnstile.
  Three panels instead: common, datanodes, fuckingfast
- datanodes knobs (`Pages`, captcha wait, Chrome path, API key) moved from environment
  variables to the GUI and are pushed into the extraction layer on every run through
  `moon_extract.configure()` — no more `setx` and restart

## [14.7]

### Changed
- Back to **one shared Chrome window**. Separate windows meant separate identities, and
  Cloudflare re-challenged each of them; one window and one profile means one `cf_clearance`

## [14.6]

### Fixed
- **The shared browser died after ~80 sequential extractions** and every later extraction
  stayed broken for the rest of the session, because nothing checked whether it was still
  alive. `open_browser()` now verifies `is_connected()` on every call and respawns the
  instance transparently
- Too many heavy tabs on one window slowed everything down: tabs are pooled per lane instead
  of opened per extraction

## [14.4]

### Added
- **fuckingfast.co over curl_cffi** — Chrome TLS fingerprint plus the `hx-redirect` header,
  ~0.25 s per link, no browser and no captcha. Without it Cloudflare answers 403 on every link
- **datanodes.to on real Chrome** driven over CDP with a persistent profile, instead of the
  Playwright Chromium: the profile is the point, because the Turnstile clearance survives
- Optional datanodes **premium API key** — a single JSON GET, no browser, no captcha
- `moon_extract.py` — the extraction layer split out of `gen_1.py`, shared by the GUI and the CLI

### Changed
- `curl_cffi` is now a hard requirement for fuckingfast.co

## [14.1]

### Added
- Stall detection with automatic lane kills for genuinely slow downloads
- Per-URL retry with exponential backoff
- Live telemetry with `.log` and `.json` output
- CLI variant (`gen_cli.py`) for headless / multi-IP deployment
- Ad overlay bypass and popup dismissal on datanodes.to

### Changed
- Default browser worker count tuned to 16 for typical 40+ file sessions
- Improved dead-link detection so failures fail fast instead of timing out
- Resource blocking widened to cover more analytics/ad domains

### Fixed
- Resume interrupted downloads via `.tmp` files instead of restarting
- Range-header edge case when server returns 200 instead of 206

## [14.0]

### Added
- Initial public release
- datanodes.to and fuckingfast.co provider support
- Tkinter GUI with dual progress bars and color-coded log
