"""Reproduce the www.maharera.maharashtra.gov.in project search with plain httpx (no browser).

1. GET with query parameters (works if the Drupal form accepts GET filters)
2. Otherwise: GET the form, read its one-time form_build_id, POST the form like the browser does
Saves every response under investigation/capture/http_search/.
"""
import re
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).parent / "capture" / "http_search"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://www.maharera.maharashtra.gov.in/projects-search-result"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
REG = re.compile(r"\bP[RM]?\d{9,14}\b")


def report(label, r):
    path = OUT / f"{label}.html"
    path.write_text(r.text, encoding="utf-8")
    regs = sorted(set(REG.findall(r.text)))
    print(f"{label}: HTTP {r.status_code} {len(r.text)} bytes, final URL {r.url}, {len(regs)} registration numbers {regs[:8]}")
    return regs


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Lodha"
    district = sys.argv[2] if len(sys.argv) > 2 else "517"
    with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"}, timeout=240,
                      follow_redirects=True) as c:
        t0 = time.time()
        r = c.get(URL, params={"project_name": name, "project_state": "27", "project_district": district, "op": "Search"})
        print(f"(GET took {time.time() - t0:.0f}s)")
        if report("1_get_query", r):
            return

        for attempt in range(1, 11):
            t0 = time.time()
            try:
                form_page = c.get(URL)
            except httpx.HTTPError as exc:
                print(f"(form GET attempt {attempt} failed after {time.time() - t0:.0f}s: {exc!r})")
                time.sleep(20)
                continue
            print(f"(form GET attempt {attempt}: HTTP {form_page.status_code} in {time.time() - t0:.0f}s)")
            if form_page.status_code == 200 and "projects-search-page-form" in form_page.text:
                break
            time.sleep(20)
        report("2_form_page", form_page)
        form = re.search(r'<form[^>]*id="projects-search-page-form".*?</form>', form_page.text, re.S).group(0)
        build_id = re.search(r'name="form_build_id" value="([^"]+)"', form).group(1)
        data = {"project_type": "0", "project_name": name, "project_location": "", "project_completion_date": "",
                "project_state": "27", "project_district": district, "form_build_id": build_id,
                "form_id": "projects_search_page_form", "op": "Search"}
        print("POST body:", {k: (v if k != "form_build_id" else v[:12] + "…") for k, v in data.items()})
        t0 = time.time()
        r = c.post(URL, data=data, headers={"Referer": URL, "Origin": "https://www.maharera.maharashtra.gov.in"})
        print(f"(POST took {time.time() - t0:.0f}s; redirect chain: {[str(h.url) for h in r.history]})")
        report("3_form_post", r)
        print("cookies held:", list(c.cookies.keys()))


if __name__ == "__main__":
    main()
