# Supported providers

Two providers, two completely different extraction mechanisms. They stopped having
anything in common in the 14.2–14.8 line, which is why the GUI has separate panels
for them and why one of them never opens a browser.

| | `datanodes.to` | `fuckingfast.co` |
|:--|:--|:--|
| Extraction | real Chrome over CDP | plain HTTPS, Chrome TLS fingerprint |
| Browser | yes — one shared window | **none** |
| Captcha | Cloudflare Turnstile | none |
| Cost per link | seconds | ~0.25 s |
| Settings that apply | `Pages`, `Captcha wait`, Chrome path, API key | none |

Both extractors live in `moon_extract.py` and are shared by the GUI (`moon_engine.py`)
and the CLI (`moon_cli.py`).

---

## `fuckingfast.co`

- **Extraction:** `POST /f/{id}/go` over `curl_cffi`, reading the `hx-redirect`
  **response header**.
- **Why not a regex on the HTML:** the landing page is Alpine + htmx and the `/dl/`
  URL is not in the markup at all — it only exists in that header. The pre-14.4
  regex extractor could not find what was never sent.
- **Why not aiohttp:** Cloudflare fingerprints the TLS ClientHello. aiohttp scores as
  a bot and gets `cf-mitigated: challenge` → **403 on every link**, whatever headers
  you send. `curl_cffi` impersonates Chrome's ClientHello and sails through, so
  `curl_cffi>=0.7` is a hard requirement for this provider.
- **Downloads still use aiohttp:** `dl.fuckingfast.co` answers 206 with a correct
  `Content-Range`, so the download engine needs no impersonation.
- **Filename note:** FitGirl-style links carry the name as a URL **fragment**
  (`https://fuckingfast.co/abc123#Game.part01.rar`). The file id is parsed off the
  path, never off the raw string.
- **Dead links fail fast** — 404 or a "not found" body, no retry can recover them.
- **No browser, no captcha, nothing to tune.**

## `datanodes.to`

- **Extraction:** real Chrome (or Edge), spawned by the app with
  `--remote-debugging-port` and attached over CDP.
- **Why not Playwright's Chromium:** Turnstile rejects it. The launcher adds
  automation switches, the binary is not a Google-branded build and the profile is
  empty — the widget answers *Verification failed / Error 600010*. A Chrome we
  spawned ourselves has none of those tells and keeps a **persistent profile**, so
  the `cf_clearance` cookie survives between links and later files are challenged
  less.
- **Why not headless:** measured on Chromium 131, the challenge platform answers 401
  on `/cdn-cgi/challenge-platform/.../pat/...` and `cf-turnstile-response` stays
  empty forever. `headless=False` is deliberate — override with
  `MOON_DN_HEADLESS=1` only if you have wired in a solver.
- **Concurrency:** `Pages` (1–8) is how many tabs may be open **on the one shared
  window**, not how many browsers. Separate contexts were tried in 14.6 and were
  worse: multiple identities from one IP read as a bot farm and Turnstile hard-failed.
- **Exactly one `POST /download` per link.** A second one re-runs SecSave server-side
  and invalidates the token step 2 is holding.
- **Premium API key:** set it in the GUI (or `MOON_DN_API_KEY`) and extraction becomes
  a single JSON GET — no browser, no captcha. Free keys get 403 and fall back to Chrome.
- **Lane pinning:** the CDN pins a session to a lane. A slow lane stays slow;
  re-extracting is what the stall killer does about it.

---

## Chrome is opened on demand

`moon_extract.BrowserGate` launches Playwright and Chrome on the **first datanodes
link** and never before. A batch of nothing but fuckingfast links opens no browser and
does not even boot the Playwright driver; a batch with one datanodes link opens exactly
one shared instance, however many extractors are running.

`python test_no_chrome.py` asserts both, for the engine and for the CLI.

---

## Adding a new provider

1. **Extractor** — write it in `moon_extract.py`, next to the two that exist. Pure
   HTTP if the site allows it; a browser only if it genuinely requires one.
2. **Dispatch** — add the domain to the `urlparse(url).netloc` branch in
   `moon_engine.py` and `moon_cli.py` (grep `datanodes.to` — there are two call sites).
   Ask `BrowserGate.get()` for a browser **inside** the branch, never before it, or
   you reintroduce the launch-for-nothing bug.
3. **Test** — 10+ links including one guaranteed-dead one, so dead-link detection is
   exercised, plus `python test_no_chrome.py`.
