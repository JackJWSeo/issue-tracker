import json
from copy import deepcopy

from config import BASE_DIR, DEFAULT_TARGETS


QUERY_SETTINGS_PATH = BASE_DIR / "query_settings.json"


def _normalize_target_list(value: object, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    return normalized or list(fallback)


def load_query_targets() -> dict[str, list[str]]:
    defaults = deepcopy(DEFAULT_TARGETS)
    if not QUERY_SETTINGS_PATH.exists():
        return defaults

    try:
        data = json.loads(QUERY_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return defaults

    if not isinstance(data, dict):
        return defaults

    result = deepcopy(defaults)
    for key, fallback in defaults.items():
        result[key] = _normalize_target_list(data.get(key), fallback)
    return result


def save_query_targets(targets: dict[str, list[str]]) -> None:
    defaults = deepcopy(DEFAULT_TARGETS)
    payload: dict[str, list[str]] = {}
    for key, fallback in defaults.items():
        payload[key] = _normalize_target_list(targets.get(key), fallback)

    QUERY_SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
