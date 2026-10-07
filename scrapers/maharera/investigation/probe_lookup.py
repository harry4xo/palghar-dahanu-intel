"""Check the registration-number lookup inside a real public browser session.

Opens a public project page (which performs the site's own anonymous `authenticatePublic`
handshake), then calls getPastExpProjectHeaderByRegistrationNo from inside the page with the
session's public token. Also reports the token lifetime (JWT exp claim; the token itself is not
printed) and whether the same token works from plain httpx.
"""
import base64
import json
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "capture" / "lookup"
OUT.mkdir(parents=True, exist_ok=True)
API = "https://maharerait.maharashtra.gov.in/api/maha-rera-public-view-project-registration-service/public/projectregistartion"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def jwt_claims(token):
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:
        return {}


def main():
    reg_nos = sys.argv[1:] or ["P52100008590", "P51700000001"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headless" in reg_nos)
        reg_nos = [r for r in reg_nos if r != "--headless"]
        page = browser.new_page(user_agent=UA)
        page.set_default_timeout(180_000)
        page.goto("https://maharerait.maharashtra.gov.in/public/project/view/10000", wait_until="domcontentloaded")
        page.wait_for_function("sessionStorage.getItem('tokens') !== null", timeout=180_000)
        tokens = json.loads(page.evaluate("sessionStorage.getItem('tokens')"))
        access = tokens["accessToken"]
        claims = jwt_claims(access)
        life = {k: claims.get(k) for k in ("iat", "exp")}
        if life.get("iat") and life.get("exp"):
            life["lifetime_minutes"] = round((life["exp"] - life["iat"]) / 60, 1)
        print("public token obtained; claims (non-secret):", {k: v for k, v in claims.items() if k in ("iat", "exp", "sub", "roles", "authorities")}, life)

        for reg in reg_nos:
            result = page.evaluate(
                """async ([url, body, token]) => {
                    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + token}, body: JSON.stringify(body)});
                    return {status: r.status, text: await r.text()};
                }""",
                [f"{API}/getPastExpProjectHeaderByRegistrationNo", {"projectRegistartionNo": reg}, access],
            )
            (OUT / f"lookup_{reg}.json").write_text(result["text"], encoding="utf-8")
            print(f"in-browser lookup {reg}: HTTP {result['status']} -> {result['text'][:600]}")
            time.sleep(1)
        browser.close()

    # Same token, outside the browser.
    r = httpx.post(f"{API}/getPastExpProjectHeaderByRegistrationNo", json={"projectRegistartionNo": reg_nos[0]},
                   headers={"Authorization": f"Bearer {access}", "User-Agent": UA}, timeout=60)
    print(f"httpx with browser-issued public token: HTTP {r.status_code} -> {r.text[:300]}")
    r = httpx.post(f"{API}/getProjectLandAddressDetails", json={"projectId": "10000"},
                   headers={"Authorization": f"Bearer {access}", "User-Agent": UA}, timeout=60)
    print(f"httpx getProjectLandAddressDetails with token: HTTP {r.status_code} -> {r.text[:300]}")


if __name__ == "__main__":
    main()
