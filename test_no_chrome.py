"""Regression: a fuckingfast-only batch must not start Chrome.

    python3 test_no_chrome.py

The v14.x/v15 engine opened one browser PER WORKER inside _run, before looking at
a single URL, so a batch of pure-HTTP fuckingfast links still launched Chrome (and
the Playwright driver). This test asserts:

    1. fuckingfast-only  -> open_browser and async_playwright are never touched
    2. one datanodes link -> the shared browser is opened exactly once

Network, extraction and Chrome are all stubbed: what is under test is the
dispatcher's decision to launch, not the extractors.
"""
from __future__ import annotations

import asyncio
import contextlib
import glob
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import moon_engine                                    # noqa: E402

FF = [f"https://fuckingfast.co/x{n}/pack.part{n:02d}.rar" for n in range(1, 4)]
DN = ["https://datanodes.to/y1/pack.part99.rar"]

calls = {"open_browser": 0, "playwright": 0, "close_browser": 0}


async def fake_ff(url):
    await asyncio.sleep(0.01)
    return url.replace("fuckingfast.co", "dl.fuckingfast.co") + "?fake"


async def fake_dn(browser, url):
    await asyncio.sleep(0.01)
    return url + "?fake", ""


class FakePlaywright:
    """Stands in for the async_playwright() context manager."""

    async def __aenter__(self):
        calls["playwright"] += 1
        return self

    async def __aexit__(self, *exc):
        return False


async def fake_open_browser(pw, args, headless=None):
    calls["open_browser"] += 1
    return object(), True


async def fake_close_browser(browser, shared):
    calls["close_browser"] += 1


def install_stubs() -> None:
    moon_engine.extract_fuckingfast = fake_ff
    moon_engine.extract_datanodes = fake_dn
    moon_engine.open_browser = fake_open_browser
    moon_engine.close_browser = fake_close_browser
    moon_engine.async_playwright = FakePlaywright
    moon_engine.shutdown_chrome = lambda: asyncio.sleep(0)
    moon_engine.close_ff_session = lambda: asyncio.sleep(0)


def run(engine, urls, label) -> dict:
    for key in calls:
        calls[key] = 0
    res = engine.start({"links": urls, "mode": "links", "out_folder": str(HERE / "_tmp_out"),
                        "workers": 4, "dl_streams": 4, "retries": 1})
    if res.get("error"):
        raise SystemExit(f"[FAIL] {label}: start refused: {res['error']}")
    deadline = time.monotonic() + 25
    while engine._get("_running") and time.monotonic() < deadline:
        time.sleep(0.15)
    snap = engine.snapshot(0)["metrics"]
    print(f"{label}: ok={snap['ok']} fail={snap['fail']} "
          f"open_browser={calls['open_browser']} playwright={calls['playwright']}")
    return dict(calls, ok=snap["ok"], fail=snap["fail"])


def main() -> int:
    install_stubs()
    engine = moon_engine.Engine()
    problems: list[str] = []

    ff = run(engine, FF, "fuckingfast only ")
    if ff["open_browser"]:
        problems.append(f"Chrome opened on a fuckingfast-only batch ({ff['open_browser']}x)")
    if ff["playwright"]:
        problems.append(f"Playwright driver started with no datanodes link ({ff['playwright']}x)")
    if ff["ok"] != len(FF):
        problems.append(f"fuckingfast batch extracted {ff['ok']}/{len(FF)}")

    mixed = run(engine, FF + DN, "mixed batch     ")
    if mixed["open_browser"] != 1:
        problems.append(f"shared Chrome opened {mixed['open_browser']}x for one datanodes link")
    if mixed["close_browser"] != 1:
        problems.append(f"browser closed {mixed['close_browser']}x, expected 1")
    if mixed["ok"] != len(FF) + len(DN):
        problems.append(f"mixed batch extracted {mixed['ok']}/{len(FF) + len(DN)}")

    # tidy up what a run leaves behind next to the script
    for pattern in ("moon_log_*.txt", "moon_log_*.json", "output_links.txt", "failed_links.txt"):
        for path in glob.glob(str(HERE / pattern)):
            with contextlib.suppress(OSError):
                os.unlink(path)
    with contextlib.suppress(OSError):
        os.rmdir(HERE / "_tmp_out")

    for line in problems:
        print("[FAIL]", line)
    if problems:
        return 1
    print("[OK] no Chrome for fuckingfast · exactly one shared Chrome when datanodes appears")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
