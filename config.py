import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "45"))
DB_PATH = os.getenv("DB_PATH", "trump_monitor.sqlite3")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

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