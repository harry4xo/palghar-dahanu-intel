# MahaRERA public website: how it works internally

Findings from a live investigation with Playwright (headed Chromium) and plain `httpx`, run from
Panvel, Maharashtra on **7 October 2026**. Everything below was observed against the live site.
Nothing is guessed, and anything not verified is marked as such.

> **TL;DR**
>
> * MahaRERA is **two separate systems**:
>   1. `www.maharera.maharashtra.gov.in`: a Drupal information site that hosts the **project search** form.
>   2. `maharerait.maharashtra.gov.in`: an Angular single-page app ("MahaRERA IT") that shows **project details**
>      and is backed by **JSON REST APIs**.
> * **Project details have a real JSON API.** Some endpoints answer plain HTTP POSTs with no auth (verified with
>   `httpx`). The rest need a short-lived *public* bearer token, which the site issues automatically to every
>   anonymous visitor.
> * **RERA number → project** works through a JSON endpoint as well (token required). It returns the internal
>   `projectId`, the full address with district and pincode, land area, total cost and the completion date.
> * **Search by name, district or pincode** only exists on the Drupal site, as a server-rendered form POST.
>   During the investigation the Drupal site returned **HTTP 504 on most requests** (backend timeouts), and
>   accepted searches never rendered any result rows. **A working search was not demonstrated.**
> * No CAPTCHA, Cloudflare or other WAF challenge was seen anywhere.

---

## 1. Site map

| Host | Technology | Purpose | Behaviour on 7 Oct 2026 |
|---|---|---|---|
| `maharera.maharashtra.gov.in` | Apache | 301 redirect to `www.` | Fast |
| `www.maharera.maharashtra.gov.in` | Drupal 9/10 + BigPipe, jQuery | Information site, **project search form** | **504 Gateway Timeout** after 70–100 s on most requests; occasionally 200 in 1–12 s |
| `maharerait.maharashtra.gov.in` | single-spa + Angular micro-frontends, Spring Boot APIs behind `/api/` | Online services, **public project view** | 200 in about 1–7 s; reliable |

The VPN was ruled out as the cause: the exit IP was in Panvel, Maharashtra, on an Indian ISP. The 504s come
from MahaRERA's own gateway timing out on its Drupal backend. `maharerait` responded normally over the same
connection at the same time.

---

## 2. Project details: `maharerait.maharashtra.gov.in` JSON API

### 2.1 How it was found

* The home page HTML has a SystemJS import map listing one micro-frontend per area
  (`/publicpage/main.js`, `/projectpage/main.js`, `/promoterpage/main.js`, …).
* `publicpage/main.js` (about 1 MB) defines the API base URLs:

```js
apiUrl:          "https://maharerait.maharashtra.gov.in/api/maha-rera-public-view-project-registration-service/public/projectregistartion"
originalApiUrl:  "https://maharerait.maharashtra.gov.in/api/maha-rera-project-registration-service/projectregistartion"
loginApiUrl:     "https://maharerait.maharashtra.gov.in/api/maha-rera-login-service/login"
```

  *(`projectregistartion` is MahaRERA's spelling.)*
* The public project page route is **`/public/project/view/{projectId}`**, where `projectId` is an internal
  sequential integer. Example: `P51700000001` has `projectId` 4, and `P52100008590` has `projectId` 10000.
* Opening `https://maharerait.maharashtra.gov.in/public/project/view/10000` in Playwright and recording all
  XHR/fetch traffic captured **78 API calls**.

### 2.2 Request format (all endpoints)

```
POST {apiUrl}/{endpoint}
Content-Type: application/json
Authorization: Bearer <public accessToken>      ← only for protected endpoints
{"projectId": "10000"}                           ← body varies per endpoint (table below)
```

Responses always have this envelope:

```json
{"message": "SUCCESS", "status": "1", "responseObject": { ... }}
{"message": "No records found", "status": "NO_RECORDS_FOUND" | "0", "responseObject": null}
```

Protected endpoints called without a token return:

```json
{"timestamp":"…","status":401,"error":"Unauthorized","message":"","path":"/maha-rera-public-view-project-registration-service/public/projectregistartion/…"}
```

Cookies, CSRF tokens, Origin and Referer headers are **not** required. A JSON body plus, where needed, the
bearer token is enough.

### 2.3 Anonymous "public" token

When the public view page loads, the Angular app calls

```
POST https://maharerait.maharashtra.gov.in/api/maha-rera-login-service/login/authenticatePublic
{"userName": "<CryptoJS AES ciphertext>", "password": "<CryptoJS AES ciphertext>"}
→ {"status":"1","responseObject":{"accessToken":"<JWT>","refreshToken":"<JWT>"}}
```

* The `userName` and `password` are built into the JavaScript bundle and encrypted in the browser.
  They identify a shared public account, not a person.
* The response is stored in `sessionStorage["tokens"]`. An HTTP interceptor then adds
  `Authorization: Bearer <accessToken>` to every API call; 76 of the 78 captured calls carried it.
* The JWT has `iat`/`exp` claims 6,000 s apart, so **the token is valid for 100 minutes**.
* The token works from any HTTP client once issued. Verified with `httpx`: protected endpoints return 200
  with the browser-issued token.

**How to use this responsibly.** Let a real browser (Playwright) load any `/public/project/view/{id}` page,
read `sessionStorage.tokens`, and reuse that token until it expires (or a 401 comes back). Then load a page
again to get a fresh one. This is the site's own anonymous-visitor flow. Do **not** extract the built-in
credentials or reimplement the encryption to mint tokens without a browser; that works around their
authentication scheme. The encrypted values are deliberately not reproduced here.

### 2.4 Endpoint reference (verified live, `projectId` 10000)

**Open: plain HTTP POST, no token (verified with `httpx`)**

| Endpoint | Body | What it returns |
|---|---|---|
| `getProjectGeneralDetailsByProjectId` | `{"projectId":"10000"}` | Name, `projectRegistartionNo`, `reraRegistrationDate`, `projectProposeComplitionDate`, original completion date, type, status names, acknowledgement no., certificate dates, units sold/total, `isProjectLapsed`, `userProfileId` (promoter) |
| `getProjectCurrentStatus` | `{"projectId":"10000"}` | `coreStatus.statusName` (e.g. *Completed*), `isDeregistered`, `isAbeyance` |
| `getBuildingWingUnitSummary` | `{"projectId":"10000"}` | Buildings/wings, floors proposed and sanctioned |
| `getBuildingFloorSummaryByFloorType` | `{"projectId":"10000"}` | Floor summary (no records for migrated projects) |
| `getMigratedBuildingDetails` | `{"projectId":"10000"}` | Building details for projects migrated from the old portal |
| `getProjectPreviousExtensionDetails` | `{"projectId":"10000"}` | Extension history |
| `getComplaintDetailsByProjectId` | `{"projectId":"10000"}` | Complaints against the project |
| `…/maha-rera-complaint-management-service/complaint/getComplaintByProjectId` | `{"projectId":"10000"}` | Complaints (other service) |
| `…/maha-rera-mdm-service/mdm/getGlobalParamByparamType`, `getDocumentType`, `getBankList` | various | Lookup lists |

**Protected: needs the public bearer token**

| Endpoint | Body | What it returns |
|---|---|---|
| `getPastExpProjectHeaderByRegistrationNo` | `{"projectRegistartionNo":"P51700000001"}` | **RERA number → project**: `projectId`, name, full address string (with taluka, district, pincode), `landArea`, `numberOfBuildingsPlots`, `totalCost`, `originalProposedCompletionDate`, current status |
| `getProjectLandAddressDetails` | `{"projectId":"10000"}` | Site address: `addressLine`, `pinCode`, `districtName`, `talukaName`, `villageName`, boundaries |
| `getProjectAndAssociatedPromoterDetails` | `{"projectId":"10000"}` | Combined project + legal land + promoter record |
| `fetchPromoterGeneralDetails` | `{"userProfileId":"104784","projectId":"10000"}` | Promoter details |
| `getPromoterAddressDetails` | `{"userProfileId":null,"projectId":"10000"}` | Promoter office address |
| `getProjectLitigationDetails` | `{"projectId":"10000"}` | Litigation |
| `getProjectLandOwnerDetails`, `getLegalInvestorDetails` | `{"projectId":"10000"}` | Landowners / investors |
| `getProjectProfessionalByType` | `{"projectId":"10000"," professionalTypeName ":null}` | Architects, engineers, CAs (note the spaces in the key, exactly as the app sends it) |
| `getProjectLegalGeoTaggingDetailByProjectId` | `{"projectId":"10000"}` | Geo-tagging (coordinates, if entered) |
| `getUploadedDocuments` | `{"projectId":"10000","documentSectionName":"Project_Technical","documentTypeId":…}` | Document list |
| `getBuildingWingsCostEstimation`, `getBuildingWingsActivityDetails`, `getProjectGeneralPlanSummary`, `getAgentByProjectId`, … | `{"projectId":"10000"}` | Remaining sections of the public page |

The bundle defines **331** endpoints on this base, including `save…` and `delete…` write operations. Only call
the read-only ones that the public page itself calls (the list above).

### 2.5 Real captured responses (trimmed)

`getProjectGeneralDetailsByProjectId`, `{"projectId":10000}`, plain `curl`, no token, HTTP 200:

```json
{"message":"SUCCESS","status":"1","responseObject":{
  "projectId":10000,"projectName":"GOVIND VILAS","projectRegistartionNo":"P52100008590",
  "reraRegistrationDate":"2017-08-19","projectProposeComplitionDate":"2017-12-31",
  "originalProjectProposeCompletionDate":"2017-12-31","projectTypeName":"Others",
  "projectStatusName":"Ongoing","projectCurrentStatus":"Certificate Signed",
  "acknowledgementNumber":"REA52100018338","projectApplicationDate":"2017-07-31",
  "registrationCertificateGenerationDate":"2017-11-13","isProjectLapsed":0,"isMigrated":1,
  "userProfileId":104784, "…": "…"}}
```

`getPastExpProjectHeaderByRegistrationNo`, `{"projectRegistartionNo":"P51700000001"}`, with the public token, HTTP 200:

```json
{"message":"SUCCESS","status":"1","responseObject":{
  "projectId":4,"mahaReraRegistrationNumber":"P51700000001","projectName":"MAYFAIR VISHWARAJA",
  "address":"S No 204/1A 226/1/2 226/2A, Ganesh Mandir Road, Near Ganesh Mandir, Titwala, Kalyan, Thane, 421605, MAHARASHTRA",
  "landArea":5847.98,"numberOfBuildingsPlots":4,"totalCost":529261892.0,
  "originalProposedCompletionDate":"2018-06-30","projectStatusId":"Certificate Signed", "…": "…"}}
```

`getProjectLandAddressDetails`, `{"projectId":"10000"}`, with the token, HTTP 200:

```json
{"responseObject":{"addressLine":"CTS NO 1391","pinCode":"411002","stateName":"MAHARASHTRA",
  "districtName":"Pune","talukaName":"Pune City","villageName":"Pune (M Corp.)", "…": "…"}}
```

`getProjectCurrentStatus`, no token:

```json
{"responseObject":{"coreStatus":{"statusId":2,"statusName":"Completed","isDeregistered":0,"isAbeyance":0},"projectId":10000}}
```

---

## 3. Project search: `www.maharera.maharashtra.gov.in` (Drupal)

### 3.1 The form (live markup)

`GET https://www.maharera.maharashtra.gov.in/projects-search-result` renders
`<form id="projects-search-page-form" method="post" action="/projects-search-result">`. Its fields:

| Field | Meaning |
|---|---|
| `project_type` | `0` = Registered Projects, `1` = Revoked Projects |
| `project_name` | free text: project name **or** MahaRERA registration number |
| `project_location` | pincode |
| `project_completion_date` | date picker |
| `project_state` | `27` = Maharashtra (options are loaded by JavaScript) |
| `project_district` | numeric code (see 3.2), loaded by AJAX after a state is chosen |
| `form_build_id` | one-time Drupal form token (`form-…`) taken from the rendered page |
| `form_id` | `projects_search_page_form` |
| `op` | `Search` |

* The page also has a second, sidebar search form (`projects-search-page-left-form`). The page therefore has two
  submit buttons (`#edit-submit`, `#edit-submit--2`), and a plain Playwright `click("#edit-submit")` timed out.
  Scope selectors to `#projects-search-page-form`.
* No CAPTCHA anywhere on the form.
* Content blocks are delivered with **Drupal BigPipe**: placeholders in the HTML are filled by
  `<script type="application/vnd.drupal-ajax">` JSON "insert" commands at the end of the same response. A
  parser has to decode those, because the plain markup is mostly placeholders.

### 3.2 AJAX helpers (verified)

```
GET /div-district-data?state_code=27&lang_id=1&division_code=&district_form=custom_se…   → district <option> list
POST /path-entry   location=<page url>                                                     → visit logging
GET /statisticscounter.php                                                                 → visitor counter
```

District codes (`project_district`), 38 options in all, for example:

| Code | District |
|---|---|
| 517 | Thane |
| 518 | Mumbai Suburban |
| 519 | Mumbai City |
| 521 | Pune |
| 990 | Palghar |

### 3.3 What a search submission does (verified)

* **GET with query parameters** (`?project_name=Lodha&project_state=27&project_district=517&op=Search`) returns
  HTTP 200 with the empty form. GET filters are ignored.
* **POST of the form** with a fresh `form_build_id` (plain `httpx`, no browser) gets HTTP 303 back to
  `/projects-search-result`, sets a session cookie `SSESS…`, and returns HTTP 200. The page re-renders the form
  with `project_name="Lodha"` filled in, but **no result rows and no registration numbers**. One BigPipe
  placeholder is returned **empty (0 bytes)**.
* The theme JavaScript (`functions.js`, `general.js`, the aggregated Drupal JS) makes **no AJAX call that loads
  results**. It only loads districts, logs visits and loads the visitor counter. The page's libraries include a
  custom module `home_search_api`, so results are most likely fetched by Drupal **server-side** from a backend
  search API and rendered into that empty placeholder.
* Conclusion: on 7 Oct 2026 the search backend was not producing results (consistent with the 504s on the rest
  of the Drupal site). It is **not established** whether a successful search renders inline after the POST
  redirect or on another page. This must be re-checked when the Drupal site is healthy.

### 3.4 How to finish the search part when the site is up

1. In headed Playwright, fill `#projects-search-page-form` (scoped selectors), submit with
   `form.requestSubmit()`, and record the traffic (see `probe_search.py`).
2. If result rows appear, note their markup and their detail links. The link should point to
   `maharerait…/public/project/view/{projectId}`, which joins search to the JSON API above.
3. If the rows come from an XHR, the probe will capture its URL and body. Then call it directly.
4. Otherwise parse the server-rendered rows (including BigPipe payloads) from the POST response.

---

## 4. Recommended architecture

```
                 ┌─────────────────────────────── search (name / district / pincode) ───┐
FastAPI ─────────┤                                                                       │
 /api/projects   │  Drupal form POST (httpx: GET form_build_id → POST)  ── parse rows ──┤──► projectId(s)
 /api/projects/  │  fallback: Playwright, same form                                      │
   {rera_number} └── RERA no. ─► getPastExpProjectHeaderByRegistrationNo (token) ───────┘
                                          │
                                          ▼
                 project detail = open endpoints (httpx, no token)
                                + protected endpoints (httpx + public token)
                                          ▲
                 TokenProvider: Playwright loads /public/project/view/{any id},
                 reads sessionStorage.tokens, caches for 100 min, refreshes on 401
```

* **Rate limiting:** about 1 request/second to `maharerait`, and ≥ 3 s between Drupal requests (it is clearly
  overloaded). Cache detail responses for 24 h and search responses for 1–6 h.
* **Retries:** Drupal needs retry-with-backoff on 504 (the gateway gives up after 70–100 s).
  `maharerait` normally answers in a few seconds.
* **IDs:** `projectId` is sequential, but don't enumerate it to crawl. Look up projects by RERA number
  or via search.

---

## 5. Reproduction scripts

These are in `scrapers/maharera/investigation/` and run with Python 3.11+, `playwright`, `httpx`:

| Script | What it does |
|---|---|
| `probe_search.py` | Headed Playwright: loads the Drupal search, lists every form control, fills name and district, submits, records all traffic |
| `probe_detail.py` | Headed Playwright: opens `/public/project/view/{id}`, records all 78 API calls, replays each with `httpx` without a token, and classifies them as open or protected |
| `probe_lookup.py` | Gets the public token through the page's own flow, then tests the RERA-number lookup in the browser and from `httpx` |
| `probe_http_search.py` / `probe_http_search2.py` | Reproduce the Drupal form POST with plain `httpx` (GET `form_build_id` → POST), with retries on 504 |

```bash
pip install playwright httpx
python -m playwright install chromium
python probe_detail.py 10000
python probe_lookup.py P51700000001
python probe_search.py --name Lodha --district Thane
```

## 6. Open items

* [ ] A successful Drupal search with result rows (blocked by 504s and empty result blocks on 7 Oct 2026).
* [ ] The search-result markup and detail-link format.
* [ ] The FastAPI service: endpoints `/api/projects` and `/api/projects/{rera_number}` per section 4. The RERA
      lookup and the detail API are ready to build on; search depends on the first item.
