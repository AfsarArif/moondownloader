# FAQ

## Does this work on macOS or Linux?

The main target is **Windows 10/11**. `avvia.bat` is Windows-only, but
`gen_1.py` and `gen_cli.py` are pure Python + Playwright + aiohttp —
they should run anywhere those libs run, provided you install them by
hand. Report anything platform-specific you hit.

## Why single-file architecture?

The project intentionally keeps everything in one `.py` file (see
`CONTRIBUTING.md`). Trade-offs:

- **Pros:** zero build step, easy to grep, drop into any folder and run.
- **Cons:** less enforced separation between layers.

The layering is documented in the README under **Architecture**.

## Can I add more providers?

Yes, but keep them in the same style: a regex-based extractor for simple
sites, a Playwright flow for the ones that require a browser. Look at
how `fuckingfast.co` (regex) and `datanodes.to` (Playwright) are
handled in `gen_1.py` as a template.

## What's the difference between `gen_1.py` and `gen_cli.py`?

Same core — different frontend.

- `gen_1.py` — tkinter GUI, live progress bars, color-coded log.
- `gen_cli.py` — headless argparse-based CLI, prints to stdout, meant
  for scripting and server-side use.

## Are proxies required?

No. They're optional. Drop a `proxies.txt` next to `gen_1.py` to enable
rotation. Format:

```
ip:port:user:pass
http://user:pass@ip:port
```

## Why isn't there a Docker image?

The tool needs to install Chromium (~150 MB) inside the container, and
GUI users generally prefer running natively on Windows. Not opposed on
principle, but no image is published yet.

## Where do I report bugs?

Open a bug report using
[the issue template](https://github.com/LeyckerS/moondownloader/issues/new?template=bug_report.yml).
Attach the `moontech_*.log` from the failed session.
