from dataclasses import dataclass
from typing import Optional


@dataclass
class Item:
    source: str
    title: str
    body: str
    url: str
    published_at: Optional[str]
    item_id: str
    priority_score: int = 0
    summary: str = ""