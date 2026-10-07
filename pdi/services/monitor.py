"""Keyword-based monitoring of news / notice feeds (no AI).

Each WatchQuery is an RSS/Atom feed (e.g. a Google News search). New entries are scored by
plain keyword matching: a document must mention at least one Palghar place name, and gets a
higher score for development topic words. Matches land in the researcher inbox.
"""

import html
import re
from datetime import datetime, timezone as dt_timezone
from urllib.parse import quote_plus

import feedparser
import requests
from django.conf import settings
from django.utils import timezone

from ..models import InboxItem, Location, WatchQuery, normalize_name

TOPIC_TERMS = [
    # English
    "project", "port", "midc", "industrial", "tender", "contract", "awarded", "acquisition", "land",
    "approval", "approved", "clearance", "crz", "environment", "notification", "expressway", "highway",
    "railway", "corridor", "bullet train", "freight", "logistics", "warehouse", "data centre", "data center",
    "township", "rera", "housing", "investment", "crore", "mou", "factory", "plant", "construction",
    "foundation stone", "inaugurat", "dtepa", "high court", "ngt", "development plan", "zoning",
    # Marathi
    "प्रकल्प", "बंदर", "भूसंपादन", "जमीन", "निविदा", "मंजुरी", "एमआयडीसी", "औद्योगिक", "महामार्ग",
    "रेल्वे", "गुंतवणूक", "कोटी", "बांधकाम", "पर्यावरण", "अधिसूचना", "गृहनिर्माण",
]

EXTRA_PLACES = ["Palghar", "पालघर", "Dahanu", "डहाणू", "Vadhvan", "Vadhavan", "Wadhwan", "वाढवण", "Boisar", "बोईसर",
                "Tarapur", "तारापूर", "Talasari", "तलासरी", "Murbe", "मुरबे", "Saphale", "सफाळे", "Wada", "वाडा"]

DEFAULT_QUERIES = [
    ("Vadhvan port (news)", "Vadhvan OR Vadhavan port", "en"),
    ("Palghar development (news)", "Palghar project OR MIDC OR land acquisition", "en"),
    ("Dahanu development (news)", "Dahanu project OR port OR DTEPA", "en"),
    ("Boisar–Tarapur industry (news)", "Boisar OR Tarapur MIDC", "en"),
    ("Palghar real estate (news)", "Palghar real estate OR township OR RERA", "en"),
    ("Palghar infrastructure (news)", "Palghar expressway OR bullet train OR freight corridor", "en"),
    ("वाढवण बंदर (मराठी)", "वाढवण बंदर", "mr"),
    ("पालघर प्रकल्प (मराठी)", "पालघर प्रकल्प", "mr"),
    ("डहाणू (मराठी)", "डहाणू प्रकल्प", "mr"),
]


def google_news_url(query, language="en"):
    if language == "mr":
        return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=mr&gl=IN&ceid=IN:mr"
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"


def ensure_default_queries():
    created = 0
    for name, query, lang in DEFAULT_QUERIES:
        _, was_created = WatchQuery.objects.get_or_create(
            feed_url=google_news_url(query, lang), defaults={"name": name, "language": lang})
        created += was_created
    return created


def place_terms():
    terms = set(EXTRA_PLACES)
    for loc in Location.objects.all():
        for name in loc.all_names():
            if len(name) >= 4:
                terms.add(name)
    return sorted(terms, key=len, reverse=True)


def _contains(text, term):
    if re.search(r"[ऀ-ॿ]", term):  # Devanagari: plain substring
        return term in text
    return re.search(rf"\b{re.escape(term.lower())}", text) is not None


def score_text(text, places=None):
    low = (text or "").lower()
    places = places if places is not None else place_terms()
    matched_places = [p for p in places if _contains(low if not re.search(r"[ऀ-ॿ]", p) else text, p)]
    matched_topics = [t for t in TOPIC_TERMS if _contains(low if not re.search(r"[ऀ-ॿ]", t) else text, t)]
    if not matched_places:
        return 0, [], matched_topics
    score = 10 * min(len(matched_places), 3) + 5 * min(len(matched_topics), 6)
    return score, matched_places, matched_topics


def _strip_html(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def _entry_time(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return datetime(*t[:6], tzinfo=dt_timezone.utc)


def ingest_entries(query, entries, places=None):
    places = places if places is not None else place_terms()
    added = 0
    for entry in entries:
        url = entry.get("link")
        title = _strip_html(entry.get("title", ""))
        if not url or not title:
            continue
        norm = normalize_name(re.sub(r"\s+-\s+[^-]+$", "", title))  # drop " - Publisher" suffix
        if InboxItem.objects.filter(url=url).exists() or InboxItem.objects.filter(normalized_title=norm).exists():
            continue
        snippet = _strip_html(entry.get("summary", ""))[:2000]
        score, mp, mt = score_text(f"{title} {snippet}", places)
        if score == 0:
            continue
        publisher = ""
        if entry.get("source") and hasattr(entry["source"], "get"):
            publisher = entry["source"].get("title", "")
        InboxItem.objects.create(
            url=url[:1000], title=title[:500], normalized_title=norm[:500], publisher=publisher[:200],
            published_at=_entry_time(entry), snippet=snippet, query=query,
            matched_places=", ".join(mp)[:500], matched_topics=", ".join(mt)[:500], score=score,
        )
        added += 1
    return added


def run_query(query, session=None):
    session = session or requests.Session()
    headers = {"User-Agent": f"Mozilla/5.0 (compatible; {settings.CRAWLER_CONTACT})"}
    try:
        resp = session.get(query.feed_url, headers=headers, timeout=30)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        added = ingest_entries(query, feed.entries)
        query.last_error = ""
    except Exception as exc:  # network problems should not stop other queries
        added = 0
        query.last_error = f"{type(exc).__name__}: {exc}"[:2000]
    query.last_checked_at = timezone.now()
    query.save(update_fields=["last_checked_at", "last_error"])
    return added


def run_all():
    session = requests.Session()
    results = {}
    for q in WatchQuery.objects.filter(active=True):
        results[q.name] = run_query(q, session)
    return results
