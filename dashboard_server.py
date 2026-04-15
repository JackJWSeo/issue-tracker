import json
import ipaddress
import re
import sqlite3
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.utils import formatdate
from html import unescape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import timeout as SocketTimeout
from urllib.parse import parse_qs, urlparse

from config import (
    DB_PATH,
    RESOURCE_DIR,
    WEB_DASHBOARD_ALLOWED_HOSTS,
    WEB_DASHBOARD_ALLOW_PUBLIC,
)
from ui_settings import load_ui_settings
from utils import (
    match_exclude_keyword,
    parse_dt,
)


DASHBOARD_HTML_PATH = RESOURCE_DIR / "web_dashboard.html"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 15242
DEFAULT_LIMIT = 100
SOCKET_TIMEOUT_SECONDS = 5
MAX_PATH_LENGTH = 2048
MAX_QUERY_LENGTH = 512
MAX_QUERY_PARAMS = 8
SECURITY_CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)
RATE_LIMIT_WINDOW_SECONDS = 10
RATE_LIMIT_MAX_REQUESTS = 40
RATE_LIMIT_MAX_API_REQUESTS = 20
RATE_LIMIT_BLOCK_SECONDS = 120
_rate_limit_lock = threading.Lock()
_rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_api_events: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_blocked_until: dict[str, float] = {}


def _is_private_or_loopback_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def is_allowed_client_ip(client_ip: str) -> bool:
    if WEB_DASHBOARD_ALLOW_PUBLIC:
        return True
    return _is_private_or_loopback_ip(client_ip)


def build_allowed_hostnames(server: ThreadingHTTPServer) -> set[str]:
    configured = {host for host in WEB_DASHBOARD_ALLOWED_HOSTS if host}
    bound_host = str(getattr(server, "server_address", ("", 0))[0] or "").strip().lower()
    allowed = {
        "localhost",
        "127.0.0.1",
        "[::1]",
        "0.0.0.0",
    }
    if bound_host and bound_host != "0.0.0.0":
        allowed.add(bound_host)
    allowed.update(configured)
    return allowed


def is_valid_host_header(host_header: str, server: ThreadingHTTPServer) -> bool:
    value = (host_header or "").strip().lower()
    if not value:
        return False
    if len(value) > 255 or any(char in value for char in ("\r", "\n", "/", "\\", "@")):
        return False
    hostname = value
    if value.startswith("["):
        bracket_end = value.find("]")
        hostname = value[: bracket_end + 1] if bracket_end > 0 else value
    elif ":" in value:
        hostname = value.split(":", 1)[0]
    if hostname in build_allowed_hostnames(server):
        return True
    if hostname == "0.0.0.0" or _is_private_or_loopback_ip(hostname):
        return True
    try:
        ipaddress.ip_address(hostname.strip("[]"))
        return True
    except ValueError:
        pass
    if re.fullmatch(r"[a-z0-9.-]+", hostname):
        local_host_suffixes = (".local", ".lan", ".home", ".internal")
        if hostname.endswith(local_host_suffixes):
            return True
        if "." in hostname:
            return True
    return False


def _prune_rate_limit_entries(events: deque[float], now_ts: float, window_seconds: int) -> None:
    cutoff = now_ts - window_seconds
    while events and events[0] < cutoff:
        events.popleft()


def check_rate_limit(client_ip: str, path: str) -> tuple[bool, int | None]:
    now_ts = datetime.now(timezone.utc).timestamp()
    is_api_request = path.startswith("/api/")
    with _rate_limit_lock:
        blocked_until = _rate_limit_blocked_until.get(client_ip, 0.0)
        if blocked_until > now_ts:
            retry_after = max(1, int(blocked_until - now_ts))
            return False, retry_after
        if blocked_until:
            _rate_limit_blocked_until.pop(client_ip, None)

        general_events = _rate_limit_events[client_ip]
        _prune_rate_limit_entries(general_events, now_ts, RATE_LIMIT_WINDOW_SECONDS)
        general_events.append(now_ts)

        if len(general_events) > RATE_LIMIT_MAX_REQUESTS:
            _rate_limit_blocked_until[client_ip] = now_ts + RATE_LIMIT_BLOCK_SECONDS
            return False, RATE_LIMIT_BLOCK_SECONDS

        if is_api_request:
            api_events = _rate_limit_api_events[client_ip]
            _prune_rate_limit_entries(api_events, now_ts, RATE_LIMIT_WINDOW_SECONDS)
            api_events.append(now_ts)
            if len(api_events) > RATE_LIMIT_MAX_API_REQUESTS:
                _rate_limit_blocked_until[client_ip] = now_ts + RATE_LIMIT_BLOCK_SECONDS
                return False, RATE_LIMIT_BLOCK_SECONDS

    return True, None


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
        ("published_at", "TEXT"),
        ("priority_score", "INTEGER NOT NULL DEFAULT 0"),
        ("priority_level", "TEXT NOT NULL DEFAULT 'normal'"),
    ):
        if column_name not in existing_columns:
            try:
                conn.execute(f"ALTER TABLE seen_items ADD COLUMN {column_name} {column_type}")
            except sqlite3.OperationalError:
                continue
    try:
        conn.execute(
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
    except sqlite3.OperationalError:
        pass
    try:
        conn.commit()
    except sqlite3.OperationalError:
        pass


def get_seen_items_columns(conn: sqlite3.Connection) -> set[str]:
    return {
        row[1]
        for row in conn.execute("PRAGMA table_info(seen_items)").fetchall()
    }


def build_seen_items_select_sql(existing_columns: set[str]) -> str:
    def select_expr(column_name: str, fallback_sql: str) -> str:
        if column_name in existing_columns:
            return column_name
        return f"{fallback_sql} AS {column_name}"

    return f"""
        SELECT
            {select_expr("item_id", "''")},
            {select_expr("source", "''")},
            {select_expr("title", "''")},
            {select_expr("body", "''")},
            {select_expr("translated_title", "''")},
            {select_expr("translated_body", "''")},
            {select_expr("url", "''")},
            {select_expr("published_at", "''")},
            {select_expr("created_at", "''")},
            {select_expr("priority_score", "0")}
            , {select_expr("priority_level", "'normal'")}
        FROM seen_items
        ORDER BY created_at DESC
        LIMIT ?
    """


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


def parse_issue_datetime(published_at: str | None, created_at: str | None) -> datetime | None:
    published_dt = parse_dt(published_at)
    if published_dt is not None:
        if published_dt.tzinfo is None:
            return published_dt.replace(tzinfo=timezone.utc)
        return published_dt.astimezone(timezone.utc)
    return parse_iso_datetime(created_at)


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


def hydrate_translations(row: sqlite3.Row) -> tuple[str, str]:
    translated_title = clean_text(row["translated_title"] or "")
    translated_body = clean_text(row["translated_body"] or "")
    return translated_title, translated_body


def normalize_priority_level(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"urgent", "important", "normal"}:
        return text
    return "normal"


def priority_level_label(level: str) -> str:
    normalized = normalize_priority_level(level)
    if normalized == "urgent":
        return "긴급"
    if normalized == "important":
        return "중요"
    return "일반"


def _collect_issue_rows(rows: list[sqlite3.Row]) -> list[dict]:
    settings = load_ui_settings()
    issues: list[dict] = []
    dedupe_candidates: list[dict] = []
    seen_title_keys: set[str] = set()
    for row in rows:
        created_at = row["created_at"]
        published_at = row["published_at"] or ""
        issue_dt = parse_issue_datetime(published_at, created_at)
        translated_title, translated_body = hydrate_translations(row)
        title = clean_text(row["title"] or "") or "(제목 없음)"
        body = clean_text(row["body"] or "")
        priority_score = int(row["priority_score"] or 0)
        priority_level = normalize_priority_level(row["priority_level"] or "normal")
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
                "published_at": published_at,
                "created_at": created_at or "",
                "issue_time_unix": int(issue_dt.timestamp()) if issue_dt else 0,
                "priority_score": priority_score,
                "priority_level": priority_level,
                "priority_label": priority_level_label(priority_level),
            }
        )

    for issue in sorted(
        dedupe_candidates,
        key=lambda item: (item["issue_time_unix"], item["item_id"]),
    ):
        translated_key = normalize_title_for_dedupe(issue.get("translated_title") or "")
        original_key = normalize_title_for_dedupe(issue.get("title") or "")
        dedupe_keys = {key for key in (translated_key, original_key) if key}
        if dedupe_keys and any(key in seen_title_keys for key in dedupe_keys):
            continue
        seen_title_keys.update(dedupe_keys)
        issues.append(issue)

    issues.sort(key=lambda item: (item["issue_time_unix"], item["item_id"]), reverse=True)
    return issues


def fetch_recent_issues(limit: int = DEFAULT_LIMIT) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        ensure_seen_items_schema(conn)
        existing_columns = get_seen_items_columns(conn)
        seen_items_select_sql = build_seen_items_select_sql(existing_columns)
        requested_limit = max(1, limit)
        candidate_limit = min(requested_limit * 6, 500)
        latest_rows = conn.execute(seen_items_select_sql, (candidate_limit,)).fetchall()
        latest_issues = _collect_issue_rows(latest_rows)
        return latest_issues[:requested_limit]
    finally:
        conn.close()


def build_payload(limit: int = DEFAULT_LIMIT) -> dict:
    issues = fetch_recent_issues(limit=limit)
    newest_issue_id = issues[0]["item_id"] if issues else None
    newest_created_at = issues[0]["created_at"] if issues else None
    return {
        "limit": limit,
        "count": len(issues),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "newest_issue_id": newest_issue_id,
        "newest_created_at": newest_created_at,
        "issues": issues,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TrumpMonitorDashboard/1.0"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)
        except OSError:
            pass

    def do_HEAD(self) -> None:
        self.do_GET(head_only=True)

    def do_POST(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def do_PUT(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def do_DELETE(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, HEAD")
        self.end_headers()

    def do_GET(self, head_only: bool = False) -> None:
        client_ip = self.client_address[0] if self.client_address else "unknown"
        parsed = urlparse(self.path)
        if len(parsed.path or "") > MAX_PATH_LENGTH or len(parsed.query or "") > MAX_QUERY_LENGTH:
            self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG, "Request too long")
            return
        if len(parse_qs(parsed.query, keep_blank_values=True)) > MAX_QUERY_PARAMS:
            self.send_error(HTTPStatus.BAD_REQUEST, "Too many query parameters")
            return
        if not is_allowed_client_ip(client_ip):
            self.send_error(HTTPStatus.FORBIDDEN, "Client IP not allowed")
            return
        if not is_valid_host_header(self.headers.get("Host", ""), self.server):
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid host header")
            return

        allowed, retry_after = check_rate_limit(client_ip, parsed.path or "")
        if not allowed:
            self.send_json(
                {
                    "ok": False,
                    "error": "rate_limited",
                    "retry_after_seconds": retry_after,
                },
                status=HTTPStatus.TOO_MANY_REQUESTS,
                extra_headers={"Retry-After": str(retry_after or RATE_LIMIT_BLOCK_SECONDS)},
                head_only=head_only,
            )
            return

        if parsed.path in {"/", "/index.html"}:
            self.serve_dashboard_html(head_only=head_only)
            return

        if parsed.path == "/api/issues":
            self.serve_issues_api(parsed.query, head_only=head_only)
            return

        if parsed.path == "/api/health":
            self.send_json({"ok": True}, head_only=head_only)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def add_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Content-Security-Policy", SECURITY_CSP)
        self.send_header("Cache-Control", "no-store")

    def end_headers(self) -> None:
        self.add_security_headers()
        super().end_headers()

    def serve_dashboard_html(self, head_only: bool = False) -> None:
        html = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Last-Modified", formatdate(usegmt=True))
        self.end_headers()
        if not head_only:
            self.safe_write(body)

    def serve_issues_api(self, query: str, head_only: bool = False) -> None:
        params = parse_qs(query)
        limit = self.parse_int(
            params.get("limit", [str(DEFAULT_LIMIT)])[0],
            DEFAULT_LIMIT,
            max_value=DEFAULT_LIMIT,
        )
        self.send_json(
            build_payload(limit=limit),
            head_only=head_only,
        )

    def send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
        head_only: bool = False,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for header_name, header_value in extra_headers.items():
                self.send_header(header_name, header_value)
        self.end_headers()
        if not head_only:
            self.safe_write(body)

    def safe_write(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, SocketTimeout):
            return

    @staticmethod
    def parse_int(value: str, default: int, max_value: int | None = None) -> int:
        try:
            parsed = max(1, int(value))
            if max_value is not None:
                parsed = min(parsed, max_value)
            return parsed
        except (TypeError, ValueError):
            return default

    def log_message(self, format: str, *args) -> None:
        return

    def log_error(self, format: str, *args) -> None:
        return


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.daemon_threads = True
    print(f"[WEB] dashboard started http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[WEB] dashboard stopped")
