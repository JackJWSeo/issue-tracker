import json
import os
import sys
from pathlib import Path

# NOTE:
# 이 파일은 실행 환경/경로/비밀키처럼 "거의 안 바뀌는 런타임 설정"만 둔다.
# 검색 쿼리, 우선순위 키워드, 이슈 분류 키워드, 주요 매체 목록은
# query_settings.json + query_settings.py에서 관리한다.
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
