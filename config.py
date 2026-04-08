import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SECRETS_PATH = Path(os.getenv("SECRETS_PATH", BASE_DIR / "secrets.dev.json"))


def load_dev_secrets() -> dict:
    if not SECRETS_PATH.exists():
        return {}

    try:
        with open(SECRETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[WARN] secrets 파일 로드 실패: {e}")
        return {}


DEV_SECRETS = load_dev_secrets()


def get_secret(name: str, default: str = "") -> str:
    # 운영 환경에서는 환경변수 우선
    value = os.getenv(name)
    if value:
        return value

    # 개발 환경에서는 secrets.dev.json fallback
    value = DEV_SECRETS.get(name)
    if value:
        return str(value)

    return default


TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_secret("TELEGRAM_CHAT_ID")

X_BEARER_TOKEN = get_secret("X_BEARER_TOKEN")
YOUTUBE_API_KEY = get_secret("YOUTUBE_API_KEY")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")

POLL_SECONDS = int(get_secret("POLL_SECONDS", "45"))
DB_PATH = get_secret("DB_PATH", str(BASE_DIR / "trump_monitor.sqlite3"))
REQUEST_TIMEOUT = int(get_secret("REQUEST_TIMEOUT", "20"))

TARGETS = {
    "x_accounts": [
        "realDonaldTrump",
        "WhiteHouse",
        "RapidResponse47",
    ],
    "youtube_queries": [
        "Donald Trump live",
        "Trump rally live",
        "White House live",
        "Trump speech live",
    ],
    "news_queries": [
        "Donald Trump",
        "Trump speech",
        "Trump rally",
        "Trump interview",
        "White House Trump",
    ],
}

HIGH_PRIORITY_KEYWORDS = [
    "tariff", "sanction", "ukraine", "china", "taiwan", "iran", "nato",
    "south korea", "korea", "trade", "military", "nuclear", "election",
    "bitcoin", "crypto", "fed", "interest rate", "tesla", "tiktok",
]