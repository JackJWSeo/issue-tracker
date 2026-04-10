import json
import os
import sys
from pathlib import Path


PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

for key in PROXY_ENV_KEYS:
    os.environ.pop(key, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from melo.api import TTS  # noqa: E402


def emit(prefix: str, payload: dict | None = None) -> None:
    if payload is None:
        print(prefix, flush=True)
        return
    print(f"{prefix}{json.dumps(payload, ensure_ascii=False)}", flush=True)


def main() -> int:
    model = TTS(language="KR", device="cpu")
    speaker_ids = model.hps.data.spk2id
    speaker_id = speaker_ids["KR"]
    emit("__READY__", {"speaker": "KR"})

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            command = json.loads(line)
        except json.JSONDecodeError as error:
            emit("__RESULT__", {"ok": False, "error": f"invalid json: {error}"})
            continue

        action = command.get("cmd")
        if action == "shutdown":
            emit("__RESULT__", {"ok": True, "shutdown": True})
            return 0

        if action != "synthesize":
            emit("__RESULT__", {"ok": False, "error": f"unknown cmd: {action}"})
            continue

        text = str(command.get("text") or "").strip()
        output_path = str(command.get("output_path") or "").strip()
        speed = float(command.get("speed") or 1.0)

        if not text or not output_path:
            emit("__RESULT__", {"ok": False, "error": "text or output_path missing"})
            continue

        try:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            model.tts_to_file(text, speaker_id, str(target), speed=speed)
            emit("__RESULT__", {"ok": True, "output_path": str(target)})
        except Exception as error:
            emit("__RESULT__", {"ok": False, "error": str(error)})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
