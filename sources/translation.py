import re
from html import unescape

import requests

from config import REQUEST_TIMEOUT
from models import Item
from utils import contains_iran_war_keywords, looks_korean, short_text


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
            if 1 <= len(tail.split()) <= 4:
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


def enrich_item_translations(item: Item) -> Item:
    try:
        item.translated_title = translate_title_fallback(item.title)
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
