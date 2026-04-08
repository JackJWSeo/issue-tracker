import json

from openai import OpenAI

from config import OPENAI_SUMMARY_MODEL, USE_AI_IRAN_WAR_FILTER
from models import Item
from utils import contains_iran_war_keywords, short_text


SYSTEM_PROMPT = """당신은 정치/외교 모니터링 분석기다.
입력된 제목, 본문, 링크를 읽고 아래 JSON만 반환한다.
{
  "is_iran_war_related": true 또는 false,
  "summary": "한국어 요약"
}

판정 기준:
- 이란과 이스라엘, 미국, 중동 분쟁, 공습, 미사일, 핵시설, 보복 공격, 휴전 등
  이란 전쟁/무력충돌 맥락이 실제로 포함될 때만 true
- 단순히 "iran"이라는 단어만 나오고 전쟁/충돌 맥락이 약하면 false
- summary는 사실 중심 한국어 4~6줄
- 이란 전쟁 관련이 아니면 summary는 짧은 한 줄로 작성 가능
"""


def build_transcript_from_snippet(item: Item) -> str:
    return (
        f"출처: {item.source}\n"
        f"제목: {item.title}\n"
        f"본문: {item.body}\n"
        f"링크: {item.url}"
    )


def summarize_and_classify_item(client: OpenAI, item: Item) -> tuple[bool, str]:
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
        return is_related, short_text(summary.strip(), 1800)
    except Exception:
        lowered = text.lower()
        is_related = '"is_iran_war_related": true' in lowered or '"is_iran_war_related":true' in lowered
        return is_related, short_text(text, 1800)


def summarize_item_only(client: OpenAI, item: Item) -> str:
    transcript = build_transcript_from_snippet(item)
    resp = client.responses.create(
        model=OPENAI_SUMMARY_MODEL,
        input=[
            {
                "role": "system",
                "content": "주어진 정치/외교 관련 텍스트를 한국어로 4~6줄, 사실 중심으로 간결하게 요약하라.",
            },
            {"role": "user", "content": transcript[:12000]},
        ],
    )
    return short_text((resp.output_text or "").strip(), 1800)


def enrich_item_with_stt_summary(item: Item, client: OpenAI | None) -> Item:
    if client is None:
        item.is_iran_war_related = contains_iran_war_keywords(item.title, item.body, item.summary)
        return item

    try:
        if USE_AI_IRAN_WAR_FILTER:
            is_related, summary = summarize_and_classify_item(client, item)
            item.is_iran_war_related = is_related
            item.summary = summary
        else:
            item.summary = summarize_item_only(client, item)
            item.is_iran_war_related = contains_iran_war_keywords(item.title, item.body, item.summary)
    except Exception as e:
        item.summary = f"[요약 실패] {e}"
        item.is_iran_war_related = contains_iran_war_keywords(item.title, item.body)
    return item
