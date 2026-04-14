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


def is_question_headline(title: str) -> bool:
    normalized_title = normalize_text(title)
    if "?" in normalized_title:
        return True

    english_question_starts = (
        "would ",
        "could ",
        "should ",
        "will ",
        "is ",
        "are ",
        "how ",
        "what ",
        "why ",
        "can ",
        "do ",
        "does ",
        "did ",
        "may ",
        "might ",
    )
    if normalized_title.startswith(english_question_starts):
        return True

    korean_question_markers = (
        "어떻게",
        "왜",
        "무엇",
        "뭘",
        "인가",
        "일까",
        "되나",
        "가능할까",
    )
    return any(marker in normalized_title for marker in korean_question_markers)


def compute_priority(title: str, body: str) -> int:
    normalized_title = normalize_text(title)
    text = normalize_text(title, body)
    score = 0

    high_priority_matches = 0
    for kw in get_query_setting_list("high_priority_keywords"):
        if kw in text:
            high_priority_matches += 1
            score += 2

    # NOTE:
    # 실제 긴급 이슈는 "봉쇄/공습/미사일/휴전 붕괴/직접 발표" 같은 강한 신호가 붙는다.
    # 반대로 영향 분석, 여론, 우려 표명, 압박 기사만으로는 중요도를 과하게 올리지 않는다.
    strong_signals = [
        "blockade", "closure", "airstrike", "bombing", "missile", "ballistic missile",
        "missile barrage", "rocket barrage", "drone", "ground offensive", "ground operation",
        "troop deployment", "carrier strike group", "warship", "proxy attack", "militia attack",
        "ceasefire collapse", "talks breakdown", "no deal", "deal reached", "ceasefire agreement",
        "peace agreement", "trump warns iran", "trump announces ceasefire", "trump announces deal",
        "israel strikes", "iran war", "israel iran conflict", "hormuz blockade", "hormuz closure",
        "봉쇄", "폐쇄", "공습", "폭격", "미사일", "탄도미사일", "지상전", "병력 증파",
        "휴전 타결", "휴전 합의", "평화 협정", "협상 결렬", "트럼프 휴전 발표", "트럼프 합의 발표",
        "이스라엘 공습", "베이루트 공습",
    ]
    strong_matches = sum(1 for keyword in strong_signals if keyword in text)
    score += strong_matches * 3

    kinetic_signals = [
        "airstrike", "bombing", "missile", "ballistic missile", "missile barrage",
        "rocket barrage", "drone", "ground offensive", "ground operation",
        "troop deployment", "carrier strike group", "warship", "proxy attack",
        "militia attack", "israel strikes", "공습", "폭격", "미사일", "탄도미사일",
        "지상전", "병력 증파", "이스라엘 공습", "베이루트 공습",
    ]
    diplomatic_breakthrough_signals = [
        "ceasefire agreement", "peace agreement", "peace deal", "deal reached",
        "ceasefire collapse", "talks breakdown", "no deal",
        "trump announces ceasefire", "trump announces deal",
        "휴전 합의", "휴전 타결", "평화 협정", "협상 결렬",
        "트럼프 휴전 발표", "트럼프 합의 발표",
    ]
    has_kinetic_signal = any(keyword in text for keyword in kinetic_signals)
    has_diplomatic_breakthrough_signal = any(keyword in text for keyword in diplomatic_breakthrough_signals)
    has_direct_diplomatic_event_signal = any(
        keyword in text
        for keyword in [
            "ceasefire", "truce", "armistice", "direct talks", "peace talks",
            "new strikes", "fresh strikes", "strike", "attack",
            "휴전", "정전", "종전", "직접 회담", "평화 회담", "공격", "공습",
        ]
    )

    analysis_or_pressure_signals = [
        "how ", "what ", "why ", "analysis", "opinion", "explainer", "explained",
        "could ", "may ", "might ", "concerned", "concern", "worried", "pressure",
        "pressing", "urges", "urge", "impact", "effects", "voters", "market reaction",
        "withdraw", "withdrawal", "drop blockade", "lift blockade", "lift sanctions",
        "우려", "압박", "영향", "분석", "해설", "가능성", "전망", "철회",
    ]
    soft_matches = sum(1 for keyword in analysis_or_pressure_signals if keyword in text)
    if soft_matches:
        score -= soft_matches * 2

    if any(k in text for k in ["saudi arabia", "turkey", "qatar", "oman", "uae", "사우디", "터키", "오만", "카타르"]):
        score -= 1

    should_cap_soft_context = soft_matches and not has_kinetic_signal and not has_diplomatic_breakthrough_signal
    if should_cap_soft_context:
        score = min(score, 5)

    if (
        any(k in text for k in ["china", "중국"])
        and any(k in text for k in ["iran", "이란"])
        and any(k in text for k in ["warns us", "warns u.s.", "interference", "미국 경고", "간섭하지 말라"])
    ):
        score += 4

    diplomatic_actor_signals = [
        "china", "russia", "saudi arabia", "turkey", "qatar", "oman", "uae",
        "britain", "uk", "france", "germany", "pakistan", "india", "egypt",
        "jordan", "iraq", "syria", "lebanon", "yemen", "european union",
        "eu", "un", "nato", "중국", "러시아", "사우디", "터키", "카타르",
        "오만", "영국", "프랑스", "독일", "파키스탄", "인도", "이집트",
        "요르단", "이라크", "시리아", "레바논", "예멘", "유럽연합", "eu", "유엔", "나토",
    ]
    diplomatic_message_signals = [
        "warns", "warning", "backs", "support", "supports", "condemns", "condemn",
        "urges", "urge", "calls for", "called for", "demands", "demand",
        "announces", "announcement", "statement", "remarks", "says", "said",
        "threatens", "threat", "rejects", "reaffirms", "pledges", "backs iran",
        "backs israel", "with us", "with iran", "with israel",
        "경고", "지지", "규탄", "촉구", "요구", "발표", "성명", "발언", "언급",
        "위협", "반대", "재확인", "동조", "지원",
    ]
    direct_conflict_parties = [
        "us", "u.s.", "america", "american", "white house", "trump",
        "iran", "iranian", "tehran", "israel", "israeli", "netanyahu",
        "미국", "백악관", "트럼프", "이란", "이스라엘", "네타냐후",
    ]
    actor_matches = sum(1 for keyword in diplomatic_actor_signals if keyword in text)
    message_matches = sum(1 for keyword in diplomatic_message_signals if keyword in text)
    direct_party_matches = sum(1 for keyword in direct_conflict_parties if keyword in text)
    if actor_matches >= 1 and message_matches >= 1 and direct_party_matches >= 2:
        score += 4
    if actor_matches >= 2 and message_matches >= 1 and direct_party_matches >= 2:
        score += 2
    has_direct_diplomatic_message = actor_matches >= 1 and message_matches >= 1 and direct_party_matches >= 2
    if has_direct_diplomatic_message and has_direct_diplomatic_event_signal:
        score += 3

    if any(k in text for k in ["live", "breaking", "urgent", "watch live", "속보", "[속보]"]):
        score += 3

    if any(k in text for k in ["speech", "remarks", "address", "rally", "press conference"]):
        score += 1

    if is_question_headline(normalized_title):
        score -= 4

    if high_priority_matches >= 3:
        score += 2
    if strong_matches >= 2:
        score += 2

    if should_cap_soft_context and not has_direct_diplomatic_message:
        score = min(score, 4)

    return max(0, score)


def classify_priority_level(score: int) -> str:
    value = int(score or 0)
    if value >= 12:
        return "urgent"
    if value >= 6:
        return "important"
    return "normal"


def priority_level_label(score: int) -> str:
    level = classify_priority_level(score)
    if level == "urgent":
        return "긴급"
    if level == "important":
        return "중요"
    return "일반"


def tokenize_news_query(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9가-힣]+", (query or "").lower())
    stopwords = {
        "a",
        "an",
        "and",
        "for",
        "house",
        "in",
        "of",
        "on",
        "the",
        "to",
    }
    return [token for token in tokens if len(token) >= 2 and token not in stopwords]


def matches_news_query(query: str, *parts: str) -> bool:
    text = normalize_text(*parts)
    normalized_text = re.sub(r"[^a-z0-9가-힣\s]", " ", text)
    normalized_text = re.sub(r"\s+", " ", normalized_text).strip()
    text_tokens = set(normalized_text.split())
    normalized_query = re.sub(r"[^a-z0-9가-힣\s]", " ", (query or "").lower())
    normalized_query = re.sub(r"\s+", " ", normalized_query).strip()

    if normalized_query and normalized_query in normalized_text:
        return True

    tokens = tokenize_news_query(query)
    if not tokens:
        return False

    matched = sum(1 for token in tokens if token in text_tokens)
    required = len(tokens) if len(tokens) <= 2 else max(2, len(tokens) - 1)
    return matched >= required


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
