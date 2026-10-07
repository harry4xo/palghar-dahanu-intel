# Seed data format (`data/seed/*.json`)

Seed files are loaded with `python manage.py load_seed data/seed/<file>.json`.
Everything loaded from seed files lands with review status **PENDING** — a researcher
must approve each event/claim in the admin before it counts as verified.

## Hard rules (PRD §21)

1. Every fact must cite a source that actually says it. No source → leave it out.
2. Never invent or estimate numbers, dates, areas or coordinates.
3. An announcement / MoU / "proposed" is NOT approval or construction. Use the stage the source supports.
4. Conflicting figures: include both, each with its own source.
5. `quote` = a short verbatim snippet (≤ 30 words) from the source proving the fact.
6. Dates: use the most precise date the source supports and set `date_precision`.

## File shape

```json
{
  "generated_by": "who/what produced this file",
  "generated_on": "YYYY-MM-DD",
  "projects": [
    {
      "key": "vadhvan-port",
      "name": "Vadhvan Port",
      "alternate_names": ["Vadhavan Port", "Wadhwan Port"],
      "category": "INFRASTRUCTURE",
      "subcategory": "Port",
      "taluka": "Dahanu",
      "village": "Vadhvan",
      "micro_market": "Vadhvan",
      "promoter": "Vadhvan Port Project Limited",
      "authorities": ["Jawaharlal Nehru Port Authority"],
      "strategic_importance": "HIGH",
      "description": "Neutral 1–2 sentence description.",
      "investment": [
        {"amount_crore": 76220, "basis": "SANCTIONED", "as_of": "2024-06-19",
         "source": "S1", "quote": "..."}
      ],
      "events": [
        {"date": "2024-06-19", "date_precision": "DAY", "stage": "APPROVAL",
         "title": "Union Cabinet approves Vadhvan port",
         "description": "optional detail", "sources": ["S1"], "quote": "..."}
      ],
      "funding": [
        {"date": "2024-06-19", "amount_crore": 76220, "stage": "APPROVED",
         "funding_type": "GOVERNMENT", "financier": "Government of India / JNPA",
         "source": "S1", "quote": "..."}
      ],
      "land": [
        {"village": "Vadhvan", "survey_numbers": "", "area_hectares": null, "area_text": "",
         "purpose": "Port", "acquirer": "", "status": "NOTIFIED", "date": "YYYY-MM-DD",
         "consideration_crore": null, "source": "S2", "quote": "..."}
      ],
      "regulatory": [
        {"item_type": "ENVIRONMENTAL_CLEARANCE", "authority": "MoEFCC", "status": "GRANTED",
         "date": "2023-02-01", "title": "...", "source": "S3", "quote": "..."}
      ],
      "relationships": [
        {"to": "mumbai-vadodara-expressway", "type": "CONNECTIVITY_FOR",
         "note": "evidence summary", "source": "S4", "quote": "..."}
      ],
      "sources": {
        "S1": {"url": "https://...", "title": "...", "publisher": "PIB",
               "level": "PRIMARY", "published_date": "2024-06-19"}
      }
    }
  ]
}
```

## Vocabularies

- `category`: INFRASTRUCTURE, REAL_ESTATE, INDUSTRIAL, LOGISTICS, DIGITAL, UTILITIES, HOSPITALITY, LAND, REGULATORY
- `strategic_importance`: HIGH, MEDIUM, LOW
- `stage` (events): ANNOUNCED, MOU, PROPOSAL, DPR, APPROVAL, LAND_IDENTIFIED, LAND_ACQUISITION,
  LAND_ACQUIRED, TENDER, TENDER_AWARDED, CONSTRUCTION_STARTED, UNDER_CONSTRUCTION,
  OPERATIONAL, COMPLETED, or a flag: DELAYED, STALLED, CANCELLED, REVIVED, or NOTE (fact with no stage change)
- `date_precision`: DAY, MONTH, YEAR (use 01 for unknown month/day parts)
- `investment.basis`: SANCTIONED, ESTIMATED, MOU, REPORTED
- `investment.scope` (optional): PROJECT (default) or WIDER — the figure covers a corridor/project extending beyond Palghar district
- `funding.stage`: ANNOUNCED, COMMITTED, APPROVED, DISBURSED, COMPLETED
- `funding.funding_type`: GOVERNMENT, BANK, NBFC, AIF, PE, CORPORATE, BOND, PPP, MULTILATERAL, OTHER
- `land.status`: PROPOSED, NOTIFIED, UNDER_ACQUISITION, ACQUIRED, ALLOTTED, TRANSACTED, DISPUTED, OTHER
- `regulatory.item_type`: RERA, CRZ, ENVIRONMENTAL_CLEARANCE, FOREST, LAND_ACQUISITION_NOTIFICATION,
  TOWN_PLANNING, ZONING, DEVELOPMENT_PLAN, GOVERNMENT_RESOLUTION, COURT_ORDER, DTEPA,
  PUBLIC_HEARING, LITIGATION, OTHER
- `regulatory.status`: APPLIED, PENDING, GRANTED, REJECTED, CHALLENGED, STAYED, DISPOSED, OTHER
- `relationships.type`: PART_OF, CONNECTIVITY_FOR, DRIVEN_BY, SUPPLIES, RELATED
- `sources.level`: PRIMARY (govt / regulator / company official), SECONDARY (credible national
  press, business publications), UNVERIFIED (local reports, unconfirmed)

## Talukas of Palghar district

Palghar, Vasai, Dahanu, Talasari, Jawhar, Mokhada, Vikramgad, Wada.

## Micro-markets

Palghar, Boisar–Tarapur, Saphale, Manor, Dahanu, Vadhvan, Gholvad–Bordi, Vangaon, Talasari,
Wada, Vasai–Virar, Jawhar–Mokhada–Vikramgad, Murbe. Use one of these exact strings.
