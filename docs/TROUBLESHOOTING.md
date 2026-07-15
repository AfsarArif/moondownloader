# Troubleshooting

Common issues and how to resolve them.

## `avvia.bat` says "Python non trovato / Python not found"

You either don't have Python installed, or Python isn't on your `PATH`.

Fix:
1. Reinstall Python from <https://www.python.org/downloads/>
2. During install, **check the "Add Python to PATH" box** on the first
   installer screen.
3. Open a fresh Command Prompt and run `python --version` — you should
   see something starting with `Python 3.10.` or higher.

## `playwright install chromium` fails

Usually a proxy / firewall issue. Try:

```bash
python -m playwright install --with-deps chromium
```

If your organisation intercepts TLS, set `HTTPS_PROXY` before running the
install.

## Downloads stall at low speed and eventually get killed

Two independent things can look like a stall:

1. **A slow lane assigned by datanodes.to** — the CDN pins your session
   to a specific lane. Sometimes it's slow. `STALL_MIN_MBS` in `gen_1.py`
   controls when the downloader gives up.
2. **A saturated local link** — if you're already using the full uplink
   for something else, individual streams look "stalled" even though
   they're just fighting for bandwidth. Lower **DL Streams** in the GUI.

## `fuckingfast.co` links return "dead link"

The provider serves 404-like pages for expired uploads. The extractor
detects this and fails fast on purpose — there's no retry that will
recover a dead link.

## `datanodes.to` needs a captcha

If you see a captcha in the automated browser window, run fewer browsers
in parallel (**Browsers** setting) and consider adding proxies via
`proxies.txt`.

## Where are my logs?

Next to `gen_1.py`:

- `moontech_YYYYMMDD_HHMMSS.log` — human-readable
- `moontech_YYYYMMDD_HHMMSS.json` — machine-readable per-file metrics

Attach the `.log` file to any bug report.
