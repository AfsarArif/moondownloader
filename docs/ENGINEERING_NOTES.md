# Engineering notes

Why the extraction layer looks the way it does. Every entry here was measured against the
live sites, and most of them are counter-intuitive enough to be worth writing down before
someone "simplifies" them back.

---

## fuckingfast.co: the URL is not in the page

The landing page is Alpine + htmx. The `/dl/` URL is **not in the HTML at all** — it is
returned in the `hx-redirect` **response header** of `POST /f/{id}/go`. Any extractor that
greps the markup is looking for something the server stopped sending.

On top of that, Cloudflare on that host does not look at headers: it **fingerprints TLS**.
aiohttp's ClientHello is marked as a bot and the request gets `cf-mitigated: challenge` →
403 on every link. `curl_cffi` reproduces Chrome's ClientHello and passes.

Measured against live FitGirl links: **0.23–0.33 s per link**, verified with `HTTP 206`, a
correct `Content-Range` and `Rar!` magic bytes. Downloads stay on aiohttp — there is
nothing to impersonate once you have the direct URL.

One parsing trap: those links carry the filename as a URL **fragment**
(`https://fuckingfast.co/abc123#Game.part01.rar`). `urlparse` drops the fragment; a naive
`rsplit` on the raw string keeps it and yields a bogus file id. The id is parsed off the
path only.

---

## datanodes.to: why a real Chrome, and why it is visible

"Verification failed / Error Code 600010" is not a click problem — the click lands.
Cloudflare discards the browser before it evaluates anything. Playwright's bundled
Chromium is caught for three reasons at once:

1. Playwright starts it with automation switches → `navigator.webdriver` is `true`
2. it is not a Google-branded build
3. the profile is empty: no history, no `cf_clearance`

So the app starts a **real Chrome** and attaches over CDP: no automation switches, a
signed build, a persistent profile. Verified: `navigator.webdriver` goes from `true` to
`false`.

Headless does not work either. Measured on Chromium 131 (headless shell, `--headless=new`,
and with a persistent profile) the challenge platform answers **401** on
`/cdn-cgi/challenge-platform/h/b/pat/...` every time and `cf-turnstile-response` stays
empty indefinitely. `headless=False` is deliberate, which is also why a datanodes run is
always visible.

Chrome is autodetected on Windows (`Program Files`, `Program Files (x86)`, `LOCALAPPDATA`,
falling back to Edge, which is branded Chromium and works the same), and on macOS/Linux in
the usual locations.

### The persistent profile is the point

All workers share **one** Chrome instance and **one** context, so there is one
`cf_clearance`: solve the captcha once and Cloudflare stops re-challenging on the
following links instead of treating every worker as a brand-new visitor. The profile
survives between runs.

If the automatic click does not get through, the tool tries for 45 s (first inside the
iframe via Playwright, then with a real mouse on the widget coordinates, moving the
pointer first — Turnstile weighs mouse entropy), then hands it over:

```
>>> Tick the 'Verify you are human' checkbox in the browser window (waiting 240s) <<<
```

Thanks to the shared profile, that one tick also covers the links after it.

---

## Separate windows made Cloudflare worse (14.6 → 14.7)

14.6 opened four separate windows (isolated contexts) to run extractions in parallel. On
paper it should have helped. Live it did the opposite: **Cloudflare started failing the
verification** — "Verification failed" in the widget, the same red screen as the original
Playwright-Chromium problem — and the session got slower, not faster.

The cause: four separate contexts are four different identities and cookie jars hitting
Cloudflare from the same IP within seconds of each other. To an anti-bot system, "several
different sessions from one network in a few seconds" is exactly the bot-farm pattern —
far more suspicious than one shared window browsing page after page with coherent cookies,
which is what 14.4/14.5 did and what worked.

So: back to **one shared window/context**. `MOON_DN_LANES` now means "how many pages may
be open at once **on** that window" (default 3), not "how many separate windows to open".
Verified live: five extractions launched in parallel, all on the same context object — one
browsing context open in total, never five.

A fast exit was added for when Cloudflare fails anyway. Previously, if the Turnstile
widget went to "Verification failed" (a widget fault, not a click problem), the tool kept
trying for the whole budget — up to 45 s of automatic attempts plus 240 s of manual wait,
almost five minutes on a single stuck file. It now recognises that text immediately,
reloads the page **once** (often enough to get a clean widget), and moves on if that fails
too. Measured: from ~45 s of useless waiting to 0.01 s of detection.

---

## The shared browser died after ~80 extractions (14.6)

From an 85-file session log: 31.9 MB/s aggregate (42.5 GB in 22m14s) but ~1.9 MB/s per
connection, with 16 workers, nearly all of them tabs on the same shared Chrome window. Two
real bugs, both fixed.

**1. The browser process died.** At lines 256 and 259 of 268:
`Browser.new_context: Target page, context or browser has been closed`. One shared Chrome
window with 16 workers opening and closing tabs in sequence eventually died under memory
pressure — and because nothing ever checked whether the shared browser was still alive,
every later extraction would have stayed broken for the rest of the session. In that run
it happened late enough to cost one file out of 85; on a longer batch it would have
stopped everything.

`open_browser()` now checks `is_connected()` on every call and respawns the instance
itself — same profile, new process — transparently for workers still holding the *old*
handle. That is the delicate part: a worker takes its `browser` once at startup and keeps
it for the whole session, so the fix has to work **underneath** that stale reference
rather than asking the caller to fetch a new one. Tested live: killing the Chrome process
mid-session, the next call detects it (`is_connected() == False`), respawns with a new
PID, rebuilds the windows, and extraction resumes cleanly.

**2. Too many heavy tabs on one window slowed everything down.** Every tab loads Turnstile
plus the full ad stack (mandatory, or `detect-adblock` fires), and with 16 tabs open on the
same window Chrome background-throttles all of them except the foreground one — the page's
own timers (the ~6 s Vue scan, the 15 s countdown) crawl when the tab is not active. The
extraction pipeline slowed down and the download side sat waiting for links.

Hence the bounded pool: pages are pooled and reused file after file instead of a new
window per file, independent of the "Extractors" number in the GUI. The ad-popup sweep
interval also went from 3 s to 1 s — every second a popup stays open is CPU and network
wasted on a shared window.

---

## The per-file speed ceiling is theirs, not ours

31.9 MB/s aggregate is respectable for a free tier: on average ~16–17 streams running in
parallel (aggregate ÷ per-connection average). The parallelism works. The ceiling is
elsewhere: datanodes' own UI states it — **"Download speed: Standard" for Free, "Maximum"
for Premium**. The ~1–3 MB/s per connection is a server-side limit on the free tier.

Faster lanes make the *extraction* pipeline smoother (less time lost opening and closing
windows, no mid-session crash), which raises the aggregate by removing dead time. The only
lever on the ceiling itself is more parallel streams, not a bypass.

---

## The datanodes flow, bug by bug

All verified against the live site:

1. The share URL **302s to `/download`** and sets a `file_code` cookie.
2. The step-1 form is in the HTML from the first byte, but inside a collapsed
   `#downloadReveal` with a `disabled` submit; the Vue scan arms it at ~6 s (the site's own
   failsafe at 8 s). The old code called `form.submit()` at t≈0.
3. The POST **must** contain `method_free=Free Download >>`, or the server re-serves step
   1. A synthetic click does not reliably register as the form's submitter, so the pair is
   materialised as a hidden input.
4. Exactly **one** `POST /download` is allowed. A second one re-runs SecSave and
   invalidates the token step 2 is holding — then download2 fails SecCheck and the server
   answers with HTML. It is written in the comments of their own source. The old
   `poll("free download")` + button-finder re-clicked the step-1 button and burned the
   token.
5. `BLOCKED_DOMS` contained `"challenges.cloudflare"` → Turnstile could never load.
6. `BLOCKED_RES` contained `"stylesheet"` → with no CSS every `getBoundingClientRect()`
   collapses to 0×0, and the button finder, which filters on `size > 0`, found nothing.
7. Blocking ad domains tripped `:detect-adblock="true"`.
8. Capturing the final URL is no longer tied to the `dlproxy` string.
9. Every DOM probe goes through `_dn_eval()`, which survives the step-1 navigation instead
   of crashing with "Execution context was destroyed".
10. Ad popups are tracked per page: on a shared context `context.pages` contains the other
    workers' tabs, and the old sweep would have closed them in their faces.

---

## Operational advice

- With the browser path, keep `Pages` low (1–3). They share one Chrome window either way,
  but less parallelism means fewer Cloudflare challenges.
- Fewer `DL streams` means more bandwidth per file. Start at 8 and go up only if the line
  is clearly idle.
- Keep the datanodes API key set even on a free account: it costs one request to try and
  it turns into the fast path the day the account goes premium.
