"""Derive a project's summary fields from its facts — deterministic rules, no AI.

Rules (PRD §4, §13, §21):
* Current stage = furthest lifecycle stage among APPROVED events. If a project has no
  approved stage events yet, unreviewed (PENDING) ones are used and the stage is marked
  provisional so the UI can say so. REJECTED facts are always ignored.
* Flags (DELAYED / STALLED / CANCELLED) stay active until a later REVIVED event or a later
  stage event clears them.
* Verification level = strongest source level among the facts that count.
* Corroborated = facts are backed by at least two different publishers.
* Headline investment = one figure per project, by basis priority SANCTIONED > ESTIMATED >
  REPORTED > MOU, then most recent. Other figures are kept and shown, never discarded.
"""

from django.db.models import Prefetch
from django.utils import timezone

from .. import vocab
from ..models import Event, FundingEvent, InvestmentFigure, LandRecord, Project, RegulatoryItem, ProjectRelationship

FACT_MODELS = (Event, InvestmentFigure, FundingEvent, LandRecord, RegulatoryItem)


def _counted(qs):
    """Approved facts if there are any, else pending ones (provisional)."""
    approved = [f for f in qs if f.review_status == vocab.ReviewStatus.APPROVED]
    if approved:
        return approved, False
    pending = [f for f in qs if f.review_status == vocab.ReviewStatus.PENDING]
    return pending, bool(pending)


def derive_stage(events):
    """Return (stage, stage_date, active_flags) for a list of events."""
    stage_events = [e for e in events if e.stage in vocab.STAGE_ORDER]
    stage, stage_date = "", None
    if stage_events:
        best = max(stage_events, key=lambda e: (vocab.STAGE_ORDER[e.stage], e.date))
        stage, stage_date = best.stage, best.date

    flags = {}
    for e in sorted(events, key=lambda e: (e.date, e.id or 0)):
        if e.stage in ("DELAYED", "STALLED", "CANCELLED"):
            flags[e.stage] = e.date
        elif e.stage == "REVIVED":
            flags.pop("STALLED", None)
            flags.pop("CANCELLED", None)
        elif e.stage in vocab.STAGE_ORDER and e.stage != "ANNOUNCED":
            # Real progress after a stall shows the project moving again.
            for f in ("STALLED",):
                if f in flags and e.date > flags[f]:
                    flags.pop(f)
        if e.stage in ("COMPLETED", "OPERATIONAL"):
            flags.pop("DELAYED", None)
    return stage, stage_date, sorted(flags)


def pick_headline_investment(figures):
    usable = [f for f in figures if f.review_status != vocab.ReviewStatus.REJECTED]
    if not usable:
        return None
    approved = [f for f in usable if f.review_status == vocab.ReviewStatus.APPROVED]
    pool = approved or usable
    return sorted(
        pool,
        key=lambda f: (vocab.INVESTMENT_BASIS_PRIORITY.get(f.basis, 9), -(f.as_of.toordinal() if f.as_of else 0)),
    )[0]


def _first_date(events, stages):
    dates = [e.date for e in events if e.stage in stages]
    return min(dates) if dates else None


def recompute_project(project):
    events = list(project.events.prefetch_related("sources").all())
    counted_events, provisional = _counted(events)
    stage, stage_date, flags = derive_stage(counted_events)

    project.current_stage = stage
    project.current_stage_date = stage_date
    project.stage_is_provisional = provisional
    project.flags = ",".join(flags)

    project.announcement_date = min((e.date for e in counted_events), default=None)
    project.approval_date = _first_date(counted_events, {s for s, o in vocab.STAGE_ORDER.items() if 40 <= o < 80})
    project.construction_start_date = _first_date(counted_events, {"CONSTRUCTION_STARTED", "UNDER_CONSTRUCTION", "OPERATIONAL", "COMPLETED"})
    project.actual_completion = _first_date(counted_events, {"OPERATIONAL", "COMPLETED"})

    # Expected completion only from RERA registrations (never assumed — rule 5).
    rera_dates = [r.revised_completion_date or r.proposed_completion_date for r in project.rera_registrations.all()]
    rera_dates = [d for d in rera_dates if d]
    project.expected_completion = max(rera_dates) if rera_dates and not project.actual_completion else None

    # Sources and verification across every fact type.
    all_facts = list(events)
    for model in FACT_MODELS[1:]:
        all_facts += list(model.objects.filter(project=project).prefetch_related("sources"))
    all_facts += list(ProjectRelationship.objects.filter(from_project=project).prefetch_related("sources"))
    live = [f for f in all_facts if f.review_status != vocab.ReviewStatus.REJECTED]
    counted = [f for f in live if f.review_status == vocab.ReviewStatus.APPROVED] or live

    sources = {}
    for f in counted:
        for s in f.sources.all():
            sources[s.pk] = s
    project.source_count = len({s.pk for f in live for s in f.sources.all()})
    if sources:
        best = min(s.level_rank for s in sources.values())
        project.verification_level = {v: k for k, v in vocab.SOURCE_LEVEL_RANK.items()}[best]
    else:
        project.verification_level = ""
    publishers = {(s.publisher or s.url.split("/")[2]).strip().lower() for s in sources.values() if s.level != "UNVERIFIED"}
    project.corroborated = len(publishers) >= 2

    headline = pick_headline_investment(list(project.investments.all()))
    project.headline_investment_crore = headline.amount_crore if headline else None
    project.headline_investment_basis = headline.basis if headline else ""
    project.headline_investment_scope = headline.scope if headline else ""

    reviewed = [f.reviewed_at for f in all_facts if f.reviewed_at]
    project.last_verified_at = max(reviewed) if reviewed else None
    project.pending_review_count = sum(1 for f in all_facts if f.review_status == vocab.ReviewStatus.PENDING)

    project.save()
    return project


def recompute_all():
    qs = Project.objects.prefetch_related(
        Prefetch("events", queryset=Event.objects.prefetch_related("sources")),
        "investments",
        "rera_registrations",
    )
    n = 0
    for project in qs:
        recompute_project(project)
        n += 1
    return n


def review_fact(fact, user, approve=True, note=""):
    fact.review_status = vocab.ReviewStatus.APPROVED if approve else vocab.ReviewStatus.REJECTED
    fact.reviewed_by = user
    fact.reviewed_at = timezone.now()
    if note:
        fact.review_note = note
    fact.save()
    project = getattr(fact, "project", None) or getattr(fact, "from_project", None)
    if project is not None:
        recompute_project(project)
