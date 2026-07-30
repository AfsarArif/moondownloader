# FAQ

## Does this work on macOS or Linux?

The engine and the CLI do — they are Python + aiohttp + curl_cffi, plus Playwright for
datanodes. `avvia.bat` is Windows-only, and the GUI needs a Chromium browser to host the
`--app` window, so on macOS/Linux run `python moon_bridge.py --serve` and open the URL.
datanodes also needs a real Chrome/Edge for Turnstile; `find_chrome()` already looks in
the usual macOS and Linux locations.

## Why does the repo have `gen_1.py` *and* `moon_engine.py`?

`gen_1.py` is the tkinter app: GUI and engine in one file. `moon_engine.py` is that same
engine with the Tk layer removed, **generated** by `apply_web_v16.py`:

```bash
python apply_web_v16.py     # gen_1.py -> moon_engine.py
```

Every replacement in the generator is exact-string and fails loudly, so the two cannot
drift silently — CI regenerates the file and fails if the result differs. Edit
`gen_1.py`, then regenerate. Never hand-edit `moon_engine.py`.

## Is it still single-file?

No. It was until 14.4, and the extraction rewrite ended that: `moon_extract.py` holds the
extraction layer shared by all three front-ends, `moon_bridge.py` hosts the GUI,
`web/` is the GUI. The `gen_1.py` + `gen_cli.py` pair is still standalone-runnable, which
was the actual point of the old rule.

## Why does fuckingfast need `curl_cffi`?

Cloudflare fingerprints the TLS ClientHello. aiohttp's scores as a bot and gets a 403 on
every link no matter which headers it sends; `curl_cffi` impersonates Chrome's and gets
through. Downloads stay on aiohttp — `dl.fuckingfast.co` serves the file with full Range
support and no impersonation needed.

## Why does datanodes need a *visible* Chrome?

Turnstile does not issue a token to a headless build: the challenge platform answers 401
and `cf-turnstile-response` stays empty. It also rejects Playwright's Chromium, which is
not a Google-branded build. So the app spawns a real Chrome with a persistent profile and
drives it over CDP — the profile is the point, because the clearance survives between
links.

## Does Chrome open for fuckingfast links too?

No, since v16. `moon_extract.BrowserGate` launches on the first datanodes link and never
before — not even the Playwright driver's node process. `python test_no_chrome.py` asserts
it for the engine and the CLI, and checks the sources of all three front-ends.

## What's the difference between `gen_1.py`, `gen_cli.py` and `moon_bridge.py`?

Same engine, three front-ends.

- `moon_bridge.py` + `web/` — the v16 GUI: loopback HTTP, Edge/Chrome `--app` window
- `gen_1.py` — the tkinter GUI (`avvia_tk.bat`)
- `gen_cli.py` — argparse CLI, prints to stdout, for scripting and headless boxes

## What does `--browsers` / `Extractors` actually control?

Parallel extraction workers. It has not meant "one browser each" since 14.7: datanodes
runs on **one** shared Chrome window, and `Pages` (1–8) bounds how many tabs may be open
on it at once. fuckingfast opens nothing at all.

## Are proxies required?

No. Drop a `proxies.txt` next to the scripts to enable rotation:

```
ip:port:user:pass
http://user:pass@ip:port
```

The status bar shows how many were loaded.

## Can I skip the captcha entirely?

With a datanodes **premium API key**, yes — extraction becomes one JSON GET, no browser,
no Turnstile. Set it in the GUI or `MOON_DN_API_KEY`. Free keys get 403 on `direct_link`
and fall back to Chrome.

## Can I add another provider?

Yes — write the extractor in `moon_extract.py`, dispatch on the domain in `gen_1.py` and
`gen_cli.py`, then regenerate `moon_engine.py`. Ask `BrowserGate.get()` for a browser
inside the branch that needs it, never before. `docs/PROVIDERS.md` has the full checklist.

## Why isn't there a Docker image?

datanodes needs a visible, real Chrome for Turnstile, which is exactly what a container
is bad at. A fuckingfast-only container would work (no browser at all) — nothing is
published yet.

## Where do I report bugs?

[Bug report template](https://github.com/LeyckerS/moondownloader/issues/new?template=bug_report.yml).
Attach `moontech_*.log` (GUI) or `moontech_cli_*.log` (CLI) from the failed session.
