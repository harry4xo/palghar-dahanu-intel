import sys, time, json
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
url = sys.argv[1]
out = sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=UA, viewport={"width":1366,"height":900}, locale="en-IN")
    page = ctx.new_page()
    log = []
    page.on("response", lambda r: log.append((r.status, r.request.method, r.request.resource_type, r.url[:200])))
    t=time.time()
    try:
        resp = page.goto(url, timeout=90000, wait_until="domcontentloaded")
        print("status", resp.status if resp else None, "t", time.time()-t, "final", page.url)
        page.wait_for_timeout(5000)
    except Exception as e:
        print("ERR", e)
    open(out,"w",encoding="utf-8").write(page.content())
    for l in log:
        if l[2] not in ("image","font","stylesheet"): print(l)
    b.close()
