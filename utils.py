import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime

from config import HIGH_PRIORITY_KEYWORDS, IRAN_WAR_KEYWORDS


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize_text(*parts: str) -> str:
    return " ".join(p for p in parts if p).strip().lower()


def compute_priority(title: str, body: str) -> int:
    text = normalize_text(title, body)
    score = 0

    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw in text:
            score += 2

    if any(k in text for k in ["live", "breaking", "urgent", "watch live"]):
        score += 2

    if any(k in text for k in ["speech", "remarks", "address", "rally", "press conference"]):
        score += 1

    return score


def contains_iran_war_keywords(*parts: str) -> bool:
    text = normalize_text(*parts)
    return any(kw in text for kw in IRAN_WAR_KEYWORDS)


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


def short_text(text: str, limit: int = 300) -> str:
    text = (text or "").strip().replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 3] + "..."
