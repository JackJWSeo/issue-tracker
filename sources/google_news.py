import json
import re
import xml.etree.ElementTree as ET
from datetime import timezone
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
ORIGINAL_ARTICLE_TIMEOUT_SECONDS = min(REQUEST_TIMEOUT, 4)
GOOGLE_NEWS_MAX_ITEMS_PER_QUERY = 6
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
            timeout=ORIGINAL_ARTICLE_TIMEOUT_SECONDS,
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


def _is_trusted_publisher_item(
    title: str,
    description: str,
    link: str,
    excluded_publishers: list[str] | None = None,
) -> bool:
    publisher = _extract_google_news_publisher(title)
    haystacks = [publisher, (description or "").lower(), (link or "").lower()]
    publisher_list = excluded_publishers if excluded_publishers is not None else get_query_setting_list("trusted_news_publishers")
    for trusted_name in publisher_list:
        if any(trusted_name in haystack for haystack in haystacks):
            return True
    return False


def _extract_published_at_from_url(url: str) -> str:
    # NOTE:
    # 일부 비주요 매체는 메타 태그에 발행시각을 안 넣어서 Google RSS 시각으로 오염될 수 있다.
    # 그 경우 URL에 포함된 날짜라도 잡아 최근 N시간 필터가 헐거워지지 않게 한다.
    if not url:
        return ""

    patterns = [
        re.compile(r"/(20\d{2})/(\d{2})/(\d{2})(?:/|$)"),
        re.compile(r"-(20\d{2})-(\d{2})-(\d{2})(?:[-/]|$)"),
        re.compile(r"/(20\d{2})(\d{2})(\d{2})(?:/|$)"),
    ]
    for pattern in patterns:
        match = pattern.search(url)
        if not match:
            continue
        year, month, day = match.groups()
        try:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}T00:00:00+00:00"
        except ValueError:
            continue
    return ""


def _resolve_recent_hours_verified_time(
    pub_date: str,
    url_published_at: str,
    original_published_at: str,
    recent_hours: int,
) -> str:
    # NOTE:
    # Google News 원문 중에는 published_time 메타가 아예 없는 경우가 적지 않다.
    # 그렇다고 전부 버리면 실제 최신 기사도 모두 탈락하므로, 검증 우선순위를 둔다.
    #
    # 1. 원문 메타가 있으면 최우선 사용
    # 2. URL 날짜가 있으면 오래된 기사 재유입 방지를 위해 그것을 신뢰
    # 3. 둘 다 없을 때만 RSS pubDate를 제한적으로 fallback 사용
    if original_published_at:
        return original_published_at if is_within_recent_hours(original_published_at, recent_hours) else ""

    if url_published_at:
        return url_published_at if is_within_recent_hours(url_published_at, recent_hours) else ""

    if pub_date and is_within_recent_hours(pub_date, recent_hours):
        return pub_date

    return ""


def fetch_google_news_rss(
    query: str,
    recent_hours: int | None = None,
    excluded_publishers: list[str] | None = None,
    source_label: str | None = None,
) -> tuple[list[Item], dict[str, int]]:
    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    r = _build_session().get(rss_url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    root = ET.fromstring(r.text)
    channel = root.find("channel")
    if channel is None:
        return [], {
            "rss_raw_items": 0,
            "publisher_filtered": 0,
            "pre_filter_passed": 0,
            "verified_passed": 0,
            "accepted": 0,
        }

    items: list[Item] = []
    raw_nodes = channel.findall("item")
    stats = {
        "rss_raw_items": len(raw_nodes),
        "publisher_filtered": 0,
        "pre_filter_passed": 0,
        "verified_passed": 0,
        "accepted": 0,
    }
    accepted_count = 0
    for node in raw_nodes:
        if accepted_count >= GOOGLE_NEWS_MAX_ITEMS_PER_QUERY:
            break

        title = (node.findtext("title") or "").strip()
        description = (node.findtext("description") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub_date = (node.findtext("pubDate") or "").strip()
        guid = (node.findtext("guid") or link or title).strip()

        if _is_trusted_publisher_item(title, description, link, excluded_publishers=excluded_publishers):
            stats["publisher_filtered"] += 1
            continue

        url_published_at = _extract_published_at_from_url(link)

        if recent_hours is not None:
            # NOTE:
            # 속도 최적화를 위해 먼저 Google RSS pubDate로 1차 컷을 한다.
            # 이 단계는 빠른 pre-filter이고, 통과한 카드만 원문 메타를 열어 최종 검증한다.
            preliminary_published_at = pub_date or url_published_at
            if preliminary_published_at and not is_within_recent_hours(preliminary_published_at, recent_hours):
                continue
            stats["pre_filter_passed"] += 1

        original_published_at = fetch_original_published_at(link)
        effective_published_at = original_published_at or url_published_at or pub_date

        if recent_hours is not None:
            # NOTE:
            # Google RSS pubDate만으로는 오래된 기사가 최근 기사처럼 보일 수 있다.
            # 그래서 1차 통과 카드에 한해서만 원문 메타/URL 날짜를 우선 검증한다.
            # 다만 둘 다 비어 있으면, 최신 기사 누락을 줄이기 위해 RSS pubDate를 제한적으로 fallback 사용한다.
            verified_published_at = _resolve_recent_hours_verified_time(
                pub_date=pub_date,
                url_published_at=url_published_at,
                original_published_at=original_published_at,
                recent_hours=recent_hours,
            )
            if not verified_published_at:
                continue
            stats["verified_passed"] += 1
            effective_published_at = verified_published_at

        items.append(
            Item(
                source=f"google_news:{source_label or query}",
                title=title,
                body=description,
                url=link,
                published_at=effective_published_at,
                item_id=sha1(f"news|{guid}"),
                priority_score=compute_priority(title, description),
            )
        )
        accepted_count += 1
        stats["accepted"] += 1

    return items, stats
