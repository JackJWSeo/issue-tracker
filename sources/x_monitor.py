from typing import Any

import requests

from config import REQUEST_TIMEOUT
from db import StateDB
from models import Item
from utils import compute_priority, sha1


def x_headers(bearer_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {bearer_token}"}


def fetch_x_user_id(username: str, bearer_token: str) -> str | None:
    url = f"https://api.x.com/2/users/by/username/{username}"
    r = requests.get(url, headers=x_headers(bearer_token), timeout=REQUEST_TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return ((data.get("data") or {}).get("id"))


def fetch_x_recent_posts_by_user_id(user_id: str, bearer_token: str) -> list[dict[str, Any]]:
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    params = {
        "max_results": 10,
        "tweet.fields": "created_at,public_metrics,entities",
        "exclude": "retweets,replies",
    }
    r = requests.get(url, headers=x_headers(bearer_token), params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return (r.json().get("data") or [])


def fetch_x_posts(username: str, bearer_token: str, db: StateDB) -> list[Item]:
    if not bearer_token:
        return []

    cache_key = f"x_user_id:{username}"
    user_id = db.get_value(cache_key)
    if not user_id:
        user_id = fetch_x_user_id(username, bearer_token)
        if not user_id:
            return []
        db.set_value(cache_key, user_id)

    rows = fetch_x_recent_posts_by_user_id(user_id, bearer_token)
    items: list[Item] = []
    for row in rows:
        post_id = (row.get("id") or "").strip()
        text = (row.get("text") or "").strip()
        created_at = (row.get("created_at") or "").strip()
        if not post_id:
            continue

        url = f"https://x.com/{username}/status/{post_id}"
        first_line = text.splitlines()[0][:120] if text else "(no text)"

        items.append(
            Item(
                source=f"x:{username}",
                title=first_line,
                body=text,
                url=url,
                published_at=created_at,
                item_id=sha1(f"x|{post_id}"),
                priority_score=compute_priority(first_line, text) + 3,
            )
        )

    return items