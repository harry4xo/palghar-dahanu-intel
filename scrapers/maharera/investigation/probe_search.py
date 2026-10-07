"""Live investigation of the MahaRERA project search with Playwright.

Records every document / XHR / fetch request and response (method, URL, headers, POST body,
status, response headers, body) to investigation/capture/, then performs a real search through
the UI and opens the first result's detail page.

    python investigation/probe_search.py [--headless] [--name Lodha] [--district Thane]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "capture"
OUT.mkdir(parents=True, exist_ok=True)
SEARCH_URL = "https://maharera.maharashtra.gov.in/projects-search-result"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--name", default="Lodha")
    ap.add_argument("--district", default="Thane")
    args = ap.parse_args()

    records = []
    counter = {"n": 0}

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("document", "xhr", "fetch", "other"):
            return
        counter["n"] += 1
        n = counter["n"]
        rec = {
            "n": n, "t": time.strftime("%H:%M:%S"), "type": req.resource_type, "method": req.method,
            "url": req.url, "request_headers": req.headers, "post_data": req.post_data,
            "status": resp.status, "response_headers": resp.headers,
        }
        try:
            body = resp.body()
            ctype = resp.headers.get("content-type", "")
            ext = "json" if "json" in ctype else "html" if "html" in ctype else "txt"
            path = OUT / f"{n:03d}_{req.method}_{re.sub(r'[^A-Za-z0-9]+', '_', req.url.split('?')[0][-60:])}.{ext}"
            path.write_bytes(body)
            rec["body_file"], rec["body_len"] = path.name, len(body)
        except Exception as exc:
            rec["body_error"] = str(exc)[:200]
        records.append(rec)
        log(f"#{n} {req.method} {resp.status} [{req.resource_type}] {req.url[:150]}"
            + (f"  POST={req.post_data[:150]!r}" if req.post_data else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=150)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900}, locale="en-IN",
                                  timezone_id="Asia/Kolkata")
        ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        page = ctx.new_page()
        page.set_default_timeout(240_000)
        page.on("response", on_response)

        def save(label):
            (OUT / f"page_{label}.html").write_text(page.content(), encoding="utf-8")
            json.dump(records, open(OUT / "network.json", "w", encoding="utf-8"), indent=1, default=str)
            json.dump(ctx.cookies(), open(OUT / f"cookies_{label}.json", "w"), indent=1)

        # 1. open the search page (the server is slow: retry patiently)
        for attempt in range(1, 16):
            try:
                t0 = time.time()
                r = page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=240_000)
                log(f"goto attempt {attempt}: HTTP {r.status} in {time.time() - t0:.0f}s, url={page.url}")
                if r.status == 200 and page.query_selector("form"):
                    break
            except Exception as exc:
                log(f"goto attempt {attempt} failed after {time.time() - t0:.0f}s: {str(exc).splitlines()[0]}")
            time.sleep(30)
        else:
            log("GAVE UP loading search page")
            save("failed")
            return 1
        page.wait_for_timeout(3000)
        save("search_initial")

        # 2. describe every form control on the page
        controls = page.eval_on_selector_all(
            "form input, form select, form textarea, form button",
            """els => els.map(e => ({tag: e.tagName, type: e.type, id: e.id, name: e.name,
                 value: e.type === 'hidden' ? e.value : undefined, placeholder: e.placeholder,
                 options: e.tagName === 'SELECT' ? Array.from(e.options).slice(0, 60).map(o => [o.value, o.textContent.trim()]) : undefined,
                 form: e.form ? (e.form.id || e.form.action) : null}))""")
        json.dump(controls, open(OUT / "form_controls.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        forms = page.eval_on_selector_all("form", "fs => fs.map(f => ({id: f.id, action: f.action, method: f.method}))")
        log("forms:", forms)
        for c in controls:
            if c["tag"] != "SELECT":
                log("  control:", {k: v for k, v in c.items() if v not in (None, "")})
            else:
                log("  select:", c["id"] or c["name"], f"{len(c['options'] or [])} options", (c["options"] or [])[:4])

        # 3. fill the search form
        name_sel = next((f"#{c['id']}" for c in controls if c["tag"] == "INPUT" and c["type"] == "text"
                         and re.search(r"project.?name|title|keyword", (c["id"] or "") + (c["name"] or "") + (c["placeholder"] or ""), re.I)), None)
        log("project-name input:", name_sel)
        if name_sel:
            page.fill(name_sel, args.name)
        state = page.query_selector("#edit-project-state")
        if state:
            page.select_option("#edit-project-state", "27")
            log("selected state 27; waiting for district list")
            page.wait_for_function("document.querySelectorAll('#edit-project-district option').length > 1", timeout=240_000)
        dist_opts = page.eval_on_selector_all("#edit-project-district option", "els => els.map(e => [e.value, e.textContent.trim()])")
        json.dump(dist_opts, open(OUT / "district_options.json", "w", encoding="utf-8"), indent=1)
        match = [v for v, label in dist_opts if label.lower() == args.district.lower()]
        log("district options:", len(dist_opts), "match:", match)
        if match:
            page.select_option("#edit-project-district", match[0])
        page.wait_for_timeout(1500)
        save("search_filled")

        # 4. submit and observe
        log(">>> submitting search")
        mark = counter["n"]
        t0 = time.time()
        try:
            with page.expect_navigation(timeout=300_000, wait_until="domcontentloaded"):
                page.click("#edit-submit")
        except Exception as exc:
            log("no full navigation after submit:", str(exc).splitlines()[0])
        page.wait_for_timeout(5000)
        log(f"after submit ({time.time() - t0:.0f}s): url={page.url}; {counter['n'] - mark} responses since submit")
        save("results")

        # 5. what does the result page contain?
        text = page.inner_text("body")
        reg = sorted(set(re.findall(r"\bP[R]?\d{8,14}\b", text)))
        log(f"registration numbers visible: {len(reg)} {reg[:10]}")
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => [e.textContent.trim().slice(0,60), e.href])")
        json.dump(links, open(OUT / "result_links.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        detail_links = [l for l in links if re.search(r"view|detail|project", l[1], re.I) and "search" not in l[1]]
        log("candidate detail links:", detail_links[:8])
        pager = [l for l in links if "page=" in l[1]]
        log("pager links:", pager[:6])

        # 6. open the first detail page
        if detail_links:
            log(">>> opening detail:", detail_links[0][1])
            mark = counter["n"]
            try:
                with ctx.expect_page(timeout=10_000) as new_page_info:
                    page.click(f"a[href='{detail_links[0][1].replace(page.url.split('/projects')[0], '')}']", timeout=10_000)
                detail = new_page_info.value
            except Exception:
                detail = page
                detail.goto(detail_links[0][1], wait_until="domcontentloaded", timeout=300_000)
            detail.on("response", on_response)
            detail.wait_for_timeout(15_000)
            (OUT / "page_detail.html").write_text(detail.content(), encoding="utf-8")
            log(f"detail url={detail.url}; {counter['n'] - mark} responses")
        save("final")
        if not args.headless:
            page.wait_for_timeout(5000)
        browser.close()
    log("done; capture in", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
