# Quick Start

This is an extended version of the Quick Start in the main README, for
first-time users who want more context.

## Requirements

- **OS:** Windows 10 or Windows 11 (primary), other platforms untested
- **Python:** 3.10 or newer
- **Disk:** ~150 MB free (Chromium browser install)
- **Network:** any speed — the tuning defaults assume fiber, but the
  tool works fine on slower links

## Option 1 — One-click launch (Windows)

1. Install [Python 3.10 or newer](https://www.python.org/downloads/).
   Make sure the **"Add Python to PATH"** checkbox is ticked in the
   installer.
2. Download or clone this repo.
3. Double-click **`avvia.bat`**.

The batch script auto-installs `aiohttp`, `playwright` and `pillow` the
first time, then downloads the Chromium browser Playwright uses. This
takes ~2 minutes on a decent connection.

## Option 2 — Manual setup

```bash
git clone https://github.com/LeyckerS/moondownloader.git
cd moondownloader

pip install -r requirements.txt
playwright install chromium

python gen_1.py       # GUI version
```

## Option 3 — CLI (headless)

```bash
python gen_cli.py --urls links.txt --output ./downloads
```

See `python gen_cli.py --help` for the full flag list.

## First run

1. Paste one or more URLs from `datanodes.to` or `fuckingfast.co` into the
   input box.
2. Pick an output folder (defaults to `~/Downloads/datanodes`).
3. Optionally tweak **Browsers** and **DL Streams** in the settings panel.
4. Click **Download**.

Live speed, per-file progress and a color-coded log appear as the download
runs. A `moontech_*.log` and `moontech_*.json` are written next to
`gen_1.py` on completion.
