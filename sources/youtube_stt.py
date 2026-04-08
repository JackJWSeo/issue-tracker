import json
import re
from html import unescape

import requests
from openai import OpenAI

from config import OPENAI_SUMMARY_MODEL, REQUEST_TIMEOUT, USE_AI_IRAN_WAR_FILTER
from models import Item
from utils import contains_iran_war_keywords, looks_korean, short_text


SYSTEM_PROMPT = """당신은 정치/외교 모니터링 분석기다.
입력된 제목, 본문, 링크를 읽고 아래 JSON만 반환한다.
{
  "is_iran_war_related": true 또는 false,
  "summary": "한국어 요약",
  "translated_title": "한국어 제목",
  "translated_body": "한국어 본문"
}

판정 기준:
- 이란과 이스라엘, 미국, 중동 분쟁, 공습, 미사일, 핵시설, 보복 공격, 휴전 등
  이란 전쟁/무력충돌 맥락이 실제로 포함될 때만 true
- 단순히 "iran"이라는 단어만 나오고 전쟁/충돌 맥락이 약하면 false
- summary는 사실 중심 한국어 4~6줄
- 이란 전쟁 관련이 아니면 summary는 짧은 한 줄로 작성 가능
- 제목과 본문이 외국어이면 자연스러운 한국어로 번역한다
- 원문이 이미 한국어여도 translated_title, translated_body는 한국어로 정리해서 채운다
"""


def build_transcript_from_snippet(item: Item) -> str:
    return (
        f"출처: {item.source}\n"
        f"제목: {item.title}\n"
        f"본문: {item.body}\n"
        f"링크: {item.url}"
    )


def clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
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


def summarize_item_fallback(item: Item, translated_title: str, translated_body: str) -> str:
    body = clean_text(translated_body)
    title = clean_text(translated_title)
    if not body:
        return f"핵심 내용: {short_text(title, 180)}"

    sentences = re.split(r"(?<=[.!?])\s+|\s*\u2022\s*|\s*-\s+", body)
    picked: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20:
            continue
        picked.append(sentence)
        if len(picked) >= 2:
            break

    if not picked:
        picked = [short_text(body, 260)]

    return short_text(f"핵심 내용: {title} / {' '.join(picked)}", 500)


def fallback_translate_and_summarize(item: Item) -> Item:
    try:
        item.translated_title = translate_text_fallback(item.title)
    except Exception as e:
        print(f"[FALLBACK] 제목 번역 실패: {e}")
        item.translated_title = clean_text(item.title)

    try:
        item.translated_body = translate_text_fallback(item.body)
    except Exception as e:
        print(f"[FALLBACK] 본문 번역 실패: {e}")
        item.translated_body = clean_text(item.body)

    item.summary = summarize_item_fallback(item, item.translated_title or item.title, item.translated_body or item.body)
    item.is_iran_war_related = contains_iran_war_keywords(
        item.title,
        item.body,
        item.translated_title,
        item.translated_body,
        item.summary,
    )
    return item


def summarize_and_classify_item(client: OpenAI, item: Item) -> tuple[bool, str, str, str]:
    transcript = build_transcript_from_snippet(item)
    resp = client.responses.create(
        model=OPENAI_SUMMARY_MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript[:12000]},
        ],
    )

    text = (resp.output_text or "").strip()

    try:
        data = json.loads(text)
        is_related = bool(data.get("is_iran_war_related"))
        summary = str(data.get("summary") or "")
        translated_title = str(data.get("translated_title") or item.title)
        translated_body = str(data.get("translated_body") or item.body)
        return (
            is_related,
            short_text(summary.strip(), 1800),
            short_text(translated_title.strip(), 300),
            short_text(translated_body.strip(), 1200),
        )
    except Exception:
        lowered = text.lower()
        is_related = '"is_iran_war_related": true' in lowered or '"is_iran_war_related":true' in lowered
        return (
            is_related,
            short_text(text, 1800),
            item.title,
            item.body,
        )


def summarize_item_only(client: OpenAI, item: Item) -> tuple[str, str, str]:
    transcript = build_transcript_from_snippet(item)
    resp = client.responses.create(
        model=OPENAI_SUMMARY_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "주어진 정치/외교 관련 텍스트를 읽고 아래 JSON만 반환하라."
                    ' {"summary":"한국어 요약","translated_title":"한국어 제목","translated_body":"한국어 본문"} '
                    "제목과 본문이 외국어이면 자연스럽게 한국어로 번역하고,"
                    " 이미 한국어여도 더 읽기 좋게 한국어로 정리하라."
                ),
            },
            {"role": "user", "content": transcript[:12000]},
        ],
    )
    text = (resp.output_text or "").strip()

    try:
        data = json.loads(text)
        return (
            short_text(str(data.get("summary") or "").strip(), 1800),
            short_text(str(data.get("translated_title") or item.title).strip(), 300),
            short_text(str(data.get("translated_body") or item.body).strip(), 1200),
        )
    except Exception:
        return short_text(text, 1800), item.title, item.body


def enrich_item_with_stt_summary(item: Item, client: OpenAI | None) -> Item:
    if client is None:
        return fallback_translate_and_summarize(item)

    try:
        if USE_AI_IRAN_WAR_FILTER:
            is_related, summary, translated_title, translated_body = summarize_and_classify_item(client, item)
            item.is_iran_war_related = is_related
            item.summary = summary
            item.translated_title = translated_title
            item.translated_body = translated_body
        else:
            summary, translated_title, translated_body = summarize_item_only(client, item)
            item.summary = summary
            item.translated_title = translated_title
            item.translated_body = translated_body
            item.is_iran_war_related = contains_iran_war_keywords(item.title, item.body, item.summary)
    except Exception as e:
        print(f"[OPENAI] 요약/번역 실패: {e}")
        return fallback_translate_and_summarize(item)

    return item
