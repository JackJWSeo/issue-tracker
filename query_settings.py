import json
from copy import deepcopy

from config import BASE_DIR


# NOTE:
# 검색어/키워드/매체 목록처럼 자주 바뀌는 데이터는 config.py가 아니라
# 반드시 query_settings.json에서 관리한다.
# 앞으로 관련 작업을 할 때 Python 상수 추가보다 JSON 수정이 기본 경로다.
QUERY_SETTINGS_PATH = BASE_DIR / "query_settings.json"

# NOTE:
# JSON 파일이 없거나 일부 키가 비어 있어도 앱이 바로 동작하도록 최소 기본값을 둔다.
# 하지만 운영 중 설정 변경은 이 딕셔너리가 아니라 query_settings.json을 수정하는 것이 원칙이다.
DEFAULT_QUERY_SETTINGS = {
    "x_accounts": [
        "realDonaldTrump",
        "WhiteHouse",
        "RapidResponse47",
    ],
    "truthsocial_accounts": [
        "realDonaldTrump",
    ],
    "youtube_queries": [
        "Donald Trump live",
        "Trump rally live",
        "White House live",
        "Trump speech live",
        "Trump Iran talks live",
        "US Iran talks live",
        "Iran nuclear talks live",
        "Iran ceasefire talks live",
        "Iran truce talks live",
        "Iran armistice talks live",
        "Iran peace talks live",
        "Iran talks breakdown live",
        "Iran ceasefire collapse live",
        "Iran sanctions relief live",
    ],
    "news_queries": [
        "Donald Trump",
        "Trump speech",
        "Trump rally",
        "Trump interview",
        "White House Trump",
        "Trump Iran talks",
        "Trump Iran negotiation",
        "Trump Iran ceasefire talks",
        "Trump Iran truce talks",
        "Trump Iran peace talks",
        "US Iran talks",
        "US Iran negotiations",
        "Iran nuclear talks",
        "Iran negotiation",
        "Iran ceasefire talks",
        "Iran truce talks",
        "Iran armistice talks",
        "Iran peace talks",
        "Iran end war talks",
        "Iran peace talks collapse",
        "Iran ceasefire collapse",
        "Iran talks breakdown",
        "Iran talks deadlock",
        "Iran sanctions relief",
        "Iran sanctions lifted",
        "Iran regulation relief",
    ],
    "trusted_news_publishers": [
        "reuters",
        "bbc",
        "npr",
        "new york times",
        "nyt",
    ],
    "high_priority_keywords": [
        "tariff", "sanction", "ukraine", "china", "taiwan", "iran", "nato",
        "south korea", "korea", "trade", "military", "nuclear", "election",
        "bitcoin", "crypto", "fed", "interest rate", "tesla", "tiktok",
        "ceasefire", "truce", "armistice", "peace talk", "peace talks",
        "negotiation", "negotiations", "end war", "end-of-war",
        "breakdown", "collapse", "deadlock", "impasse",
        "no deal", "without a deal", "without agreement", "without an agreement",
        "failed to reach", "fail to reach resolution", "ended without a deal",
        "ended without agreement", "ended without an agreement",
        "direct talks", "ceasefire talks", "end in islamabad", "islamabad",
        "hormuz", "strait of hormuz", "common framework",
        "excessive demands", "final offer", "best offer", "red line", "red lines",
        "휴전", "정전", "종전", "종전 협상", "휴전 협상", "종전협상",
        "협상 결렬", "결렬", "노딜", "합의 없이", "합의 도달 못 해", "협상 종료",
    ],
    "iran_topic_keywords": [
        "iran",
        "iranian",
        "tehran",
        "irgc",
        "revolutionary guard",
        "persian gulf",
        "hormuz",
        "strait of hormuz",
        "islamabad",
        "nuclear site",
        "uranium",
    ],
    "iran_secondary_topic_keywords": [
        "israel",
        "israeli",
        "middle east",
        "gaza",
        "hamas",
        "hezbollah",
        "syria",
        "lebanon",
        "u.s.",
        "us",
        "american",
    ],
    "iran_conflict_keywords": [
        "war",
        "missile",
        "airstrike",
        "strike",
        "attack",
        "bombing",
        "retaliation",
        "conflict",
        "clash",
        "military",
        "troops",
        "drone",
        "ceasefire",
        "truce",
        "armistice",
        "peace talk",
        "peace talks",
        "negotiation",
        "negotiations",
        "breakdown",
        "collapse",
        "deadlock",
        "impasse",
        "stalled talks",
        "talks fail",
        "talks failed",
        "no deal",
        "without a deal",
        "without agreement",
        "without an agreement",
        "ended without a deal",
        "ended without agreement",
        "ended without an agreement",
        "failed to reach",
        "fail to reach resolution",
        "direct talks",
        "ceasefire talks",
        "common framework",
        "excessive demands",
        "final offer",
        "best offer",
        "red line",
        "red lines",
        "노딜",
        "합의 없이",
        "합의 도달 못 해",
        "협상 종료",
        "intercepted",
        "rocket",
        "ballistic",
    ],
    "iran_war_strict_keywords": [
        "iran war",
        "war with iran",
        "attack on iran",
        "attack against iran",
        "strike on iran",
        "strike against iran",
        "iran missile attack",
        "iran nuclear site",
        "israel iran conflict",
        "iran israel war",
        "iran ceasefire talks",
        "iran truce talks",
        "iran armistice talks",
        "iran peace talks",
        "iran end war talks",
        "iran talks collapse",
        "iran ceasefire collapse",
        "us iran talks",
        "trump iran talks",
        "us leaves iran peace talks without a deal",
        "talks with iran have ended without an agreement",
        "direct us iran talks fail to reach resolution",
        "iran us talks end in islamabad",
        "ceasefire talks without agreement",
        "first peace talks no deal",
        "미국 이란 협상 결렬",
        "미국 이란 휴전 협상 결렬",
        "미국 이란 종전 협상 결렬",
        "미국 이란 노딜",
        "합의 없이 귀국",
    ],
    "epstein_keywords": [
        "epstein",
        "jeffrey epstein",
        "epstein files",
        "epstein list",
        "epstein case",
        "epstein scandal",
    ],
    "impeachment_keywords": [
        "impeach",
        "impeached",
        "impeachment",
        "articles of impeachment",
    ],
}

TARGET_SETTING_KEYS = (
    "x_accounts",
    "truthsocial_accounts",
    "youtube_queries",
    "news_queries",
)

_cached_query_settings: dict[str, list[str]] | None = None
_cached_query_settings_mtime_ns: int | None = None


def _normalize_string_list(value: object, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    return normalized or list(fallback)


def _get_file_mtime_ns() -> int:
    if not QUERY_SETTINGS_PATH.exists():
        return -1
    return QUERY_SETTINGS_PATH.stat().st_mtime_ns


def _load_query_settings_from_disk() -> dict[str, list[str]]:
    defaults = deepcopy(DEFAULT_QUERY_SETTINGS)
    if not QUERY_SETTINGS_PATH.exists():
        return defaults

    try:
        data = json.loads(QUERY_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    if not isinstance(data, dict):
        return defaults

    result = deepcopy(defaults)
    for key, fallback in defaults.items():
        result[key] = _normalize_string_list(data.get(key), fallback)
    return result


def load_query_settings(force_reload: bool = False) -> dict[str, list[str]]:
    global _cached_query_settings, _cached_query_settings_mtime_ns

    current_mtime_ns = _get_file_mtime_ns()
    if (
        not force_reload
        and _cached_query_settings is not None
        and _cached_query_settings_mtime_ns == current_mtime_ns
    ):
        return deepcopy(_cached_query_settings)

    loaded = _load_query_settings_from_disk()
    _cached_query_settings = deepcopy(loaded)
    _cached_query_settings_mtime_ns = current_mtime_ns
    return loaded


def load_query_targets() -> dict[str, list[str]]:
    settings = load_query_settings()
    return {key: list(settings[key]) for key in TARGET_SETTING_KEYS}


def get_query_setting_list(key: str) -> list[str]:
    settings = load_query_settings()
    return list(settings.get(key, []))


def save_query_targets(targets: dict[str, list[str]]) -> None:
    # NOTE:
    # UI에서 검색어만 저장하더라도, keyword 설정을 날리지 않기 위해
    # 전체 query_settings.json 구조를 유지한 채 target 섹션만 갱신한다.
    payload = load_query_settings(force_reload=True)
    for key in TARGET_SETTING_KEYS:
        fallback = DEFAULT_QUERY_SETTINGS[key]
        payload[key] = _normalize_string_list(targets.get(key), fallback)

    QUERY_SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
