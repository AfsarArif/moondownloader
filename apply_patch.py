"""Apply the extraction rebuild to gen_1.py and gen_cli.py by exact-string surgery.

Idempotent against the PRISTINE v14.1 sources: always run this against a fresh
copy of the original gen_1.py / gen_cli.py (build_release.sh does that). Running
it twice on the same pristine copy is a no-op the second time; it is not designed
to be re-run against an already-patched (v14.2-14.5) file.
"""
import pathlib, sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/home/user/md")

def import_shim(need_sys_import: bool) -> str:
    sys_line = ("import sys                                       "
                "# noqa: E402  (gen_1.py has no top-level `import sys`)\n"
                if need_sys_import else "")
    return f'''# ── EXTRACTION ────────────────────────────────────────────────────────────────
# Both host front-ends changed in 2026; the extraction layer now lives in
# moon_extract.py so gen_1.py and gen_cli.py share one implementation.
{sys_line}from moon_extract import (                       # noqa: E402
    extract_fuckingfast,
    extract_datanodes,
    open_browser,
    close_browser,
    shutdown_chrome,
    close_ff_session,
    referer_for,
    HAVE_CURL_CFFI,
    DN_API_KEY,
    DN_LANES,
)
import moon_extract as _moon_extract            # noqa: E402

# The degraded no-curl_cffi fuckingfast path, and the lane pool's per-context user
# agent, both reuse this module's own HTTP/UA plumbing.
_moon_extract._sess = _sess
_moon_extract.USER_AGENTS = USER_AGENTS

if DN_API_KEY:
    print("datanodes: MOON_DN_API_KEY set - trying the API first "
          "(direct_link requires a premium account; free keys get 403 "
          "and fall back to the browser)")

if not HAVE_CURL_CFFI:
    print("WARNING: curl_cffi is not installed. fuckingfast.co will fail with "
          "Cloudflare 403 on every link \\u2014 run: pip install curl_cffi",
          file=sys.stderr)

print(f"datanodes: up to {{DN_LANES}} persistent browser window(s) "
      "(set MOON_DN_LANES to change)")

'''

# Final dispatcher shape for the GUI (gen_1.py). All context/lane/crash-recovery
# lifecycle now lives inside extract_datanodes() itself — the dispatcher just
# calls it with the long-lived `browser` handle and never touches a context.
GUI_DISPATCH_OLD = '''                    elif "datanodes.to" in parsed.netloc:
                        # Fresh context per extraction = fresh cookies = fresh CDN session
                        ctx = await browser.new_context(
                            user_agent=USER_AGENTS[wid % len(USER_AGENTS)],
                            viewport={"width": 1280, "height": 800}, locale="en-US",
                            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
                        try:
                            proxy_url, cookies = await extract_datanodes(ctx, url)
                        finally:
                            try: await ctx.close()
                            except Exception: pass'''
GUI_DISPATCH_NEW = '''                    elif "datanodes.to" in parsed.netloc:
                        # API key set -> single JSON GET, no browser, no captcha.
                        # Otherwise extract_datanodes() re-validates the shared
                        # Chrome (respawning it if it died) and checks out one
                        # window from the persistent lane pool internally.
                        proxy_url, cookies = await extract_datanodes(browser, url)'''

CLI_DISPATCH_OLD = '''                elif "datanodes.to" in parsed.netloc:
                    ctx = await browser.new_context(
                        user_agent=USER_AGENTS[wid % len(USER_AGENTS)],
                        viewport={"width": 1280, "height": 800}, locale="en-US",
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"})
                    try:
                        proxy_url, cookies = await extract_datanodes(ctx, url)
                    finally:
                        try: await ctx.close()
                        except Exception: pass'''
CLI_DISPATCH_NEW = '''                elif "datanodes.to" in parsed.netloc:
                    # API key set -> single JSON GET, no browser, no captcha.
                    # Otherwise extract_datanodes() re-validates the shared
                    # Chrome (respawning it if it died) and checks out one
                    # window from the persistent lane pool internally.
                    proxy_url, cookies = await extract_datanodes(browser, url)'''

LAUNCH_OLD_GUI = '''                b = await p.chromium.launch(headless=True, args=LAUNCH_ARGS)
                try:
                    await self._browser_worker(
                        b, wid, q, dl_sem, all_done, mark_done,
                        kill_counts, all_tasks, tasks_lock,
                        output_links, failed_urls, dest_folder, mode, max_retries, telem)
                finally:
                    try: await b.close()
                    except Exception: pass'''
LAUNCH_NEW_GUI = '''                b, _shared = await open_browser(p, LAUNCH_ARGS)
                try:
                    await self._browser_worker(
                        b, wid, q, dl_sem, all_done, mark_done,
                        kill_counts, all_tasks, tasks_lock,
                        output_links, failed_urls, dest_folder, mode, max_retries, telem)
                finally:
                    await close_browser(b, _shared)'''

LAUNCH_OLD_CLI = '''            b = await p.chromium.launch(headless=True, args=LAUNCH_ARGS)
            try:
                await browser_worker(b, wid)
            finally:
                try: await b.close()
                except Exception: pass'''
LAUNCH_NEW_CLI = '''            b, _shared = await open_browser(p, LAUNCH_ARGS)
            try:
                await browser_worker(b, wid)
            finally:
                await close_browser(b, _shared)'''

# ── GUI: settings split per host, matching how each method actually works now ──
GUI_VARS_OLD = '''        self._retry_var   = tk.IntVar(value=3)'''
GUI_VARS_NEW = '''        self._retry_var   = tk.IntVar(value=3)
        # datanodes-only knobs — previously env vars that needed setx + a restart
        self._dn_lanes_var   = tk.IntVar(value=DN_LANES)
        self._dn_capwait_var = tk.IntVar(value=int(_moon_extract.DN_MANUAL_CAPTCHA_TIMEOUT))
        self._dn_chrome_var  = tk.StringVar(value=_moon_extract.CHROME_PATH
                                            or (_moon_extract.find_chrome() or ""))
        self._dn_apikey_var  = tk.StringVar(value=DN_API_KEY)'''

GUI_SETTINGS_OLD = '''        # Settings — compact
        self._label(left, "SETTINGS", top=12)
        sf = tk.Frame(left, bg=BG3, highlightbackground=BORDER, highlightthickness=1)
        sf.pack(fill="x")
        sinn = tk.Frame(sf, bg=BG3); sinn.pack(fill="x", padx=10, pady=8)

        rows = [
            ("Browsers", self._workers_var, 8, 32, 16, "rec. 16"),
            ("DL streams", self._dl_conc_var, 16, 64, 48, "rec. 48"),
            ("Retries", self._retry_var, 0, 5, 3, ""),
        ]
        for label, var, frm, to, opt, hint in rows:
            row = tk.Frame(sinn, bg=BG3); row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=("Courier",8), fg=TEXT2,
                     bg=BG3, width=10, anchor="w").pack(side="left")
            tk.Scale(row, from_=frm, to=to, orient="horizontal", variable=var,
                     font=("Courier",7), fg=TEXT3, bg=BG3, troughcolor=SURFACE,
                     activebackground=ACC, highlightthickness=0, bd=0,
                     sliderrelief="flat", showvalue=True).pack(side="left", fill="x", expand=True)
            if hint:
                tk.Label(row, text=hint, font=("Courier",7), fg=TEXT3,
                         bg=BG3).pack(side="right")'''

GUI_SETTINGS_NEW = '''        # Settings — split per host, because the two methods no longer share a
        # mechanism: fuckingfast is pure HTTP (no browser, no captcha), datanodes
        # is Chrome + Turnstile. One "Browsers" slider could not describe both.
        def _panel(title, top=10):
            self._label(left, title, top=top)
            box = tk.Frame(left, bg=BG3, highlightbackground=BORDER, highlightthickness=1)
            box.pack(fill="x")
            inner = tk.Frame(box, bg=BG3); inner.pack(fill="x", padx=10, pady=8)
            return inner

        def _slider(parent, label, var, frm, to, hint):
            row = tk.Frame(parent, bg=BG3); row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=("Courier",8), fg=TEXT2,
                     bg=BG3, width=11, anchor="w").pack(side="left")
            if hint:
                tk.Label(row, text=hint, font=("Courier",7), fg=TEXT3,
                         bg=BG3).pack(side="right")
            tk.Scale(row, from_=frm, to=to, orient="horizontal", variable=var,
                     font=("Courier",7), fg=TEXT3, bg=BG3, troughcolor=SURFACE,
                     activebackground=ACC, highlightthickness=0, bd=0,
                     sliderrelief="flat", showvalue=True).pack(side="left", fill="x", expand=True)

        def _entry(parent, label, var, browse=None, show=None):
            row = tk.Frame(parent, bg=BG3); row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=("Courier",8), fg=TEXT2,
                     bg=BG3, width=11, anchor="w").pack(side="left")
            if browse:
                tk.Button(row, text="\\u2026", command=browse, font=("Courier",8),
                          bg=SURFACE, fg=TEXT2, activebackground=BORDER,
                          relief="flat", bd=0, cursor="hand2", padx=7).pack(side="right")
            tk.Entry(row, textvariable=var, font=("Courier",8), bg=SURFACE,
                     fg=TEXT2, insertbackground=ACC, relief="flat", bd=4,
                     show=show, highlightthickness=0).pack(side="left", fill="x", expand=True)

        common = _panel("SETTINGS  \\u00b7  COMMON", top=12)
        _slider(common, "Extractors", self._workers_var, 2, 32, "rec. 16")
        _slider(common, "DL streams", self._dl_conc_var, 2, 48, "rec. 8")
        _slider(common, "Retries",    self._retry_var,   0, 5,  "")
        tk.Label(common, text="fewer streams = more bandwidth per file; the pipe is the ceiling",
                 font=("Courier",7), fg=TEXT3, bg=BG3, anchor="w").pack(fill="x", pady=(3,0))

        ff = _panel("FUCKINGFAST  \\u00b7  HTTP, NO BROWSER")
        tk.Label(ff, text=("\\u2713  curl_cffi active \\u2014 hx-redirect, ~0.25s per link"
                           if HAVE_CURL_CFFI else
                           "\\u2717  curl_cffi MISSING \\u2014 pip install curl_cffi"),
                 font=("Courier",7), fg=(ACC2 if HAVE_CURL_CFFI else "#ff5555"),
                 bg=BG3, anchor="w").pack(fill="x")
        tk.Label(ff, text="nothing to tune: opens no browser, has no captcha",
                 font=("Courier",7), fg=TEXT3, bg=BG3, anchor="w").pack(fill="x")

        dn = _panel("DATANODES  \\u00b7  CHROME + TURNSTILE")
        _slider(dn, "Pages", self._dn_lanes_var, 1, 8, "rec. 3")
        _slider(dn, "Captcha s", self._dn_capwait_var, 30, 600, "manual wait")
        _entry(dn, "Chrome", self._dn_chrome_var, browse=self._pick_chrome)
        _entry(dn, "API key", self._dn_apikey_var, show="\\u2022")
        tk.Label(dn, text="pages = tabs on one window/identity, not separate windows",
                 font=("Courier",7), fg=TEXT3, bg=BG3, anchor="w").pack(fill="x", pady=(3,0))'''

GUI_PICKER_OLD = '''    def _pick_folder(self):
        d = filedialog.askdirectory()
        if d: self._out_folder.set(d)'''
GUI_PICKER_NEW = '''    def _pick_folder(self):
        d = filedialog.askdirectory()
        if d: self._out_folder.set(d)

    def _pick_chrome(self):
        f = filedialog.askopenfilename(
            title="Select chrome.exe / msedge.exe",
            filetypes=[("Chrome / Edge", "chrome.exe msedge.exe"), ("All files", "*.*")])
        if f: self._dn_chrome_var.set(f)'''

GUI_RUNSTART_OLD = '''        n, d, r = self._workers_var.get(), self._dl_conc_var.get(), self._retry_var.get()'''
GUI_RUNSTART_NEW = '''        n, d, r = self._workers_var.get(), self._dl_conc_var.get(), self._retry_var.get()

        # What is on screen is what runs: push the per-host settings into the
        # extraction layer before any worker thread starts. Previously each of
        # these was read once at import time, so the only way to change them was
        # setx plus a restart.
        eff = _moon_extract.configure(
            lanes=self._dn_lanes_var.get(),
            chrome_path=self._dn_chrome_var.get(),
            api_key=self._dn_apikey_var.get(),
            captcha_wait=self._dn_capwait_var.get())'''

GUI_LOG_OLD = ('        self.log(f"\u25b6  {len(urls)} links  \u00b7  {n} browsers  \u00b7  '
               '{d} streams  \u00b7  {r} retries  \u00b7  {VERSION}", "info")')
GUI_LOG_NEW = ('        self.log(f"\u25b6  {len(urls)} links  \u00b7  {n} extractors  \u00b7  '
               '{d} streams  \u00b7  {r} retries  \u00b7  {VERSION}", "info")\n'
               '        self.log(f"   fuckingfast: direct HTTP"\n'
               '                 f"{\'\' if eff[\'curl_cffi\'] else \'  \u2717 curl_cffi MISSING\'}"\n'
               '                 f"   \u00b7   datanodes: {eff[\'lanes\']} pages, '
               'captcha {eff[\'captcha_wait\']}s"\n'
               '                 f"{\', API key\' if eff[\'api_key\'] else \'\'}", "dim")\n'
               '        self.log(f"   chrome: {eff[\'chrome\']}", "dim")')


def cut(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    if start_marker not in text:
        print(f"  - {label}: start marker absent (already patched?)")
        return text
    i = text.index(start_marker)
    j = text.index(end_marker, i)
    print(f"  + {label}: removed {text[i:j].count(chr(10))} lines")
    return text[:i] + replacement + text[j:]


def sub(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        print(f"  - {label}: not found (already patched?)")
        return text
    print(f"  + {label}")
    return text.replace(old, new, 1)


def patch(path: pathlib.Path, is_gui: bool) -> None:
    print(f"\n{path.name}")
    t = path.read_text(encoding="utf-8")

    # 1. drop the old route/JS constants (used only by the old extractors)
    t = cut(t, 'BLOCKED_RES  = {"image"', "_WIN_INVALID = re.compile", "", "old JS constants")

    # 2. swap the whole extraction section for the shared module
    end = "# ── DOWNLOAD ─" if "# ── DOWNLOAD ─" in t else "class _StallKill"
    t = cut(t, "# ── EXTRACTION ─" if "# ── EXTRACTION ─" in t else "async def extract_fuckingfast",
            end, import_shim(need_sys_import=is_gui), "extraction section")

    # 3. referer keyed on the parsed host instead of a substring test
    t = sub(t,
            '        ref = "https://fuckingfast.co/" if "fuckingfast" in proxy_url else "https://datanodes.to/"',
            "        ref = referer_for(proxy_url)",
            "referer_for()")

    # 4. real Chrome over CDP instead of Playwright's bundled Chromium, with
    #    crash-respawn baked into open_browser()/close_browser()
    if is_gui:
        t = sub(t, LAUNCH_OLD_GUI, LAUNCH_NEW_GUI, "open_browser (gui)")
        t = sub(t, GUI_DISPATCH_OLD, GUI_DISPATCH_NEW, "datanodes dispatch (gui)")
    else:
        t = sub(t, LAUNCH_OLD_CLI, LAUNCH_NEW_CLI, "open_browser (cli)")
        t = sub(t, CLI_DISPATCH_OLD, CLI_DISPATCH_NEW, "datanodes dispatch (cli)")

    # 5. close the impersonating session + shared Chrome, at whatever indentation
    #    the call site actually uses
    if "await close_ff_session()" in t:
        print("  - close_ff_session()/shutdown_chrome(): already present")
    else:
        done = False
        out = []
        for line in t.split("\n"):
            out.append(line)
            if not done and line.strip() == "await _close_sess()":
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f"{indent}await close_ff_session()")
                out.append(f"{indent}await shutdown_chrome()")
                done = True
        t = "\n".join(out)
        print(f"  {'+' if done else '-'} close_ff_session() / shutdown_chrome()")

    # 6. GUI only: settings panel split per host + runtime wiring, so the values
    #    on screen are the ones that actually run
    if is_gui:
        t = sub(t, 'VERSION = "v14.1"', 'VERSION = "v14.8"', "version string")
        t = sub(t, GUI_VARS_OLD, GUI_VARS_NEW, "settings vars")
        t = sub(t, GUI_SETTINGS_OLD, GUI_SETTINGS_NEW, "per-host settings panel")
        t = sub(t, GUI_PICKER_OLD, GUI_PICKER_NEW, "chrome file picker")
        t = sub(t, GUI_RUNSTART_OLD, GUI_RUNSTART_NEW, "configure() at run start")
        t = sub(t, GUI_LOG_OLD, GUI_LOG_NEW, "per-host run banner")

    path.write_text(t, encoding="utf-8")


patch(ROOT / "gen_1.py", is_gui=True)
patch(ROOT / "gen_cli.py", is_gui=False)

req = ROOT / "requirements.txt"
r = req.read_text(encoding="utf-8")
if "curl_cffi" not in r:
    r = r.rstrip("\n") + "\ncurl_cffi>=0.7      # Chrome TLS fingerprint — mandatory for fuckingfast.co\n"
    req.write_text(r, encoding="utf-8")
    print("\nrequirements.txt: added curl_cffi")
print("\ndone")
