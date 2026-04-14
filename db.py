import sqlite3
from datetime import datetime, timezone

from models import Item
from utils import (
    classify_priority_level,
    compute_priority,
    normalize_title_for_dedupe,
    title_similarity,
)


class StateDB:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_items (
                item_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT,
                body TEXT,
                translated_title TEXT,
                translated_body TEXT,
                url TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        existing_columns = {
            row[1]
            for row in cur.execute("PRAGMA table_info(seen_items)").fetchall()
        }
        for column_name, column_type in (
            ("body", "TEXT"),
            ("translated_title", "TEXT"),
            ("translated_body", "TEXT"),
            ("published_at", "TEXT"),
            ("priority_score", "INTEGER NOT NULL DEFAULT 0"),
            ("priority_level", "TEXT NOT NULL DEFAULT 'normal'"),
            ("normalized_title", "TEXT"),
            ("topic_tag", "TEXT"),
            ("duplicate_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_duplicate_at", "TEXT"),
        ):
            if column_name not in existing_columns:
                cur.execute(f"ALTER TABLE seen_items ADD COLUMN {column_name} {column_type}")
        cur.execute(
            """
            UPDATE seen_items
            SET priority_level = CASE
                WHEN COALESCE(priority_score, 0) >= 12 THEN 'urgent'
                WHEN COALESCE(priority_score, 0) >= 6 THEN 'important'
                ELSE 'normal'
            END
            WHERE priority_level IS NULL OR priority_level = ''
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                k TEXT PRIMARY KEY,
                v TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ignored_items (
                item_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._backfill_priority_fields(cur)
        self.conn.commit()

    def _backfill_priority_fields(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            SELECT item_id, title, body, translated_title, translated_body, priority_score, priority_level
            FROM seen_items
            WHERE COALESCE(priority_score, 0) = 0
               OR priority_level IS NULL
               OR priority_level = ''
            """
        )
        pending_rows = cur.fetchall()
        if not pending_rows:
            return

        for item_id, title, body, translated_title, translated_body, priority_score, priority_level in pending_rows:
            merged_title = " ".join(part for part in ((title or "").strip(), (translated_title or "").strip()) if part)
            merged_body = " ".join(part for part in ((body or "").strip(), (translated_body or "").strip()) if part)
            recomputed_score = compute_priority(merged_title, merged_body)
            recomputed_level = classify_priority_level(recomputed_score)
            cur.execute(
                """
                UPDATE seen_items
                SET priority_score = ?,
                    priority_level = ?
                WHERE item_id = ?
                """,
                (recomputed_score, recomputed_level, item_id),
            )

    def has_seen(self, item_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM seen_items WHERE item_id = ? LIMIT 1", (item_id,))
        return cur.fetchone() is not None

    def has_ignored(self, item_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM ignored_items WHERE item_id = ? LIMIT 1", (item_id,))
        return cur.fetchone() is not None

    def mark_seen(self, item: Item, topic_tag: str = ""):
        cur = self.conn.cursor()
        normalized_title = normalize_title_for_dedupe(item.title)
        cur.execute(
            """
            INSERT OR IGNORE INTO seen_items(
                item_id, source, title, body, translated_title, translated_body, url, published_at, created_at,
                priority_score, priority_level, normalized_title, topic_tag, duplicate_count, last_duplicate_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.item_id,
                item.source,
                item.title,
                item.body,
                item.translated_title,
                item.translated_body,
                item.url,
                item.published_at,
                datetime.now(timezone.utc).isoformat(),
                int(item.priority_score or 0),
                str(item.priority_level or "normal"),
                normalized_title,
                topic_tag,
                0,
                None,
            ),
        )
        self.conn.commit()

    def find_similar_seen_title(
        self,
        title: str,
        topic_tag: str = "",
        threshold: float = 0.95,
    ) -> tuple[str, str, float, int]:
        normalized_title = normalize_title_for_dedupe(title)
        if not normalized_title:
            return "", "", 0.0, 0

        cur = self.conn.cursor()
        if topic_tag:
            cur.execute(
                """
                SELECT item_id, title, normalized_title, duplicate_count
                FROM seen_items
                WHERE normalized_title IS NOT NULL
                  AND normalized_title != ''
                  AND topic_tag = ?
                """,
                (topic_tag,),
            )
        else:
            cur.execute(
                """
                SELECT item_id, title, normalized_title, duplicate_count
                FROM seen_items
                WHERE normalized_title IS NOT NULL
                  AND normalized_title != ''
                """
            )

        best_item_id = ""
        best_title = ""
        best_score = 0.0
        best_duplicate_count = 0
        for existing_item_id, existing_title, existing_normalized, existing_duplicate_count in cur.fetchall():
            score = title_similarity(normalized_title, existing_normalized or "")
            if score > best_score:
                best_score = score
                best_item_id = existing_item_id or ""
                best_title = existing_title or ""
                best_duplicate_count = int(existing_duplicate_count or 0)

        if best_score >= threshold:
            return best_item_id, best_title, best_score, best_duplicate_count
        return "", "", best_score, 0

    def increment_duplicate_count(self, item_id: str) -> int:
        cur = self.conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            UPDATE seen_items
            SET duplicate_count = COALESCE(duplicate_count, 0) + 1,
                last_duplicate_at = ?
            WHERE item_id = ?
            """,
            (now, item_id),
        )
        self.conn.commit()
        cur.execute(
            """
            SELECT COALESCE(duplicate_count, 0)
            FROM seen_items
            WHERE item_id = ?
            LIMIT 1
            """,
            (item_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_value(self, key: str, default: str = "") -> str:
        cur = self.conn.cursor()
        cur.execute("SELECT v FROM kv WHERE k = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def set_value(self, key: str, value: str):
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO kv(k, v) VALUES(?, ?)
            ON CONFLICT(k) DO UPDATE SET v = excluded.v
            """,
            (key, value),
        )
        self.conn.commit()

    def mark_ignored(self, item: Item):
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO ignored_items(item_id, source, created_at)
            VALUES (?, ?, ?)
            """,
            (
                item.item_id,
                item.source,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
