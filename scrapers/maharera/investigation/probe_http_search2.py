"""Repeat the form POST several times and record where results appear (if at all).

For every attempt: status, size, timing, registration numbers anywhere in the raw response
(including BigPipe JSON payloads), and the size of each BigPipe block.
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent / "capture" / "http_search"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://www.maharera.maharashtra.gov.in/projects-search-result"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
REG = re.compile(r"P[RM]?\d{9,14}")


def blocks(html):
    out = {}
    for blob in re.findall(r'<script type="application/vnd.drupal-ajax"[^>]*>(.*?)</script>', html, re.S):
        blob = blob.strip()
        if not blob.startswith("["):
            continue
        for cmd in json.loads(blob):
            if cmd.get("command") == "insert":
                m = re.search(r"args%5B0%5D=([a-z_]+)", cmd.get("selector", ""))
                out[m.group(1) if m else cmd.get("selector", "")[-50:]] = len(cmd.get("data") or "")
    return out


def get_form(c):
    for attempt in range(12):
        t0 = time.time()
        try:
            r = c.get(URL)
        except httpx.HTTPError as exc:
            print(f"  form GET error after {time.time() - t0:.0f}s: {exc!r}")
            time.sleep(15)
            continue
        print(f"  form GET HTTP {r.status_code} in {time.time() - t0:.0f}s")
        if r.status_code == 200 and "form_build_id" in r.text:
            return re.search(r'id="projects-search-page-form".*?name="form_build_id" value="([^"]+)"', r.text, re.S).group(1)
        time.sleep(15)
    raise SystemExit("form never loaded")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Lodha"
    district = sys.argv[2] if len(sys.argv) > 2 else "517"
    pincode = sys.argv[3] if len(sys.argv) > 3 else ""
    with httpx.Client(headers={"User-Agent": UA}, timeout=300, follow_redirects=True) as c:
        for attempt in range(1, 4):
            build_id = get_form(c)
            data = {"project_type": "0", "project_name": name, "project_location": pincode, "project_completion_date": "",
                    "project_state": "27" if district else "", "project_district": district, "form_build_id": build_id,
                    "form_id": "projects_search_page_form", "op": "Search"}
            t0 = time.time()
            r = c.post(URL, data=data, headers={"Referer": URL})
            regs = sorted(set(REG.findall(r.text)))
            path = OUT / f"post_{name}_{district}_{attempt}.html"
            path.write_text(r.text, encoding="utf-8")
            print(f"attempt {attempt}: HTTP {r.status_code} in {time.time() - t0:.0f}s, {len(r.text)} bytes, "
                  f"redirects={[h.status_code for h in r.history]}, regs={len(regs)} {regs[:6]}, blocks={blocks(r.text)}")
            if regs:
                break
            time.sleep(10)


if __name__ == "__main__":
    main()
