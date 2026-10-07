"""Patient investigator: retries until the search page loads, then runs a Palghar search."""
import time, json, sys, traceback
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
OUT = sys.argv[1]
URL = "https://www.maharera.maharashtra.gov.in/projects-search-result"
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=UA, viewport={"width":1366,"height":900}, locale="en-IN")
    ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image","media","font") else r.continue_())
    page = ctx.new_page(); page.set_default_timeout(180000)
    reqs = []
    page.on("request", lambda r: reqs.append((time.strftime("%H:%M:%S"), r.method, r.resource_type, r.url[:250], (r.post_data or "")[:800])) if r.resource_type in ("document","xhr","fetch") else None)
    ok = False
    for attempt in range(40):
        try:
            r = page.goto(URL, wait_until="domcontentloaded", timeout=180000)
            log("goto", r.status)
            if r.status == 200 and page.query_selector("#edit-project-state"): ok = True; break
        except Exception as e: log("err", str(e).splitlines()[0])
        time.sleep(60)
    if not ok: log("GAVE UP"); sys.exit(1)
    open(OUT+"_initial.html","w",encoding="utf-8").write(page.content())
    try:
        for t in range(4):
            try:
                page.select_option("#edit-project-state", "27")
                page.wait_for_function("document.querySelectorAll('#edit-project-district option').length > 1", timeout=180000)
                break
            except Exception as e: log("district wait err", str(e).splitlines()[0]); time.sleep(30)
        opts = page.eval_on_selector_all("#edit-project-district option", "els => els.map(e => [e.value, e.textContent.trim()])")
        json.dump(opts, open(OUT+"_districts.json","w"), indent=0)
        log("districts", len(opts), [o for o in opts if 'palghar' in o[1].lower()])
        pal = [o for o in opts if o[1].strip().lower()=="palghar"][0][0]
        page.select_option("#edit-project-district", pal)
        time.sleep(3)
        with page.expect_navigation(timeout=240000, wait_until="domcontentloaded"):
            page.click("#edit-submit")
        page.wait_for_timeout(3000)
        log("after submit url", page.url)
        open(OUT+"_palghar_p1.html","w",encoding="utf-8").write(page.content())
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        pag = sorted(set(l for l in links if "page=" in l))
        log("pagination links", pag[:20])
        det = sorted(set(l for l in links if "maharerait" in l or "view" in l.lower()))
        log("detail-ish links", det[:20])
        json.dump(links, open(OUT+"_links.json","w"), indent=0)
        if pag:
            time.sleep(5)
            r = page.goto(pag[0], wait_until="domcontentloaded", timeout=240000)
            log("page2", r.status, page.url)
            open(OUT+"_palghar_p2.html","w",encoding="utf-8").write(page.content())
    except Exception:
        traceback.print_exc()
    for r in reqs: print(r)
    json.dump(reqs, open(OUT+"_reqs.json","w"), indent=0)
    b.close()
