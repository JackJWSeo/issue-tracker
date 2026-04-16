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
from publisher_ignore import load_ignored_news_publishers
from sources.google_news import fetch_google_news_rss
from sources.trusted_news import (
    fetch_trusted_feed_snapshot,
    fetch_trusted_news_articles_grouped_from_snapshot,
)
from sources.truth_social import fetch_truthsocial_posts
from sources.x_monitor import fetch_x_posts
from sources.translation import enrich_item_translations
from sources.youtube_live import fetch_youtube_live
from query_settings import build_google_news_query_groups, load_query_targets
from ui_settings import UISettings, load_ui_settings
from utils import (
    classify_priority_level,
    classify_trump_content,
    compute_priority,
    is_within_recent_hours,
    matches_news_query,
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

    if settings.collect_x_enabled:
        for username in targets["x_accounts"]:
            log(f"[X] 수집 시작: {username}")
            try:
                rows = apply_time_filter(fetch_x_posts(username, X_BEARER_TOKEN, db), f"X:{username}", settings, log=log)
                results.extend(rows)
                log(f"[X] 수집 완료: {username} items={len(rows)}")
            except Exception as e:
                log(f"[X] {username} 실패: {e}")
    else:
        log("[X] 수집 비활성화")

    if settings.collect_truthsocial_enabled:
        for username in targets["truthsocial_accounts"]:
            log(f"[TRUTH] 수집 시작: {username}")
            try:
                rows = apply_time_filter(fetch_truthsocial_posts(username, db), f"TRUTH:{username}", settings, log=log)
                results.extend(rows)
                log(f"[TRUTH] 수집 완료: {username} items={len(rows)}")
            except Exception as e:
                log(f"[TRUTH] {username} 실패: {e}")
    else:
        log("[TRUTH] 수집 비활성화")

    if settings.collect_youtube_enabled:
        for query in targets["youtube_queries"]:
            log(f"[YT] 수집 시작: {query}")
            try:
                rows = apply_time_filter(fetch_youtube_live(query, YOUTUBE_API_KEY), f"YT:{query}", settings, log=log)
                results.extend(rows)
                log(f"[YT] 수집 완료: {query} items={len(rows)}")
            except Exception as e:
                log(f"[YT] {query} 실패: {e}")
    else:
        log("[YT] 수집 비활성화")

    trusted_snapshot_entries: list[dict[str, str]] = []
    trusted_succeeded_publishers: set[str] = set()
    trusted_failed_publishers: set[str] = set()
    ignored_publishers = set(load_ignored_news_publishers())
    if ignored_publishers:
        log(
            f"[NEWS][IGNORE] 사용자 무시 매체 로드 "
            f"count={len(ignored_publishers)} publishers={sorted(ignored_publishers)}"
        )
    if settings.collect_trusted_news_enabled:
        try:
            trusted_snapshot_entries, trusted_succeeded_publishers, trusted_failed_publishers = fetch_trusted_feed_snapshot()
            log(
                f"[NEWS][TRUSTED] 피드 스냅샷 완료 "
                f"entries={len(trusted_snapshot_entries)} "
                f"trusted_ok={sorted(trusted_succeeded_publishers)} "
                f"trusted_fallback={sorted(trusted_failed_publishers)}"
            )
        except Exception as e:
            log(f"[NEWS][TRUSTED] 피드 스냅샷 실패: {e}")
    else:
        log("[NEWS][TRUSTED] 수집 비활성화")

    # NOTE:
    # Google News는 query별 개별 호출보다 OR 그룹 호출이 훨씬 빠르다.
    # 따라서 news_queries 전체를 소그룹으로 묶어 한 번씩만 호출하고,
    # 받은 결과를 아래에서 다시 원래 query별 bucket으로 분배한다.
    google_rows_by_query: dict[str, list[Item]] = {query: [] for query in targets["news_queries"]}
    if settings.collect_google_news_enabled:
        google_news_groups = build_google_news_query_groups(targets["news_queries"], group_size=4)
        for group in google_news_groups:
            group_queries = list(group["queries"])
            group_query = str(group["search_query"])
            group_label = str(group["label"])
            try:
                group_rows, google_stats = fetch_google_news_rss(
                    group_query,
                    recent_hours=settings.recent_hours if settings.use_recent_hours_filter else None,
                    excluded_publishers=sorted(trusted_succeeded_publishers | ignored_publishers),
                    source_label=group_label,
                )
            except Exception as e:
                log(f"[NEWS][GOOGLE-GROUP] {group_label} 실패: {e}")
                group_rows = []
                google_stats = {
                    "rss_raw_items": 0,
                    "publisher_filtered": 0,
                    "pre_filter_passed": 0,
                    "verified_passed": 0,
                    "accepted": 0,
                }

            for row in group_rows:
                for query in group_queries:
                    if matches_news_query(
                        query,
                        row.title,
                        row.body,
                        row.translated_title,
                        row.translated_body,
                    ):
                        google_rows_by_query[query].append(row)

            log(
                f"[NEWS][GOOGLE-GROUP] 수집 완료: {group_label} "
                f"rss_raw={google_stats['rss_raw_items']} "
                f"publisher_filtered={google_stats['publisher_filtered']} "
                f"pre_filter={google_stats['pre_filter_passed']} "
                f"verified={google_stats['verified_passed']} "
                f"google_total={len(group_rows)}"
            )
    else:
        log("[NEWS][GOOGLE] 수집 비활성화")

    trusted_rows_by_query: dict[str, list[Item]] = {query: [] for query in targets["news_queries"]}
    if settings.collect_trusted_news_enabled:
        try:
            trusted_rows_by_query = fetch_trusted_news_articles_grouped_from_snapshot(
                trusted_snapshot_entries,
                targets["news_queries"],
                recent_hours=settings.recent_hours if settings.use_recent_hours_filter else None,
            )
            trusted_total = sum(len(rows) for rows in trusted_rows_by_query.values())
            log(
                f"[NEWS][TRUSTED-GROUP] 수집 완료 "
                f"queries={len(targets['news_queries'])} trusted_total={trusted_total} "
                f"trusted_ok={sorted(trusted_succeeded_publishers)} trusted_fallback={sorted(trusted_failed_publishers)}"
            )
        except Exception as e:
            log(f"[NEWS][TRUSTED-GROUP] 실패: {e}")

    # NOTE:
    # 개별 query 로그는 네트워크 재검색이 아니라, 이미 모은 trusted/google 결과를
    # query별로 합쳐 최종 bucket을 만드는 로컬 분배 단계다.
    for query in targets["news_queries"]:
        trusted_rows = trusted_rows_by_query.get(query, [])
        google_rows = google_rows_by_query.get(query, [])
        rows = trusted_rows + google_rows
        rows = apply_time_filter(rows, f"NEWS:{query}", settings, log=log)
        results.extend(rows)
        if rows:
            log(
                f"[NEWS][QUERY] {query} "
                f"trusted={len(trusted_rows)} google={len(google_rows)} total={len(rows)}"
            )

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

                    item = enrich_item_translations(item)
                    item.priority_score = compute_priority(
                        " ".join(part for part in (item.title, item.translated_title) if part),
                        " ".join(part for part in (item.body, item.translated_body) if part),
                    )
                    item.priority_level = classify_priority_level(item.priority_score)
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
