"""Regression: only a datanodes.to link may open a browser.

    python3 test_no_chrome.py

Up to v15 every front-end opened one browser PER WORKER at the top of the run,
before reading a single URL, so a batch of pure-HTTP fuckingfast links still
launched Chrome (visible, since Turnstile hands no token to a headless build) and
the Playwright driver with it. The launch decision now lives in
`moon_extract.BrowserGate`, and only the datanodes branch asks it for a browser.

Asserted here, for the WebView engine and for the CLI:

    1. fuckingfast-only -> zero browsers, zero Playwright driver boots
    2. one datanodes link -> exactly one shared browser, torn down exactly once
    3. no front-end calls open_browser() outside the gate  (static, covers gen_1.py,
       which cannot be imported without a display)

Network, extraction and Chrome are all stubbed at the moon_extract level: what is
under test is the dispatcher's decision to launch, not the extractors.
"""
from __future__ import annotations

import asyncio
import contextlib
import glob
import os
import pathlib
import re
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import moon_extract                                   # noqa: E402
import moon_engine                                    # noqa: E402
import gen_cli                                        # noqa: E402

FF = [f"https://fuckingfast.co/x{n}/pack.part{n:02d}.rar" for n in range(1, 4)]
DN = ["https://datanodes.to/y1/pack.part99.rar"]

FRONT_ENDS = ("gen_1.py", "gen_cli.py", "moon_engine.py")

calls = {"playwright": 0, "open_browser": 0, "close_browser": 0, "shutdown_chrome": 0}


def reset() -> None:
    for key in calls:
        calls[key] = 0


# ── stubs ─────────────────────────────────────────────────────────────────────
async def fake_ff(url):
    await asyncio.sleep(0.01)
    return url.replace("fuckingfast.co", "dl.fuckingfast.co") + "?fake"


async def fake_dn(browser, url):
    await asyncio.sleep(0.01)
    if browser is None:
        raise AssertionError("extract_datanodes got no browser")
    return url + "?fake", ""


async def fake_download(*a, **kw):
    await asyncio.sleep(0.01)
    return True, "", 1024


async def fake_start_playwright():
    calls["playwright"] += 1
    return object()


async def fake_open_browser(pw, args, headless=None):
    calls["open_browser"] += 1
    return object(), True          # True = the shared CDP Chrome


async def fake_close_browser(browser, shared=None):
    calls["close_browser"] += 1


async def fake_shutdown_chrome():
    calls["shutdown_chrome"] += 1


def install_stubs() -> None:
    # The gate resolves these from moon_extract's own globals at call time.
    moon_extract._start_playwright = fake_start_playwright
    moon_extract.open_browser      = fake_open_browser
    moon_extract.close_browser     = fake_close_browser
    moon_extract.shutdown_chrome   = fake_shutdown_chrome

    # Each front-end imported the extractors by name into its own namespace.
    for host in (moon_engine, gen_cli):
        host.extract_fuckingfast = fake_ff
        host.extract_datanodes   = fake_dn
        host.close_ff_session    = lambda: asyncio.sleep(0)
    gen_cli.download_file = fake_download


# ── runners ───────────────────────────────────────────────────────────────────
def run_engine(engine, urls, label) -> dict:
    reset()
    res = engine.start({"links": urls, "mode": "links", "out_folder": str(HERE / "_tmp_out"),
                        "workers": 4, "dl_streams": 4, "retries": 1})
    if res.get("error"):
        raise SystemExit(f"[FAIL] {label}: start refused: {res['error']}")
    deadline = time.monotonic() + 25
    while engine._get("_running") and time.monotonic() < deadline:
        time.sleep(0.15)
    metrics = engine.snapshot(0)["metrics"]
    return report(label, dict(calls, ok=metrics["ok"], fail=metrics["fail"]))


def run_cli(urls, label) -> dict:
    reset()
    with tempfile.TemporaryDirectory() as out:
        asyncio.run(gen_cli.run(urls, out, 4, 4, 1, "proxies.txt"))
        done = len(os.listdir(out))
    return report(label, dict(calls, ok=len(urls) if done == 0 else done, fail=0))


def report(label, result) -> dict:
    print(f"{label}: ok={result['ok']} browsers={result['open_browser']} "
          f"driver_boots={result['playwright']} teardowns="
          f"{result['close_browser'] + result['shutdown_chrome']}")
    return result


def check(result, label, urls, want_browsers: int, problems: list[str]) -> None:
    if result["open_browser"] != want_browsers:
        problems.append(f"{label}: {result['open_browser']} browser(s) opened, "
                        f"expected {want_browsers}")
    if result["playwright"] != want_browsers:
        problems.append(f"{label}: Playwright driver booted {result['playwright']}x, "
                        f"expected {want_browsers}")
    teardowns = result["close_browser"] + result["shutdown_chrome"]
    if teardowns != want_browsers:
        problems.append(f"{label}: torn down {teardowns}x, expected {want_browsers}")
    if result["ok"] != len(urls):
        problems.append(f"{label}: handled {result['ok']}/{len(urls)} links")


def check_sources(problems: list[str]) -> None:
    """gen_1.py needs a display to run; its launch path is checked as source."""
    for name in FRONT_ENDS:
        text = (HERE / name).read_text(encoding="utf-8")
        if re.search(r"(?<!def )(?<!fake_)open_browser\s*\(", text):
            problems.append(f"{name} calls open_browser() directly instead of BrowserGate")
        if "BrowserGate(" not in text:
            problems.append(f"{name} never builds a BrowserGate")
        if "await get_browser()" not in text and "gate.get" not in text:
            problems.append(f"{name} does not fetch the browser lazily at the datanodes branch")
    print(f"sources        : {', '.join(FRONT_ENDS)} route every launch through BrowserGate")


def cleanup() -> None:
    for pattern in ("moon_log_*.txt", "moon_log_*.json", "moontech_cli_*.log",
                    "moontech_cli_*.json", "output_links.txt", "failed_links.txt"):
        for path in glob.glob(str(HERE / pattern)):
            with contextlib.suppress(OSError):
                os.unlink(path)
    with contextlib.suppress(OSError):
        os.rmdir(HERE / "_tmp_out")


def main() -> int:
    install_stubs()
    problems: list[str] = []

    engine = moon_engine.Engine()
    check(run_engine(engine, FF, "engine ff-only "), "engine ff-only", FF, 0, problems)
    check(run_engine(engine, FF + DN, "engine mixed   "), "engine mixed", FF + DN, 1, problems)

    check(run_cli(FF, "cli    ff-only "), "cli ff-only", FF, 0, problems)
    check(run_cli(FF + DN, "cli    mixed   "), "cli mixed", FF + DN, 1, problems)

    check_sources(problems)
    cleanup()

    for line in problems:
        print("[FAIL]", line)
    if problems:
        return 1
    print("[OK] no browser for fuckingfast \u00b7 exactly one shared Chrome when datanodes appears")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
