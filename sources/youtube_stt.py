from openai import OpenAI

from models import Item
from sources.translation import enrich_item_translations


def enrich_item_with_stt_summary(item: Item, client: OpenAI | None) -> Item:
    # 호환성 유지용 래퍼.
    return enrich_item_translations(item)
