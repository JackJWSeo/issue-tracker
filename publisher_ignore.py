from __future__ import annotations

from config import IGNORED_NEWS_PUBLISHERS_PATH


_cached_publishers: tuple[str, ...] = ()
_cached_signature: tuple[str, int, int] | None = None


def _read_ignored_news_publishers() -> tuple[str, ...]:
    path = IGNORED_NEWS_PUBLISHERS_PATH
    publishers: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            publishers.append(line.lower())
    return tuple(dict.fromkeys(publishers))


def load_ignored_news_publishers() -> tuple[str, ...]:
    global _cached_publishers, _cached_signature

    path = IGNORED_NEWS_PUBLISHERS_PATH
    if not path.exists():
        _cached_publishers = ()
        _cached_signature = None
        return ()

    publishers: list[str] = []
    try:
        stat = path.stat()
        signature = (str(path), stat.st_mtime_ns, stat.st_size)
        if _cached_signature == signature:
            return _cached_publishers
        publishers = list(_read_ignored_news_publishers())
    except Exception as exc:
        print(f"[WARN] 무시 매체 파일 로드 실패: {path} ({exc})")
        return _cached_publishers if _cached_signature is not None else ()

    _cached_publishers = tuple(publishers)
    _cached_signature = signature
    return _cached_publishers
