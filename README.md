# Palghar–Dahanu Development Intelligence Database

A structured, source-backed database of development activity in Palghar district (Maharashtra), with Dahanu
and Vadhvan as distinct micro-markets. It covers infrastructure, real estate / MahaRERA, industry, logistics,
land, regulation and funding. Each project has one record and a dated timeline, and every fact is traced to a source.

**No AI is used inside the application.** Data enters through deterministic crawlers (MahaRERA),
keyword-based news monitoring, and researcher data entry. Summaries — current stage, verification level,
headline investment, micro-market activity — are calculated by fixed, documented rules
(see `/methodology/` in the app).

## What's in the app

| Page | What it does |
|---|---|
| **Dashboard** `/` | Totals by lifecycle phase, reported investment (excludes MoUs and double counting), activity by year, sectors, micro-market activity, major infrastructure, most active developers, latest events |
| **Projects** `/projects/` | Searchable table with filters that combine (micro-market, taluka, village, category, stage, phase, flags, verification, organisation, MahaRERA, investment range, land size, announcement/approval/construction/completion year); CSV export |
| **Project page** | Status and lifecycle path, timeline with quotes and sources, all investment figures (conflicts kept), funding, land, regulatory/legal items, MahaRERA data, linked projects, sources list |
| **Map** `/map/` | Leaflet / OpenStreetMap, same filters; hollow markers = approximate (village/taluka) location |
| **Micro-markets** `/markets/` | Activity in each of 8 categories for every micro-market, HIGH / MEDIUM / LOW with the reasons, reviewed-only toggle |
| **Companies & authorities** | Developers, promoters, authorities and their projects |
| **Research desk** (staff) | Review queue (approve / reject each fact against its source), monitoring inbox, one-screen fact entry with duplicate suggestions, research log ("searched, nothing found") |
| **Admin** `/admin/` | Full editing of every table, bulk approve/reject |

## Data model in one paragraph

`Project` is the Common Project Master (ID `PDI-00001`…, aliases, location, promoter, authorities). Facts hang
off it, each with its own sources, quote and review status: `Event` (timeline/stage), `InvestmentFigure`,
`FundingEvent`, `LandRecord`, `RegulatoryItem`, `ProjectRelationship`. `Source` stores level
(PRIMARY / SECONDARY / UNVERIFIED) and an archived copy. `ReraProject` + `ReraSnapshot` keep every MahaRERA
crawl, so changes become timeline events. `ResearchLog` records searches that found nothing, so the app can say
*"No material verified development identified during the research period."*

## Quick start (Windows, macOS, Linux)

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # only needed for the MahaRERA crawler

python manage.py bootstrap              # creates the DB, loads locations, seed research, MahaRERA data
python manage.py createsuperuser        # your researcher login
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the dashboard and http://127.0.0.1:8000/admin/ to log in.

## Day-to-day workflow

1. **Collect.** Run the collectors on a schedule (see below). They:
   * pull new keyword matches into the **Inbox** (`monitor_news`)
   * re-crawl MahaRERA and import changes (`scrapers.maharera.cli` then `import_rera`)
2. **Record.** In the Inbox, open a document, check the suggested existing projects, then record the fact
   with its stage, date, quote and source level.
3. **Review.** In **Review**, open each source and approve or reject the fact. Until a project has reviewed
   stage facts, its stage is labelled *provisional*.
4. **Log the gaps.** When a search finds nothing for a micro-market and category, use **Log a search** on the micro-market page.

## Commands

| Command | Purpose |
|---|---|
| `python manage.py bootstrap` | One-shot setup of a fresh database |
| `python manage.py load_locations` | Load `data/locations.json` (talukas, villages, micro-markets) |
| `python manage.py geocode_locations [--force] [--write-json]` | Fill coordinates from OpenStreetMap Nominatim |
| `python manage.py load_seed [files…]` | Load researched seed files from `data/seed/` (arrive as *pending review*) |
| `python -m scrapers.maharera.cli list --district Palghar --out data/rera/list.jsonl` | Crawl the MahaRERA project list |
| `python -m scrapers.maharera.cli details --in data/rera/list.jsonl --out data/rera/projects.jsonl` | Crawl project detail pages |
| `python manage.py import_rera [data/rera/projects.jsonl]` | Import a MahaRERA crawl; changes become events |
| `python manage.py monitor_news` | Check news/notice feeds and fill the Inbox |
| `python manage.py archive_sources [--limit N]` | Save local copies of source documents |
| `python manage.py recompute` | Recalculate every project's derived fields |
| `python manage.py test` | Run the test suite |

See `docs/maharera.md` for crawler details and `docs/seed-format.md` for the research file format.

### Scheduling

Windows Task Scheduler, every morning (adjust paths):

```
schtasks /Create /SC DAILY /ST 07:00 /TN "PDI monitor" /TR "C:\path\to\palghar-dahanu-intel\.venv\Scripts\python.exe C:\path\to\palghar-dahanu-intel\manage.py monitor_news"
```

cron (Linux):

```
0 7 * * *  cd /srv/pdi && .venv/bin/python manage.py monitor_news
0 2 * * 0  cd /srv/pdi && .venv/bin/python -m scrapers.maharera.cli list --district Palghar --out data/rera/list.jsonl && .venv/bin/python -m scrapers.maharera.cli details --in data/rera/list.jsonl --out data/rera/projects.jsonl && .venv/bin/python manage.py import_rera
```

## Production notes

* Set `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` and a Postgres `DATABASE_URL`
  (`pip install "psycopg[binary]"`). See `.env.example`.
* `python manage.py collectstatic` and serve with any WSGI server (`gunicorn config.wsgi` on Linux, `waitress-serve config.wsgi:application` on Windows).
* Public pages are read-only; data entry and review require a staff login.

## Data and sourcing rules

These come from the PRD and are enforced by the loaders and the status calculation:

1. Every fact has a source; seed files without one are rejected.
2. An announcement is never an approval; an MoU is never an investment.
3. Completion dates are never assumed. Expected completion only comes from official MahaRERA dates.
4. Land values and other numbers are never invented; "not disclosed" is shown instead.
5. Conflicting figures are all kept; the headline follows a fixed priority (sanctioned > estimate > reported > MoU).
6. Status history is kept as events; nothing is overwritten.
7. Each review records who checked the fact and when.

The seed research in `data/seed/` was compiled with AI assistance during development, from public sources.
Every item is loaded as **pending review** and must be checked against its source by a researcher before it counts as verified.
