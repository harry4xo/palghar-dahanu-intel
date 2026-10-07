"""Data model.

Design rule: facts are stored as rows with their own sources and review status, never as
bare fields on the project. A project's "current status", verification level and
headline investment are *derived* from approved facts (see services/status.py), so
conflicting information is preserved and history is never overwritten.
"""

import re

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from . import vocab


def normalize_name(value):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (value or "").lower())).strip()


class Location(models.Model):
    district = models.CharField(max_length=60, default="Palghar")
    taluka = models.CharField(max_length=60, choices=vocab.TALUKA_CHOICES)
    name = models.CharField(max_length=120, help_text="Village / town name")
    alternate_names = models.TextField(blank=True, help_text="One per line (English or Marathi spellings)")
    micro_market = models.CharField(max_length=60, choices=vocab.MICRO_MARKET_CHOICES)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    coord_source = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [("taluka", "name")]
        ordering = ["taluka", "name"]

    def __str__(self):
        return f"{self.name} ({self.taluka})"

    def all_names(self):
        names = [self.name] + [n.strip() for n in self.alternate_names.splitlines() if n.strip()]
        return names


class Organization(models.Model):
    name = models.CharField(max_length=255, unique=True)
    org_type = models.CharField(max_length=20, choices=vocab.OrgType.choices, default=vocab.OrgType.OTHER)
    aliases = models.TextField(blank=True, help_text="One per line")
    website = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("pdi:organization_detail", args=[self.pk])


class Source(models.Model):
    url = models.URLField(max_length=1000, unique=True)
    title = models.CharField(max_length=500, blank=True)
    publisher = models.CharField(max_length=200, blank=True)
    level = models.CharField(max_length=12, choices=vocab.SourceLevel.choices)
    published_date = models.DateField(null=True, blank=True)
    accessed_at = models.DateTimeField(default=timezone.now)
    archive_path = models.CharField(max_length=500, blank=True, help_text="Local copy, relative to data/")
    archive_sha256 = models.CharField(max_length=64, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["level", "-published_date"]

    def __str__(self):
        return self.title or self.url

    @property
    def level_rank(self):
        return vocab.SOURCE_LEVEL_RANK.get(self.level, 9)


def next_project_code():
    last = Project.objects.order_by("-id").values_list("code", flat=True).first()
    n = 0
    if last and last.startswith("PDI-"):
        try:
            n = int(last[4:])
        except ValueError:
            n = Project.objects.count()
    return f"PDI-{n + 1:05d}"


class Project(models.Model):
    """Common Project Master (PRD §13)."""

    code = models.CharField(max_length=12, unique=True, editable=False)
    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=vocab.Category.choices)
    subcategory = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    district = models.CharField(max_length=60, default="Palghar")
    taluka = models.CharField(max_length=60, choices=vocab.TALUKA_CHOICES, blank=True)
    village = models.CharField(max_length=120, blank=True)
    micro_market = models.CharField(max_length=60, choices=vocab.MICRO_MARKET_CHOICES, blank=True)
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    coord_precision = models.CharField(
        max_length=20, blank=True,
        choices=[("EXACT", "Exact site"), ("VILLAGE", "Village centroid (approximate)"), ("TALUKA", "Taluka (approximate)")],
    )

    promoter = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="promoted_projects")
    organizations = models.ManyToManyField(Organization, through="ProjectOrganization", related_name="projects", blank=True)
    strategic_importance = models.CharField(max_length=6, choices=vocab.Importance.choices, default=vocab.Importance.MEDIUM)

    # ---- Derived fields (recomputed by services.status.recompute_project) ----
    current_stage = models.CharField(max_length=24, choices=vocab.Stage.choices, blank=True)
    current_stage_date = models.DateField(null=True, blank=True)
    stage_is_provisional = models.BooleanField(default=False, help_text="True when only unreviewed facts support the stage")
    flags = models.CharField(max_length=100, blank=True, help_text="Active flags, comma separated")
    verification_level = models.CharField(max_length=12, choices=vocab.SourceLevel.choices, blank=True)
    source_count = models.PositiveIntegerField(default=0)
    corroborated = models.BooleanField(default=False, help_text="At least two independent publishers")
    announcement_date = models.DateField(null=True, blank=True)
    approval_date = models.DateField(null=True, blank=True)
    construction_start_date = models.DateField(null=True, blank=True)
    expected_completion = models.DateField(null=True, blank=True)
    actual_completion = models.DateField(null=True, blank=True)
    headline_investment_crore = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    headline_investment_basis = models.CharField(max_length=12, choices=vocab.InvestmentBasis.choices, blank=True)
    headline_investment_scope = models.CharField(max_length=8, choices=vocab.InvestmentScope.choices, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    pending_review_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_project_code()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("pdi:project_detail", args=[self.code])

    @property
    def phase(self):
        return vocab.phase_of(self.current_stage)

    @property
    def flag_list(self):
        return [f for f in self.flags.split(",") if f]


class ProjectAlias(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="aliases")
    name = models.CharField(max_length=255)
    normalized = models.CharField(max_length=255, db_index=True, editable=False)

    class Meta:
        unique_together = [("project", "normalized")]
        verbose_name_plural = "project aliases"

    def save(self, *args, **kwargs):
        self.normalized = normalize_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProjectOrganization(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    role = models.CharField(max_length=12, choices=vocab.OrgRole.choices)

    class Meta:
        unique_together = [("project", "organization", "role")]

    def __str__(self):
        return f"{self.organization} — {self.get_role_display()}"


class Fact(models.Model):
    """Common fields for every sourced, reviewable fact."""

    sources = models.ManyToManyField(Source, related_name="%(class)s_items", blank=True)
    quote = models.TextField(blank=True, help_text="Short verbatim snippet from the source supporting this fact")
    review_status = models.CharField(max_length=10, choices=vocab.ReviewStatus.choices, default=vocab.ReviewStatus.PENDING, db_index=True)
    origin = models.CharField(max_length=10, choices=vocab.Origin.choices, default=vocab.Origin.MANUAL)
    entered_by = models.CharField(max_length=150, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def best_level(self):
        ranks = [s.level_rank for s in self.sources.all()]
        if not ranks:
            return ""
        best = min(ranks)
        return {v: k for k, v in vocab.SOURCE_LEVEL_RANK.items()}[best]


class Event(Fact):
    """A dated timeline entry; stage events move the project along its lifecycle."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="events")
    date = models.DateField()
    date_precision = models.CharField(max_length=5, choices=vocab.DatePrecision.choices, default=vocab.DatePrecision.DAY)
    stage = models.CharField(max_length=24, choices=vocab.Stage.choices)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["date", "id"]

    def __str__(self):
        return f"{self.date} {self.get_stage_display()}: {self.title}"

    @property
    def display_date(self):
        if self.date_precision == "YEAR":
            return self.date.strftime("%Y")
        if self.date_precision == "MONTH":
            return self.date.strftime("%b %Y")
        return self.date.strftime("%d %b %Y")


class InvestmentFigure(Fact):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="investments")
    amount_crore = models.DecimalField(max_digits=14, decimal_places=2)
    basis = models.CharField(max_length=12, choices=vocab.InvestmentBasis.choices)
    as_of = models.DateField(null=True, blank=True)
    scope = models.CharField(max_length=8, choices=vocab.InvestmentScope.choices, default=vocab.InvestmentScope.PROJECT,
                             help_text="WIDER when the figure covers a corridor/project extending beyond Palghar district")
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-as_of"]

    def __str__(self):
        return f"₹{self.amount_crore} cr ({self.get_basis_display()})"


class FundingEvent(Fact):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="funding")
    date = models.DateField(null=True, blank=True)
    amount_crore = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    stage = models.CharField(max_length=10, choices=vocab.FundingStage.choices)
    funding_type = models.CharField(max_length=12, choices=vocab.FundingType.choices, default=vocab.FundingType.OTHER)
    financier = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_stage_display()} funding — {self.financier or 'unknown'}"


class LandRecord(Fact):
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="land_records")
    taluka = models.CharField(max_length=60, choices=vocab.TALUKA_CHOICES, blank=True)
    village = models.CharField(max_length=120, blank=True)
    micro_market = models.CharField(max_length=60, choices=vocab.MICRO_MARKET_CHOICES, blank=True)
    survey_numbers = models.CharField(max_length=500, blank=True, help_text="Survey / Gat numbers as written in the source")
    area_hectares = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    area_text = models.CharField(max_length=200, blank=True, help_text="Area exactly as stated, if not in hectares")
    purpose = models.CharField(max_length=200, blank=True)
    acquirer = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=vocab.LandStatus.choices, default=vocab.LandStatus.OTHER)
    date = models.DateField(null=True, blank=True)
    consideration_crore = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Land — {self.village or self.taluka} ({self.get_status_display()})"


class RegulatoryItem(Fact):
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="regulatory_items")
    item_type = models.CharField(max_length=32, choices=vocab.RegulatoryType.choices)
    authority = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=vocab.RegulatoryStatus.choices, default=vocab.RegulatoryStatus.OTHER)
    date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=300)
    reference_no = models.CharField(max_length=200, blank=True)
    taluka = models.CharField(max_length=60, choices=vocab.TALUKA_CHOICES, blank=True)
    micro_market = models.CharField(max_length=60, choices=vocab.MICRO_MARKET_CHOICES, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_item_type_display()}: {self.title}"


class ProjectRelationship(Fact):
    """Evidence-backed link between projects (PRD §11 strategic drivers, §20 intelligence layer)."""

    from_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="relationships_out")
    to_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="relationships_in")
    rel_type = models.CharField(max_length=20, choices=vocab.RelationshipType.choices)
    note = models.TextField(blank=True, help_text="What the evidence says about the link")

    class Meta:
        unique_together = [("from_project", "to_project", "rel_type")]

    def __str__(self):
        return f"{self.from_project.name} → {self.get_rel_type_display()} → {self.to_project.name}"


class ResearchLog(models.Model):
    """Records searches, including ones that found nothing (PRD §21 'no material development')."""

    micro_market = models.CharField(max_length=60, choices=vocab.MICRO_MARKET_CHOICES)
    dimension = models.CharField(max_length=20, choices=vocab.ACTIVITY_DIMENSIONS)
    period_start = models.DateField()
    period_end = models.DateField()
    sources_searched = models.TextField(help_text="Portals, search terms and archives checked")
    result = models.CharField(max_length=20, choices=[("FOUND", "Development found"), ("NONE", "No material verified development")])
    notes = models.TextField(blank=True)
    researcher = models.CharField(max_length=150, blank=True)
    logged_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-logged_at"]

    def __str__(self):
        return f"{self.micro_market} / {self.get_dimension_display()} — {self.get_result_display()}"


class ReraProject(models.Model):
    """Latest MahaRERA state for one registration; history lives in ReraSnapshot."""

    rera_no = models.CharField(max_length=40, unique=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="rera_registrations")
    project_name = models.CharField(max_length=300, blank=True)
    promoter = models.CharField(max_length=300, blank=True)
    taluka = models.CharField(max_length=60, blank=True)
    village = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    project_type = models.CharField(max_length=100, blank=True)
    survey_numbers = models.TextField(blank=True)
    land_area_sqm = models.FloatField(null=True, blank=True)
    total_units = models.IntegerField(null=True, blank=True)
    booked_units = models.IntegerField(null=True, blank=True)
    registration_date = models.DateField(null=True, blank=True)
    proposed_completion_date = models.DateField(null=True, blank=True)
    revised_completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    detail_url = models.URLField(max_length=1000, blank=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-registration_date"]
        verbose_name = "MahaRERA registration"

    def __str__(self):
        return f"{self.rera_no} · {self.project_name}"


class ReraSnapshot(models.Model):
    rera = models.ForeignKey(ReraProject, on_delete=models.CASCADE, related_name="snapshots")
    fetched_at = models.DateTimeField()
    data = models.JSONField()
    raw_path = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-fetched_at"]
        unique_together = [("rera", "fetched_at")]


class WatchQuery(models.Model):
    """A feed or search the monitor checks for new documents (keyword based, no AI)."""

    name = models.CharField(max_length=150)
    feed_url = models.URLField(max_length=1000, unique=True)
    language = models.CharField(max_length=5, default="en")
    active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "watch queries"

    def __str__(self):
        return self.name


class InboxItem(models.Model):
    """A document found by the monitor, waiting for a researcher to process it."""

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        PROCESSED = "PROCESSED", "Processed"
        IGNORED = "IGNORED", "Ignored"

    url = models.URLField(max_length=1000, unique=True)
    title = models.CharField(max_length=500)
    normalized_title = models.CharField(max_length=500, db_index=True)
    publisher = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    snippet = models.TextField(blank=True)
    query = models.ForeignKey(WatchQuery, null=True, blank=True, on_delete=models.SET_NULL)
    matched_places = models.CharField(max_length=500, blank=True)
    matched_topics = models.CharField(max_length=500, blank=True)
    score = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="inbox_items")
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-score", "-published_at"]

    def __str__(self):
        return self.title
