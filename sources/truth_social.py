import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests

from config import REQUEST_TIMEOUT, TRUTHSOCIAL_BASE_URL
from db import StateDB
from models import Item
from utils import compute_priority, sha1


def clean_html_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truthsocial_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    session.trust_env = False
    return session


def fetch_truthsocial_account_id(username: str, db: StateDB) -> str | None:
    cache_key = f"truthsocial_account_id:{username}"
    cached = db.get_value(cache_key)
    if cached:
        return cached

    session = truthsocial_session()
    lookup_url = urljoin(TRUTHSOCIAL_BASE_URL, "/api/v1/accounts/lookup")
    response = session.get(
        lookup_url,
        params={"acct": username},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code == 404:
        return None

    if response.ok:
        data = response.json()
        account_id = str(data.get("id") or "").strip()
        if account_id:
            db.set_value(cache_key, account_id)
            return account_id

    search_url = urljoin(TRUTHSOCIAL_BASE_URL, "/api/v2/search")
    response = session.get(
        search_url,
        params={"q": username, "type": "accounts", "limit": 5},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    accounts = data.get("accounts") or []

    for account in accounts:
        acct = str(account.get("acct") or "").lstrip("@").lower()
        username_value = str(account.get("username") or "").lstrip("@").lower()
        if username.lower() in {acct, username_value}:
            account_id = str(account.get("id") or "").strip()
            if account_id:
                db.set_value(cache_key, account_id)
                return account_id

    return None


def fetch_truthsocial_statuses_by_account_id(account_id: str) -> list[dict[str, Any]]:
    session = truthsocial_session()
    statuses_url = urljoin(TRUTHSOCIAL_BASE_URL, f"/api/v1/accounts/{account_id}/statuses")
    response = session.get(
        statuses_url,
        params={
            "limit": 10,
            "exclude_replies": "true",
            "exclude_reblogs": "true",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def fetch_truthsocial_posts(username: str, db: StateDB) -> list[Item]:
    account_id = fetch_truthsocial_account_id(username, db)
    if not account_id:
        return []

    rows = fetch_truthsocial_statuses_by_account_id(account_id)
    items: list[Item] = []

    for row in rows:
        status_id = str(row.get("id") or "").strip()
        if not status_id:
            continue

        content = clean_html_text(str(row.get("content") or ""))
        created_at = str(row.get("created_at") or "").strip()
        title = short_truthsocial_title(content)
        account = row.get("account") or {}
        account_name = str(account.get("acct") or account.get("username") or username).strip()
        url = str(row.get("url") or "").strip()
        if not url:
            url = urljoin(TRUTHSOCIAL_BASE_URL, f"/@{account_name}/{status_id}")

        items.append(
            Item(
                source=f"truthsocial:{account_name}",
                title=title,
                body=content,
                url=url,
                published_at=created_at,
                item_id=sha1(f"truthsocial|{status_id}"),
                priority_score=compute_priority(title, content) + 3,
            )
        )

    return items


def short_truthsocial_title(text: str) -> str:
    if not text:
        return "(no text)"

    line = text.splitlines()[0].strip()
    return line[:120] if line else "(no text)"
