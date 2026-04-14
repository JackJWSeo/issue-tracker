from __future__ import annotations

from functools import lru_cache

from config import IGNORED_NEWS_PUBLISHERS_PATH


@lru_cache(maxsize=1)
def load_ignored_news_publishers() -> tuple[str, ...]:
    path = IGNORED_NEWS_PUBLISHERS_PATH
    if not path.exists():
        return ()

    publishers: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                publishers.append(line.lower())
    except Exception as exc:
        print(f"[WARN] 무시 매체 파일 로드 실패: {path} ({exc})")
        return ()

    # 파일에는 중복이 들어갈 수 있으므로, 최초 등장 순서만 유지한다.
    return tuple(dict.fromkeys(publishers))
