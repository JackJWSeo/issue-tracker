import sqlite3
from datetime import datetime, timezone

from models import Item


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
        ):
            if column_name not in existing_columns:
                cur.execute(f"ALTER TABLE seen_items ADD COLUMN {column_name} {column_type}")
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
        self.conn.commit()

    def has_seen(self, item_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM seen_items WHERE item_id = ? LIMIT 1", (item_id,))
        return cur.fetchone() is not None

    def has_ignored(self, item_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM ignored_items WHERE item_id = ? LIMIT 1", (item_id,))
        return cur.fetchone() is not None

    def mark_seen(self, item: Item):
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO seen_items(
                item_id, source, title, body, translated_title, translated_body, url, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.item_id,
                item.source,
                item.title,
                item.body,
                item.translated_title,
                item.translated_body,
                item.url,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

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
