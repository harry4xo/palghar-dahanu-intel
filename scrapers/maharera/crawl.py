"""Crawl flows: search listing for a district, then project detail pages.

Form flow discovered on www.maharera.maharashtra.gov.in/projects-search-result:
  1. select #edit-project-state = "27" (Maharashtra); this loads the district list by AJAX
  2. wait until #edit-project-district has options, select the district by its visible name
  3. click #edit-submit; results come back as a normal page with pager links
The site is very slow to answer automated browsers, so every wait is long.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import parse
from .client import CaptchaEncountered, FetchError, MahaReraClient, utc_iso

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.maharera.maharashtra.gov.in/projects-search-result"
STATE_MAHARASHTRA = "27"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _submit_search(client: MahaReraClient, district: str):
    """Fill in the search form and return (html, url, raw_path) of results page 1."""
    client.fetch(SEARCH_URL, key="list", wait_selector="#edit-project-state")
    page = client._page
    page.select_option("#edit-project-state", STATE_MAHARASHTRA)
    page.wait_for_function("document.querySelectorAll('#edit-project-district option').length > 1",
                           timeout=client.timeout_ms)
    options = page.eval_on_selector_all("#edit-project-district option",
                                        "els => els.map(e => [e.value, e.textContent.trim()])")
    match = [value for value, label in options if label.strip().lower() == district.strip().lower()]
    if not match:
        raise FetchError(f"district {district!r} not in dropdown ({len(options)} options)")
    page.select_option("#edit-project-district", match[0])
    client._throttle()
    with page.expect_navigation(timeout=client.timeout_ms, wait_until="domcontentloaded"):
        page.click("#edit-submit")
    page.wait_for_timeout(2000)
    html = page.content()
    raw = client.save_raw("list", html)
    return html, page.url, raw.as_posix()


def crawl_list(client: MahaReraClient, district: str, out: Path, taluka=None, max_pages=None, resume=False) -> int:
    """Walk every results page for a district and append one JSON row per registration."""
    state_file = out.with_suffix(".state.json")
    seen = {r["rera_no"] for r in _read_jsonl(out)} if resume else set()
    if not resume and out.exists():
        out.unlink()
    state = json.loads(state_file.read_text()) if resume and state_file.exists() else {}
    if state.get("next_url"):
        res = client.fetch(state["next_url"], key="list")
        html, page_url, raw_path = res.html, res.final_url, res.raw_path
    else:
        html, page_url, raw_path = _submit_search(client, district)

    written, pages = 0, 0
    while True:
        pages += 1
        rows = parse.parse_listing(html, page_url)
        log.info("page %d: %d rows (%s)", pages, len(rows), page_url)
        for row in rows:
            if row["rera_no"] in seen:
                continue
            if taluka and taluka.lower() not in row["extra"].get("listing_text", "").lower():
                continue
            seen.add(row["rera_no"])
            row.update({"district": district, "fetched_at": utc_iso(), "raw_path": raw_path})
            _append(out, row)
            written += 1
        nxt = parse.next_page_url(html, page_url)
        state_file.write_text(json.dumps({"next_url": nxt, "pages_done": pages}))
        if not nxt or not rows or (max_pages and pages >= max_pages):
            break
        res = client.fetch(nxt, key="list")
        html, page_url, raw_path = res.html, res.final_url, res.raw_path
    return written


def _priority(row: dict, prefer: list[str]) -> int:
    text = json.dumps(row, ensure_ascii=False).lower()
    return 0 if any(t.lower() in text for t in prefer) else 1


def crawl_details(client: MahaReraClient, inp: Path, out: Path, limit=None, skip_existing=False, prefer_talukas=()) -> int:
    """Fetch each project's detail page and append a full record to ``out``."""
    rows = [r for r in _read_jsonl(inp) if r.get("detail_url")]
    done = {r["rera_no"] for r in _read_jsonl(out)} if skip_existing else set()
    rows.sort(key=lambda r: _priority(r, list(prefer_talukas)))
    written = 0
    for row in rows:
        if limit and written >= limit:
            break
        if row["rera_no"] in done:
            continue
        try:
            res = client.fetch(row["detail_url"], key=row["rera_no"])
        except CaptchaEncountered as exc:
            log.error("stopping: %s (CAPTCHA pages are never bypassed)", exc)
            break
        except FetchError as exc:
            log.warning("skipping %s: %s", row["rera_no"], exc)
            continue
        rec = parse.parse_detail(res.html, res.final_url)
        for key, value in row.items():  # the listing fills gaps but never overrides the detail page
            if key != "extra" and rec.get(key) is None:
                rec[key] = value
        rec["rera_no"] = rec["rera_no"] or row["rera_no"]
        rec["extra"]["listing_text"] = row.get("extra", {}).get("listing_text")
        rec["fetched_at"], rec["raw_path"] = res.fetched_at, res.raw_path
        _append(out, rec)
        written += 1
    return written
