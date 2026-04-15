import contextlib
import io
import json
import os
import shutil
import sys
import wave
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


def log_message(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def prepend_silence_to_wav(path: Path, milliseconds: int = 420) -> None:
    with wave.open(str(path), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(reader.getnframes())

    frame_width = params.sampwidth * params.nchannels
    silence_frame_count = int(params.framerate * (milliseconds / 1000.0))
    silence = b"\x00" * frame_width * silence_frame_count

    with wave.open(str(path), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(silence + frames)


def cleanup_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


@contextlib.contextmanager
def suppress_noisy_output() -> io.StringIO:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        yield buffer


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    with suppress_noisy_output() as startup_logs:
        model = TTS(language="KR", device="cpu")
    speaker_ids = model.hps.data.spk2id
    speaker_id = speaker_ids["KR"]
    startup_output = startup_logs.getvalue().strip()
    if startup_output:
        for line in startup_output.splitlines():
            log_message(line)
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
        request_id = str(command.get("request_id") or "").strip()
        speed = float(command.get("speed") or 1.0)
        leading_silence_ms = int(command.get("leading_silence_ms") or 420)

        if not text or not output_path:
            emit("__RESULT__", {"ok": False, "error": "text or output_path missing"})
            continue

        try:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_target = target.with_name(f"{target.stem}.{request_id or 'tmp'}.tmp.wav")
            cleanup_file(temp_target)
            with suppress_noisy_output() as synth_logs:
                model.tts_to_file(text, speaker_id, str(temp_target), speed=speed)
            prepend_silence_to_wav(temp_target, milliseconds=leading_silence_ms)
            final_output_path = temp_target
            try:
                if target.exists():
                    cleanup_file(target)
                shutil.move(str(temp_target), str(target))
                final_output_path = target
            except Exception:
                final_output_path = temp_target
            synth_output = synth_logs.getvalue().strip()
            if synth_output:
                for line in synth_output.splitlines():
                    log_message(line)
            emit("__RESULT__", {"ok": True, "output_path": str(final_output_path), "request_id": request_id})
        except Exception as error:
            cleanup_file(Path(output_path))
            if output_path:
                cleanup_file(Path(output_path).with_name(f"{Path(output_path).stem}.{request_id or 'tmp'}.tmp.wav"))
            emit("__RESULT__", {"ok": False, "error": str(error), "output_path": output_path, "request_id": request_id})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
