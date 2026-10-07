"""Loading structured files into the database: locations and researched seed projects.

Seed facts always arrive as PENDING — a researcher approves them in the review queue.
Loading the same file twice updates records instead of duplicating them.
"""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.text import slugify

from .. import vocab
from ..models import (
    Event, FundingEvent, InvestmentFigure, LandRecord, Location, Organization, Project,
    ProjectAlias, ProjectOrganization, ProjectRelationship, RegulatoryItem, Source, normalize_name,
)
from .status import recompute_project


class SeedError(ValueError):
    pass


def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", value)
    if not m:
        raise SeedError(f"Bad date {value!r} (expected YYYY, YYYY-MM or YYYY-MM-DD)")
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    return date(y, mo, d)


def precision_for(value, declared=None):
    if declared in ("DAY", "MONTH", "YEAR"):
        return declared
    parts = str(value).count("-")
    return {0: "YEAR", 1: "MONTH"}.get(parts, "DAY")


def to_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise SeedError(f"Bad number {value!r}")


def _choice(value, choices, field, default=None):
    valid = {c for c, _ in choices}
    v = (value or "").strip().upper() if isinstance(value, str) else value
    if v in valid:
        return v
    if default is not None:
        return default
    raise SeedError(f"{field}: {value!r} is not one of {sorted(valid)}")


def _market_choice(value):
    if not value:
        return ""
    lookup = {normalize_name(m).replace(" ", ""): m for m in vocab.MICRO_MARKETS}
    key = normalize_name(value.replace("-", "–")).replace(" ", "")
    return lookup.get(key, "")


def resolve_location(taluka="", village="", micro_market=""):
    """Find the best Location for a place; returns (location or None, taluka, micro_market)."""
    taluka = taluka if taluka in vocab.TALUKAS else ""
    loc = None
    if village:
        wanted = normalize_name(village)
        qs = Location.objects.filter(taluka=taluka) if taluka else Location.objects.all()
        for candidate in qs:
            if any(normalize_name(n) == wanted for n in candidate.all_names()):
                loc = candidate
                break
    if loc:
        return loc, loc.taluka, micro_market or loc.micro_market
    market = micro_market or vocab.TALUKA_DEFAULT_MARKET.get(taluka, "")
    if not loc and taluka:
        loc = Location.objects.filter(taluka=taluka, name=taluka).first()
    return loc, taluka, market


def coords_for(loc, taluka="", has_village=True):
    """(lat, lng, precision) from a Location, falling back to the taluka HQ when the village has no coordinates."""
    if loc and loc.latitude is not None:
        precision = "TALUKA" if (loc.name == loc.taluka and not has_village) else "VILLAGE"
        return loc.latitude, loc.longitude, precision
    hq = Location.objects.filter(taluka=(loc.taluka if loc else taluka), name=(loc.taluka if loc else taluka),
                                 latitude__isnull=False).first() if (loc or taluka) else None
    if hq:
        return hq.latitude, hq.longitude, "TALUKA"
    return None, None, ""


def load_locations(path):
    data = json.loads(open(path, encoding="utf-8").read())
    created = updated = 0
    for row in data["locations"]:
        obj, was_created = Location.objects.update_or_create(
            taluka=row["taluka"], name=row["name"],
            defaults={
                "district": row.get("district", "Palghar"),
                "micro_market": row["micro_market"],
                "alternate_names": "\n".join(row.get("alternate_names", [])),
                **({"latitude": row["latitude"], "longitude": row["longitude"], "coord_source": row.get("coord_source", "")}
                   if row.get("latitude") is not None else {}),
            },
        )
        created += was_created
        updated += not was_created
    return created, updated


def _org(name, org_type=vocab.OrgType.OTHER):
    name = (name or "").strip()
    if not name:
        return None
    existing = Organization.objects.filter(name__iexact=name).first()
    if existing:
        return existing
    norm = normalize_name(name)
    for org in Organization.objects.exclude(aliases=""):
        if any(normalize_name(a) == norm for a in org.aliases.splitlines()):
            return org
    return Organization.objects.create(name=name, org_type=org_type)


def _sources(spec, project_sources, ref_list):
    out = []
    for ref in ref_list:
        if ref not in project_sources:
            raise SeedError(f"{spec}: unknown source reference {ref!r}")
        out.append(project_sources[ref])
    return out


def _refs(item):
    refs = item.get("sources") or ([item["source"]] if item.get("source") else [])
    if isinstance(refs, str):
        refs = [refs]
    return refs


def _upsert_fact(model, lookup, defaults, sources, quote, entered_by):
    obj = model.objects.filter(**lookup).first()
    if obj is None:
        obj = model(**lookup, **defaults)
        obj.origin = vocab.Origin.SEED
        obj.entered_by = entered_by
        obj.quote = quote or ""
        obj.save()
    else:
        for k, v in defaults.items():
            setattr(obj, k, v)
        if quote:
            obj.quote = quote
        obj.save()
    obj.sources.add(*sources)
    return obj


@transaction.atomic
def load_seed(path, entered_by="seed research"):
    data = json.loads(open(path, encoding="utf-8").read())
    entered_by = data.get("generated_by") or entered_by
    stats = {"projects": 0, "events": 0, "facts": 0, "relationships": 0, "sources": 0}
    pending_relationships = []
    projects_by_key = {}

    for spec in data.get("projects", []):
        key = spec.get("key") or slugify(spec["name"])
        label = f"[{key}]"
        if not spec.get("sources"):
            raise SeedError(f"{label} has no sources — every project must have a source (rule 1)")

        # Sources
        project_sources = {}
        for ref, s in spec["sources"].items():
            if not s.get("url"):
                raise SeedError(f"{label} source {ref} has no url")
            src, created = Source.objects.get_or_create(
                url=s["url"],
                defaults={
                    "title": (s.get("title") or "")[:500],
                    "publisher": (s.get("publisher") or "")[:200],
                    "level": _choice(s.get("level"), vocab.SourceLevel.choices, f"{label} source {ref} level"),
                    "published_date": parse_date(s.get("published_date")),
                },
            )
            stats["sources"] += created
            project_sources[ref] = src

        loc, taluka, market = resolve_location(spec.get("taluka", ""), spec.get("village", ""), _market_choice(spec.get("micro_market")))
        promoter = _org(spec.get("promoter"), vocab.OrgType.OTHER)
        project, _ = Project.objects.update_or_create(
            slug=key,
            defaults={
                "name": spec["name"],
                "category": _choice(spec.get("category"), vocab.Category.choices, f"{label} category"),
                "subcategory": spec.get("subcategory", "")[:100],
                "description": spec.get("description", ""),
                "taluka": taluka,
                "village": spec.get("village", "") or (loc.name if loc and loc.name != taluka else ""),
                "micro_market": market,
                "location": loc,
                "promoter": promoter,
                "strategic_importance": _choice(spec.get("strategic_importance"), vocab.Importance.choices, f"{label} importance", "MEDIUM"),
            },
        )
        if spec.get("latitude") is not None and spec.get("longitude") is not None:
            project.latitude, project.longitude, project.coord_precision = spec["latitude"], spec["longitude"], "EXACT"
        else:
            project.latitude, project.longitude, project.coord_precision = coords_for(loc, taluka, bool(spec.get("village")))
        project.save()
        projects_by_key[key] = project
        stats["projects"] += 1

        for alt in spec.get("alternate_names", []):
            if alt and normalize_name(alt) != normalize_name(project.name):
                ProjectAlias.objects.get_or_create(project=project, normalized=normalize_name(alt), defaults={"name": alt})
        if promoter:
            ProjectOrganization.objects.get_or_create(project=project, organization=promoter, role=vocab.OrgRole.PROMOTER)
        for auth in spec.get("authorities", []):
            org = _org(auth, vocab.OrgType.GOVERNMENT)
            if org:
                if org.org_type == vocab.OrgType.OTHER:
                    org.org_type = vocab.OrgType.GOVERNMENT
                    org.save()
                ProjectOrganization.objects.get_or_create(project=project, organization=org, role=vocab.OrgRole.AUTHORITY)

        for e in spec.get("events", []):
            srcs = _sources(label, project_sources, _refs(e))
            if not srcs:
                raise SeedError(f"{label} event {e.get('title')!r} has no source")
            d = parse_date(e["date"])
            _upsert_fact(
                Event,
                {"project": project, "date": d, "stage": _choice(e.get("stage"), vocab.Stage.choices, f"{label} stage"), "title": e["title"][:300]},
                {"date_precision": precision_for(e["date"], e.get("date_precision")), "description": e.get("description", "")},
                srcs, e.get("quote"), entered_by,
            )
            stats["events"] += 1

        for inv in spec.get("investment", []) or []:
            srcs = _sources(label, project_sources, _refs(inv))
            _upsert_fact(
                InvestmentFigure,
                {"project": project, "amount_crore": to_decimal(inv["amount_crore"]),
                 "basis": _choice(inv.get("basis"), vocab.InvestmentBasis.choices, f"{label} investment basis")},
                {"as_of": parse_date(inv.get("as_of")), "note": inv.get("note", "")[:300],
                 "scope": _choice(inv.get("scope"), vocab.InvestmentScope.choices, f"{label} investment scope", "PROJECT")},
                srcs, inv.get("quote"), entered_by,
            )
            stats["facts"] += 1

        for f in spec.get("funding", []) or []:
            srcs = _sources(label, project_sources, _refs(f))
            _upsert_fact(
                FundingEvent,
                {"project": project, "date": parse_date(f.get("date")),
                 "stage": _choice(f.get("stage"), vocab.FundingStage.choices, f"{label} funding stage"),
                 "financier": (f.get("financier") or "")[:255]},
                {"amount_crore": to_decimal(f.get("amount_crore")),
                 "funding_type": _choice(f.get("funding_type"), vocab.FundingType.choices, "funding type", "OTHER"),
                 "note": f.get("note", "")[:300]},
                srcs, f.get("quote"), entered_by,
            )
            stats["facts"] += 1

        for lr in spec.get("land", []) or []:
            srcs = _sources(label, project_sources, _refs(lr))
            l_loc, l_taluka, l_market = resolve_location(lr.get("taluka") or taluka, lr.get("village", ""), "")
            _upsert_fact(
                LandRecord,
                {"project": project, "village": lr.get("village", "")[:120], "purpose": (lr.get("purpose") or "")[:200],
                 "date": parse_date(lr.get("date"))},
                {"taluka": l_taluka, "micro_market": l_market or market,
                 "survey_numbers": lr.get("survey_numbers", "")[:500],
                 "area_hectares": to_decimal(lr.get("area_hectares")), "area_text": (lr.get("area_text") or "")[:200],
                 "acquirer": (lr.get("acquirer") or "")[:255],
                 "status": _choice(lr.get("status"), vocab.LandStatus.choices, "land status", "OTHER"),
                 "consideration_crore": to_decimal(lr.get("consideration_crore"))},
                srcs, lr.get("quote"), entered_by,
            )
            stats["facts"] += 1

        for ri in spec.get("regulatory", []) or []:
            srcs = _sources(label, project_sources, _refs(ri))
            _upsert_fact(
                RegulatoryItem,
                {"project": project, "item_type": _choice(ri.get("item_type"), vocab.RegulatoryType.choices, "regulatory type", "OTHER"),
                 "title": ri["title"][:300], "date": parse_date(ri.get("date"))},
                {"authority": (ri.get("authority") or "")[:255],
                 "status": _choice(ri.get("status"), vocab.RegulatoryStatus.choices, "regulatory status", "OTHER"),
                 "reference_no": (ri.get("reference_no") or "")[:200], "taluka": taluka, "micro_market": market},
                srcs, ri.get("quote"), entered_by,
            )
            stats["facts"] += 1

        for rel in spec.get("relationships", []) or []:
            pending_relationships.append((project, rel, _sources(label, project_sources, _refs(rel)), label))

    for project, rel, srcs, label in pending_relationships:
        target = projects_by_key.get(rel["to"]) or Project.objects.filter(slug=rel["to"]).first()
        if target is None:
            # The target may arrive in another seed file; it is linked when that file loads.
            stats.setdefault("unresolved_relationships", []).append(f"{label} → {rel['to']}")
            continue
        _upsert_fact(
            ProjectRelationship,
            {"from_project": project, "to_project": target,
             "rel_type": _choice(rel.get("type"), vocab.RelationshipType.choices, "relationship type", "RELATED")},
            {"note": rel.get("note", "")},
            srcs, rel.get("quote"), entered_by,
        )
        stats["relationships"] += 1

    for project in projects_by_key.values():
        recompute_project(project)
    return stats
