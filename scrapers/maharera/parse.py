"""Pure, deterministic parsers for MahaRERA pages (HTML/JSON in -> dict out).

No network access and no randomness here; every function is safe to unit-test
against saved fixtures.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE_URL = "https://maharera.maharashtra.gov.in"

PROJECT_KEYS = (
    "rera_no", "project_name", "promoter", "district", "taluka", "village", "address",
    "pincode", "project_type", "survey_numbers", "land_area_sqm", "total_units",
    "booked_units", "registration_date", "proposed_completion_date",
    "revised_completion_date", "status", "latitude", "longitude", "detail_url",
    "fetched_at", "raw_path", "extra",
)

# --------------------------------------------------------------------- primitives
_WS = re.compile(r"\s+")


def clean(text: Any) -> Optional[str]:
    """Collapse whitespace; return None for empty / placeholder values."""
    if text is None:
        return None
    s = _WS.sub(" ", str(text).replace("\xa0", " ")).strip()
    if s in ("", "-", "--", "NA", "N/A", "n/a", "na", "null", "None", "Not Available"):
        return None
    return s


_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
    "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y", "%d/%m/%y", "%Y/%m/%d", "%d-%b-%y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M",
)


def parse_date(text: Any) -> Optional[str]:
    """Normalise a date string to YYYY-MM-DD. Unparseable -> None (never guessed)."""
    s = clean(text)
    if not s:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    if re.search(r"\d[T ]\d\d:\d\d", s):  # only ISO date-times carry fractions / time zones
        s = re.sub(r"\.\d+(Z|[+-]\d\d:?\d\d)?$", "", s)
        s = re.sub(r"(Z|[+-]\d\d:?\d\d)$", "", s)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
        except ValueError:
            return None
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
        except ValueError:
            return None
    return None


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_float(text: Any) -> Optional[float]:
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    s = clean(text)
    if not s:
        return None
    m = _NUM.search(s.replace(",", ""))
    return float(m.group(0)) if m else None


def parse_int(text: Any) -> Optional[int]:
    """Integer value, or None when absent or not a whole number."""
    f = parse_float(text)
    if f is None or f != int(f):
        return None
    return int(f)


def parse_pincode(text: Any) -> Optional[str]:
    s = clean(text)
    if not s:
        return None
    m = re.search(r"(?<!\d)([1-9]\d{5})(?!\d)", s)
    return m.group(1) if m else None


RERA_NO_RE = re.compile(r"\b(P[RM]?\d{9,14}|PR\d{8,14}|P\d{11})\b")


def find_rera_no(text: Any) -> Optional[str]:
    s = clean(text)
    if not s:
        return None
    m = RERA_NO_RE.search(s)
    return m.group(1) if m else None


def empty_project() -> dict:
    rec = {k: None for k in PROJECT_KEYS}
    rec["extra"] = {}
    return rec


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# --------------------------------------------------------------------- listing pages
# The search-results markup has not been captured from the live site yet (it was too
# slow to answer during development), so these parsers are deliberately generic: they
# anchor on MahaRERA registration numbers and on label/value pairs, not on CSS classes.

_ROW_TAGS = ("tr", "li", "article")
_DETAIL_HINTS = ("view", "detail", "maharerait", "project/", "projectdetails", "public/project")


def _row_container(node):
    """Closest ancestor that looks like one result row/card."""
    for parent in node.parents:
        if parent.name in _ROW_TAGS:
            return parent
        cls = " ".join(parent.get("class") or []).lower()
        if parent.name == "div" and any(k in cls for k in ("row", "card", "shadow", "result", "views-row", "project")):
            if len(parent.get_text(" ", strip=True)) < 3000:
                return parent
    return node.parent


def parse_listing(html: str, page_url: str = BASE_URL) -> list[dict]:
    """Rows of a search-results page: one dict per distinct RERA number found."""
    soup = soup_of(html)
    rows, seen = [], set()
    for text_node in soup.find_all(string=RERA_NO_RE):
        rera_no = find_rera_no(text_node)
        if not rera_no or rera_no in seen:
            continue
        box = _row_container(text_node)
        seen.add(rera_no)
        texts = [t for t in (clean(s) for s in box.stripped_strings) if t]
        link = None
        for a in box.find_all("a", href=True):
            if any(h in a["href"].lower() for h in _DETAIL_HINTS):
                link = urljoin(page_url, a["href"])
                break
        name = None
        for tag in box.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"]):
            t = clean(tag.get_text(" "))
            if t and not RERA_NO_RE.search(t):
                name = t
                break
        rows.append({
            "rera_no": rera_no,
            "project_name": name,
            "detail_url": link,
            "extra": {"listing_text": " | ".join(texts)[:2000]},
        })
    return rows


def next_page_url(html: str, page_url: str) -> Optional[str]:
    soup = soup_of(html)
    a = soup.find("a", rel=lambda v: v and "next" in v) or soup.select_one("li.pager__item--next a, li.next a, a.next")
    if a is None:
        for cand in soup.find_all("a", href=True):
            if clean(cand.get_text(" ")) in ("Next", "Next ›", "›", "»", "Next »", "next"):
                a = cand
                break
    return urljoin(page_url, a["href"]) if a is not None and a.get("href") else None


# --------------------------------------------------------------------- detail pages
def label_value_pairs(html: str) -> list[tuple[str, str]]:
    """Every (label, value) pair visible on a page: table rows, dt/dd, and 'Label : value' text."""
    soup = soup_of(html)
    pairs: list[tuple[str, str]] = []
    for tr in soup.find_all("tr"):
        cells = [c for c in (clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])) if c]
        for i in range(0, len(cells) - 1, 2):
            pairs.append((cells[i], cells[i + 1]))
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            k, v = clean(dt.get_text(" ")), clean(dd.get_text(" "))
            if k and v:
                pairs.append((k, v))
    for node in soup.find_all(["label", "span", "div", "p", "b", "strong"]):
        if node.find(["div", "table", "ul", "p"]):
            continue
        t = clean(node.get_text(" "))
        if not t:
            continue
        if ":" in t and len(t) < 300:
            k, _, v = t.partition(":")
            k, v = clean(k), clean(v)
            if k and v and len(k) < 80:
                pairs.append((k, v))
        elif len(t) < 80 and node.name in ("label", "b", "strong"):
            sib = node.find_next_sibling()
            v = clean(sib.get_text(" ")) if sib is not None else None
            if v and len(v) < 500:
                pairs.append((t, v))
    return pairs


# (field, label keywords that must all appear, value kind). First match wins.
_FIELD_RULES = [
    ("rera_no", ("registration", "number"), "rera"),
    ("rera_no", ("rera", "no"), "rera"),
    ("project_name", ("project", "name"), "text"),
    ("promoter", ("promoter", "name"), "text"),
    ("promoter", ("organization", "name"), "text"),
    ("promoter", ("organisation", "name"), "text"),
    ("district", ("district",), "text"),
    ("taluka", ("taluka",), "text"),
    ("village", ("village",), "text"),
    ("pincode", ("pin",), "pincode"),
    ("project_type", ("project", "type"), "text"),
    ("survey_numbers", ("survey",), "text"),
    ("survey_numbers", ("cts",), "text"),
    ("land_area_sqm", ("land", "area"), "float"),
    ("total_units", ("total", "apartment"), "int"),
    ("total_units", ("total", "units"), "int"),
    ("total_units", ("number", "apartment"), "int"),
    ("booked_units", ("booked",), "int"),
    ("registration_date", ("registration", "date"), "date"),
    ("registration_date", ("date", "registration"), "date"),
    ("revised_completion_date", ("revised", "completion"), "date"),
    ("revised_completion_date", ("extended", "completion"), "date"),
    ("revised_completion_date", ("extension", "date"), "date"),
    ("proposed_completion_date", ("proposed", "completion"), "date"),
    ("proposed_completion_date", ("completion", "date"), "date"),
    ("status", ("project", "status"), "text"),
    ("status", ("registration", "status"), "text"),
    ("latitude", ("latitude",), "float"),
    ("longitude", ("longitude",), "float"),
]

_CONVERTERS = {"text": clean, "date": parse_date, "float": parse_float, "int": parse_int,
               "pincode": parse_pincode, "rera": find_rera_no}


def parse_detail(html: str, url: Optional[str] = None) -> dict:
    """Project record from a detail page. Unknown fields stay None — nothing is guessed."""
    rec = empty_project()
    rec["detail_url"] = url
    pairs = label_value_pairs(html)
    for label, value in pairs:
        low = label.lower()
        for field, words, kind in _FIELD_RULES:
            if rec[field] is not None or not all(w in low for w in words):
                continue
            if field == "proposed_completion_date" and ("revised" in low or "extend" in low):
                continue
            converted = _CONVERTERS[kind](value)
            if converted is not None:
                rec[field] = converted
                break
    if rec["rera_no"] is None:
        rec["rera_no"] = find_rera_no(soup_of(html).get_text(" "))
    rec["extra"]["fields"] = dict(pairs[:400])
    return rec
