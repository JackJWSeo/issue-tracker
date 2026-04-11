import asyncio
import threading
import time
from collections.abc import Callable

from config import (
    DB_PATH,
    OPENAI_API_KEY,
    POLL_SECONDS,
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
from query_settings import load_query_targets
from ui_settings import UISettings, load_ui_settings
from utils import (
    classify_trump_content,
    is_within_recent_hours,
    match_exclude_keyword,
    parse_dt,
)


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
    targets = load_query_targets()

    for username in targets["x_accounts"]:
        log(f"[X] 수집 시작: {username}")
        try:
            rows = apply_time_filter(fetch_x_posts(username, X_BEARER_TOKEN, db), f"X:{username}", settings, log=log)
            results.extend(rows)
            log(f"[X] 수집 완료: {username} items={len(rows)}")
        except Exception as e:
            log(f"[X] {username} 실패: {e}")

    for username in targets["truthsocial_accounts"]:
        log(f"[TRUTH] 수집 시작: {username}")
        try:
            rows = apply_time_filter(fetch_truthsocial_posts(username, db), f"TRUTH:{username}", settings, log=log)
            results.extend(rows)
            log(f"[TRUTH] 수집 완료: {username} items={len(rows)}")
        except Exception as e:
            log(f"[TRUTH] {username} 실패: {e}")

    for query in targets["youtube_queries"]:
        log(f"[YT] 수집 시작: {query}")
        try:
            rows = apply_time_filter(fetch_youtube_live(query, YOUTUBE_API_KEY), f"YT:{query}", settings, log=log)
            results.extend(rows)
            log(f"[YT] 수집 완료: {query} items={len(rows)}")
        except Exception as e:
            log(f"[YT] {query} 실패: {e}")

    for query in targets["news_queries"]:
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
        poll_seconds = max(5, int(getattr(settings, "monitor_poll_seconds", POLL_SECONDS) or POLL_SECONDS))
        if OPENAI_API_KEY:
            log("[INFO] AI 요약 기능은 주석 처리되어 비활성화됨")

        log("[START] Trump Monitor 시작")
        log(f"[INFO] poll={poll_seconds}s db={DB_PATH}")

        while stop_event is None or not stop_event.is_set():
            try:
                cycle_started_at = time.time()
                log("[LOOP] 새 수집 사이클 시작")
                items = collect_items(db, settings=settings, log=log)
                new_count = 0

                for item in items:
                    if stop_event is not None and stop_event.is_set():
                        break

                    if db.has_seen(item.item_id) or db.has_ignored(item.item_id):
                        continue

                    item = enrich_item_with_stt_summary(item, ai_client)
                    display_title = item.translated_title or item.title
                    matched_exclude_keyword = match_exclude_keyword(
                        settings.exclude_keywords,
                        item.title,
                        item.body,
                        item.translated_title,
                        item.translated_body,
                    )
                    content_topic = classify_trump_content(
                        item.title,
                        item.body,
                        item.translated_title,
                        item.translated_body,
                    )
                    item.is_iran_war_related = content_topic == "iran_war"

                    if matched_exclude_keyword:
                        log(
                            f"[SKIP] 제외 키워드 일치({matched_exclude_keyword}): "
                            f"{item.source} | {display_title[:80]}"
                        )
                        db.mark_ignored(item)
                    elif not content_topic:
                        log(f"[SKIP] 관심 주제 아님: {item.source} | {display_title[:80]}")
                        db.mark_ignored(item)
                    else:
                        existing_item_id, similar_title, similarity_score, duplicate_count = db.find_similar_seen_title(
                            item.title,
                            topic_tag=content_topic,
                            threshold=0.95,
                        )
                        if similar_title:
                            updated_duplicate_count = db.increment_duplicate_count(existing_item_id)
                            log(
                                f"[SKIP] 유사 제목 중복({similarity_score:.2%}, dup={updated_duplicate_count}): "
                                f"{item.source} | {display_title[:80]} ~= {similar_title[:80]}"
                            )
                            db.mark_ignored(item)
                            new_count += 1
                            await asyncio.sleep(0.6)
                            continue

                        log(f"[MATCH] {content_topic} 관련 감지: {item.source} | {display_title[:80]}")
                        if settings.telegram_enabled:
                            notifier.send(format_alert(item, settings))
                        else:
                            log("[TELEGRAM] 전송 비활성화 상태라 메시지를 보내지 않음")
                        db.mark_seen(item, topic_tag=content_topic)
                    new_count += 1
                    await asyncio.sleep(0.6)

                elapsed = time.time() - cycle_started_at
                log(f"[checked={len(items)} new={new_count} elapsed={elapsed:.1f}s]")

            except Exception as e:
                log(f"[LOOP ERROR] {e}")

            if stop_event is not None and stop_event.is_set():
                break

            await asyncio.sleep(poll_seconds)
    finally:
        db.close()


if __name__ == "__main__":
    from main_ui import launch_main_ui

    launch_main_ui()
