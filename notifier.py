from datetime import timezone

import requests

from config import REQUEST_TIMEOUT
from models import Item
from ui_settings import UISettings
from utils import parse_dt, short_text


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str):
        if not self.enabled():
            print("[WARN] 텔레그램 설정이 없어 콘솔에만 출력합니다.")
            print(text)
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()


def format_alert(item: Item, settings: UISettings) -> str:
    dt = parse_dt(item.published_at)
    dt_text = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if dt else (item.published_at or "시간없음")
    icon = "🔥" if item.priority_score >= 5 else "📢"
    topic = "이란 전쟁 관련" if item.is_iran_war_related else "일반"
    display_title = item.translated_title or item.title
    display_body = item.translated_body or item.body

    lines = [f"{icon} 트럼프 모니터 감지"]
    if settings.include_topic:
        lines.append(f"분류: {topic}")
    if settings.include_source:
        lines.append(f"출처: {item.source}")
    if settings.include_time:
        lines.append(f"시각: {dt_text}")
    if settings.include_title:
        lines.append(f"제목: {short_text(display_title, 180)}")
    if settings.include_content:
        lines.append(f"내용: {short_text(display_body, 400)}")
    if settings.include_link and item.url:
        lines.append(f"링크: {item.url}")

    return "\n".join(lines)
