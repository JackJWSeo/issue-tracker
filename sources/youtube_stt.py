from openai import OpenAI

from models import Item
from utils import short_text


SYSTEM_PROMPT = """당신은 정치 발언 모니터링 요약기다.
아래 전사 텍스트를 바탕으로 다음 형식으로 한국어 요약을 만든다.
1. 핵심 발언 3줄
2. 시장/외교/한국 관련 영향 3줄
3. 자극적 표현이나 논란 포인트 2줄
과장 없이 팩트 중심으로 쓴다.
"""


def build_transcript_from_snippet(item: Item) -> str:
    # 실제 방송 오디오 STT가 붙기 전까지는 제목/설명 기반 임시 텍스트
    return f"제목: {item.title}\n설명: {item.body}\n링크: {item.url}"


def summarize_transcript(client: OpenAI, transcript: str) -> str:
    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript[:12000]},
        ],
    )
    return short_text(resp.output_text.strip(), 1800)


def enrich_item_with_stt_summary(item: Item, client: OpenAI | None) -> Item:
    if client is None:
        return item

    try:
        transcript = build_transcript_from_snippet(item)
        item.summary = summarize_transcript(client, transcript)
    except Exception as e:
        item.summary = f"[요약 실패] {e}"
    return item