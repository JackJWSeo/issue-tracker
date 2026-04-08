import requests

from config import REQUEST_TIMEOUT
from models import Item
from utils import compute_priority, sha1


def fetch_youtube_live(query: str, api_key: str) -> list[Item]:
    if not api_key:
        return []

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "eventType": "live",
        "maxResults": 10,
        "key": api_key,
    }
    r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    items: list[Item] = []
    for row in data.get("items", []):
        video_id = (((row.get("id") or {}).get("videoId")) or "").strip()
        snippet = row.get("snippet") or {}
        title = (snippet.get("title") or "").strip()
        desc = (snippet.get("description") or "").strip()
        published_at = (snippet.get("publishedAt") or "").strip()
        channel = (snippet.get("channelTitle") or "").strip()

        if not video_id:
            continue

        items.append(
            Item(
                source=f"youtube_live:{channel}",
                title=title,
                body=desc,
                url=f"https://www.youtube.com/watch?v={video_id}",
                published_at=published_at,
                item_id=sha1(f"youtube|{video_id}"),
                priority_score=compute_priority(title, desc) + 2,
            )
        )

    return items