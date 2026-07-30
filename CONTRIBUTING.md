# Contributing to Moon Downloader

Thanks for your interest in contributing!

## How to contribute

1. **Fork** the repository
2. **Create a branch** for your feature or fix
3. **Test** your changes against both providers (datanodes.to and fuckingfast.co)
4. **Run the verification suite** (below) — it is fast and catches the regressions that
   actually happened
5. **Submit a pull request** describing what changed and why

## Architecture

Three front-ends, one engine, one extraction layer.

```
moon_bridge.py     loopback HTTP + token, launches Edge/Chrome --app, OS dialogs
  web/             index.html · styles.css · app.js        the v16 GUI
  moon_engine.py   the engine with no GUI: start/stop/snapshot   (GENERATED)
    moon_extract.py  datanodes (real Chrome over CDP) · fuckingfast (curl_cffi)
                     BrowserGate: the launch, deferred until a datanodes link

gen_1.py           tkinter GUI + engine in one file            (the source of truth)
gen_cli.py         argparse CLI
apply_web_v16.py   regenerates moon_engine.py from gen_1.py
```

Layers inside the engine:

- **Extraction** — `moon_extract.py`, shared by all three front-ends
- **Download engine** — aiohttp, Range-header resume, stall detection, proxy rotation
- **Telemetry** — 1 Hz snapshots, `.txt` + `.json` output
- **GUI** — either `web/` over the loopback API (v16) or tkinter (`gen_1.py`)

## Rules that are not style preferences

- **`moon_engine.py` is generated. Never hand-edit it.** Change `gen_1.py`, then run
  `python apply_web_v16.py`. CI regenerates it and fails if your commit disagrees.
- **Shared logic goes in `moon_extract.py`**, not copy-pasted between front-ends. If a
  change touches extraction, the Chrome lifecycle or the download engine, it must land
  in one place and be visible from `gen_1.py`, `gen_cli.py` and `moon_engine.py`.
- **Never open a browser before you know you need one.** Ask `BrowserGate.get()` inside
  the provider branch that requires it. A launch at the top of a run is the bug
  `test_no_chrome.py` exists to prevent.
- **Any change to `gen_1.py`'s shared logic must be mirrored in `gen_cli.py`.**
- **No new dependencies without a strong reason.** The stack is deliberately small:
  `aiohttp`, `playwright`, `curl_cffi`, with `pillow` optional.
- **English only.** Code, comments, log lines, dialog titles and docs. The GUI's EN/IT
  dictionary in `web/app.js` is the one exception — that is the runtime language switch.

## Verification

```bash
python test_no_chrome.py       # no browser for fuckingfast, exactly one for datanodes
python apply_web_v16.py        # regenerate the engine; git diff must be empty
python integration_http.py     # browser -> loopback HTTP -> engine
python integration_web.py      # pywebview path
python shots.py out/           # GUI renders + overflow audit
```

`test_no_chrome.py` stubs Chrome and the network at the `moon_extract` boundary, so it
needs no browser, no display and no Playwright install.

Live testing: at least 10 links per provider, including one guaranteed-dead one so
dead-link detection is exercised, and one session long enough (40+ files) to hit the
concurrency paths.

## Reporting bugs

Use the [bug report template](https://github.com/LeyckerS/moondownloader/issues/new?template=bug_report.yml)
and attach `moontech_*.log` (GUI) or `moontech_cli_*.log` (CLI). `MOON_DEBUG=1` adds
extraction-level tracing.

## Coding style

- 4-space indentation, no tabs.
- f-strings over `%` or `.format()`.
- Top-level constants uppercase (`RECV_CHUNK`, `WRITE_BUF`, `DN_LANES`).
- No blanket `except:` — name the exception, or `except Exception:` with a comment when
  the swallow is deliberate.
- Comments explain **why**, not what. The gotchas in `moon_extract.py` are the model:
  each one states a specific fact that cost a debugging session.
- Match the surrounding style. Read the nearby code first.
