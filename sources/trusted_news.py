import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from html import unescape

import requests

from config import REQUEST_TIMEOUT
from models import Item
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
TRUSTED_NEWS_FEEDS = [
    ("reuters", "Reuters Top", "https://feeds.reuters.com/reuters/topNews"),
    ("reuters", "Reuters World", "https://feeds.reuters.com/Reuters/worldNews"),
    ("reuters", "Reuters Politics", "https://feeds.reuters.com/Reuters/PoliticsNews"),
    ("bbc", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("bbc", "BBC Politics", "https://feeds.bbci.co.uk/news/politics/rss.xml"),
    ("npr", "NPR News", "https://feeds.npr.org/1001/rss.xml"),
    ("new york times", "NYT World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("new york times", "NYT Politics", "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml"),
]
STOPWORDS = {
    "a",
    "an",
    "and",
    "end",
    "for",
    "house",
    "in",
    "of",
    "on",
    "the",
    "to",
    "trump",
    "white",
}


def _build_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(REQUEST_HEADERS)
    for key in PROXY_ENV_KEYS:
        session.headers.pop(key, None)
    return session


def _clean_html_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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


@lru_cache(maxsize=512)
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


def _normalize_query_tokens(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", (query or "").lower())
    return [token for token in tokens if len(token) >= 2 and token not in STOPWORDS]


def _matches_query(query: str, title: str, body: str) -> bool:
    text = f"{title} {body}".lower()
    normalized_text = re.sub(r"[^a-z0-9\s]", " ", text)
    normalized_text = re.sub(r"\s+", " ", normalized_text).strip()
    normalized_query = re.sub(r"[^a-z0-9\s]", " ", (query or "").lower())
    normalized_query = re.sub(r"\s+", " ", normalized_query).strip()

    if normalized_query and normalized_query in normalized_text:
        return True

    tokens = _normalize_query_tokens(query)
    if not tokens:
        return False

    matched = sum(1 for token in tokens if token in normalized_text)
    required = len(tokens) if len(tokens) <= 2 else max(2, len(tokens) - 1)
    return matched >= required


def _get_child_text(node: ET.Element, *names: str) -> str:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _get_atom_link(node: ET.Element) -> str:
    for child in node.findall("{http://www.w3.org/2005/Atom}link"):
        href = (child.attrib.get("href") or "").strip()
        rel = (child.attrib.get("rel") or "alternate").strip().lower()
        if href and rel == "alternate":
            return href
    return ""


def _parse_feed_entries(feed_xml: str) -> list[dict[str, str]]:
    root = ET.fromstring(feed_xml)
    channel = root.find("channel")
    entries: list[dict[str, str]] = []

    if channel is not None:
        for node in channel.findall("item"):
            entries.append(
                {
                    "title": _clean_html_text(_get_child_text(node, "title")),
                    "body": _clean_html_text(
                        _get_child_text(
                            node,
                            "description",
                            "{http://purl.org/rss/1.0/modules/content/}encoded",
                        )
                    ),
                    "link": _get_child_text(node, "link"),
                    "published_at": _get_child_text(node, "pubDate"),
                    "guid": _get_child_text(node, "guid"),
                }
            )
        return entries

    for node in root.findall("{http://www.w3.org/2005/Atom}entry"):
        summary = _get_child_text(
            node,
            "{http://www.w3.org/2005/Atom}summary",
            "{http://www.w3.org/2005/Atom}content",
        )
        entries.append(
            {
                "title": _clean_html_text(_get_child_text(node, "{http://www.w3.org/2005/Atom}title")),
                "body": _clean_html_text(summary),
                "link": _get_atom_link(node),
                "published_at": _get_child_text(
                    node,
                    "{http://www.w3.org/2005/Atom}updated",
                    "{http://www.w3.org/2005/Atom}published",
                ),
                "guid": _get_child_text(node, "{http://www.w3.org/2005/Atom}id"),
            }
        )
    return entries


def fetch_trusted_feed_snapshot() -> tuple[list[dict[str, str]], set[str], set[str]]:
    # NOTE:
    # 주요 매체 RSS는 쿼리마다 다시 받지 않고, 한 수집 사이클에서 한 번만 받아 재사용한다.
    # 느린/실패한 피드 대기를 query 개수만큼 반복하지 않도록 하기 위한 구조다.
    session = _build_session()
    all_entries: list[dict[str, str]] = []
    succeeded_publishers: set[str] = set()
    attempted_publishers: set[str] = set()

    for publisher_name, outlet_name, feed_url in TRUSTED_NEWS_FEEDS:
        attempted_publishers.add(publisher_name)
        try:
            response = session.get(feed_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException:
            continue

        succeeded_publishers.add(publisher_name)

        for entry in _parse_feed_entries(response.text):
            entry["source_label"] = outlet_name
            entry["publisher_name"] = publisher_name
            all_entries.append(entry)

    failed_publishers = attempted_publishers - succeeded_publishers
    return all_entries, succeeded_publishers, failed_publishers


def fetch_trusted_news_articles_from_snapshot(
    snapshot_entries: list[dict[str, str]],
    query: str,
    recent_hours: int | None = None,
) -> list[Item]:
    items: list[Item] = []
    seen_ids: set[str] = set()

    for entry in snapshot_entries:
        title = entry["title"]
        body = entry["body"]
        link = entry["link"]
        guid = entry["guid"] or link or title
        published_at = entry["published_at"]
        outlet_name = entry["source_label"]

        if not link or not _matches_query(query, title, body):
            continue

        original_published_at = fetch_original_published_at(link)
        effective_published_at = original_published_at or published_at
        if recent_hours is not None and not is_within_recent_hours(effective_published_at, recent_hours):
            continue

        item_id = sha1(f"trusted_news|{guid}")
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        items.append(
            Item(
                source=f"trusted_news:{outlet_name}",
                title=title,
                body=body,
                url=link,
                published_at=effective_published_at,
                item_id=item_id,
                priority_score=compute_priority(title, body),
            )
        )

    return items


def fetch_trusted_news_articles_grouped_from_snapshot(
    snapshot_entries: list[dict[str, str]],
    queries: list[str],
    recent_hours: int | None = None,
) -> dict[str, list[Item]]:
    # NOTE:
    # trusted_news도 query마다 snapshot 전체를 다시 돌지 않고,
    # 한 번의 순회에서 모든 query bucket에 동시에 분배한다.
    # Google OR 그룹 호출과 마찬가지로, 후반부 로컬 매칭 비용과 로그 노이즈를 줄이기 위한 구조다.
    grouped_items: dict[str, list[Item]] = {query: [] for query in queries}
    seen_ids_by_query: dict[str, set[str]] = {query: set() for query in queries}

    for entry in snapshot_entries:
        title = entry["title"]
        body = entry["body"]
        link = entry["link"]
        guid = entry["guid"] or link or title
        published_at = entry["published_at"]
        outlet_name = entry["source_label"]

        if not link:
            continue

        original_published_at = fetch_original_published_at(link)
        effective_published_at = original_published_at or published_at
        if recent_hours is not None and not is_within_recent_hours(effective_published_at, recent_hours):
            continue

        item_id = sha1(f"trusted_news|{guid}")
        item = Item(
            source=f"trusted_news:{outlet_name}",
            title=title,
            body=body,
            url=link,
            published_at=effective_published_at,
            item_id=item_id,
            priority_score=compute_priority(title, body),
        )

        for query in queries:
            if not _matches_query(query, title, body):
                continue
            if item_id in seen_ids_by_query[query]:
                continue
            seen_ids_by_query[query].add(item_id)
            grouped_items[query].append(item)

    return grouped_items


def fetch_trusted_news_articles_with_status(
    query: str,
    recent_hours: int | None = None,
) -> tuple[list[Item], set[str], set[str]]:
    snapshot_entries, succeeded_publishers, failed_publishers = fetch_trusted_feed_snapshot()
    items = fetch_trusted_news_articles_from_snapshot(
        snapshot_entries,
        query,
        recent_hours=recent_hours,
    )
    return items, succeeded_publishers, failed_publishers


def fetch_trusted_news_articles(query: str, recent_hours: int | None = None) -> list[Item]:
    snapshot_entries, _succeeded_publishers, _failed_publishers = fetch_trusted_feed_snapshot()
    items = fetch_trusted_news_articles_from_snapshot(
        snapshot_entries,
        query,
        recent_hours=recent_hours,
    )
    return items
