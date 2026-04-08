import asyncio
import time

from config import (
    DB_PATH,
    OPENAI_API_KEY,
    POLL_SECONDS,
    TARGETS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    X_BEARER_TOKEN,
    YOUTUBE_API_KEY,
)
from db import StateDB
from models import Item
from notifier import TelegramNotifier, format_alert
from sources.google_news import fetch_google_news_rss
from sources.x_monitor import fetch_x_posts
from sources.youtube_live import fetch_youtube_live
from sources.youtube_stt import enrich_item_with_stt_summary
from utils import parse_dt


def collect_items(db: StateDB) -> list[Item]:
    results: list[Item] = []

    for username in TARGETS["x_accounts"]:
        try:
            results.extend(fetch_x_posts(username, X_BEARER_TOKEN, db))
        except Exception as e:
            print(f"[X] {username} 실패: {e}")

    for query in TARGETS["youtube_queries"]:
        try:
            results.extend(fetch_youtube_live(query, YOUTUBE_API_KEY))
        except Exception as e:
            print(f"[YT] {query} 실패: {e}")

    for query in TARGETS["news_queries"]:
        try:
            results.extend(fetch_google_news_rss(query))
        except Exception as e:
            print(f"[NEWS] {query} 실패: {e}")

    def sort_key(item: Item):
        dt = parse_dt(item.published_at)
        ts = dt.timestamp() if dt else 0.0
        return (item.priority_score, ts)

    results.sort(key=sort_key, reverse=True)
    return results


async def monitor_loop():
    db = StateDB(DB_PATH)
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    ai_client = None
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            ai_client = OpenAI(api_key=OPENAI_API_KEY)
        except Exception as e:
            print(f"[WARN] openai SDK 로드 실패: {e}")
            print("[WARN] 요약 기능 없이 계속 실행합니다. python -m pip install openai 로 설치 가능")

    print("[START] Trump Monitor 시작")
    print(f"[INFO] poll={POLL_SECONDS}s db={DB_PATH}")

    while True:
        try:
            items = collect_items(db)
            new_count = 0

            for item in items:
                if db.has_seen(item.item_id):
                    continue

                db.mark_seen(item)
                new_count += 1

                if item.priority_score < 1:
                    continue

                # 3) STT/요약 단계
                # 현재 버전은 YouTube 라이브/영상의 제목·설명 기반 임시 전사 요약.
                # 실제 음성 STT를 넣고 싶으면 yt-dlp + ffmpeg로 오디오 추출 후
                # Whisper 전사 함수로 교체하면 된다.
                if item.source.startswith("youtube_live:") or item.source.startswith("x:"):
                    item = enrich_item_with_stt_summary(item, ai_client)

                notifier.send(format_alert(item))
                time.sleep(0.6)

            print(f"[checked={len(items)} new={new_count}]")

        except Exception as e:
            print(f"[LOOP ERROR] {e}")

        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(monitor_loop())