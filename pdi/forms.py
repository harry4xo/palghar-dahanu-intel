from django import forms

from . import vocab
from .models import Project


def _blank(choices, label="Any"):
    return [("", label)] + list(choices)


class ProjectFilterForm(forms.Form):
    """All project filters (PRD §16–17). Every field is optional and they combine with AND."""

    q = forms.CharField(required=False, label="Search", widget=forms.TextInput(attrs={"placeholder": "Name, alias, code, village"}))
    micro_market = forms.MultipleChoiceField(required=False, choices=vocab.MICRO_MARKET_CHOICES)
    taluka = forms.MultipleChoiceField(required=False, choices=vocab.TALUKA_CHOICES)
    village = forms.CharField(required=False)
    category = forms.MultipleChoiceField(required=False, choices=vocab.Category.choices)
    subcategory = forms.CharField(required=False)
    stage = forms.MultipleChoiceField(required=False, choices=[(k, v) for k, v in vocab.Stage.choices if k in vocab.STAGE_ORDER])
    phase = forms.ChoiceField(required=False, choices=_blank([(k, v[0]) for k, v in vocab.PHASES.items()]))
    flag = forms.ChoiceField(required=False, choices=_blank([("DELAYED", "Delayed"), ("STALLED", "Stalled"), ("CANCELLED", "Cancelled")]))
    verification = forms.ChoiceField(required=False, choices=_blank(vocab.SourceLevel.choices))
    verified_only = forms.BooleanField(required=False, label="Reviewed facts only")
    importance = forms.ChoiceField(required=False, choices=_blank(vocab.Importance.choices))
    organization = forms.CharField(required=False, label="Developer / authority / investor")
    rera = forms.ChoiceField(required=False, label="MahaRERA", choices=[("", "Any"), ("yes", "Registered"), ("no", "Not registered")])
    investment_min = forms.DecimalField(required=False, label="Investment ≥ (₹ cr)")
    investment_max = forms.DecimalField(required=False, label="Investment ≤ (₹ cr)")
    land_min_ha = forms.DecimalField(required=False, label="Land ≥ (ha)")
    announced_from = forms.IntegerField(required=False, label="Announced from (year)")
    announced_to = forms.IntegerField(required=False, label="Announced to (year)")
    approval_year = forms.IntegerField(required=False)
    construction_year = forms.IntegerField(required=False)
    completion_year = forms.IntegerField(required=False)
    sort = forms.ChoiceField(required=False, choices=[
        ("name", "Name"), ("-headline_investment_crore", "Investment (high first)"),
        ("-announcement_date", "Most recently announced"), ("-updated_at", "Recently updated"),
        ("stage", "Stage (furthest first)"),
    ])


class QuickFactForm(forms.Form):
    """One screen to record one sourced fact — the researcher's main tool."""

    # Project
    project = forms.ModelChoiceField(queryset=Project.objects.order_by("name"), required=False,
                                     help_text="Pick an existing project, or fill 'new project' below")
    new_project_name = forms.CharField(required=False, max_length=255)
    new_project_category = forms.ChoiceField(required=False, choices=_blank(vocab.Category.choices, "—"))
    new_project_taluka = forms.ChoiceField(required=False, choices=_blank(vocab.TALUKA_CHOICES, "—"))
    new_project_village = forms.CharField(required=False, max_length=120)

    # Source
    source_url = forms.URLField(max_length=1000, help_text="If this is a news.google.com link, open it and paste the publisher's own article URL instead")
    source_title = forms.CharField(max_length=500, required=False)
    source_publisher = forms.CharField(max_length=200, required=False)
    source_level = forms.ChoiceField(choices=vocab.SourceLevel.choices)
    source_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    # Event
    event_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    date_precision = forms.ChoiceField(choices=vocab.DatePrecision.choices)
    stage = forms.ChoiceField(choices=vocab.Stage.choices)
    title = forms.CharField(max_length=300)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    quote = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), help_text="Copy the exact words from the source that prove this")

    # Optional investment figure stated by the same source
    investment_crore = forms.DecimalField(required=False, label="Investment stated (₹ crore)")
    investment_basis = forms.ChoiceField(required=False, choices=_blank(vocab.InvestmentBasis.choices, "—"))

    approve_now = forms.BooleanField(required=False, label="I checked this against the source — mark as approved")

    def clean(self):
        data = super().clean()
        if not data.get("project") and not data.get("new_project_name"):
            raise forms.ValidationError("Choose an existing project or give a name for a new one.")
        if not data.get("project") and not data.get("new_project_category"):
            self.add_error("new_project_category", "Category is required for a new project.")
        if data.get("investment_crore") is not None and not data.get("investment_basis"):
            self.add_error("investment_basis", "Say what kind of figure this is (MoU values are not investments).")
        return data


class ResearchLogForm(forms.Form):
    micro_market = forms.ChoiceField(choices=vocab.MICRO_MARKET_CHOICES)
    dimension = forms.ChoiceField(choices=vocab.ACTIVITY_DIMENSIONS)
    period_start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    period_end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    sources_searched = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    result = forms.ChoiceField(choices=[("NONE", "No material verified development"), ("FOUND", "Development found")])
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
