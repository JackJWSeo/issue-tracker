import json
import os
import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SOURCE_DIR))
APP_BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_DIR
BASE_DIR = APP_BASE_DIR
SECRETS_PATH = Path(os.getenv("SECRETS_PATH", APP_BASE_DIR / "secrets.dev.json"))


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
TRUTHSOCIAL_BASE_URL = get_secret("TRUTHSOCIAL_BASE_URL", "https://truthsocial.com").rstrip("/")

POLL_SECONDS = int(get_secret("POLL_SECONDS", "45"))
DB_PATH = get_secret("DB_PATH", str(APP_BASE_DIR / "trump_monitor.sqlite3"))
REQUEST_TIMEOUT = int(get_secret("REQUEST_TIMEOUT", "20"))
OPENAI_SUMMARY_MODEL = get_secret("OPENAI_SUMMARY_MODEL", "gpt-4.1-mini")
USE_AI_IRAN_WAR_FILTER = get_secret("USE_AI_IRAN_WAR_FILTER", "1").lower() in {"1", "true", "yes", "on"}
LOCAL_TIMEZONE = get_secret("LOCAL_TIMEZONE", "Asia/Seoul")

TARGETS = {
    "x_accounts": [
        "realDonaldTrump",
        "WhiteHouse",
        "RapidResponse47",
    ],
    "truthsocial_accounts": [
        "realDonaldTrump",
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

IRAN_TOPIC_KEYWORDS = [
    "iran",
    "iranian",
    "tehran",
    "irgc",
    "revolutionary guard",
    "persian gulf",
    "nuclear site",
    "uranium",
]

IRAN_SECONDARY_TOPIC_KEYWORDS = [
    "israel",
    "israeli",
    "middle east",
    "gaza",
    "hamas",
    "hezbollah",
    "syria",
    "lebanon",
    "u.s.",
    "us",
    "american",
]

IRAN_CONFLICT_KEYWORDS = [
    "war",
    "missile",
    "airstrike",
    "strike",
    "attack",
    "bombing",
    "retaliation",
    "conflict",
    "clash",
    "military",
    "troops",
    "drone",
    "ceasefire",
    "intercepted",
    "rocket",
    "ballistic",
]

IRAN_WAR_STRICT_KEYWORDS = [
    "iran war",
    "war with iran",
    "attack on iran",
    "attack against iran",
    "strike on iran",
    "strike against iran",
    "iran missile attack",
    "iran nuclear site",
    "israel iran conflict",
    "iran israel war",
]

EPSTEIN_KEYWORDS = [
    "epstein",
    "jeffrey epstein",
    "epstein files",
    "epstein list",
    "epstein case",
    "epstein scandal",
]

IMPEACHMENT_KEYWORDS = [
    "impeach",
    "impeached",
    "impeachment",
    "articles of impeachment",
]
