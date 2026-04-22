import re
from html import unescape
from typing import Any

import requests

from config import OPENAI_API_KEY, OPENAI_TRANSLATION_MODEL, REQUEST_TIMEOUT
from models import Item
from utils import contains_iran_war_keywords, looks_korean, short_text

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - SDK import failure should not break monitoring
    OpenAI = None  # type: ignore[assignment]


NEGATION_PATTERNS = [
    re.compile(r"\bnot\b", re.IGNORECASE),
    re.compile(r"\bno\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\bwithout\b", re.IGNORECASE),
    re.compile(r"\bdenies?\b", re.IGNORECASE),
    re.compile(r"\bwon't\b", re.IGNORECASE),
    re.compile(r"\bcan't\b", re.IGNORECASE),
    re.compile(r"\bdoesn't\b", re.IGNORECASE),
    re.compile(r"\bdidn't\b", re.IGNORECASE),
    re.compile(r"\bisn't\b", re.IGNORECASE),
    re.compile(r"\baren't\b", re.IGNORECASE),
    re.compile(r"\bunlikely\b", re.IGNORECASE),
    re.compile(r"\bunlikely to\b", re.IGNORECASE),
    re.compile(r"\bunless\b", re.IGNORECASE),
    re.compile(r"\bhalts?\b", re.IGNORECASE),
    re.compile(r"\bstops?\b", re.IGNORECASE),
    re.compile(r"\brefuses?\b", re.IGNORECASE),
    re.compile(r"\b반대\b"),
    re.compile(r"\b부인\b"),
    re.compile(r"\b중단\b"),
    re.compile(r"\b거부\b"),
    re.compile(r"\b않[는다]\b"),
]
CONDITIONAL_PATTERNS = [
    re.compile(r"\bif\b", re.IGNORECASE),
    re.compile(r"\bunless\b", re.IGNORECASE),
    re.compile(r"\buntil\b", re.IGNORECASE),
    re.compile(r"\bwithout\b", re.IGNORECASE),
    re.compile(r"\bas long as\b", re.IGNORECASE),
    re.compile(r"\bon condition that\b", re.IGNORECASE),
]
QUESTION_START_PATTERNS = [
    re.compile(r"^(would|could|should|will|is|are|can|do|does|did|how|what|why|when|where|who)\b", re.IGNORECASE),
]
QUOTE_OR_ATTRIBUTION_PATTERNS = [
    re.compile(r"[:\"'“”‘’]"),
    re.compile(r"\b(says|said|claims|claimed|warns|warning|threatens|threat|denies|denied|announces|announced)\b", re.IGNORECASE),
]
KOREAN_NEGATION_MARKERS = (
    "않",
    "아니",
    "못",
    "없",
    "반대",
    "부인",
    "거부",
    "중단",
    "금지",
    "불가",
)
KOREAN_CONDITIONAL_MARKERS = (
    "없이",
    "없이는",
    "않으면",
    "아니면",
    "경우",
    "때까지",
    "전까지",
    "조건",
)
KOREAN_QUESTION_MARKERS = (
    "?",
    "인가",
    "일까",
    "되나",
    "할까",
    "가능할까",
)
MEANINGFUL_TITLE_SUFFIXES = {
    "reuters",
    "ap",
    "ap news",
    "associated press",
    "cnn",
    "bbc",
    "fox news",
    "msnbc",
    "abc news",
    "cbs news",
    "nbc news",
    "the hill",
    "politico",
    "newsweek",
    "time",
    "axios",
    "npr",
    "pbs",
    "pbs news",
    "guardian",
    "the guardian",
    "washington post",
    "new york times",
    "wsj",
    "wall street journal",
    "bloomberg",
    "financial times",
}
TRANSLATION_SYSTEM_PROMPT = """You translate English news headlines into natural Korean.

Rules:
- Preserve the original meaning exactly. Never flip polarity, certainty, or causality.
- Keep negation words such as not, no, never, deny, halt, refuse, unless, fail to, and without.
- Keep whether something is a claim, quote, threat, question, warning, proposal, or analysis.
- Do not add facts or interpretations.
- Do not summarize.
- Output only one Korean headline line.
"""
TRANSLATION_CHECK_SYSTEM_PROMPT = """You validate whether a Korean headline preserves the exact meaning of the English headline.

Rules:
- Focus on polarity, negation, conditions, causality, and whether it is a quote/question/claim.
- Mark UNSAFE if the Korean changes or drops any critical condition such as not, without, unless, if, refuse, deny, halt.
- Reply with exactly one token: SAFE or UNSAFE.
"""
_openai_client: Any | None = None
_openai_client_ready = False


def clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title_for_translation(title: str) -> str:
    text = clean_text(title)
    if not text:
        return ""

    split_patterns = [
        r"\s+\|\s+",
        r"\s+[-–—]\s+",
    ]
    for pattern in split_patterns:
        parts = re.split(pattern, text)
        if len(parts) >= 2:
            tail = parts[-1].strip()
            normalized_tail = re.sub(r"[^a-z0-9\s]", " ", tail.lower())
            normalized_tail = re.sub(r"\s+", " ", normalized_tail).strip()
            if normalized_tail in MEANINGFUL_TITLE_SUFFIXES:
                text = " ".join(parts[:-1]).strip()
                break

    text = re.sub(r"^\[(breaking|live|watch live|video)\]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\((video|live|photos?)\)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def translate_text_fallback(text: str) -> str:
    text = clean_text(text)
    if not text or looks_korean(text):
        return text

    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": "ko",
        "dt": "t",
        "q": text[:4000],
    }
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    segments = payload[0] if isinstance(payload, list) and payload else []
    translated = "".join(part[0] for part in segments if isinstance(part, list) and part and part[0])
    return clean_text(translated) or text


def translate_title_fallback(title: str) -> str:
    normalized_title = normalize_title_for_translation(title)
    if not normalized_title:
        return ""
    translated = translate_text_fallback(normalized_title)
    return short_text(translated, 300)


def count_negation_signals(text: str) -> int:
    normalized = clean_text(text)
    if not normalized:
        return 0

    matches = sum(1 for pattern in NEGATION_PATTERNS if pattern.search(normalized))
    matches += sum(1 for marker in KOREAN_NEGATION_MARKERS if marker in normalized)
    return matches


def translation_preserves_negation(source_text: str, translated_text: str) -> bool:
    source_negations = count_negation_signals(source_text)
    translated_negations = count_negation_signals(translated_text)
    if source_negations == 0:
        return True
    return translated_negations > 0


def has_conditional_signal(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in CONDITIONAL_PATTERNS)


def has_question_signal(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    if "?" in normalized:
        return True
    return any(pattern.search(normalized) for pattern in QUESTION_START_PATTERNS)


def has_quote_or_attribution_signal(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in QUOTE_OR_ATTRIBUTION_PATTERNS)


def translation_preserves_conditionals(source_text: str, translated_text: str) -> bool:
    if not has_conditional_signal(source_text):
        return True
    normalized = clean_text(translated_text)
    return any(marker in normalized for marker in KOREAN_CONDITIONAL_MARKERS)


def translation_preserves_question(source_text: str, translated_text: str) -> bool:
    if not has_question_signal(source_text):
        return True
    normalized = clean_text(translated_text)
    return any(marker in normalized for marker in KOREAN_QUESTION_MARKERS)


def is_high_risk_headline(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    return (
        count_negation_signals(normalized) > 0
        or has_conditional_signal(normalized)
        or has_question_signal(normalized)
        or has_quote_or_attribution_signal(normalized)
    )


def translation_preserves_core_meaning(source_text: str, translated_text: str) -> bool:
    normalized_translation = clean_text(translated_text)
    if not normalized_translation:
        return False
    return (
        translation_preserves_negation(source_text, normalized_translation)
        and translation_preserves_conditionals(source_text, normalized_translation)
        and translation_preserves_question(source_text, normalized_translation)
    )


def get_openai_client() -> Any | None:
    global _openai_client, _openai_client_ready

    if _openai_client_ready:
        return _openai_client

    _openai_client_ready = True
    if not OPENAI_API_KEY or OpenAI is None:
        return None

    try:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        _openai_client = None
    return _openai_client


def verify_title_translation_with_openai(source_title: str, translated_title: str, client: Any | None = None) -> bool:
    client = client or get_openai_client()
    if client is None:
        return True

    response = client.responses.create(
        model=OPENAI_TRANSLATION_MODEL,
        input=[
            {"role": "system", "content": TRANSLATION_CHECK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"English headline: {source_title[:1000]}\n"
                    f"Korean headline: {translated_title[:1000]}"
                ),
            },
        ],
    )
    verdict = clean_text(response.output_text).upper()
    return verdict == "SAFE"


def translate_title_with_openai(title: str, client: Any | None = None) -> str:
    normalized_title = normalize_title_for_translation(title)
    if not normalized_title or looks_korean(normalized_title):
        return normalized_title

    client = client or get_openai_client()
    if client is None:
        return ""

    response = client.responses.create(
        model=OPENAI_TRANSLATION_MODEL,
        input=[
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Translate this headline into Korean exactly:\n{normalized_title[:1000]}",
            },
        ],
    )
    translated = short_text(clean_text(response.output_text), 300)
    if not translated:
        return ""
    if not translation_preserves_core_meaning(normalized_title, translated):
        return ""
    if not verify_title_translation_with_openai(normalized_title, translated, client=client):
        return ""
    return translated


def translate_title(title: str) -> str:
    normalized_title = normalize_title_for_translation(title)
    if not normalized_title:
        return ""
    if looks_korean(normalized_title):
        return normalized_title

    high_risk = is_high_risk_headline(normalized_title)
    translated = ""
    try:
        translated = translate_title_with_openai(normalized_title)
    except Exception:
        translated = ""

    if translated:
        return translated

    if high_risk:
        return normalized_title

    translated = translate_title_fallback(normalized_title)
    if translation_preserves_core_meaning(normalized_title, translated):
        return translated
    return normalized_title


def enrich_item_translations(item: Item) -> Item:
    try:
        item.translated_title = translate_title(item.title)
    except Exception as e:
        print(f"[FALLBACK] 제목 번역 실패: {e}")
        item.translated_title = clean_text(item.title)

    item.translated_body = ""
    item.summary = ""
    item.is_iran_war_related = contains_iran_war_keywords(
        item.title,
        item.body,
        item.translated_title,
        item.translated_body,
    )
    return item
