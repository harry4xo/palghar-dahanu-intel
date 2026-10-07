import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from pdi import vocab
from pdi.models import (
    Event, InboxItem, InvestmentFigure, Location, Project, ProjectRelationship, ReraProject, ResearchLog, Source,
)
from pdi.services import matching, monitor
from pdi.services.activity import market_activity
from pdi.services.loaders import SeedError, load_seed
from pdi.services.rera_import import import_row
from pdi.services.status import derive_stage, recompute_project, review_fact


def make_project(**kw):
    defaults = {"slug": kw.get("name", "p").lower().replace(" ", "-"), "name": "Test Project",
                "category": "INFRASTRUCTURE", "taluka": "Dahanu", "micro_market": "Dahanu"}
    defaults.update(kw)
    return Project.objects.create(**defaults)


def make_source(url="https://pib.gov.in/x", level="PRIMARY", publisher="PIB"):
    return Source.objects.get_or_create(url=url, defaults={"level": level, "publisher": publisher})[0]


def add_event(project, d, stage, status="APPROVED", source=None, title=None):
    e = Event.objects.create(project=project, date=d, stage=stage, title=title or stage, review_status=status)
    e.sources.add(source or make_source())
    return e


class StageRulesTests(TestCase):
    def test_furthest_stage_wins_regardless_of_order(self):
        p = make_project(name="Port")
        add_event(p, date(2024, 6, 1), "APPROVAL")
        add_event(p, date(2021, 1, 1), "ANNOUNCED")
        add_event(p, date(2023, 1, 1), "PROPOSAL")
        stage, d, flags = derive_stage(list(p.events.all()))
        self.assertEqual(stage, "APPROVAL")
        self.assertEqual(d, date(2024, 6, 1))
        self.assertEqual(flags, [])

    def test_flags_and_revival(self):
        p = make_project(name="Road")
        add_event(p, date(2021, 1, 1), "APPROVAL")
        add_event(p, date(2022, 1, 1), "STALLED")
        self.assertEqual(derive_stage(list(p.events.all()))[2], ["STALLED"])
        add_event(p, date(2023, 1, 1), "REVIVED")
        self.assertEqual(derive_stage(list(p.events.all()))[2], [])

    def test_announcement_is_not_approval(self):
        p = make_project(name="Airport")
        add_event(p, date(2022, 1, 1), "ANNOUNCED")
        recompute_project(p)
        self.assertEqual(p.current_stage, "ANNOUNCED")
        self.assertEqual(p.phase, "PRE_APPROVAL")
        self.assertIsNone(p.approval_date)

    def test_pending_only_is_provisional_and_rejected_ignored(self):
        p = make_project(name="Park")
        add_event(p, date(2022, 1, 1), "ANNOUNCED", status="PENDING")
        add_event(p, date(2023, 1, 1), "COMPLETED", status="REJECTED")
        recompute_project(p)
        self.assertEqual(p.current_stage, "ANNOUNCED")
        self.assertTrue(p.stage_is_provisional)
        self.assertEqual(p.pending_review_count, 1)

    def test_approved_facts_take_precedence_over_pending(self):
        p = make_project(name="Corridor")
        add_event(p, date(2021, 1, 1), "APPROVAL", status="APPROVED")
        add_event(p, date(2024, 1, 1), "COMPLETED", status="PENDING")
        recompute_project(p)
        self.assertEqual(p.current_stage, "APPROVAL")
        self.assertFalse(p.stage_is_provisional)

    def test_review_updates_project(self):
        user = get_user_model().objects.create_user("r", password="x", is_staff=True)
        p = make_project(name="Bridge")
        e = add_event(p, date(2025, 1, 1), "TENDER_AWARDED", status="PENDING")
        review_fact(e, user, approve=True)
        p.refresh_from_db()
        self.assertEqual(p.current_stage, "TENDER_AWARDED")
        self.assertFalse(p.stage_is_provisional)
        self.assertIsNotNone(p.last_verified_at)

    def test_headline_investment_priority_keeps_conflicts(self):
        p = make_project(name="Port 2")
        s = make_source()
        for amount, basis in [(100, "MOU"), (90, "REPORTED"), (76, "SANCTIONED")]:
            f = InvestmentFigure.objects.create(project=p, amount_crore=amount, basis=basis, review_status="PENDING")
            f.sources.add(s)
        recompute_project(p)
        self.assertEqual(p.headline_investment_crore, Decimal("76"))
        self.assertEqual(p.headline_investment_basis, "SANCTIONED")
        self.assertEqual(p.investments.count(), 3)

    def test_corroboration_needs_two_publishers(self):
        p = make_project(name="Expressway")
        add_event(p, date(2021, 1, 1), "APPROVAL", source=make_source("https://a.example/1", "PRIMARY", "NHAI"))
        recompute_project(p)
        self.assertFalse(p.corroborated)
        add_event(p, date(2022, 1, 1), "TENDER", source=make_source("https://b.example/2", "SECONDARY", "Hindu BusinessLine"))
        recompute_project(p)
        self.assertTrue(p.corroborated)
        self.assertEqual(p.verification_level, "PRIMARY")
        self.assertEqual(p.source_count, 2)


class MatchingTests(TestCase):
    def test_transliteration_skeleton(self):
        self.assertEqual(matching.skeleton("Vadhvan Port"), matching.skeleton("Vadhavan port"))
        self.assertEqual(matching.skeleton("Wadhwan Port"), matching.skeleton("Vadhvan Port"))

    def test_candidates_by_alias_and_rera(self):
        p = make_project(name="Vadhvan Port", slug="vadhvan-port")
        p.aliases.create(name="JNPA Vadhavan project")
        found = matching.candidates(name="Wadhwan Port")
        self.assertEqual(found[0][0], p)
        self.assertEqual(found[0][1], "strong")
        ReraProject.objects.create(rera_no="P99000012345", project=p)
        found = matching.candidates(text="Registration P99000012345 lapsed")
        self.assertEqual(found[0][1], "certain")


class SeedLoaderTests(TestCase):
    def _write(self, data):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.close()
        return f.name

    def setUp(self):
        Location.objects.create(taluka="Dahanu", name="Dahanu", micro_market="Dahanu", latitude=19.98, longitude=72.73)
        Location.objects.create(taluka="Dahanu", name="Vadhvan", micro_market="Vadhvan", alternate_names="Vadhavan")

    def seed(self):
        return {"projects": [
            {"key": "port", "name": "Vadhvan Port", "alternate_names": ["Vadhavan Port"], "category": "INFRASTRUCTURE",
             "taluka": "Dahanu", "village": "Vadhavan", "promoter": "VPPL", "authorities": ["JNPA"],
             "investment": [{"amount_crore": 76220, "basis": "SANCTIONED", "source": "S1", "quote": "q"}],
             "events": [{"date": "2024-06", "stage": "APPROVAL", "title": "Cabinet approval", "sources": ["S1"], "quote": "q"}],
             "relationships": [{"to": "road", "type": "RELATED", "source": "S1"}],
             "sources": {"S1": {"url": "https://pib.gov.in/1", "level": "PRIMARY", "publisher": "PIB"}}},
            {"key": "road", "name": "Port Road", "category": "INFRASTRUCTURE", "taluka": "Dahanu",
             "events": [{"date": "2025", "stage": "PROPOSAL", "title": "Proposed", "source": "S1"}],
             "sources": {"S1": {"url": "https://example.org/r", "level": "SECONDARY"}}},
        ]}

    def test_load_is_pending_idempotent_and_resolves_location(self):
        path = self._write(self.seed())
        load_seed(path)
        load_seed(path)
        self.assertEqual(Project.objects.count(), 2)
        self.assertEqual(Event.objects.count(), 2)
        port = Project.objects.get(slug="port")
        self.assertEqual(port.micro_market, "Vadhvan")
        self.assertEqual(port.coord_precision, "TALUKA")  # village has no coords → taluka centroid
        self.assertTrue(port.stage_is_provisional)
        self.assertEqual(port.events.get().date_precision, "MONTH")
        self.assertEqual(port.headline_investment_basis, "SANCTIONED")
        self.assertEqual(ProjectRelationship.objects.count(), 1)
        self.assertTrue(all(e.review_status == "PENDING" for e in Event.objects.all()))
        Path(path).unlink()

    def test_rejects_unsourced_and_bad_stage(self):
        data = self.seed()
        data["projects"][0]["events"][0]["sources"] = ["S9"]
        with self.assertRaises(SeedError):
            load_seed(self._write(data))
        data = self.seed()
        data["projects"][0]["events"][0]["stage"] = "BUILT"
        with self.assertRaises(SeedError):
            load_seed(self._write(data))
        data = self.seed()
        data["projects"][0]["sources"] = {}
        with self.assertRaises(SeedError):
            load_seed(self._write(data))


class ReraImportTests(TestCase):
    def row(self, **kw):
        base = {"rera_no": "P99000054321", "project_name": "Sea View", "promoter": "ABC Developers", "taluka": "Palghar",
                "village": "Boisar", "registration_date": "2022-03-01", "proposed_completion_date": "2025-12-31",
                "revised_completion_date": None, "status": "Registered", "total_units": 100, "booked_units": 10,
                "detail_url": "https://maharera.example/p/1", "fetched_at": "2026-01-01T00:00:00Z"}
        base.update(kw)
        return base

    def test_import_creates_project_and_change_events(self):
        rera, created = import_row(self.row())
        p = rera.project
        self.assertEqual(p.category, "REAL_ESTATE")
        self.assertEqual(p.current_stage, "APPROVAL")
        self.assertFalse(p.stage_is_provisional)  # MahaRERA facts are primary and auto-reviewed
        self.assertEqual(p.verification_level, "PRIMARY")
        rera, created = import_row(self.row(revised_completion_date="2027-06-30", booked_units=40, status="Lapsed",
                                            fetched_at="2026-02-01T00:00:00Z"))
        stages = sorted(e.stage for e in created)
        self.assertIn("DELAYED", stages)
        self.assertIn("STALLED", stages)
        p.refresh_from_db()
        self.assertIn("DELAYED", p.flag_list)
        self.assertEqual(rera.snapshots.count(), 2)
        # Same snapshot again changes nothing.
        _, again = import_row(self.row(fetched_at="2026-02-01T00:00:00Z"))
        self.assertEqual(again, [])


class MonitorTests(TestCase):
    def test_place_required_and_marathi(self):
        score, places, topics = monitor.score_text("New port tender awarded in Gujarat", places=["Dahanu", "वाढवण"])
        self.assertEqual(score, 0)
        score, places, topics = monitor.score_text("वाढवण बंदर प्रकल्पासाठी निविदा", places=["Dahanu", "वाढवण"])
        self.assertGreater(score, 0)
        self.assertIn("वाढवण", places)

    def test_ingest_dedupes(self):
        entries = [{"link": "https://news.example/a", "title": "Dahanu land acquisition notified - Example Times", "summary": ""},
                   {"link": "https://news.example/b", "title": "Dahanu land acquisition notified - Other Paper", "summary": ""}]
        added = monitor.ingest_entries(None, entries, places=["Dahanu"])
        self.assertEqual(added, 1)
        self.assertEqual(InboxItem.objects.count(), 1)


class ActivityTests(TestCase):
    def test_classification_rules(self):
        prim = make_source()
        for cat in ("INFRASTRUCTURE", "INDUSTRIAL", "LOGISTICS"):
            p = make_project(name=f"Dahanu {cat}", slug=f"d-{cat.lower()}", category=cat, micro_market="Dahanu")
            add_event(p, date(2023, 1, 1), "APPROVAL", source=prim)
            recompute_project(p)
        q = make_project(name="Wada thing", slug="wada", category="INDUSTRIAL", micro_market="Wada", taluka="Wada")
        add_event(q, date(2023, 1, 1), "ANNOUNCED", source=make_source("https://local.example/x", "UNVERIFIED", "Local"))
        ResearchLog.objects.create(micro_market="Talasari", dimension="industrial", period_start=date(2021, 1, 1),
                                   period_end=date(2025, 12, 31), sources_searched="MIDC site", result="NONE")
        rows = {r["market"]: r for r in market_activity()}
        self.assertEqual(rows["Dahanu"]["level"], "HIGH")
        self.assertEqual(rows["Wada"]["level"], "LOW")
        self.assertIn("unverified", rows["Wada"]["reasons"][0].lower())
        self.assertEqual(rows["Talasari"]["reasons"][0], vocab.NO_MATERIAL_TEXT)
        # The Dahanu events are approved, so the reviewed-only view gives the same result.
        self.assertEqual({r["market"]: r for r in market_activity(include_pending=False)}["Dahanu"]["level"], "HIGH")


class ViewTests(TestCase):
    def setUp(self):
        Location.objects.create(taluka="Dahanu", name="Dahanu", micro_market="Dahanu", latitude=19.98, longitude=72.73)
        self.p = make_project(name="Vadhvan Port", slug="vadhvan-port", latitude=19.98, longitude=72.73, coord_precision="TALUKA")
        add_event(self.p, date(2024, 6, 19), "APPROVAL", status="PENDING")
        f = InvestmentFigure.objects.create(project=self.p, amount_crore=76220, basis="SANCTIONED")
        f.sources.add(make_source())
        recompute_project(self.p)
        self.staff = get_user_model().objects.create_user("staff", password="pw-12345-x", is_staff=True)

    def test_public_pages(self):
        for url in ["/", "/projects/", f"/projects/{self.p.code}/", "/map/", "/markets/", "/markets/Dahanu/",
                    "/organizations/", "/methodology/", "/projects/?category=INFRASTRUCTURE&phase=APPROVED&investment_min=500",
                    "/projects/?sort=stage", "/markets/?verified=1"]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
        self.assertContains(self.client.get(f"/projects/{self.p.code}/"), "provisional")

    def test_dashboard_total_excludes_mou_and_wider_corridors(self):
        hsr = make_project(name="Bullet train", slug="hsr")
        f = InvestmentFigure.objects.create(project=hsr, amount_crore=108000, basis="REPORTED", scope="WIDER")
        f.sources.add(make_source())
        steel = make_project(name="Steel MoU", slug="steel", category="INDUSTRIAL")
        f = InvestmentFigure.objects.create(project=steel, amount_crore=12000, basis="MOU")
        f.sources.add(make_source())
        recompute_project(hsr)
        recompute_project(steel)
        ctx = self.client.get("/").context
        self.assertEqual(ctx["total_investment"], Decimal("76220"))
        self.assertEqual(ctx["wider_investment"], Decimal("108000"))
        self.assertEqual(ctx["mou_investment"], Decimal("12000"))

    def test_project_without_any_facts_renders(self):
        bare = make_project(name="Bare", slug="bare", micro_market="Vadhvan")
        for url in ["/projects/", f"/projects/{bare.code}/", "/markets/Vadhvan/", "/"]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
        self.assertContains(self.client.get("/projects/"), "No stage evidence")

    def test_geojson_and_csv(self):
        data = self.client.get("/api/projects.geojson").json()
        self.assertEqual(len(data["features"]), 1)
        resp = self.client.get("/projects/?format=csv")
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Vadhvan Port", resp.content.decode("utf-8"))

    def test_filters_combine(self):
        resp = self.client.get("/projects/?micro_market=Dahanu&category=INDUSTRIAL")
        self.assertEqual(resp.context["count"], 0)
        resp = self.client.get("/projects/?micro_market=Dahanu&investment_min=500")
        self.assertEqual(resp.context["count"], 1)

    def test_desk_requires_staff(self):
        for url in ["/review/", "/inbox/", "/entry/", "/research-log/new/"]:
            self.assertEqual(self.client.get(url).status_code, 302, url)

    def test_review_and_fact_entry(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/review/").status_code, 200)
        ev = self.p.events.get()
        self.client.post(f"/review/event/{ev.pk}/", {"decision": "approve"})
        self.p.refresh_from_db()
        self.assertFalse(self.p.stage_is_provisional)

        resp = self.client.post("/entry/", {
            "new_project_name": "Dahanu Logistics Park", "new_project_category": "LOGISTICS", "new_project_taluka": "Dahanu",
            "source_url": "https://news.example/park", "source_level": "SECONDARY",
            "event_date": "2025-02-01", "date_precision": "MONTH", "stage": "ANNOUNCED",
            "title": "Logistics park announced", "quote": "will set up a logistics park",
            "investment_crore": "500", "investment_basis": "MOU",
        })
        self.assertEqual(resp.status_code, 302)
        park = Project.objects.get(name="Dahanu Logistics Park")
        self.assertEqual(park.current_stage, "ANNOUNCED")
        self.assertEqual(park.headline_investment_basis, "MOU")
        self.assertEqual(park.coord_precision, "TALUKA")

        item = InboxItem.objects.create(url="https://news.example/v", title="Vadhvan port tender", normalized_title="vadhvan port tender")
        resp = self.client.get(f"/inbox/{item.pk}/process/")
        self.assertContains(resp, "Vadhvan Port")  # matching suggestion shown
