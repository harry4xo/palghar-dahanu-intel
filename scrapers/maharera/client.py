"""Playwright session wrapper for the public MahaRERA website.

Responsibilities
----------------
* one headless Chromium browser/context for the whole run (cookies carried over);
* polite rate limiting (default: >= 3 s between *any* two navigations/requests);
* retries with exponential backoff on network errors and 429/5xx responses;
* robots.txt check before every URL (fail-closed for disallowed paths);
* every raw page fetched is written to
  ``data/raw/maharera/<key>/<UTC timestamp>.html`` (key = safe RERA number or "list").

There is deliberately no CAPTCHA handling of any kind.  If a page shows a CAPTCHA
the client raises :class:`CaptchaEncountered` and the caller must stop that path.
"""
from __future__ import annotations

import logging
import random
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "data" / "raw" / "maharera"

BASE_URL = "https://maharera.maharashtra.gov.in"
SEARCH_PATH = "/projects-search-result"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}

# Markers of a CAPTCHA / bot-challenge page.  We never try to get past these.
_CAPTCHA_MARKERS = re.compile(
    r"(enter the captcha|g-recaptcha|hcaptcha|cf-challenge|captcha-container|"
    r"project-captcha-validation|id=\"captcahCanvas\")",
    re.I,
)


class FetchError(RuntimeError):
    """Raised when a URL could not be fetched after all retries."""


class CaptchaEncountered(RuntimeError):
    """Raised when a fetched page is a CAPTCHA / bot-check gate."""


class RobotsDisallowed(RuntimeError):
    """Raised when robots.txt disallows the URL."""


def safe_key(value: str) -> str:
    """Filesystem-safe directory name for a RERA number or other key."""
    value = (value or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("._") or "unknown"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class FetchResult:
    url: str              # URL requested
    final_url: str        # URL after redirects
    status: Optional[int]
    html: str
    raw_path: str         # path relative to repo root, POSIX separators
    fetched_at: str       # ISO-8601 UTC


class MahaReraClient:
    """Context-managed Playwright session.

    >>> with MahaReraClient(delay=3.0) as c:
    ...     res = c.fetch("https://maharera.maharashtra.gov.in/projects-search-result", key="list")
    """

    def __init__(
        self,
        delay: float = 3.0,
        timeout: float = 120.0,
        retries: int = 4,
        backoff: float = 10.0,
        headless: bool = True,
        user_agent: str = DEFAULT_UA,
        raw_root: Path = RAW_ROOT,
        respect_robots: bool = True,
    ):
        self.delay = float(delay)
        self.timeout_ms = int(timeout * 1000)
        self.retries = int(retries)
        self.backoff = float(backoff)
        self.headless = headless
        self.user_agent = user_agent
        self.raw_root = Path(raw_root)
        self.respect_robots = respect_robots
        self._last_request = 0.0
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._robots: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self) -> "MahaReraClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        from playwright.sync_api import sync_playwright  # imported lazily: parse.py users don't need it

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1366, "height": 900},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
        )
        # Images/fonts/media are never needed for parsing: skip them to be light on the server.
        self._context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "media", "font")
            else route.continue_(),
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    def close(self) -> None:
        for obj in (self._context, self._browser):
            try:
                if obj is not None:
                    obj.close()
            except Exception:  # pragma: no cover - best effort shutdown
                pass
        if self._pw is not None:
            self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    # ------------------------------------------------------------------ politeness
    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.5))
        self._last_request = time.monotonic()

    def _robots_for(self, url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        rp: Optional[urllib.robotparser.RobotFileParser] = None
        try:
            self._throttle()
            resp = self._context.request.get(origin + "/robots.txt", timeout=60_000)
            body = resp.text() if resp.ok else ""
            if resp.ok and "<html" not in body[:500].lower():
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(body.splitlines())
                log.info("robots.txt loaded for %s", origin)
            else:
                log.warning("robots.txt for %s: HTTP %s / not a robots file; treating as no rules", origin, resp.status)
        except Exception as exc:  # network trouble: no rules known
            log.warning("robots.txt for %s unreachable (%s); treating as no rules", origin, exc)
        self._robots[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(self.user_agent, url) and rp.can_fetch("*", url)

    # ------------------------------------------------------------------ fetching
    def save_raw(self, key: str, html: str, ext: str = "html") -> Path:
        d = self.raw_root / safe_key(key)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{utc_stamp()}.{ext}"
        p.write_text(html, encoding="utf-8")
        return p

    def fetch(self, url: str, key: str, wait_selector: Optional[str] = None) -> FetchResult:
        """Navigate to ``url`` and return the rendered HTML (saved to disk first).

        ``wait_selector`` - optional CSS selector to wait for after DOMContentLoaded.
        """
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        last_err: Optional[str] = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status = None
            try:
                resp = self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                status = resp.status if resp else None
                if wait_selector and (status is None or status < 400):
                    try:
                        self._page.wait_for_selector(wait_selector, timeout=min(self.timeout_ms, 30_000))
                    except Exception:
                        log.debug("selector %s not found on %s", wait_selector, url)
                html = self._page.content()
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
                log.warning("attempt %d/%d %s failed: %s", attempt, self.retries, url, last_err)
                self._sleep_backoff(attempt)
                continue

            if status in RETRY_STATUSES:
                last_err = f"HTTP {status}"
                log.warning("attempt %d/%d %s -> HTTP %s", attempt, self.retries, url, status)
                # keep evidence of server errors too, but under a separate key
                self.save_raw("_errors", html)
                self._sleep_backoff(attempt)
                continue

            raw = self.save_raw(key, html)
            rel = raw.relative_to(REPO_ROOT).as_posix() if raw.is_relative_to(REPO_ROOT) else str(raw)
            if _CAPTCHA_MARKERS.search(html):
                raise CaptchaEncountered(f"CAPTCHA/bot-check on {url} (saved {rel})")
            if status is not None and status >= 400:
                raise FetchError(f"HTTP {status} for {url} (saved {rel})")
            return FetchResult(url=url, final_url=self._page.url, status=status, html=html,
                               raw_path=rel, fetched_at=utc_iso())
        raise FetchError(f"giving up on {url} after {self.retries} attempts: {last_err}")

    def _sleep_backoff(self, attempt: int) -> None:
        if attempt < self.retries:
            t = self.backoff * (2 ** (attempt - 1)) + random.uniform(0, 2)
            log.info("backing off %.1fs", t)
            time.sleep(t)
