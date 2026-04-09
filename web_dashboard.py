import json
import sqlite3
from datetime import UTC, datetime, timedelta
from email.utils import formatdate
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import DB_PATH


BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_HTML_PATH = BASE_DIR / "web_dashboard.html"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 15242
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_LIMIT = 100


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fetch_recent_issues(window_minutes: int = DEFAULT_WINDOW_MINUTES, limit: int = DEFAULT_LIMIT) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(minutes=max(1, window_minutes))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT item_id, source, title, url, created_at
            FROM seen_items
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cutoff.isoformat(), max(1, limit)),
        ).fetchall()
    finally:
        conn.close()

    issues: list[dict] = []
    for row in rows:
        created_at = row["created_at"]
        created_dt = parse_iso_datetime(created_at)
        issues.append(
            {
                "item_id": row["item_id"],
                "source": row["source"] or "",
                "title": row["title"] or "(제목 없음)",
                "url": row["url"] or "",
                "created_at": created_at or "",
                "created_at_unix": int(created_dt.timestamp()) if created_dt else 0,
            }
        )
    return issues


def build_payload(window_minutes: int = DEFAULT_WINDOW_MINUTES, limit: int = DEFAULT_LIMIT) -> dict:
    issues = fetch_recent_issues(window_minutes=window_minutes, limit=limit)
    newest_issue_id = issues[0]["item_id"] if issues else None
    newest_created_at = issues[0]["created_at"] if issues else None
    return {
        "window_minutes": window_minutes,
        "limit": limit,
        "count": len(issues),
        "generated_at": datetime.now(UTC).isoformat(),
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
