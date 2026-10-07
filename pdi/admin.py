from django.contrib import admin, messages

from . import models
from .services.status import recompute_project, review_fact

admin.site.site_header = "Palghar–Dahanu Development Intelligence — Research desk"
admin.site.site_title = "PDI research desk"
admin.site.index_title = "Data entry & review"


def _review_action(approve):
    def action(modeladmin, request, queryset):
        for fact in queryset:
            review_fact(fact, request.user, approve=approve)
        modeladmin.message_user(request, f"{queryset.count()} item(s) {'approved' if approve else 'rejected'}.", messages.SUCCESS)
    action.short_description = "Approve selected (verified against source)" if approve else "Reject selected"
    action.__name__ = "approve_selected" if approve else "reject_selected"
    return action


class FactAdmin(admin.ModelAdmin):
    actions = [_review_action(True), _review_action(False)]
    autocomplete_fields = ["sources"]
    readonly_fields = ["origin", "entered_by", "reviewed_by", "reviewed_at", "created_at"]
    list_filter = ["review_status", "origin"]

    def save_model(self, request, obj, form, change):
        if not change and not obj.entered_by:
            obj.entered_by = request.user.get_username()
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        project = getattr(form.instance, "project", None) or getattr(form.instance, "from_project", None)
        if project:
            recompute_project(project)


class FactInline(admin.StackedInline):
    extra = 0
    autocomplete_fields = ["sources"]
    readonly_fields = ["review_status", "origin", "entered_by", "reviewed_at"]
    show_change_link = True


class EventInline(FactInline):
    model = models.Event
    fields = ["date", "date_precision", "stage", "title", "description", "quote", "sources", "review_status", "origin", "entered_by", "reviewed_at"]


class InvestmentInline(FactInline):
    model = models.InvestmentFigure
    fields = ["amount_crore", "basis", "as_of", "note", "quote", "sources", "review_status", "origin"]


class FundingInline(FactInline):
    model = models.FundingEvent
    fields = ["date", "amount_crore", "stage", "funding_type", "financier", "note", "quote", "sources", "review_status"]


class LandInline(FactInline):
    model = models.LandRecord
    fields = ["date", "taluka", "village", "survey_numbers", "area_hectares", "area_text", "purpose", "acquirer",
              "status", "consideration_crore", "quote", "sources", "review_status"]


class RegulatoryInline(FactInline):
    model = models.RegulatoryItem
    fields = ["date", "item_type", "authority", "status", "title", "reference_no", "quote", "sources", "review_status"]


class RelationshipInline(FactInline):
    model = models.ProjectRelationship
    fk_name = "from_project"
    autocomplete_fields = ["sources", "to_project"]
    fields = ["rel_type", "to_project", "note", "quote", "sources", "review_status"]


class AliasInline(admin.TabularInline):
    model = models.ProjectAlias
    extra = 0
    fields = ["name"]


class ProjectOrgInline(admin.TabularInline):
    model = models.ProjectOrganization
    extra = 0
    autocomplete_fields = ["organization"]


@admin.register(models.Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "category", "micro_market", "current_stage", "stage_is_provisional",
                    "verification_level", "source_count", "pending_review_count", "strategic_importance"]
    list_filter = ["category", "micro_market", "taluka", "current_stage", "verification_level", "strategic_importance", "stage_is_provisional"]
    search_fields = ["code", "name", "aliases__name", "village", "promoter__name"]
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ["promoter", "location"]
    readonly_fields = ["code", "current_stage", "current_stage_date", "stage_is_provisional", "flags", "verification_level",
                       "source_count", "corroborated", "announcement_date", "approval_date", "construction_start_date",
                       "expected_completion", "actual_completion", "headline_investment_crore", "headline_investment_basis",
                       "last_verified_at", "pending_review_count", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["code", "name", "slug", "category", "subcategory", "description", "strategic_importance", "promoter"]}),
        ("Location", {"fields": ["district", "taluka", "village", "micro_market", "location", "latitude", "longitude", "coord_precision"]}),
        ("Derived from approved facts (read-only)", {"classes": ["collapse"], "fields": [
            "current_stage", "current_stage_date", "stage_is_provisional", "flags", "verification_level", "source_count",
            "corroborated", "announcement_date", "approval_date", "construction_start_date", "expected_completion",
            "actual_completion", "headline_investment_crore", "headline_investment_basis", "last_verified_at",
            "pending_review_count", "created_at", "updated_at"]}),
    ]
    inlines = [AliasInline, ProjectOrgInline, EventInline, InvestmentInline, FundingInline, LandInline, RegulatoryInline, RelationshipInline]
    actions = ["recompute_selected"]

    @admin.action(description="Recompute derived fields")
    def recompute_selected(self, request, queryset):
        for p in queryset:
            recompute_project(p)
        self.message_user(request, f"Recomputed {queryset.count()} project(s).")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        recompute_project(form.instance)


@admin.register(models.Event)
class EventAdmin(FactAdmin):
    list_display = ["date", "project", "stage", "title", "review_status", "origin"]
    list_filter = ["review_status", "origin", "stage", "project__category", "project__micro_market"]
    search_fields = ["title", "description", "quote", "project__name"]
    autocomplete_fields = ["sources", "project"]
    date_hierarchy = "date"


@admin.register(models.InvestmentFigure)
class InvestmentAdmin(FactAdmin):
    list_display = ["project", "amount_crore", "basis", "as_of", "review_status"]
    list_filter = ["review_status", "basis"]
    search_fields = ["project__name", "note"]
    autocomplete_fields = ["sources", "project"]


@admin.register(models.FundingEvent)
class FundingAdmin(FactAdmin):
    list_display = ["project", "date", "amount_crore", "stage", "funding_type", "financier", "review_status"]
    list_filter = ["review_status", "stage", "funding_type"]
    search_fields = ["project__name", "financier"]
    autocomplete_fields = ["sources", "project"]


@admin.register(models.LandRecord)
class LandAdmin(FactAdmin):
    list_display = ["date", "village", "taluka", "survey_numbers", "area_hectares", "status", "project", "review_status"]
    list_filter = ["review_status", "status", "taluka", "micro_market"]
    search_fields = ["village", "survey_numbers", "purpose", "acquirer", "project__name"]
    autocomplete_fields = ["sources", "project"]


@admin.register(models.RegulatoryItem)
class RegulatoryAdmin(FactAdmin):
    list_display = ["date", "item_type", "title", "status", "authority", "project", "review_status"]
    list_filter = ["review_status", "item_type", "status", "micro_market"]
    search_fields = ["title", "authority", "reference_no", "project__name"]
    autocomplete_fields = ["sources", "project"]


@admin.register(models.ProjectRelationship)
class RelationshipAdmin(FactAdmin):
    list_display = ["from_project", "rel_type", "to_project", "review_status"]
    list_filter = ["review_status", "rel_type"]
    autocomplete_fields = ["sources", "from_project", "to_project"]


@admin.register(models.Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["title", "publisher", "level", "published_date", "archived_at"]
    list_filter = ["level", "publisher"]
    search_fields = ["title", "url", "publisher"]
    readonly_fields = ["archive_path", "archive_sha256", "archived_at"]


@admin.register(models.Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "org_type"]
    list_filter = ["org_type"]
    search_fields = ["name", "aliases"]


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "taluka", "micro_market", "latitude", "longitude"]
    list_filter = ["taluka", "micro_market"]
    search_fields = ["name", "alternate_names"]


@admin.register(models.ResearchLog)
class ResearchLogAdmin(admin.ModelAdmin):
    list_display = ["micro_market", "dimension", "period_start", "period_end", "result", "researcher", "logged_at"]
    list_filter = ["result", "micro_market", "dimension"]


class SnapshotInline(admin.TabularInline):
    model = models.ReraSnapshot
    extra = 0
    fields = ["fetched_at", "raw_path"]
    readonly_fields = fields
    can_delete = False


@admin.register(models.ReraProject)
class ReraProjectAdmin(admin.ModelAdmin):
    list_display = ["rera_no", "project_name", "promoter", "taluka", "village", "registration_date", "revised_completion_date", "status"]
    list_filter = ["taluka", "status"]
    search_fields = ["rera_no", "project_name", "promoter", "village", "survey_numbers"]
    autocomplete_fields = ["project"]
    inlines = [SnapshotInline]


@admin.register(models.WatchQuery)
class WatchQueryAdmin(admin.ModelAdmin):
    list_display = ["name", "language", "active", "last_checked_at", "last_error"]


@admin.register(models.InboxItem)
class InboxItemAdmin(admin.ModelAdmin):
    list_display = ["title", "publisher", "published_at", "score", "status", "project"]
    list_filter = ["status", "query"]
    search_fields = ["title", "snippet", "matched_places"]
