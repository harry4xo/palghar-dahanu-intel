"""Import MahaRERA crawler output (data/rera/projects.jsonl) and turn changes into events.

MahaRERA is a PRIMARY source, and these facts are copied field-for-field from it, so the
events created here are auto-approved with entered_by="system:maharera". Each crawl is
stored as a snapshot; comparing a snapshot with the previous one produces timeline events
(completion date revised, status changed, bookings changed). This is how history builds up
over time even though MahaRERA itself only shows the current state.
"""

import json
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .. import vocab
from ..models import (
    Event, Organization, Project, ProjectOrganization, RegulatoryItem, ReraProject, ReraSnapshot, Source,
)
from .loaders import coords_for, parse_date, resolve_location
from .status import recompute_project

SYSTEM = "system:maharera"
TRACKED_FIELDS = ["status", "proposed_completion_date", "revised_completion_date", "total_units", "booked_units", "project_name", "promoter"]


def _clean_taluka(value):
    if not value:
        return ""
    v = value.strip().title()
    return v if v in vocab.TALUKAS else ""


def _parse_fetched(value):
    if not value:
        return timezone.now()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return timezone.now()
    return dt if dt.tzinfo else dt.replace(tzinfo=dt_timezone.utc)


def _status_stage(status):
    s = (status or "").lower()
    if "deregist" in s or "revok" in s or "cancel" in s:
        return "CANCELLED"
    if "lapse" in s:
        return "STALLED"
    if "complet" in s:
        return "COMPLETED"
    return None


def _system_event(project, source, d, stage, title, description="", quote=""):
    if d is None:
        return None
    ev, created = Event.objects.get_or_create(
        project=project, date=d, stage=stage, title=title[:300],
        defaults={
            "description": description, "quote": quote, "origin": vocab.Origin.MAHARERA,
            "entered_by": SYSTEM, "review_status": vocab.ReviewStatus.APPROVED,
            "reviewed_at": timezone.now(), "date_precision": "DAY",
        },
    )
    ev.sources.add(source)
    return ev if created else None


def _ensure_project(rera, row, source):
    if rera.project_id:
        return rera.project
    loc, taluka, market = resolve_location(_clean_taluka(row.get("taluka")), row.get("village") or "", "")
    promoter = None
    if row.get("promoter"):
        promoter = Organization.objects.filter(name__iexact=row["promoter"].strip()).first() or Organization.objects.create(
            name=row["promoter"].strip()[:255], org_type=vocab.OrgType.DEVELOPER)
    name = row.get("project_name") or rera.rera_no
    base_slug = slugify(f"rera-{rera.rera_no}")[:110]
    project = Project.objects.create(
        slug=base_slug, name=name[:255], category=vocab.Category.REAL_ESTATE,
        subcategory=(row.get("project_type") or "")[:100],
        taluka=taluka, village=(row.get("village") or "")[:120], micro_market=market, location=loc,
        promoter=promoter, strategic_importance=vocab.Importance.LOW,
        description=f"MahaRERA-registered project {rera.rera_no}.",
    )
    if row.get("latitude") and row.get("longitude"):
        project.latitude, project.longitude, project.coord_precision = row["latitude"], row["longitude"], "EXACT"
    else:
        project.latitude, project.longitude, project.coord_precision = coords_for(loc, taluka, bool(row.get("village")))
    project.save()
    if promoter:
        ProjectOrganization.objects.get_or_create(project=project, organization=promoter, role=vocab.OrgRole.PROMOTER)
    rera.project = project
    rera.save(update_fields=["project"])
    return project


def _fmt(v):
    return "—" if v in (None, "") else str(v)


@transaction.atomic
def import_row(row):
    rera_no = (row.get("rera_no") or "").strip().upper()
    if not rera_no:
        return None, []
    fetched_at = _parse_fetched(row.get("fetched_at"))
    rera, _ = ReraProject.objects.get_or_create(rera_no=rera_no)
    previous = rera.snapshots.order_by("-fetched_at").first()
    if ReraSnapshot.objects.filter(rera=rera, fetched_at=fetched_at).exists():
        return rera, []

    fields = {
        "project_name": (row.get("project_name") or "")[:300],
        "promoter": (row.get("promoter") or "")[:300],
        "taluka": (row.get("taluka") or "")[:60],
        "village": (row.get("village") or "")[:120],
        "address": row.get("address") or "",
        "pincode": (row.get("pincode") or "")[:10],
        "project_type": (row.get("project_type") or "")[:100],
        "survey_numbers": row.get("survey_numbers") or "",
        "land_area_sqm": row.get("land_area_sqm"),
        "total_units": row.get("total_units"),
        "booked_units": row.get("booked_units"),
        "registration_date": parse_date(row.get("registration_date")),
        "proposed_completion_date": parse_date(row.get("proposed_completion_date")),
        "revised_completion_date": parse_date(row.get("revised_completion_date")),
        "status": (row.get("status") or "")[:100],
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "detail_url": (row.get("detail_url") or "")[:1000],
        "extra": row.get("extra") or {},
    }
    if previous is None or fetched_at >= previous.fetched_at:
        for k, v in fields.items():
            setattr(rera, k, v)
        rera.last_fetched_at = fetched_at
        rera.save()
    ReraSnapshot.objects.create(rera=rera, fetched_at=fetched_at, data=row, raw_path=row.get("raw_path") or "")

    url = rera.detail_url or f"https://maharera.maharashtra.gov.in/#rera-{rera_no}"
    source, _ = Source.objects.get_or_create(
        url=url, defaults={"title": f"MahaRERA registration {rera_no}", "publisher": "MahaRERA", "level": "PRIMARY"})
    project = _ensure_project(rera, row, source)

    created = []
    if rera.registration_date:
        ev = _system_event(project, source, rera.registration_date, "APPROVAL", f"Registered on MahaRERA ({rera_no})")
        if ev:
            created.append(ev)
        RegulatoryItem.objects.get_or_create(
            project=project, item_type="RERA", reference_no=rera_no,
            defaults={"title": f"MahaRERA registration {rera_no}", "authority": "MahaRERA", "status": "GRANTED",
                      "date": rera.registration_date, "origin": vocab.Origin.MAHARERA, "entered_by": SYSTEM,
                      "review_status": vocab.ReviewStatus.APPROVED, "reviewed_at": timezone.now(),
                      "taluka": project.taluka, "micro_market": project.micro_market},
        )[0].sources.add(source)

    if rera.proposed_completion_date and rera.revised_completion_date and rera.revised_completion_date > rera.proposed_completion_date:
        ev = _system_event(
            project, source, fetched_at.date(), "DELAYED",
            f"Completion revised from {rera.proposed_completion_date:%d %b %Y} to {rera.revised_completion_date:%d %b %Y}",
            "Revised completion date on MahaRERA is later than the original proposed date.")
        if ev:
            created.append(ev)

    if previous is not None:
        old = previous.data
        for field in TRACKED_FIELDS:
            before, after = old.get(field), row.get(field)
            if before == after or after in (None, ""):
                continue
            stage = "NOTE"
            if field == "status":
                stage = _status_stage(after) or "NOTE"
            elif field in ("revised_completion_date", "proposed_completion_date") and before and after and str(after) > str(before):
                stage = "DELAYED"
            ev = _system_event(project, source, fetched_at.date(), stage,
                               f"MahaRERA {field.replace('_', ' ')} changed: {_fmt(before)} → {_fmt(after)}")
            if ev:
                created.append(ev)
    else:
        stage = _status_stage(rera.status)
        if stage:
            ev = _system_event(project, source, fetched_at.date(), stage, f"MahaRERA status: {rera.status}")
            if ev:
                created.append(ev)

    recompute_project(project)
    return rera, created


def import_file(path):
    imported, events = 0, 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rera, created = import_row(json.loads(line))
            if rera:
                imported += 1
                events += len(created)
    return imported, events
