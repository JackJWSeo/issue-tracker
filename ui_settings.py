import json
from dataclasses import asdict, dataclass

from config import BASE_DIR


UI_SETTINGS_PATH = BASE_DIR / "ui_settings.json"


@dataclass
class UISettings:
    telegram_enabled: bool = True
    use_recent_hours_filter: bool = True
    recent_hours: int = 24
    exclude_keywords: str = "melania, melania trump, 멜라니아"
    include_topic: bool = True
    include_source: bool = True
    include_time: bool = True
    include_title: bool = True
    include_content: bool = True
    include_link: bool = False


def load_ui_settings() -> UISettings:
    if not UI_SETTINGS_PATH.exists():
        return UISettings()

    try:
        data = json.loads(UI_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return UISettings()

    defaults = asdict(UISettings())
    for key, value in data.items():
        if key not in defaults:
            continue
        if isinstance(defaults[key], bool):
            defaults[key] = bool(value)
        elif isinstance(defaults[key], int):
            try:
                defaults[key] = max(1, int(value))
            except Exception:
                pass
        elif isinstance(defaults[key], str):
            defaults[key] = str(value)
    return UISettings(**defaults)


def save_ui_settings(settings: UISettings) -> None:
    UI_SETTINGS_PATH.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
