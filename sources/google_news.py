import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from html import unescape
from urllib.parse import quote_plus

import requests

from config import REQUEST_TIMEOUT
from models import Item
from query_settings import get_query_setting_list
from utils import compute_priority, is_within_recent_hours, parse_dt, sha1


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]
PUBLISH_META_PATTERNS = [
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']og:article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']parsely-pub-date["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']date["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
]
JSON_LD_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _build_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(REQUEST_HEADERS)
    for key in PROXY_ENV_KEYS:
        session.headers.pop(key, None)
    return session


def _normalize_datetime_text(value: str) -> str:
    text = unescape((value or "").strip())
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


def _extract_jsonld_published_dates(html: str) -> list[str]:
    matches: list[str] = []
    for raw_payload in JSON_LD_PATTERN.findall(html):
        payload_text = raw_payload.strip()
        if not payload_text:
            continue
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key in ("datePublished", "dateCreated", "uploadDate"):
                    value = _normalize_datetime_text(str(current.get(key) or ""))
                    if value:
                        matches.append(value)
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
    return matches


@lru_cache(maxsize=256)
def fetch_original_published_at(url: str) -> str:
    if not url:
        return ""
    try:
        response = _build_session().get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "html" not in content_type:
        return ""

    html = response.text or ""
    candidates: list[str] = []
    for pattern in PUBLISH_META_PATTERNS:
        candidates.extend(_normalize_datetime_text(match) for match in pattern.findall(html))
    candidates.extend(_extract_jsonld_published_dates(html))

    parsed_candidates = []
    for candidate in candidates:
        dt = parse_dt(candidate)
        if dt is None:
            continue
        parsed_candidates.append((dt, candidate))

    if not parsed_candidates:
        return ""

    parsed_candidates.sort(key=lambda item: item[0])
    return parsed_candidates[0][1]


def _extract_google_news_publisher(title: str) -> str:
    text = (title or "").strip()
    if " - " in text:
        return text.rsplit(" - ", 1)[-1].strip().lower()
    for dash in (" – ", " — "):
        if dash in text:
            return text.rsplit(dash, 1)[-1].strip().lower()
    return ""


def _is_trusted_publisher_item(title: str, description: str, link: str) -> bool:
    publisher = _extract_google_news_publisher(title)
    haystacks = [publisher, (description or "").lower(), (link or "").lower()]
    for trusted_name in get_query_setting_list("trusted_news_publishers"):
        if any(trusted_name in haystack for haystack in haystacks):
            return True
    return False


def fetch_google_news_rss(query: str, recent_hours: int | None = None) -> list[Item]:
    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    r = _build_session().get(rss_url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    root = ET.fromstring(r.text)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[Item] = []
    for node in channel.findall("item"):
        title = (node.findtext("title") or "").strip()
        description = (node.findtext("description") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub_date = (node.findtext("pubDate") or "").strip()
        guid = (node.findtext("guid") or link or title).strip()

        if _is_trusted_publisher_item(title, description, link):
            continue

        original_published_at = fetch_original_published_at(link)
        effective_published_at = original_published_at or pub_date

        if recent_hours is not None and not is_within_recent_hours(effective_published_at, recent_hours):
            continue

        items.append(
            Item(
                source=f"google_news:{query}",
                title=title,
                body=description,
                url=link,
                published_at=effective_published_at,
                item_id=sha1(f"news|{guid}"),
                priority_score=compute_priority(title, description),
            )
        )

    return items
