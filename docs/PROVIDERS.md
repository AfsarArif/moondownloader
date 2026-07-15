# Supported providers

Moon Downloader currently extracts direct links from two providers.
Each has a different extraction strategy tuned to how the site delivers
files.

## `datanodes.to`

- **Extraction:** full browser automation (Playwright + Chromium).
- **Why:** the direct-link form uses JS-generated tokens, cannot be
  scraped with a plain HTTP request.
- **Notes:**
  - Ad-overlay dismissal is handled automatically.
  - CDN pins sessions to a specific "lane" — slow lanes cannot be
    recovered by re-extracting.
  - Recommended concurrency: **16 browsers** for 40+ file sessions,
    **32 browsers** for 200+ files.

## `fuckingfast.co`

- **Extraction:** pure regex on the initial HTML response.
- **Why:** the direct-download URL is baked into a `window.open` call
  in the source of the intermediate page — no browser needed.
- **Notes:**
  - Much faster to extract than `datanodes.to` (~50–100 ms vs a full
    page load).
  - Dead links fail instantly (the server returns a distinctive HTML
    marker).
  - No captcha or ad flow.

## Adding a new provider

If you want to add support for another host, follow the same pattern:

1. **Detection:** add the domain to the URL-router that dispatches
   between providers (grep `datanodes` in `gen_1.py`).
2. **Extractor:** write either a regex-based extractor (like
   `fuckingfast.co`) or a Playwright flow (like `datanodes.to`).
3. **Mirror in `gen_cli.py`:** as `CONTRIBUTING.md` requires — shared
   logic goes in both files.
4. **Test:** at least 10+ links, including one guaranteed-dead one, to
   confirm dead-link detection kicks in.
