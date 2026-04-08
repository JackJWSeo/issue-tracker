import asyncio
import os
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
from sources.truth_social import fetch_truthsocial_posts
from sources.x_monitor import fetch_x_posts
from sources.youtube_live import fetch_youtube_live
from sources.youtube_stt import enrich_item_with_stt_summary
from utils import contains_iran_war_keywords, parse_dt


def collect_items(db: StateDB) -> list[Item]:
    results: list[Item] = []

    for username in TARGETS["x_accounts"]:
        print(f"[X] 수집 시작: {username}")
        try:
            rows = fetch_x_posts(username, X_BEARER_TOKEN, db)
            results.extend(rows)
            print(f"[X] 수집 완료: {username} items={len(rows)}")
        except Exception as e:
            print(f"[X] {username} 실패: {e}")

    for username in TARGETS["truthsocial_accounts"]:
        print(f"[TRUTH] 수집 시작: {username}")
        try:
            rows = fetch_truthsocial_posts(username, db)
            results.extend(rows)
            print(f"[TRUTH] 수집 완료: {username} items={len(rows)}")
        except Exception as e:
            print(f"[TRUTH] {username} 실패: {e}")

    for query in TARGETS["youtube_queries"]:
        print(f"[YT] 수집 시작: {query}")
        try:
            rows = fetch_youtube_live(query, YOUTUBE_API_KEY)
            results.extend(rows)
            print(f"[YT] 수집 완료: {query} items={len(rows)}")
        except Exception as e:
            print(f"[YT] {query} 실패: {e}")

    for query in TARGETS["news_queries"]:
        print(f"[NEWS] 수집 시작: {query}")
        try:
            rows = fetch_google_news_rss(query)
            results.extend(rows)
            print(f"[NEWS] 수집 완료: {query} items={len(rows)}")
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
            from openai import DefaultHttpxClient, OpenAI

            proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]
            active_proxies = {name: os.getenv(name, "") for name in proxy_vars if os.getenv(name)}
            if active_proxies:
                print(f"[INFO] OpenAI 호출 시 시스템 프록시 무시: {active_proxies}")

            ai_client = OpenAI(
                api_key=OPENAI_API_KEY,
                http_client=DefaultHttpxClient(trust_env=False),
            )
        except Exception as e:
            print(f"[WARN] openai SDK 로드 실패: {e}")
            print("[WARN] 요약 기능 없이 계속 실행합니다. python -m pip install openai 로 설치 가능")

    print("[START] Trump Monitor 시작")
    print(f"[INFO] poll={POLL_SECONDS}s db={DB_PATH}")

    while True:
        try:
            cycle_started_at = time.time()
            print("[LOOP] 새 수집 사이클 시작")
            items = collect_items(db)
            new_count = 0

            for item in items:
                if db.has_seen(item.item_id):
                    continue

                item.is_iran_war_related = contains_iran_war_keywords(item.title, item.body)
                item = enrich_item_with_stt_summary(item, ai_client)
                display_title = item.translated_title or item.title

                if item.is_iran_war_related:
                    print(f"[MATCH] 이란 전쟁 관련 감지: {item.source} | {display_title[:80]}")
                    notifier.send(format_alert(item))
                else:
                    print(f"[SKIP] 일반 항목 스킵: {item.source} | {display_title[:80]}")

                db.mark_seen(item)
                new_count += 1
                await asyncio.sleep(0.6)

            elapsed = time.time() - cycle_started_at
            print(f"[checked={len(items)} new={new_count} elapsed={elapsed:.1f}s]")

        except Exception as e:
            print(f"[LOOP ERROR] {e}")

        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(monitor_loop())
