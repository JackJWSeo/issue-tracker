import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from config import DB_PATH, RESOURCE_DIR
from ui_settings import load_ui_settings
from utils import looks_korean, match_exclude_keyword


DASHBOARD_HTML_PATH = RESOURCE_DIR / "web_dashboard.html"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 15242
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_LIMIT = 100
TRANSLATION_TIMEOUT_SECONDS = 10
_translation_cache: dict[str, str] = {}


def ensure_seen_items_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
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
    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(seen_items)").fetchall()
    }
    for column_name, column_type in (
        ("body", "TEXT"),
        ("translated_title", "TEXT"),
        ("translated_body", "TEXT"),
    ):
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE seen_items ADD COLUMN {column_name} {column_type}")
    conn.commit()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clean_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title_for_dedupe(value: str) -> str:
    text = clean_text(value).lower()
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
    )
    text = re.sub(r"\s+", " ", text)
    while True:
        updated = re.sub(r"\s(?:\||-)\s[^|^-]{1,80}$", "", text).strip()
        if updated == text:
            break
        text = updated
    text = re.sub(r"[^0-9a-z가-힣\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def translate_to_korean(text: str) -> str:
    text = clean_text(text)
    if not text or looks_korean(text):
        return text

    cached = _translation_cache.get(text)
    if cached is not None:
        return cached

    translated = text
    try:
        query = urlencode(
            {
                "client": "gtx",
                "sl": "auto",
                "tl": "ko",
                "dt": "t",
                "q": text[:4000],
            }
        )
        with urlopen(
            f"https://translate.googleapis.com/translate_a/single?{query}",
            timeout=TRANSLATION_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        segments = payload[0] if isinstance(payload, list) and payload else []
        merged = "".join(part[0] for part in segments if isinstance(part, list) and part and part[0])
        translated = clean_text(merged) or text
    except (OSError, ValueError, URLError):
        translated = text

    _translation_cache[text] = translated
    return translated


def hydrate_translations(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, str]:
    translated_title = clean_text(row["translated_title"] or "")
    translated_body = clean_text(row["translated_body"] or "")
    original_title = clean_text(row["title"] or "")
    original_body = clean_text(row["body"] or "")

    changed = False
    if not translated_title and original_title:
        translated_title = translate_to_korean(original_title)
        changed = translated_title != clean_text(row["translated_title"] or "")

    if not translated_body and original_body:
        translated_body = translate_to_korean(original_body)
        changed = changed or translated_body != clean_text(row["translated_body"] or "")

    if changed:
        conn.execute(
            """
            UPDATE seen_items
            SET translated_title = ?, translated_body = ?
            WHERE item_id = ?
            """,
            (translated_title, translated_body, row["item_id"]),
        )
        conn.commit()

    return translated_title, translated_body


def fetch_recent_issues(window_minutes: int = DEFAULT_WINDOW_MINUTES, limit: int = DEFAULT_LIMIT) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, window_minutes))
    settings = load_ui_settings()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    issues: list[dict] = []
    dedupe_candidates: list[dict] = []
    seen_title_keys: set[str] = set()
    try:
        ensure_seen_items_schema(conn)
        candidate_limit = min(max(1, limit) * 4, 500)
        rows = conn.execute(
            """
            SELECT item_id, source, title, body, translated_title, translated_body, url, created_at
            FROM seen_items
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cutoff.isoformat(), candidate_limit),
        ).fetchall()

        for row in rows:
            created_at = row["created_at"]
            created_dt = parse_iso_datetime(created_at)
            translated_title, translated_body = hydrate_translations(conn, row)
            title = clean_text(row["title"] or "") or "(제목 없음)"
            body = clean_text(row["body"] or "")
            matched_exclude_keyword = match_exclude_keyword(
                settings.exclude_keywords,
                title,
                body,
                translated_title,
                translated_body,
                row["source"] or "",
            )
            if matched_exclude_keyword:
                continue
            dedupe_candidates.append(
                {
                    "item_id": row["item_id"],
                    "source": row["source"] or "",
                    "title": title,
                    "body": body,
                    "translated_title": translated_title,
                    "translated_body": translated_body,
                    "url": row["url"] or "",
                    "created_at": created_at or "",
                    "created_at_unix": int(created_dt.timestamp()) if created_dt else 0,
                }
            )

        for issue in sorted(dedupe_candidates, key=lambda item: (item["created_at_unix"], item["item_id"])):
            translated_key = normalize_title_for_dedupe(issue.get("translated_title") or "")
            original_key = normalize_title_for_dedupe(issue.get("title") or "")
            dedupe_keys = {key for key in (translated_key, original_key) if key}
            if dedupe_keys and any(key in seen_title_keys for key in dedupe_keys):
                continue
            seen_title_keys.update(dedupe_keys)
            issues.append(issue)

        issues.sort(key=lambda item: (item["created_at_unix"], item["item_id"]), reverse=True)
        issues = issues[: max(1, limit)]
    finally:
        conn.close()
    return issues


def build_payload(window_minutes: int = DEFAULT_WINDOW_MINUTES, limit: int = DEFAULT_LIMIT) -> dict:
    issues = fetch_recent_issues(window_minutes=window_minutes, limit=limit)
    newest_issue_id = issues[0]["item_id"] if issues else None
    newest_created_at = issues[0]["created_at"] if issues else None
    return {
        "window_minutes": window_minutes,
        "limit": limit,
        "count": len(issues),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "newest_issue_id": newest_issue_id,
        "newest_created_at": newest_created_at,
        "issues": issues,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TrumpMonitorDashboard/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.serve_dashboard_html()
            return

        if parsed.path == "/api/issues":
            self.serve_issues_api(parsed.query)
            return

        if parsed.path == "/api/health":
            self.send_json({"ok": True, "db_path": DB_PATH})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def serve_dashboard_html(self) -> None:
        html = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Last-Modified", formatdate(usegmt=True))
        self.end_headers()
        self.wfile.write(body)

    def serve_issues_api(self, query: str) -> None:
        params = parse_qs(query)
        window_minutes = self.parse_int(params.get("minutes", [str(DEFAULT_WINDOW_MINUTES)])[0], DEFAULT_WINDOW_MINUTES)
        limit = self.parse_int(params.get("limit", [str(DEFAULT_LIMIT)])[0], DEFAULT_LIMIT)
        self.send_json(build_payload(window_minutes=window_minutes, limit=limit))

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def parse_int(value: str, default: int) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default

    def log_message(self, format: str, *args) -> None:
        return


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"[WEB] dashboard started http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[WEB] dashboard stopped")


if __name__ == "__main__":
    run_server()
