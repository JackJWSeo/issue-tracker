import asyncio
import threading
import time
from collections.abc import Callable

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
from ui_settings import UISettings, load_ui_settings
from utils import contains_iran_war_keywords, is_within_recent_hours, parse_dt


LogFn = Callable[[str], None]


def default_log(message: str) -> None:
    print(message)


def apply_time_filter(
    items: list[Item],
    label: str,
    settings: UISettings,
    log: LogFn = default_log,
) -> list[Item]:
    if not settings.use_recent_hours_filter:
        return items

    kept = [item for item in items if is_within_recent_hours(item.published_at, settings.recent_hours)]
    dropped = len(items) - len(kept)
    if dropped:
        log(
            f"[DATE] 최근 {settings.recent_hours}시간 범위를 벗어난 {label} 항목 제외: "
            f"dropped={dropped} kept={len(kept)}"
        )
    return kept


def collect_items(db: StateDB, settings: UISettings, log: LogFn = default_log) -> list[Item]:
    results: list[Item] = []

    for username in TARGETS["x_accounts"]:
        log(f"[X] 수집 시작: {username}")
        try:
            rows = apply_time_filter(fetch_x_posts(username, X_BEARER_TOKEN, db), f"X:{username}", settings, log=log)
            results.extend(rows)
            log(f"[X] 수집 완료: {username} items={len(rows)}")
        except Exception as e:
            log(f"[X] {username} 실패: {e}")

    for username in TARGETS["truthsocial_accounts"]:
        log(f"[TRUTH] 수집 시작: {username}")
        try:
            rows = apply_time_filter(fetch_truthsocial_posts(username, db), f"TRUTH:{username}", settings, log=log)
            results.extend(rows)
            log(f"[TRUTH] 수집 완료: {username} items={len(rows)}")
        except Exception as e:
            log(f"[TRUTH] {username} 실패: {e}")

    for query in TARGETS["youtube_queries"]:
        log(f"[YT] 수집 시작: {query}")
        try:
            rows = apply_time_filter(fetch_youtube_live(query, YOUTUBE_API_KEY), f"YT:{query}", settings, log=log)
            results.extend(rows)
            log(f"[YT] 수집 완료: {query} items={len(rows)}")
        except Exception as e:
            log(f"[YT] {query} 실패: {e}")

    for query in TARGETS["news_queries"]:
        log(f"[NEWS] 수집 시작: {query}")
        try:
            rows = apply_time_filter(fetch_google_news_rss(query), f"NEWS:{query}", settings, log=log)
            results.extend(rows)
            log(f"[NEWS] 수집 완료: {query} items={len(rows)}")
        except Exception as e:
            log(f"[NEWS] {query} 실패: {e}")

    def sort_key(item: Item):
        dt = parse_dt(item.published_at)
        ts = dt.timestamp() if dt else 0.0
        return (item.priority_score, ts)

    results.sort(key=sort_key, reverse=True)
    return results


async def monitor_loop(
    stop_event: threading.Event | None = None,
    log: LogFn = default_log,
    settings: UISettings | None = None,
):
    db = StateDB(DB_PATH)
    try:
        notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        ai_client = None
        settings = settings or load_ui_settings()
        if OPENAI_API_KEY:
            log("[INFO] AI 요약 기능은 주석 처리되어 비활성화됨")

        log("[START] Trump Monitor 시작")
        log(f"[INFO] poll={POLL_SECONDS}s db={DB_PATH}")

        while stop_event is None or not stop_event.is_set():
            try:
                cycle_started_at = time.time()
                log("[LOOP] 새 수집 사이클 시작")
                items = collect_items(db, settings=settings, log=log)
                new_count = 0

                for item in items:
                    if stop_event is not None and stop_event.is_set():
                        break

                    if db.has_seen(item.item_id):
                        continue

                    item.is_iran_war_related = contains_iran_war_keywords(item.title, item.body)
                    item = enrich_item_with_stt_summary(item, ai_client)
                    display_title = item.translated_title or item.title

                    if item.is_iran_war_related:
                        log(f"[MATCH] 이란 전쟁 관련 감지: {item.source} | {display_title[:80]}")
                        if settings.telegram_enabled:
                            notifier.send(format_alert(item, settings))
                        else:
                            log("[TELEGRAM] 전송 비활성화 상태라 메시지를 보내지 않음")
                    else:
                        log(f"[SKIP] 일반 항목 스킵: {item.source} | {display_title[:80]}")

                    db.mark_seen(item)
                    new_count += 1
                    await asyncio.sleep(0.6)

                elapsed = time.time() - cycle_started_at
                log(f"[checked={len(items)} new={new_count} elapsed={elapsed:.1f}s]")

            except Exception as e:
                log(f"[LOOP ERROR] {e}")

            if stop_event is not None and stop_event.is_set():
                break

            await asyncio.sleep(POLL_SECONDS)
    finally:
        db.close()


if __name__ == "__main__":
    from main_ui import launch_main_ui

    launch_main_ui()
