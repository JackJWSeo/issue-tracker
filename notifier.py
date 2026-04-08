from datetime import timezone

import requests

from config import REQUEST_TIMEOUT
from models import Item
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


def format_alert(item: Item) -> str:
    dt = parse_dt(item.published_at)
    dt_text = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if dt else (item.published_at or "시간없음")
    icon = "🔥" if item.priority_score >= 5 else "📢"

    summary_block = f"\n요약: {short_text(item.summary, 500)}" if item.summary else ""

    return (
        f"{icon} 트럼프 모니터 감지\n"
        f"출처: {item.source}\n"
        f"시각: {dt_text}\n"
        f"제목: {short_text(item.title, 180)}\n"
        f"내용: {short_text(item.body, 400)}"
        f"{summary_block}\n"
        f"링크: {item.url}"
    )