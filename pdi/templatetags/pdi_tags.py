from decimal import Decimal
from urllib.parse import urlparse

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .. import vocab

register = template.Library()

STAGE_LABELS = dict(vocab.Stage.choices)
LEVEL_LABELS = dict(vocab.SourceLevel.choices)


@register.filter
def crore(value):
    """₹ crore with Indian digit grouping."""
    if value in (None, ""):
        return "—"
    v = Decimal(value)
    whole = int(v)
    s = str(abs(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    frac = abs(v - whole)
    out = s + (f"{frac:.2f}"[1:] if frac and abs(whole) < 100 else "")
    return f"₹{'-' if whole < 0 else ''}{out} cr"


@register.simple_tag
def stage_badge(stage, provisional=False):
    if not stage:
        return mark_safe('<span class="badge badge-muted">No stage evidence</span>')
    phase = vocab.phase_of(stage) or ("flag" if stage in vocab.FLAG_STAGES else "note")
    return format_html('<span class="badge stage-{}">{}{}</span>', phase.lower(), STAGE_LABELS.get(stage, stage),
                       " · provisional" if provisional else "")


@register.simple_tag
def level_badge(level):
    if not level:
        return mark_safe('<span class="badge badge-muted">No source</span>')
    return format_html('<span class="badge level-{}">{}</span>', level.lower(), LEVEL_LABELS.get(level, level))


@register.simple_tag
def review_badge(status):
    label = {"PENDING": "Pending review", "APPROVED": "Reviewed", "REJECTED": "Rejected"}.get(status, status)
    return format_html('<span class="badge review-{}">{}</span>', status.lower(), label)


@register.filter
def domain(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except ValueError:
        return url


@register.filter
def get_item(d, key):
    return d.get(key) if hasattr(d, "get") else None


@register.filter
def flag_label(flag):
    return STAGE_LABELS.get(flag, flag)
