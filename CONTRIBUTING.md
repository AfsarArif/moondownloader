# Contributing to Moon Downloader

Thanks for your interest in contributing!

## How to contribute

1. **Fork** the repository
2. **Create a branch** for your feature or fix
3. **Test** your changes with both providers (datanodes.to and fuckingfast.co)
4. **Submit a pull request** with a clear description of what you changed and why

## Architecture

The entire application lives in a single file (`gen_1.py`, ~1350 lines). This is intentional — no package structure, no build step. The CLI version (`gen_cli.py`) mirrors the same architecture for headless deployment.

Key layers:
- **Extraction** — Playwright-based for datanodes.to, regex-based for fuckingfast.co
- **Download engine** — aiohttp with Range-header resume, stall detection, proxy rotation
- **GUI** — tkinter with 8 Hz stat updates and color-coded log output
- **Telemetry** — 1 Hz snapshots with `.log` and `.json` output

## Guidelines

- Keep the single-file architecture. Don't split into packages.
- Any change to `gen_1.py` that affects shared logic (extraction, download engine) should also be applied to `gen_cli.py`.
- Test with at least 10+ files to verify concurrency behavior.
- Don't add dependencies without a strong reason — the current stack (aiohttp + playwright + pillow) is intentionally minimal.

## Reporting bugs

Use the [bug report template](https://github.com/LeyckerS/moondownloader/issues/new?template=bug_report.yml) and include your `moontech_*.log` file if possible.


## Coding style

- 4-space indentation, no tabs.
- Prefer f-strings over `%` or `.format()`.
- Keep top-level constants uppercase (e.g. `RECV_CHUNK`, `WRITE_BUF`).
- No blanket `except:` — always name the exception type or use `except Exception:` with a comment when the swallow is intentional.
- Match the surrounding style. This project isn't linted by CI, so consistency comes from reading nearby code first.
