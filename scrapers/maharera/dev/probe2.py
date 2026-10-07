import sys, time, json
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
url = sys.argv[1]; out = sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=UA, viewport={"width":1366,"height":900}, locale="en-IN")
    page = ctx.new_page()
    xhr = []
    def onresp(r):
        if r.request.resource_type in ("xhr","fetch"):
            try: body = r.text()[:3000]
            except Exception as e: body = f"<{e}>"
            xhr.append({"status": r.status, "method": r.request.method, "url": r.url, "post": r.request.post_data, "reqh": dict(r.request.headers), "body": body})
    page.on("response", onresp)
    t=time.time()
    try:
        resp = page.goto(url, timeout=90000, wait_until="networkidle")
        print("status", resp.status if resp else None, "t", round(time.time()-t,1), "final", page.url)
    except Exception as e:
        print("ERR", e)
    page.wait_for_timeout(8000)
    open(out+".html","w",encoding="utf-8").write(page.content())
    json.dump(xhr, open(out+".xhr.json","w",encoding="utf-8"), indent=1)
    for x in xhr: print(x["status"], x["method"], x["url"][:160], (x["post"] or "")[:200])
    page.screenshot(path=out+".png", full_page=True)
    b.close()
