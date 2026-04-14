import json
from copy import deepcopy

from config import BASE_DIR

# IMPORTANT:
# 이 파일은 query_settings.json을 읽어 앱에 전달하는 로더/백업 역할만 한다.
# 실제 운영 중 검색어/키워드 변경은 반드시 query_settings.json에서만 수정한다.
# 앞으로 키워드 개편 요청이 오면 이 파일의 리스트를 직접 수정하지 말고,
# query_settings.json만 수정한 뒤 load_query_settings() 경로로 반영해야 한다.

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
        "Trump press conference live",
        "Trump direct statement live",
        "Trump Iran statement live",
        "Trump Hormuz statement live",
        "Trump Middle East remarks live",
        "Trump Iran talks live",
        "Trump Iran war live",
        "Trump Israel Iran live",
        "US Iran talks live",
        "Iran nuclear talks live",
        "Iran Israel war live",
        "Strait of Hormuz live",
        "Hormuz shipping live",
        "Iran ceasefire talks live",
        "Iran truce talks live",
        "Iran armistice talks live",
        "Iran peace talks live",
        "Iran talks breakdown live",
        "Iran ceasefire collapse live",
        "Iran sanctions relief live",
        "Israel strikes Syria live",
        "Israel strikes Lebanon live",
        "Israel strikes Yemen live",
    ],
    "news_queries": [
        "Donald Trump",
        "Trump speech",
        "Trump rally",
        "Trump interview",
        "White House Trump",
        "Trump direct statement Iran",
        "Trump direct statement Hormuz",
        "Trump remarks on Iran",
        "Trump remarks on Strait of Hormuz",
        "Trump Middle East statement",
        "Trump warns Iran",
        "Trump Israel Iran statement",
        "Trump Iran talks",
        "Trump Iran negotiation",
        "Trump Iran ceasefire talks",
        "Trump Iran truce talks",
        "Trump Iran peace talks",
        "Trump Iran war",
        "Trump Iran uranium",
        "Trump Iran enrichment",
        "US Iran talks",
        "US Iran negotiations",
        "US Iran uranium",
        "US Iran enrichment",
        "Iran nuclear talks",
        "Iran nuclear deal",
        "Iran Israel war",
        "Iran blockade",
        "Hormuz",
        "Strait of Hormuz",
        "Hormuz closure",
        "Hormuz blockade",
        "Hormuz shipping",
        "Persian Gulf shipping attack",
        "Iran uranium",
        "Iran uranium enrichment",
        "Iran enrichment",
        "Iran negotiation",
        "Iran ceasefire talks",
        "Iran truce talks",
        "Iran armistice talks",
        "Iran peace talks",
        "Iran end war talks",
        "Iran end the war",
        "Iran peace talks collapse",
        "Iran ceasefire collapse",
        "Iran talks breakdown",
        "Iran talks deadlock",
        "Iran war end conditions",
        "Iran US conditions",
        "Israel strikes Syria",
        "Israel strikes Lebanon",
        "Israel strikes Yemen",
        "Israel attacks neighboring countries",
        "Middle East escalation Iran Israel",
        "이란 우라늄 농축",
        "호르무즈 해협",
        "호르무즈 봉쇄",
        "트럼프 이란 발언",
        "트럼프 호르무즈 발언",
        "트럼프 중동 발언",
        "이란 전쟁 종식",
        "이란 미국 조건",
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
        "south korea", "korea", "trade", "military", "nuclear", "blockade",
        "hormuz closure", "shipping", "shipping lane", "shipping lanes",
        "oil tanker", "tanker", "persian gulf", "uranium", "enrichment", "enrich",
        "iran israel", "middle east", "escalation", "retaliation", "airstrike",
        "strike", "attack", "bombing", "drone", "missile", "rocket", "ballistic",
        "trump statement", "trump remarks", "direct statement", "direct remarks",
        "election", "bitcoin", "crypto", "fed", "interest rate", "tesla", "tiktok",
        "ceasefire", "truce", "armistice", "peace talk", "peace talks",
        "negotiation", "negotiations", "end war", "end-of-war",
        "breakdown", "collapse", "deadlock", "impasse",
        "no deal", "without a deal", "without agreement", "without an agreement",
        "failed to reach", "fail to reach resolution", "ended without a deal",
        "ended without agreement", "ended without an agreement",
        "direct talks", "ceasefire talks", "end the war", "war end", "terms",
        "condition", "conditions", "offer", "end in islamabad", "islamabad",
        "hormuz", "strait of hormuz", "common framework",
        "excessive demands", "final offer", "best offer", "red line", "red lines",
        "호르무즈", "호르무즈 해협", "봉쇄", "해협", "유조선", "중동",
        "공습", "미사일", "드론", "트럼프 발언", "직접 발언",
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
        "gulf",
        "shipping lane",
        "shipping lanes",
        "oil tanker",
        "tanker",
        "hormuz closure",
        "hormuz blockade",
        "islamabad",
        "nuclear site",
        "uranium",
        "enrichment",
        "농축",
        "우라늄",
        "호르무즈",
        "호르무즈 해협",
        "페르시아만",
        "미국",
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
        "yemen",
        "iraq",
        "jordan",
        "oman",
        "red sea",
        "u.s.",
        "us",
        "american",
        "america",
        "미국",
        "미 당국",
        "워싱턴",
        "이스라엘",
        "시리아",
        "레바논",
        "예멘",
        "이라크",
        "요르단",
    ],
    "iran_conflict_keywords": [
        "war",
        "missile",
        "airstrike",
        "strike",
        "attack",
        "bombing",
        "blockade",
        "closure",
        "shut",
        "shutdown",
        "shipping disruption",
        "tanker seizure",
        "retaliation",
        "conflict",
        "clash",
        "escalation",
        "raid",
        "operation",
        "incursion",
        "shelling",
        "targeted",
        "launched",
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
        "봉쇄",
        "폐쇄",
        "차단",
        "공격",
        "공습",
        "폭격",
        "보복",
        "확전",
        "미사일",
        "드론",
        "로켓",
    ],
    "iran_war_strict_keywords": [
        "iran war",
        "iran blockade",
        "war with iran",
        "attack on iran",
        "attack against iran",
        "strike on iran",
        "strike against iran",
        "iran missile attack",
        "iran nuclear site",
        "israel iran conflict",
        "iran israel war",
        "strait of hormuz",
        "hormuz closure",
        "hormuz blockade",
        "persian gulf shipping attack",
        "iran shipping disruption",
        "israel strikes syria",
        "israel strikes lebanon",
        "israel strikes yemen",
        "israel attacks neighboring countries",
        "iran ceasefire talks",
        "iran truce talks",
        "iran armistice talks",
        "iran peace talks",
        "iran end war talks",
        "iran end the war",
        "iran talks collapse",
        "iran ceasefire collapse",
        "us iran talks",
        "us iran conditions",
        "iran uranium enrichment",
        "iran enrichment",
        "iran gives up uranium enrichment",
        "iran may give up enrichment",
        "trump iran talks",
        "trump iran war",
        "trump statement on iran",
        "trump statement on hormuz",
        "trump direct statement on iran",
        "trump direct statement on strait of hormuz",
        "trump middle east statement",
        "trump warns iran",
        "trump israel iran statement",
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
        "우라늄 농축 포기",
        "미국의 조건",
        "전쟁 종식",
        "호르무즈 해협",
        "호르무즈 봉쇄",
        "트럼프 이란 발언",
        "트럼프 호르무즈 발언",
        "트럼프 중동 발언",
        "이스라엘 시리아 공습",
        "이스라엘 레바논 공습",
        "이스라엘 예멘 공습",
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


def _tokenize_google_news_query(query: str) -> list[str]:
    # NOTE:
    # Google News 묶음 검색은 문장 전체 exact phrase보다
    # 단어 단위 AND/OR 조합이 더 유연하다.
    text = str(query or "").strip()
    if not text:
        return []
    return [token for token in text.split() if token]


def _build_google_news_boolean_clause(query: str) -> str:
    tokens = _tokenize_google_news_query(query)
    if not tokens:
        return ""
    if len(tokens) == 1:
        return f'"{tokens[0]}"'

    # NOTE:
    # Google News RSS는 일반 검색엔진처럼 AND 연산자를 엄격하게 지원하지 않을 수 있다.
    # 그래서 문장 내부는 AND 문자열 대신 핵심 토큰 나열 + 일부 phrase 유지 방식으로 완화한다.
    first_two_phrase = " ".join(tokens[:2])
    remaining_tokens = tokens[2:]
    parts = [f'"{first_two_phrase}"'] if first_two_phrase else []
    parts.extend(f'"{token}"' for token in remaining_tokens)
    return "(" + " ".join(parts) + ")"


def build_google_news_query_groups(queries: list[str], group_size: int = 4) -> list[dict[str, object]]:
    # NOTE:
    # Google News는 query마다 별도 호출하면 느려지므로,
    # 여러 검색어를 OR 묶음으로 합쳐 호출 횟수를 줄인다.
    # 문장 그대로 OR 하지 않고, 문장 내부는 단어 AND로 양자화해서 사용한다.
    normalized_queries = _normalize_string_list(queries, [])
    size = max(1, int(group_size))
    groups: list[dict[str, object]] = []
    for index in range(0, len(normalized_queries), size):
        group_queries = normalized_queries[index:index + size]
        clauses = [clause for clause in (_build_google_news_boolean_clause(query) for query in group_queries) if clause]
        if not clauses:
            continue
        groups.append(
            {
                "queries": group_queries,
                "search_query": " OR ".join(clauses),
                "label": " | ".join(group_queries),
            }
        )
    return groups


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
