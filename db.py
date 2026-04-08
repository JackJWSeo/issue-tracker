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
                url TEXT,
                created_at TEXT NOT NULL
            )
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
        self.conn.commit()

    def has_seen(self, item_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM seen_items WHERE item_id = ? LIMIT 1", (item_id,))
        return cur.fetchone() is not None

    def mark_seen(self, item: Item):
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO seen_items(item_id, source, title, url, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item.item_id,
                item.source,
                item.title,
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