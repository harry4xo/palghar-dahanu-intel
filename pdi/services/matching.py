"""Rule-based duplicate matching (no AI).

Order of evidence, strongest first:
  1. Same MahaRERA registration number            → certain
  2. Exact name / alias match (normalised)         → strong
  3. Same transliteration skeleton                 → strong  (Vadhvan = Vadhavan = Wadhwan)
  4. Fuzzy name similarity ≥ 0.82 on the skeleton  → possible
  5. Same survey numbers + village                 → possible
Anything below "certain" is shown to a researcher as a suggestion, never merged automatically.
"""

import re
from difflib import SequenceMatcher

from ..models import LandRecord, Project, ProjectAlias, ReraProject, normalize_name

STOPWORDS = {
    "project", "projects", "the", "ltd", "limited", "pvt", "private", "and", "of", "at", "in",
    "phase", "proposed", "new", "scheme", "plan", "maharashtra", "palghar", "district",
}

RERA_RE = re.compile(r"\b(P\d{11}|PR[A-Z0-9]{6,})\b", re.I)


def skeleton(text):
    """Consonant skeleton that survives common English/Marathi transliteration variants."""
    words = [w for w in normalize_name(text).split() if w not in STOPWORDS]
    out = []
    for w in words:
        w = w.replace("w", "v").replace("ph", "f").replace("sh", "s").replace("ch", "c")
        w = w.replace("h", "")
        w = re.sub(r"[aeiouy]", "", w)
        w = re.sub(r"(.)\1+", r"\1", w)
        if w:
            out.append(w)
    return " ".join(out)


def find_rera_numbers(text):
    return sorted({m.upper() for m in RERA_RE.findall(text or "")})


def candidates(name="", text="", village="", survey_numbers="", limit=8):
    """Return [(project, confidence, reason)] best first."""
    found = {}

    def add(project, confidence, reason):
        prev = found.get(project.pk)
        rank = {"certain": 3, "strong": 2, "possible": 1}
        if prev is None or rank[confidence] > rank[prev[1]]:
            found[project.pk] = (project, confidence, reason)

    for rera_no in find_rera_numbers(f"{name} {text}"):
        for r in ReraProject.objects.filter(rera_no__iexact=rera_no, project__isnull=False).select_related("project"):
            add(r.project, "certain", f"Same MahaRERA number {rera_no}")

    if name:
        norm = normalize_name(name)
        skel = skeleton(name)
        for p in Project.objects.filter(name__iexact=name):
            add(p, "strong", "Same project name")
        for a in ProjectAlias.objects.filter(normalized=norm).select_related("project"):
            add(a.project, "strong", f"Matches alternate name “{a.name}”")
        if skel:
            pool = list(Project.objects.only("id", "name", "code", "slug"))
            alias_pool = list(ProjectAlias.objects.select_related("project"))
            for p in pool:
                ps = skeleton(p.name)
                if ps and ps == skel:
                    add(p, "strong", "Same name after spelling normalisation")
                elif ps and SequenceMatcher(None, ps, skel).ratio() >= 0.82:
                    add(p, "possible", "Similar name")
            for a in alias_pool:
                s = skeleton(a.name)
                if s and s == skel:
                    add(a.project, "strong", f"Alternate name “{a.name}” after spelling normalisation")

    # Mentions of known project names / aliases inside free text (e.g. a news headline).
    if text:
        text_skel = f" {skeleton(text)} "
        for p in Project.objects.only("id", "name", "code", "slug"):
            ps = skeleton(p.name)
            if ps and len(ps) >= 3 and f" {ps} " in text_skel:
                add(p, "possible", "Project name appears in the text")
        for a in ProjectAlias.objects.select_related("project"):
            s = skeleton(a.name)
            if s and len(s) >= 3 and f" {s} " in text_skel:
                add(a.project, "possible", f"Alternate name “{a.name}” appears in the text")

    if survey_numbers and village:
        wanted = {s.strip().lower() for s in re.split(r"[,;/ ]+", survey_numbers) if s.strip()}
        for rec in LandRecord.objects.filter(village__iexact=village, project__isnull=False).select_related("project"):
            have = {s.strip().lower() for s in re.split(r"[,;/ ]+", rec.survey_numbers) if s.strip()}
            if wanted & have:
                add(rec.project, "possible", f"Shares survey no. {', '.join(sorted(wanted & have))} in {village}")

    rank = {"certain": 3, "strong": 2, "possible": 1}
    return sorted(found.values(), key=lambda t: (-rank[t[1]], t[0].name))[:limit]
