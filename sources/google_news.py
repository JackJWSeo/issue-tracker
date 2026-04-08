import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

from config import REQUEST_TIMEOUT
from models import Item
from utils import compute_priority, sha1


def fetch_google_news_rss(query: str) -> list[Item]:
    rss_url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    r = requests.get(rss_url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    root = ET.fromstring(r.text)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[Item] = []
    for node in channel.findall("item"):
        title = (node.findtext("title") or "").strip()
        description = (node.findtext("description") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub_date = (node.findtext("pubDate") or "").strip()
        guid = (node.findtext("guid") or link or title).strip()

        items.append(
            Item(
                source=f"google_news:{query}",
                title=title,
                body=description,
                url=link,
                published_at=pub_date,
                item_id=sha1(f"news|{guid}"),
                priority_score=compute_priority(title, description),
            )
        )

    return items
