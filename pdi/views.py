import csv
import json
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Sum, Value, When
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import vocab
from .forms import ProjectFilterForm, QuickFactForm, ResearchLogForm
from .models import (
    Event, FundingEvent, InboxItem, InvestmentFigure, LandRecord, Organization, Project, ProjectAlias,
    ProjectOrganization, ProjectRelationship, RegulatoryItem, ResearchLog, Source,
)
from .services import matching
from .services.activity import market_activity
from .services.loaders import coords_for, resolve_location
from .services.status import recompute_project, review_fact

FACT_TYPES = {
    "event": Event,
    "investment": InvestmentFigure,
    "funding": FundingEvent,
    "land": LandRecord,
    "regulatory": RegulatoryItem,
    "relationship": ProjectRelationship,
}

STAGE_RANK = Case(*[When(current_stage=k, then=Value(v)) for k, v in vocab.STAGE_ORDER.items()],
                  default=Value(0), output_field=IntegerField())


# --------------------------------------------------------------------------- filtering

def filter_projects(params):
    form = ProjectFilterForm(params or None)
    qs = Project.objects.select_related("promoter").all()
    if not form.is_valid():
        return qs.order_by("name"), form
    d = form.cleaned_data
    if d["q"]:
        q = d["q"].strip()
        qs = qs.filter(Q(name__icontains=q) | Q(aliases__name__icontains=q) | Q(code__iexact=q) | Q(village__icontains=q)
                       | Q(rera_registrations__rera_no__iexact=q))
    if d["micro_market"]:
        qs = qs.filter(micro_market__in=d["micro_market"])
    if d["taluka"]:
        qs = qs.filter(taluka__in=d["taluka"])
    if d["village"]:
        qs = qs.filter(village__icontains=d["village"])
    if d["category"]:
        qs = qs.filter(category__in=d["category"])
    if d["subcategory"]:
        qs = qs.filter(subcategory__icontains=d["subcategory"])
    if d["stage"]:
        qs = qs.filter(current_stage__in=d["stage"])
    if d["phase"]:
        qs = qs.filter(current_stage__in=vocab.PHASES[d["phase"]][1])
    if d["flag"]:
        qs = qs.filter(flags__contains=d["flag"])
    if d["verification"]:
        qs = qs.filter(verification_level=d["verification"])
    if d["verified_only"]:
        qs = qs.filter(stage_is_provisional=False).exclude(current_stage="")
    if d["importance"]:
        qs = qs.filter(strategic_importance=d["importance"])
    if d["organization"]:
        o = d["organization"]
        qs = qs.filter(Q(promoter__name__icontains=o) | Q(organizations__name__icontains=o) | Q(funding__financier__icontains=o))
    if d["rera"] == "yes":
        qs = qs.filter(rera_registrations__isnull=False)
    elif d["rera"] == "no":
        qs = qs.filter(rera_registrations__isnull=True)
    if d["investment_min"] is not None:
        qs = qs.filter(headline_investment_crore__gte=d["investment_min"])
    if d["investment_max"] is not None:
        qs = qs.filter(headline_investment_crore__lte=d["investment_max"])
    if d["land_min_ha"] is not None:
        qs = qs.filter(land_records__area_hectares__gte=d["land_min_ha"])
    if d["announced_from"]:
        qs = qs.filter(announcement_date__year__gte=d["announced_from"])
    if d["announced_to"]:
        qs = qs.filter(announcement_date__year__lte=d["announced_to"])
    if d["approval_year"]:
        qs = qs.filter(approval_date__year=d["approval_year"])
    if d["construction_year"]:
        qs = qs.filter(construction_start_date__year=d["construction_year"])
    if d["completion_year"]:
        qs = qs.filter(actual_completion__year=d["completion_year"])
    qs = qs.distinct()
    sort = d.get("sort") or "name"
    if sort == "stage":
        qs = qs.annotate(stage_rank=STAGE_RANK).order_by("-stage_rank", "name")
    else:
        qs = qs.order_by(sort, "name") if sort != "name" else qs.order_by("name")
    return qs, form


def _non_double_counted(qs):
    """Exclude components that are PART_OF another project, so investment isn't counted twice."""
    part_ids = set(ProjectRelationship.objects.filter(rel_type="PART_OF").exclude(review_status="REJECTED")
                   .values_list("from_project_id", flat=True))
    return qs.exclude(id__in=part_ids)


# --------------------------------------------------------------------------- public pages

def dashboard(request):
    projects = Project.objects.all()
    today = date.today()
    phase_counts = Counter(vocab.phase_of(s) for s in projects.values_list("current_stage", flat=True))
    inv_all = _non_double_counted(projects).exclude(headline_investment_crore__isnull=True)
    wider_investment = inv_all.filter(headline_investment_scope="WIDER").exclude(headline_investment_basis="MOU")         .aggregate(t=Sum("headline_investment_crore"))["t"]
    inv_qs = inv_all.exclude(headline_investment_scope="WIDER")
    by_basis = {row["headline_investment_basis"]: row["total"] for row in
                inv_qs.values("headline_investment_basis").annotate(total=Sum("headline_investment_crore"))}
    total_investment = sum(v for k, v in by_basis.items() if k != "MOU")

    years = list(range(2021, today.year + 1))
    timeline = defaultdict(lambda: [0] * len(years))
    for ev in Event.objects.exclude(review_status="REJECTED").filter(date__year__gte=years[0]).select_related("project"):
        if ev.date.year <= years[-1]:
            timeline[ev.project.category][years.index(ev.date.year)] += 1
    cat_labels = dict(vocab.Category.choices)
    timeline_data = {"years": years, "series": [{"label": cat_labels.get(k, k), "key": k, "data": v} for k, v in sorted(timeline.items())]}

    sector = list(projects.values("category").annotate(n=Count("id")).order_by("-n"))
    for row in sector:
        row["label"] = cat_labels.get(row["category"], row["category"])

    developers = (Organization.objects.filter(projectorganization__role="PROMOTER")
                  .annotate(n=Count("projectorganization__project", distinct=True)).order_by("-n", "name")[:8])
    major_infra = projects.filter(category__in=["INFRASTRUCTURE", "UTILITIES"], strategic_importance="HIGH").order_by("name")[:10]
    recent = Event.objects.exclude(review_status="REJECTED").select_related("project").order_by("-date")[:12]

    ctx = {
        "total": projects.count(),
        "new_projects": projects.filter(announcement_date__gte=today - timedelta(days=365)).count(),
        "pre_approval": phase_counts.get("PRE_APPROVAL", 0),
        "approved": phase_counts.get("APPROVED", 0),
        "construction": phase_counts.get("CONSTRUCTION", 0),
        "done": phase_counts.get("DONE", 0),
        "active": phase_counts.get("APPROVED", 0) + phase_counts.get("CONSTRUCTION", 0),
        "total_investment": total_investment,
        "mou_investment": by_basis.get("MOU"),
        "wider_investment": wider_investment,
        "by_basis": [(dict(vocab.InvestmentBasis.choices)[k], v) for k, v in sorted(by_basis.items(), key=lambda kv: vocab.INVESTMENT_BASIS_PRIORITY.get(kv[0], 9)) if k],
        "provisional": projects.filter(stage_is_provisional=True).count(),
        "pending_facts": Event.objects.filter(review_status="PENDING").count(),
        "developers": developers,
        "major_infra": major_infra,
        "recent": recent,
        "timeline_json": timeline_data,
        "sector_json": [{"label": r["label"], "n": r["n"], "key": r["category"]} for r in sector],
        "sector": sector,
        "markets": market_activity(),
    }
    return render(request, "pdi/dashboard.html", ctx)


def project_list(request):
    qs, form = filter_projects(request.GET)
    if request.GET.get("format") == "csv":
        return _projects_csv(qs)
    params = request.GET.copy()
    params.pop("format", None)
    return render(request, "pdi/project_list.html", {
        "projects": qs[:1000], "count": qs.count(), "form": form, "querystring": params.urlencode(),
    })


def _projects_csv(qs):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="pdi-projects-{date.today():%Y%m%d}.csv"'
    resp.write("﻿")  # Excel-friendly UTF-8
    w = csv.writer(resp)
    w.writerow(["Project ID", "Name", "Alternate names", "Category", "Sub-category", "District", "Taluka", "Village",
                "Micro-market", "Latitude", "Longitude", "Coordinate precision", "Promoter", "Strategic importance",
                "Current stage", "Stage provisional", "Flags", "Announcement date", "Approval date", "Construction start",
                "Expected completion", "Actual completion", "Headline investment (₹ cr)", "Investment basis", "Investment scope",
                "Verification level", "Corroborated", "Source count", "Pending review", "Last verified", "Last updated", "URL"])
    for p in qs.prefetch_related("aliases"):
        w.writerow([p.code, p.name, "; ".join(a.name for a in p.aliases.all()), p.get_category_display(), p.subcategory,
                    p.district, p.taluka, p.village, p.micro_market, p.latitude or "", p.longitude or "", p.coord_precision,
                    p.promoter.name if p.promoter else "", p.strategic_importance, p.get_current_stage_display(),
                    "yes" if p.stage_is_provisional else "no", p.flags, p.announcement_date or "", p.approval_date or "",
                    p.construction_start_date or "", p.expected_completion or "", p.actual_completion or "",
                    p.headline_investment_crore or "", p.headline_investment_basis, p.headline_investment_scope, p.verification_level,
                    "yes" if p.corroborated else "no", p.source_count, p.pending_review_count,
                    p.last_verified_at or "", p.updated_at, p.get_absolute_url()])
    return resp


def project_detail(request, code):
    project = get_object_or_404(Project.objects.select_related("promoter", "location"), code=code)
    events = project.events.exclude(review_status="REJECTED").prefetch_related("sources").order_by("date", "id")
    timeline = defaultdict(list)
    for e in events:
        timeline[e.date.year].append(e)
    sources = {}
    for model in (Event, InvestmentFigure, FundingEvent, LandRecord, RegulatoryItem):
        for f in model.objects.filter(project=project).exclude(review_status="REJECTED").prefetch_related("sources"):
            for s in f.sources.all():
                sources[s.pk] = s
    for rel in project.relationships_out.prefetch_related("sources"):
        for s in rel.sources.all():
            sources[s.pk] = s
    investments = list(project.investments.exclude(review_status="REJECTED").prefetch_related("sources"))
    distinct_amounts = {(i.amount_crore, i.basis) for i in investments}
    return render(request, "pdi/project_detail.html", {
        "p": project,
        "timeline": sorted(timeline.items()),
        "investments": investments,
        "investment_conflict": len({i.amount_crore for i in investments if i.basis == "SANCTIONED"}) > 1 or len(distinct_amounts) > 1,
        "funding": project.funding.exclude(review_status="REJECTED").prefetch_related("sources"),
        "land": project.land_records.exclude(review_status="REJECTED").prefetch_related("sources"),
        "regulatory": project.regulatory_items.exclude(review_status="REJECTED").prefetch_related("sources"),
        "rel_out": project.relationships_out.exclude(review_status="REJECTED").select_related("to_project").prefetch_related("sources"),
        "rel_in": project.relationships_in.exclude(review_status="REJECTED").select_related("from_project").prefetch_related("sources"),
        "orgs": ProjectOrganization.objects.filter(project=project).select_related("organization"),
        "sources": sorted(sources.values(), key=lambda s: (s.level_rank, s.title)),
        "rera": project.rera_registrations.all(),
        "stage_path": [(k, dict(vocab.Stage.choices)[k], v) for k, v in vocab.STAGE_ORDER.items()],
        "current_rank": vocab.STAGE_ORDER.get(project.current_stage, 0),
    })


def map_view(request):
    _qs, form = filter_projects(request.GET)
    return render(request, "pdi/map.html", {"form": form, "querystring": request.GET.urlencode(),
                                            "categories": vocab.Category.choices})


def projects_geojson(request):
    qs, _ = filter_projects(request.GET)
    features = []
    for p in qs.exclude(latitude__isnull=True):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
            "properties": {
                "code": p.code, "name": p.name, "category": p.category, "category_label": p.get_category_display(),
                "stage": p.get_current_stage_display() or "No stage evidence", "provisional": p.stage_is_provisional,
                "micro_market": p.micro_market, "precision": p.get_coord_precision_display(),
                "investment": float(p.headline_investment_crore) if p.headline_investment_crore is not None else None,
                "basis": p.headline_investment_basis, "url": p.get_absolute_url(),
            },
        })
    return JsonResponse({"type": "FeatureCollection", "features": features})


def markets(request):
    include_pending = request.GET.get("verified") != "1"
    start = _parse_year(request.GET.get("from"), date(2021, 1, 1))
    end = _parse_year(request.GET.get("to"), date.today(), end=True)
    return render(request, "pdi/markets.html", {
        "rows": market_activity(start, end, include_pending), "include_pending": include_pending,
        "dimensions": vocab.ACTIVITY_DIMENSIONS, "start": start, "end": end,
    })


def market_detail(request, market):
    if market not in vocab.MICRO_MARKETS:
        raise Http404
    include_pending = request.GET.get("verified") != "1"
    row = market_activity(include_pending=include_pending, markets=[market])[0]
    projects = Project.objects.filter(micro_market=market).order_by("category", "name")
    logs = ResearchLog.objects.filter(micro_market=market)
    return render(request, "pdi/market_detail.html", {"row": row, "projects": projects, "logs": logs,
                                                      "include_pending": include_pending})


def _parse_year(value, default, end=False):
    try:
        y = int(value)
        return date(y, 12, 31) if end else date(y, 1, 1)
    except (TypeError, ValueError):
        return default


def organization_list(request):
    q = request.GET.get("q", "")
    orgs = Organization.objects.annotate(n=Count("projectorganization__project", distinct=True)).order_by("-n", "name")
    if q:
        orgs = orgs.filter(Q(name__icontains=q) | Q(aliases__icontains=q))
    return render(request, "pdi/organization_list.html", {"orgs": orgs, "q": q})


def organization_detail(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    links = ProjectOrganization.objects.filter(organization=org).select_related("project").order_by("project__name")
    return render(request, "pdi/organization_detail.html", {"org": org, "links": links})


def methodology(request):
    return render(request, "pdi/methodology.html", {
        "stages": [(k, dict(vocab.Stage.choices)[k]) for k in vocab.STAGE_ORDER],
        "levels": vocab.SourceLevel.choices, "no_material": vocab.NO_MATERIAL_TEXT,
    })


# --------------------------------------------------------------------------- researcher desk

@staff_member_required
def review_queue(request):
    kind = request.GET.get("type", "event")
    model = FACT_TYPES.get(kind, Event)
    qs = model.objects.filter(review_status="PENDING").prefetch_related("sources")
    qs = qs.select_related("from_project", "to_project") if model is ProjectRelationship else qs.select_related("project")
    counts = {k: m.objects.filter(review_status="PENDING").count() for k, m in FACT_TYPES.items()}
    return render(request, "pdi/review_queue.html", {"items": qs[:200], "kind": kind, "counts": counts})


@staff_member_required
@require_POST
def review_action(request, kind, pk):
    model = FACT_TYPES.get(kind)
    if model is None:
        raise Http404
    fact = get_object_or_404(model, pk=pk)
    review_fact(fact, request.user, approve=request.POST.get("decision") == "approve", note=request.POST.get("note", ""))
    return redirect(request.POST.get("next") or f"/review/?type={kind}")


@staff_member_required
def inbox(request):
    status = request.GET.get("status", "NEW")
    items = InboxItem.objects.filter(status=status).select_related("query", "project")[:300]
    return render(request, "pdi/inbox.html", {"items": items, "status": status,
                                              "statuses": InboxItem.Status.choices})


@staff_member_required
@require_POST
def inbox_ignore(request, pk):
    item = get_object_or_404(InboxItem, pk=pk)
    item.status = InboxItem.Status.IGNORED
    item.processed_by, item.processed_at = request.user, timezone.now()
    item.save()
    return redirect("pdi:inbox")


@staff_member_required
def fact_entry(request, inbox_pk=None):
    item = get_object_or_404(InboxItem, pk=inbox_pk) if inbox_pk else None
    initial = {"date_precision": "DAY", "source_level": "SECONDARY"}
    if item:
        initial.update({"source_url": item.url, "source_title": item.title, "source_publisher": item.publisher,
                        "source_date": item.published_at.date() if item.published_at else None,
                        "event_date": item.published_at.date() if item.published_at else None, "title": item.title[:300]})
    if request.GET.get("project"):
        initial["project"] = Project.objects.filter(code=request.GET["project"]).first()
    form = QuickFactForm(request.POST or None, initial=initial)
    suggestions = matching.candidates(name=item.title, text=f"{item.title} {item.snippet}") if item else []

    if request.method == "POST" and form.is_valid():
        project = _save_quick_fact(form.cleaned_data, request.user)
        if item:
            item.status, item.project = InboxItem.Status.PROCESSED, project
            item.processed_by, item.processed_at = request.user, timezone.now()
            item.save()
        messages.success(request, f"Saved to {project.code} · {project.name}")
        if "add_another" in request.POST:
            return redirect(f"{request.path}?project={project.code}")
        return redirect("pdi:inbox" if item else project.get_absolute_url())

    return render(request, "pdi/fact_entry.html", {"form": form, "item": item, "suggestions": suggestions})


@transaction.atomic
def _save_quick_fact(d, user):
    project = d.get("project")
    if project is None:
        loc, taluka, market = resolve_location(d.get("new_project_taluka") or "", d.get("new_project_village") or "", "")
        slug = base = slugify(d["new_project_name"])[:100] or "project"
        n = 2
        while Project.objects.filter(slug=slug).exists():
            slug, n = f"{base}-{n}", n + 1
        lat, lng, precision = coords_for(loc, taluka, bool(d.get("new_project_village")))
        project = Project.objects.create(
            slug=slug, name=d["new_project_name"], category=d["new_project_category"],
            taluka=taluka, village=d.get("new_project_village") or "", micro_market=market, location=loc,
            latitude=lat, longitude=lng, coord_precision=precision,
        )
    source, _ = Source.objects.get_or_create(url=d["source_url"], defaults={
        "title": d.get("source_title") or "", "publisher": d.get("source_publisher") or "",
        "level": d["source_level"], "published_date": d.get("source_date")})
    approved = d.get("approve_now")
    common = {
        "quote": d["quote"], "origin": vocab.Origin.MANUAL, "entered_by": user.get_username(),
        "review_status": "APPROVED" if approved else "PENDING",
        "reviewed_by": user if approved else None, "reviewed_at": timezone.now() if approved else None,
    }
    ev = Event.objects.create(project=project, date=d["event_date"], date_precision=d["date_precision"], stage=d["stage"],
                              title=d["title"], description=d.get("description") or "", **common)
    ev.sources.add(source)
    if d.get("investment_crore") is not None:
        inv = InvestmentFigure.objects.create(project=project, amount_crore=d["investment_crore"], basis=d["investment_basis"],
                                              as_of=d["event_date"], **common)
        inv.sources.add(source)
    recompute_project(project)
    return project


@staff_member_required
def research_log_new(request):
    form = ResearchLogForm(request.POST or None, initial={"period_start": date(2021, 1, 1), "period_end": date(2025, 12, 31),
                                                          "micro_market": request.GET.get("market")})
    if request.method == "POST" and form.is_valid():
        ResearchLog.objects.create(researcher=request.user.get_username(), **form.cleaned_data)
        messages.success(request, "Research log saved.")
        return redirect("pdi:market_detail", market=form.cleaned_data["micro_market"])
    return render(request, "pdi/research_log_form.html", {"form": form})
