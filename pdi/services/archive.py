"""Save a local copy of every source document, because government pages disappear."""

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone

from ..models import Source


def _target(source, content_type):
    host = urlparse(source.url).netloc.replace(":", "_") or "unknown"
    ext = ".pdf" if "pdf" in content_type else ".html"
    name = re.sub(r"[^A-Za-z0-9]+", "_", urlparse(source.url).path).strip("_")[:80] or "index"
    return Path("archive") / host / f"{source.pk}_{name}{ext}"


def archive_source(source, session=None, timeout=40):
    session = session or requests.Session()
    resp = session.get(source.url, timeout=timeout, headers={"User-Agent": f"Mozilla/5.0 (compatible; {settings.CRAWLER_CONTACT})"})
    resp.raise_for_status()
    rel = _target(source, resp.headers.get("content-type", ""))
    path = settings.DATA_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    source.archive_path = rel.as_posix()
    source.archive_sha256 = hashlib.sha256(resp.content).hexdigest()
    source.archived_at = timezone.now()
    source.save(update_fields=["archive_path", "archive_sha256", "archived_at"])
    return path


def archive_missing(limit=None):
    ok, failed = 0, []
    session = requests.Session()
    qs = Source.objects.filter(archive_path="").order_by("id")
    if limit:
        qs = qs[:limit]
    for source in qs:
        try:
            archive_source(source, session)
            ok += 1
        except Exception as exc:
            failed.append((source.url, f"{type(exc).__name__}: {exc}"[:200]))
    return ok, failed
