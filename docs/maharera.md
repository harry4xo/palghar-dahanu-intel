# MahaRERA crawler

Deterministic Playwright crawler for public MahaRERA project data (`scrapers/maharera/`). No CAPTCHA
is ever bypassed: if one appears, the crawler saves the page and stops.

## Status (7 Oct 2026)

| Part | State |
|---|---|
| Browser session, rate limit, retries, robots.txt, raw-page archive (`client.py`) | Done |
| Search-form flow for a district (`crawl.py`) | Done, based on the live form |
| Listing and detail parsers (`parse.py`) | Done, **generic** (see below) |
| Import into the app (`manage.py import_rera`) | Done and tested |
| A real crawl of Palghar | **Not yet obtained**: the site was too slow during development |

### What we observed

* `maharera.maharashtra.gov.in/...` redirects (301) to `www.maharera.maharashtra.gov.in/...`.
* Plain HTTP clients (curl, requests) got no response at all within 150 s.
* A real headless Chromium gets through, but only intermittently. Over roughly an hour, the search page loaded
  a handful of times, with waits of several minutes. A full Palghar search did not complete in that window.
* No CAPTCHA was seen on the search form.

### Search form (live markup)

1. `GET https://www.maharera.maharashtra.gov.in/projects-search-result`
2. `#edit-project-state`: value `27` = Maharashtra. Selecting it loads `#edit-project-district` by AJAX.
3. `#edit-project-district`: pick the option whose text is `Palghar`.
4. Click `#edit-submit`. Results come back as a normal page, with pager links.

### Parsers are generic until real pages are saved

The results and detail markup was never captured, so the parsers rely on stable things rather than CSS classes:

* **Listing:** each distinct registration number (`P…`, `PR…`) found on the page becomes one row. The row's
  container provides the project name, the visible text, and the first link that looks like a detail page.
* **Detail:** all label/value pairs are collected from tables, `dt/dd` and `Label: value` text, then mapped to
  fields by keyword rules (e.g. a label containing "revised" and "completion" becomes `revised_completion_date`).
  Every pair is also kept in `extra.fields`, so nothing is lost if a rule misses.

**After the first successful crawl:** save one results page and two detail pages into
`tests/fixtures/maharera/`, add tests against them, and tighten the selectors in `parse.py` if needed.
Raw pages are already saved automatically under `data/raw/maharera/`.

## Running it

```bash
python -m playwright install chromium
# 1. listing (resumable: --resume continues from the last page reached)
python -m scrapers.maharera.cli --timeout 300 --retries 8 list --district Palghar --out data/rera/list.jsonl
# 2. details (Palghar/Dahanu/Talasari/Wada first)
python -m scrapers.maharera.cli --timeout 300 details --in data/rera/list.jsonl --out data/rera/projects.jsonl --skip-existing
# 3. into the app (changes since the previous crawl become timeline events)
python manage.py import_rera data/rera/projects.jsonl
```

Global options: `--delay` (seconds between requests, default 3), `--timeout` (seconds per page, default 180),
`--retries`, `-v`.

## Recommendations

* Run from an Indian connection, early morning or late night, as a scheduled job. Use `--resume` so a slow
  night just continues the next day.
* In parallel, file an **RTI request** with MahaRERA for a dataset of Palghar district registrations
  (registration no., promoter, location, dates, status). A one-off official dataset is the most reliable backfill.
* Keep the request rate low (≥ 3 s between pages). The server is clearly under strain.

## Output format (`projects.jsonl`)

One JSON object per line, with these keys (`null` when unknown, never guessed): `rera_no, project_name, promoter,
district, taluka, village, address, pincode, project_type, survey_numbers, land_area_sqm, total_units,
booked_units, registration_date, proposed_completion_date, revised_completion_date, status, latitude,
longitude, detail_url, fetched_at, raw_path, extra`.
