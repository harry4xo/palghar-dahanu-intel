"""Micro-market activity classification (PRD §18) — transparent written rules, no scoring model.

A dimension (RERA, industrial, infrastructure, …) is *evidenced* in a micro-market when at
least one non-rejected fact dated inside the period is backed by a PRIMARY or SECONDARY
source. Facts backed only by UNVERIFIED sources are listed but do not count.

  HIGH    — 3 or more evidenced dimensions AND at least one project in that market has
            reached Approval or beyond on a PRIMARY source.
  MEDIUM  — at least one evidenced dimension.
  LOW     — nothing evidenced. If researchers logged a "no material development" search,
            the page states that explicitly; otherwise the market is shown as not yet researched.

Every classification is returned with the reasons that produced it.
"""

from collections import defaultdict
from datetime import date

from .. import vocab
from ..models import Event, FundingEvent, LandRecord, Project, RegulatoryItem, ReraProject, ResearchLog

CATEGORY_DIMENSION = {
    "REAL_ESTATE": "developer",
    "HOSPITALITY": "developer",
    "INDUSTRIAL": "industrial",
    "INFRASTRUCTURE": "infrastructure",
    "UTILITIES": "infrastructure",
    "LAND": "land",
    "LOGISTICS": "logistics",
    "DIGITAL": "logistics",
    "REGULATORY": "regulatory",
}

DIMENSION_LABELS = dict(vocab.ACTIVITY_DIMENSIONS)
DEFAULT_START = date(2021, 1, 1)


def _level(fact):
    return fact.best_level()


def _allowed(fact, include_pending):
    if fact.review_status == vocab.ReviewStatus.REJECTED:
        return False
    if not include_pending and fact.review_status != vocab.ReviewStatus.APPROVED:
        return False
    return True


def _in_period(d, start, end):
    return d is not None and start <= d <= end


def market_activity(start=None, end=None, include_pending=True, markets=None):
    start = start or DEFAULT_START
    end = end or date.today()
    markets = markets or vocab.MICRO_MARKETS

    # evidence[market][dimension] -> list of (level, label, url)
    evidence = defaultdict(lambda: defaultdict(list))

    def put(market, dim, level, label, url):
        if market:
            evidence[market][dim].append({"level": level, "label": label, "url": url})

    events = Event.objects.select_related("project").prefetch_related("sources")
    for e in events:
        if not _allowed(e, include_pending) or not _in_period(e.date, start, end):
            continue
        dim = CATEGORY_DIMENSION.get(e.project.category)
        if dim:
            put(e.project.micro_market, dim, _level(e), f"{e.project.name}: {e.title}", e.project.get_absolute_url())

    for r in ReraProject.objects.select_related("project"):
        market = r.project.micro_market if r.project else ""
        if _in_period(r.registration_date, start, end):
            put(market, "rera", "PRIMARY", f"MahaRERA {r.rera_no} registered — {r.project_name}",
                r.project.get_absolute_url() if r.project else "")

    for lr in LandRecord.objects.select_related("project").prefetch_related("sources"):
        if not _allowed(lr, include_pending) or not _in_period(lr.date, start, end):
            continue
        market = lr.micro_market or (lr.project.micro_market if lr.project else "")
        put(market, "land", _level(lr), f"Land: {lr.purpose or lr.village} ({lr.get_status_display()})",
            lr.project.get_absolute_url() if lr.project else "")

    for ri in RegulatoryItem.objects.select_related("project").prefetch_related("sources"):
        if not _allowed(ri, include_pending) or not _in_period(ri.date, start, end):
            continue
        market = ri.micro_market or (ri.project.micro_market if ri.project else "")
        put(market, "regulatory", _level(ri), f"{ri.get_item_type_display()}: {ri.title}",
            ri.project.get_absolute_url() if ri.project else "")

    for fe in FundingEvent.objects.select_related("project").prefetch_related("sources"):
        if not _allowed(fe, include_pending) or not _in_period(fe.date, start, end):
            continue
        put(fe.project.micro_market, "funding", _level(fe), f"{fe.project.name}: {fe.get_stage_display()} funding",
            fe.project.get_absolute_url())

    # Projects that reached approval+ on a primary source, per market.
    advanced = defaultdict(list)
    for p in Project.objects.exclude(current_stage=""):
        if vocab.STAGE_ORDER.get(p.current_stage, 0) >= 40 and p.verification_level == "PRIMARY":
            if include_pending or not p.stage_is_provisional:
                advanced[p.micro_market].append(p)

    logs = defaultdict(list)
    for log in ResearchLog.objects.filter(result="NONE"):
        logs[log.micro_market].append(log)

    results = []
    for market in markets:
        dims = []
        evidenced = []
        for key, label in vocab.ACTIVITY_DIMENSIONS:
            items = evidence[market][key]
            strong = [i for i in items if i["level"] in ("PRIMARY", "SECONDARY")]
            if strong:
                state = "evidenced"
                evidenced.append(label)
            elif items:
                state = "unverified"
            else:
                logged_none = any(l.dimension == key for l in logs[market])
                state = "none_logged" if logged_none else "not_researched"
            dims.append({
                "key": key, "label": label, "state": state,
                "count": len(items), "strong_count": len(strong), "items": items,
            })

        reasons = []
        if len(evidenced) >= 3 and advanced[market]:
            level = "HIGH"
            reasons.append(f"Evidenced activity in {len(evidenced)} dimensions: {', '.join(evidenced)}.")
            names = ", ".join(p.name for p in advanced[market][:3])
            reasons.append(f"Primary-sourced projects at approval stage or beyond: {names}.")
        elif evidenced:
            level = "MEDIUM"
            reasons.append(f"Evidenced activity in {len(evidenced)} dimension(s): {', '.join(evidenced)}.")
            if len(evidenced) >= 3:
                reasons.append("Not HIGH: no project here has reached approval or beyond on a primary source.")
            else:
                reasons.append("Not HIGH: fewer than 3 dimensions have primary or secondary evidence.")
        else:
            level = "LOW"
            if logs[market]:
                reasons.append(vocab.NO_MATERIAL_TEXT)
            elif any(d["state"] == "unverified" for d in dims):
                reasons.append("Only unverified reports found; no primary or secondary evidence yet.")
            else:
                reasons.append("Not yet researched for this period.")

        results.append({
            "market": market,
            "level": level,
            "reasons": reasons,
            "dimensions": dims,
            "evidenced_count": len(evidenced),
            "total_items": sum(d["count"] for d in dims),
        })
    return results
