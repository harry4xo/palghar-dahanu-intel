"""Open a public project page on maharerait.maharashtra.gov.in and record its API traffic.

Saves every XHR/fetch request (URL, method, headers, body) and response to
investigation/capture/detail/, then replays each captured API call WITHOUT the browser
(plain httpx, no Authorization header) to classify endpoints as open vs. token-protected.

    python investigation/probe_detail.py [project_id] [--headless]
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "capture" / "detail"
OUT.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    project_id = next((a for a in sys.argv[1:] if a.isdigit()), "10000")
    headless = "--headless" in sys.argv
    calls = []

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("xhr", "fetch") or "/api/" not in req.url:
            return
        rec = {"method": req.method, "url": req.url, "request_headers": req.headers,
               "post_data": req.post_data, "status": resp.status}
        try:
            body = resp.body()
            name = f"{len(calls) + 1:03d}_{req.url.rstrip('/').split('/')[-1].strip()[:60]}.json"
            (OUT / name).write_bytes(body)
            rec["body_file"], rec["body_len"] = name, len(body)
        except Exception as exc:
            rec["body_error"] = str(exc)[:200]
        calls.append(rec)
        auth = "Bearer" if "authorization" in {k.lower() for k in req.headers} else "no-auth"
        log(f"{req.method} {resp.status} {auth} {req.url.split('/api/')[1][:110]}  body={(req.post_data or '')[:90]!r}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=100)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900}, locale="en-IN")
        page = ctx.new_page()
        page.set_default_timeout(180_000)
        page.on("response", on_response)
        url = f"https://maharerait.maharashtra.gov.in/public/project/view/{project_id}"
        t0 = time.time()
        page.goto(url, wait_until="domcontentloaded")
        log(f"loaded {url} in {time.time() - t0:.0f}s")
        try:
            page.wait_for_load_state("networkidle", timeout=120_000)
        except Exception:
            log("network never went idle; continuing")
        page.wait_for_timeout(8000)
        # Scroll through the page so lazily loaded sections fire their requests.
        for _ in range(12):
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(1200)
        page.wait_for_timeout(5000)
        (OUT / "page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(OUT / "page.png"), full_page=True)
        tokens = page.evaluate("sessionStorage.getItem('tokens')")
        log("sessionStorage.tokens present:", bool(tokens),
            "keys:", list(json.loads(tokens).keys()) if tokens else None)
        browser.close()

    # Replay each distinct read call without the browser and without a token.
    log("---- replaying captured API calls with plain httpx (no Authorization) ----")
    seen = set()
    with httpx.Client(timeout=60, headers={"User-Agent": UA, "Content-Type": "application/json"}) as client:
        for c in calls:
            endpoint = c["url"].rstrip("/").split("/")[-1].strip()
            key = (c["url"].strip(), c["post_data"])
            if key in seen or c["method"] != "POST" or not endpoint.startswith("get") or "authenticate" in c["url"]:
                continue
            seen.add(key)
            try:
                r = client.post(c["url"].strip(), content=c["post_data"] or "{}")
                c["replay_no_token"] = r.status_code
                ok = r.status_code == 200 and '"status":"1"' in r.text.replace(" ", "")
                log(f"replay {endpoint}: HTTP {r.status_code} {'OPEN' if ok else 'needs token' if r.status_code == 401 else r.text[:80]}")
            except Exception as exc:
                c["replay_no_token"] = f"error {exc}"
            time.sleep(1)
    json.dump(calls, open(OUT / "api_calls.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    log(f"done: {len(calls)} API calls recorded in {OUT}")


if __name__ == "__main__":
    main()
