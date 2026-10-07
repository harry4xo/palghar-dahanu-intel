"""Investigate the search form: district options, Palghar search, pagination."""
import time, json, sys
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
OUT = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=UA, viewport={"width":1366,"height":900}, locale="en-IN")
    ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image","media","font") else r.continue_())
    page = ctx.new_page(); page.set_default_timeout(150000)
    reqs = []
    page.on("request", lambda r: reqs.append((r.method, r.resource_type, r.url[:250], (r.post_data or "")[:600])) if r.resource_type in ("document","xhr","fetch") else None)
    for attempt in range(5):
        try:
            r = page.goto("https://www.maharera.maharashtra.gov.in/projects-search-result", wait_until="domcontentloaded")
            print("goto", r.status); 
            if r.status == 200: break
        except Exception as e: print("err", e)
        time.sleep(20)
    page.wait_for_timeout(3000)
    # trigger district load
    page.select_option("#edit-project-state", "27")
    page.wait_for_function("document.querySelectorAll('#edit-project-district option').length > 1", timeout=150000)
    opts = page.eval_on_selector_all("#edit-project-district option", "els => els.map(e => [e.value, e.textContent.trim()])")
    json.dump(opts, open(OUT+"_districts.json","w"), indent=0)
    print("districts", len(opts), [o for o in opts if 'alghar' in o[1].lower() or 'thane' in o[1].lower()])
    pal = [o for o in opts if o[1].strip().lower()=="palghar"][0][0]
    page.select_option("#edit-project-district", pal)
    time.sleep(3)
    page.click("#edit-submit")
    page.wait_for_load_state("domcontentloaded", timeout=150000)
    page.wait_for_timeout(3000)
    print("after submit url", page.url)
    open(OUT+"_palghar_p1.html","w",encoding="utf-8").write(page.content())
    for r in reqs: print(r)
    b.close()
