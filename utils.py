import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from config import LOCAL_TIMEZONE
from query_settings import get_query_setting_list


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize_text(*parts: str) -> str:
    return " ".join(p for p in parts if p).strip().lower()


def parse_keyword_csv(value: str) -> list[str]:
    return [part.strip().lower() for part in (value or "").split(",") if part.strip()]


def compute_priority(title: str, body: str) -> int:
    text = normalize_text(title, body)
    score = 0

    for kw in get_query_setting_list("high_priority_keywords"):
        if kw in text:
            score += 2

    if any(k in text for k in ["live", "breaking", "urgent", "watch live"]):
        score += 2

    if any(k in text for k in ["speech", "remarks", "address", "rally", "press conference"]):
        score += 1

    return score


def contains_iran_war_keywords(*parts: str) -> bool:
    text = normalize_text(*parts)
    if any(kw in text for kw in get_query_setting_list("iran_war_strict_keywords")):
        return True

    has_primary_topic = any(kw in text for kw in get_query_setting_list("iran_topic_keywords"))
    has_secondary_topic = any(kw in text for kw in get_query_setting_list("iran_secondary_topic_keywords"))
    has_conflict = any(kw in text for kw in get_query_setting_list("iran_conflict_keywords"))
    return has_primary_topic and has_secondary_topic and has_conflict


def match_exclude_keyword(exclude_keywords: str, *parts: str) -> str:
    text = normalize_text(*parts)
    for keyword in parse_keyword_csv(exclude_keywords):
        if keyword in text:
            return keyword
    return ""


def classify_trump_content(*parts: str) -> str:
    text = normalize_text(*parts)
    if contains_iran_war_keywords(text):
        return "iran_war"
    if any(keyword in text for keyword in get_query_setting_list("epstein_keywords")):
        return "epstein"
    if any(keyword in text for keyword in get_query_setting_list("impeachment_keywords")):
        return "impeachment"
    return ""


def normalize_title_for_dedupe(title: str) -> str:
    text = (title or "").strip()
    separator_index = text.rfind("-")
    if separator_index < 0:
        for separator in ("–", "—"):
            separator_index = text.rfind(separator)
            if separator_index >= 0:
                break

    if separator_index >= 0 and separator_index >= len(text) * 0.5:
        text = text[:separator_index].strip()

    text = text.lower()
    text = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", text)
    text = re.sub(r"\b(live|breaking|watch live|stream|official|full speech|full video)\b", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def looks_korean(text: str) -> bool:
    return bool(re.search(r"[\uac00-\ud7a3]", text or ""))


def parse_dt(value: str | None):
    if not value:
        return None

    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        pass

    try:
        return parsedate_to_datetime(value)
    except Exception:
        return None


def is_today_content(value: str | None) -> bool:
    if not value:
        return False

    now_local = datetime.now(ZoneInfo(LOCAL_TIMEZONE))
    text = value.strip().lower()

    if text in {"just now", "now", "today"}:
        return True
    if text == "yesterday":
        return False

    minute_match = re.fullmatch(r"(\d+)\s*(m|min|mins|minute|minutes)", text)
    if minute_match:
        return True

    hour_match = re.fullmatch(r"(\d+)\s*(h|hr|hrs|hour|hours)", text)
    if hour_match:
        hours = int(hour_match.group(1))
        return hours < 24

    day_match = re.fullmatch(r"(\d+)\s*(d|day|days)", text)
    if day_match:
        days = int(day_match.group(1))
        return days == 0

    dt = parse_dt(value)
    if dt is None:
        return False

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    return dt.astimezone(ZoneInfo(LOCAL_TIMEZONE)).date() == now_local.date()


def is_within_recent_hours(value: str | None, hours: int) -> bool:
    if not value:
        return False

    hours = max(1, int(hours))
    now_local = datetime.now(ZoneInfo(LOCAL_TIMEZONE))
    text = value.strip().lower()

    if text in {"just now", "now", "today"}:
        return True
    if text == "yesterday":
        return hours >= 24 and False

    minute_match = re.fullmatch(r"(\d+)\s*(m|min|mins|minute|minutes)", text)
    if minute_match:
        minutes = int(minute_match.group(1))
        return minutes <= hours * 60

    hour_match = re.fullmatch(r"(\d+)\s*(h|hr|hrs|hour|hours)", text)
    if hour_match:
        value_hours = int(hour_match.group(1))
        return value_hours <= hours

    day_match = re.fullmatch(r"(\d+)\s*(d|day|days)", text)
    if day_match:
        days = int(day_match.group(1))
        return days == 0

    dt = parse_dt(value)
    if dt is None:
        return False

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    delta = now_local - dt.astimezone(ZoneInfo(LOCAL_TIMEZONE))
    return 0 <= delta.total_seconds() <= hours * 3600


def short_text(text: str, limit: int = 300) -> str:
    text = (text or "").strip().replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."
