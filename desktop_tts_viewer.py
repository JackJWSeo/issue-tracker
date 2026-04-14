import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
import wave
import winsound
import audioop
from ctypes import wintypes, windll
from pathlib import Path
from tkinter import messagebox

import requests
import webview
from webview.menu import Menu, MenuAction

from config import APP_BASE_DIR, RESOURCE_DIR
from web_dashboard import DEFAULT_PORT, DEFAULT_WINDOW_MINUTES, run_server


APP_HOST = "192.168.2.11"
APP_POLL_SECONDS = 5
MELOTTS_WINDOWS_ENV = "melotts-win"
DEFAULT_MELO_SPEED = 1.0
DEFAULT_LEADING_SILENCE_MS = 420
DEFAULT_TTS_VOLUME = 1.0
WAV_CACHE_MAX_AGE_SECONDS = 60 * 60
DEBUG_LOG_RETENTION_DAYS = 7
WORKER_READY_TIMEOUT_SECONDS = 180
WORKER_COMMAND_TIMEOUT_SECONDS = 180
WORKER_RESULT_POLL_INTERVAL_SECONDS = 0.2
WORKER_OUTPUT_WAIT_SECONDS = 8
CACHE_DIR = APP_BASE_DIR / "tts_cache"
WEBVIEW_STORAGE_DIR = Path.home() / "AppData" / "Local" / "IssueTrackerWebView"
WORKER_SCRIPT_PATH = RESOURCE_DIR / "melotts_windows_worker.py"
SETTINGS_PATH = APP_BASE_DIR / "tts_viewer_settings.json"
MELOTTS_INSTALL_SCRIPT_PATH = APP_BASE_DIR / "install_melotts_runtime.bat"
DEBUG_LOG_DIR = APP_BASE_DIR / "logs"
BLOCKED_CHARS_PATH = APP_BASE_DIR / "tts_blocked_chars.txt"
PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

for _proxy_key in PROXY_ENV_KEYS:
    os.environ.pop(_proxy_key, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MCI_WAIT = 0x00000002


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = text.replace("\xa0", " ")
    return text


def load_blocked_characters() -> set[str]:
    blocked: set[str] = set()
    if not BLOCKED_CHARS_PATH.exists():
        return blocked
    try:
        for raw_line in BLOCKED_CHARS_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.upper().startswith("U+"):
                hex_part = line.split("#", 1)[0].strip()[2:]
                try:
                    blocked.add(chr(int(hex_part, 16)))
                except ValueError:
                    continue
            else:
                blocked.add(line[0])
    except Exception:
        return blocked
    return blocked


def append_blocked_character(char: str, reason: str = "") -> bool:
    if not char:
        return False
    try:
        existing = load_blocked_characters()
        if char in existing:
            return False
        BLOCKED_CHARS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with BLOCKED_CHARS_PATH.open("a", encoding="utf-8") as handle:
            codepoint = f"U+{ord(char):04X}"
            name = unicodedata.name(char, "UNKNOWN")
            suffix = f" # {name}"
            if reason:
                suffix += f" / {normalize_text(reason)[:120]}"
            handle.write(f"{codepoint}{suffix}\n")
        return True
    except Exception:
        return False


def extract_problem_characters(error_text: str) -> set[str]:
    text = str(error_text or "")
    found: set[str] = set()
    stripped = text.strip()
    if len(stripped) == 1:
        found.add(stripped)
    for hex_match in re.findall(r"\\u([0-9a-fA-F]{4,8})", text):
        try:
            found.add(chr(int(hex_match, 16)))
        except ValueError:
            continue
    for quoted in re.findall(r"'([^']+)'", text):
        if len(quoted) == 1:
            found.add(quoted)
    return {char for char in found if char.strip() or unicodedata.category(char).startswith("C")}


def sanitize_tts_text(value: str, blocked_chars: set[str] | None = None) -> str:
    text = normalize_text(value)
    blocked = blocked_chars or set()
    cleaned: list[str] = []
    for char in text:
        if char in blocked:
            continue
        category = unicodedata.category(char)
        if category.startswith("C") and char not in {" ", "\n", "\t"}:
            continue
        cleaned.append(char)
    text = "".join(cleaned)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_debug_log_path() -> Path:
    return DEBUG_LOG_DIR / f"tts_viewer_{time.strftime('%Y-%m-%d')}.log"


def prune_old_debug_logs() -> None:
    if not DEBUG_LOG_DIR.exists():
        return
    cutoff = time.time() - (DEBUG_LOG_RETENTION_DAYS * 24 * 60 * 60)
    for log_path in DEBUG_LOG_DIR.glob("tts_viewer_*.log"):
        try:
            if log_path.stat().st_mtime < cutoff:
                log_path.unlink()
        except OSError:
            continue


def should_log_worker_stderr(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    noisy_patterns = [
        "loading weights:",
        "0%|",
        "100%|",
        "futurewarning:",
        "userwarning:",
        "weightnorm.apply",
        "bertformaskedlm load report",
        "cls.seq_relationship.",
        "bert.embeddings.position_ids",
        "bert.pooler.dense.",
        "notes:",
        "- unexpected:",
    ]
    lowered = normalized.lower()
    return not any(pattern in lowered for pattern in noisy_patterns)


def debug_log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        DEBUG_LOG_DIR.mkdir(exist_ok=True)
        prune_old_debug_logs()
        with get_debug_log_path().open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {normalize_text(message)}\n")
    except Exception:
        pass


def safe_print(message: str) -> None:
    text = normalize_text(message)
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            encoded = text.encode(sys.stdout.encoding or "utf-8", errors="replace")
            print(encoded.decode(sys.stdout.encoding or "utf-8", errors="replace"))
        except Exception:
            pass


def clean_title_for_tts(value: str) -> str:
    text = sanitize_tts_text(value, load_blocked_characters())
    separators = [" - ", " – ", " — ", " | "]
    for separator in separators:
        index = text.rfind(separator)
        if index > 15:
            text = text[:index].strip()
            break
    # Remove short section labels like "의견 | ..." or other visual separators
    text = re.sub(r"^[^|]{1,15}\|\s*", "", text).strip()
    text = text.replace("|", " ")
    text = re.sub(r"\s+", " ", text).strip(" -|/")
    return text


def build_issue_cache_key(issue: dict) -> str:
    item_id = str(issue.get("item_id") or "").strip()
    created_at = str(issue.get("created_at") or "").strip()
    title = clean_title_for_tts(issue.get("translated_title") or issue.get("title") or "")
    base = item_id or created_at or title or "tts"
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", base)[:120].strip("_") or "tts"


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {
            "speed": DEFAULT_MELO_SPEED,
            "leading_silence_ms": DEFAULT_LEADING_SILENCE_MS,
            "volume": DEFAULT_TTS_VOLUME,
        }
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return {
        "speed": float(data.get("speed") or DEFAULT_MELO_SPEED),
        "leading_silence_ms": int(data.get("leading_silence_ms") or DEFAULT_LEADING_SILENCE_MS),
        "volume": float(data.get("volume") or DEFAULT_TTS_VOLUME),
    }


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def build_melotts_help_message() -> str:
    lines = [
        f"MeloTTS 실행 환경 '{MELOTTS_WINDOWS_ENV}' 을(를) 찾지 못했습니다.",
        "",
        "viewer.exe는 가볍게 유지하기 위해 MeloTTS를 별도 환경으로 실행합니다.",
        "",
        "해결 방법",
        "1. 같은 폴더의 install_melotts_runtime.bat 를 먼저 실행",
        "2. 설치가 끝나면 tts_viewer를 다시 실행",
    ]
    if MELOTTS_INSTALL_SCRIPT_PATH.exists():
        lines.extend(
            [
                "",
                f"설치 스크립트: {MELOTTS_INSTALL_SCRIPT_PATH}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "conda가 설치되어 있어야 하며, 'melotts-win' 환경에 melo 패키지가 필요합니다.",
            ]
        )
    return "\n".join(lines)


def play_wav_file(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.exists():
        raise RuntimeError(f"재생할 wav 파일이 없습니다: {resolved}")

    debug_log(f"play_wav_file start: {resolved}")

    errors: list[str] = []
    try:
        winsound.PlaySound(str(resolved), winsound.SND_FILENAME)
        debug_log("play_wav_file success: winsound")
        return
    except RuntimeError as error:
        errors.append(f"winsound={error}")
        debug_log(f"play_wav_file winsound failed: {error}")

    alias = f"ttsviewer_{int(time.time() * 1000)}"
    open_command = f'open "{resolved}" type waveaudio alias {alias}'
    play_command = f"play {alias} wait"
    close_command = f"close {alias}"
    try:
        if windll.winmm.mciSendStringW(open_command, None, 0, 0) != 0:
            raise RuntimeError("mci open failed")
        if windll.winmm.mciSendStringW(play_command, None, 0, 0) != 0:
            raise RuntimeError("mci play failed")
        windll.winmm.mciSendStringW(close_command, None, 0, 0)
        debug_log("play_wav_file success: mci")
        return
    except Exception as error:
        errors.append(f"mci={error}")
        debug_log(f"play_wav_file mci failed: {error}")
        try:
            windll.winmm.mciSendStringW(close_command, None, 0, 0)
        except Exception:
            pass

    powershell_script = (
        "$player = New-Object System.Media.SoundPlayer($args[0]); "
        "$player.Load(); "
        "$player.PlaySync()"
    )
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_script,
                str(resolved),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
        )
        debug_log("play_wav_file success: powershell soundplayer")
        return
    except Exception as error:
        detail = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            stderr = (error.stderr or "").strip()
            stdout = (error.stdout or "").strip()
            detail = stderr or stdout or detail
        errors.append(f"powershell={detail}")
        debug_log(f"play_wav_file powershell failed: {detail}")
        raise RuntimeError("오디오 재생 실패: " + " | ".join(errors)) from error


def build_volume_adjusted_wav(source_path: Path, output_path: Path, volume: float) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source_path), "rb") as source_wav:
        params = source_wav.getparams()
        frames = source_wav.readframes(source_wav.getnframes())

    adjusted_frames = audioop.mul(frames, params.sampwidth, max(0.0, volume))

    with wave.open(str(output_path), "wb") as output_wav:
        output_wav.setparams(params)
        output_wav.writeframes(adjusted_frames)

    return output_path


class DashboardTTSViewer:
    def __init__(self) -> None:
        self.base_url = f"http://{APP_HOST}:{DEFAULT_PORT}"
        self.api_url = f"{self.base_url}/api/issues?minutes={DEFAULT_WINDOW_MINUTES}&limit=100"
        self.web_url = f"{self.base_url}/"
        self.stop_event = threading.Event()
        self.server_thread: threading.Thread | None = None
        self.poll_thread: threading.Thread | None = None
        self.audio_thread: threading.Thread | None = None
        self.worker_reader_thread: threading.Thread | None = None
        self.tts_queue: queue.Queue[dict | None] = queue.Queue()
        self.worker_result_queue: queue.Queue[dict] = queue.Queue()
        self.seen_ids: set[str] = set()
        self.latest_issues: list[dict] = []
        self.last_status = "대기 중"
        self.session = requests.Session()
        self.session.trust_env = False
        self.worker_process: subprocess.Popen[str] | None = None
        self.worker_ready_event = threading.Event()
        self.settings = load_settings()
        self.blocked_chars = load_blocked_characters()
        CACHE_DIR.mkdir(exist_ok=True)
        WEBVIEW_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        debug_log(f"viewer init: base={APP_BASE_DIR} resource={RESOURCE_DIR}")

    def verify_melotts_runtime(self) -> None:
        env = os.environ.copy()
        for key in PROXY_ENV_KEYS:
            env.pop(key, None)
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
        env["PYTHONIOENCODING"] = "utf-8"

        command = [
            "conda",
            "run",
            "--no-capture-output",
            "-n",
            MELOTTS_WINDOWS_ENV,
            "python",
            "-c",
            "from melo.api import TTS; print('MELOTTS_OK')",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=90,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
        except FileNotFoundError as error:
            raise RuntimeError(build_melotts_help_message()) from error
        except subprocess.SubprocessError as error:
            raise RuntimeError(build_melotts_help_message()) from error

        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
        if completed.returncode != 0 or "MELOTTS_OK" not in output:
            detail = output.strip()
            if detail:
                raise RuntimeError(f"{build_melotts_help_message()}\n\n상세 오류:\n{detail}")
            raise RuntimeError(build_melotts_help_message())

    def ensure_server(self) -> None:
        if self.is_server_ready():
            return

        self.server_thread = threading.Thread(
            target=run_server,
            kwargs={"host": APP_HOST, "port": DEFAULT_PORT},
            daemon=True,
        )
        self.server_thread.start()

        deadline = time.time() + 10
        while time.time() < deadline:
            if self.is_server_ready():
                return
            time.sleep(0.2)
        raise RuntimeError("대시보드 서버를 시작하지 못했습니다.")

    def is_server_ready(self) -> bool:
        try:
            response = self.session.get(f"{self.base_url}/api/health", timeout=1.5)
            return response.ok
        except requests.RequestException:
            return False

    def ensure_worker(self) -> None:
        if self.worker_process and self.worker_process.poll() is None:
            return

        env = os.environ.copy()
        for key in PROXY_ENV_KEYS:
            env.pop(key, None)
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
        env["PYTHONIOENCODING"] = "utf-8"

        command = [
            "conda",
            "run",
            "--no-capture-output",
            "-n",
            MELOTTS_WINDOWS_ENV,
            "python",
            "-u",
            str(WORKER_SCRIPT_PATH),
        ]
        safe_print(f"[APP] starting melotts worker: {' '.join(command)}")
        debug_log(f"starting worker: {' '.join(command)}")
        self.worker_ready_event.clear()
        self.worker_process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        self.worker_reader_thread = threading.Thread(target=self.read_worker_output, daemon=True)
        self.worker_reader_thread.start()
        if self.worker_process.stderr:
            threading.Thread(target=self.read_worker_error_output, daemon=True).start()
        if not self.worker_ready_event.wait(WORKER_READY_TIMEOUT_SECONDS):
            raise RuntimeError("MeloTTS worker가 준비되지 않았습니다.")

    def read_worker_output(self) -> None:
        if not self.worker_process or not self.worker_process.stdout:
            return

        for line in self.worker_process.stdout:
            text = line.rstrip()
            if not text:
                continue
            if text.startswith("__READY__"):
                safe_print(f"[APP] worker ready: {text}")
                debug_log(f"worker ready: {text}")
                self.worker_ready_event.set()
                continue
            if text.startswith("__RESULT__"):
                payload_text = text[len("__RESULT__") :]
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError:
                    payload = {"ok": False, "error": payload_text}
                self.worker_result_queue.put(payload)
                continue
            safe_print(f"[MELO] {text}")
            debug_log(f"worker output: {text}")

    def read_worker_error_output(self) -> None:
        if not self.worker_process or not self.worker_process.stderr:
            return

        for line in self.worker_process.stderr:
            text = line.rstrip()
            if not text:
                continue
            safe_print(f"[MELO] {text}")
            if should_log_worker_stderr(text):
                debug_log(f"worker stderr: {text}")

    def start_background_workers(self) -> None:
        self.verify_melotts_runtime()
        self.ensure_worker()
        self.poll_thread = threading.Thread(target=self.poll_loop, daemon=True)
        self.audio_thread = threading.Thread(target=self.audio_loop, daemon=True)
        self.poll_thread.start()
        self.audio_thread.start()

    def poll_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                response = self.session.get(self.api_url, timeout=10)
                response.raise_for_status()
                payload = response.json()
                issues = payload.get("issues") or []
                self.latest_issues = issues
                ids = {str(issue.get("item_id") or "") for issue in issues if issue.get("item_id")}

                if not self.seen_ids:
                    self.seen_ids = ids
                else:
                    new_items = [issue for issue in reversed(issues) if issue.get("item_id") not in self.seen_ids]
                    if new_items:
                        self.replace_queue_with_latest(new_items[-1])
                    self.seen_ids.update(ids)
            except requests.RequestException as error:
                safe_print(f"[APP] poll error: {error}")
                self.set_status(f"폴링 오류: {error}")
            except Exception as error:
                safe_print(f"[APP] unexpected poll error: {error}")
                self.set_status(f"예상치 못한 오류: {error}")

            self.stop_event.wait(APP_POLL_SECONDS)

    def audio_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                issue = self.tts_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if issue is None:
                break

            try:
                if not clean_title_for_tts(issue.get("translated_title") or issue.get("title") or ""):
                    continue
                self.play_issue(issue)
            except Exception as error:
                safe_print(f"[APP] tts error: {error}")
                debug_log(f"tts error: {error}")
                self.set_status(f"TTS 오류: {error}")

    def replace_queue_with_latest(self, issue: dict) -> None:
        while True:
            try:
                pending = self.tts_queue.get_nowait()
                if pending is None:
                    self.tts_queue.put(None)
                    break
            except queue.Empty:
                break
        self.tts_queue.put(issue)
        title = clean_title_for_tts(issue.get("translated_title") or issue.get("title") or "")
        if title:
            self.set_status(f"새 카드 감지: {title}")

    def get_cache_path(self, cache_key: str) -> Path:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", cache_key.strip())[:120].strip("_") or "tts"
        return CACHE_DIR / f"{safe_name}.wav"

    def sanitize_title(self, value: str) -> str:
        text = sanitize_tts_text(value, self.blocked_chars)
        text = clean_title_for_tts(text)
        return sanitize_tts_text(text, self.blocked_chars)

    def register_problem_characters(self, error: Exception) -> bool:
        added = False
        for char in extract_problem_characters(str(error)):
            if append_blocked_character(char, reason=str(error)):
                self.blocked_chars.add(char)
                debug_log(f"blocked char added: U+{ord(char):04X} {unicodedata.name(char, 'UNKNOWN')}")
                added = True
        return added

    def play_issue(self, issue: dict) -> None:
        title = self.sanitize_title(issue.get("translated_title") or issue.get("title") or "")
        if not title:
            return
        cache_key = f"melotts_windows_{build_issue_cache_key(issue)}"
        for attempt in range(2):
            try:
                self.speak_with_melotts_windows(title, cache_key)
                break
            except Exception as error:
                if attempt == 0 and self.register_problem_characters(error):
                    title = self.sanitize_title(title)
                    if title:
                        debug_log(f"retry tts after blocked-char update: {title}")
                        continue
                raise
        safe_print(f"[APP] melotts-windows played: {title}")
        self.set_status(f"재생 완료: {title}")

    def fetch_issues_once(self) -> list[dict]:
        response = self.session.get(self.api_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
        issues = payload.get("issues") or []
        self.latest_issues = issues
        return issues

    def enqueue_issue_for_test(self, issue: dict | None) -> None:
        if not issue:
            self.set_status("읽을 카드가 없습니다.")
            return
        title = clean_title_for_tts(issue.get("translated_title") or issue.get("title") or "")
        self.set_status(f"수동 읽기 요청: {title or '제목 없음'}")
        self.replace_queue_with_latest(issue)

    def read_current_card(self) -> None:
        try:
            self.set_status("현재 카드 읽기를 준비 중입니다...")
            issues = self.latest_issues or self.fetch_issues_once()
            self.enqueue_issue_for_test(issues[0] if issues else None)
        except Exception as error:
            self.set_status(f"현재 카드 읽기 실패: {error}")

    def read_top_three_cards(self) -> None:
        try:
            self.set_status("상위 카드 읽기를 준비 중입니다...")
            issues = self.latest_issues or self.fetch_issues_once()
            selected = issues[:3]
            if not selected:
                self.set_status("읽을 카드가 없습니다.")
                return
            for issue in reversed(selected):
                self.tts_queue.put(issue)
            self.set_status(f"상위 {len(selected)}개 카드 읽기 시작")
        except Exception as error:
            self.set_status(f"상위 카드 읽기 실패: {error}")

    def read_first_visible_card_again(self) -> None:
        self.set_status("첫 카드를 다시 읽는 중입니다...")
        issue = self.latest_issues[0] if self.latest_issues else None
        self.enqueue_issue_for_test(issue)

    def set_status(self, text: str) -> None:
        normalized = normalize_text(text)
        safe_print(f"[APP] {normalized}")
        debug_log(normalized)
        self.last_status = normalized

    def prune_old_wav_cache(self) -> None:
        cutoff = time.time() - WAV_CACHE_MAX_AGE_SECONDS
        for wav_path in CACHE_DIR.glob("*.wav"):
            try:
                if wav_path.stat().st_mtime < cutoff:
                    wav_path.unlink()
                    safe_print(f"[APP] 오래된 wav 삭제: {wav_path.name}")
            except FileNotFoundError:
                continue
            except OSError as error:
                safe_print(f"[APP] wav 삭제 실패: {wav_path.name} / {error}")

    def settings_summary(self) -> str:
        return (
            f"속도 {self.settings['speed']:.2f}, "
            f"시작 여유 {self.settings['leading_silence_ms']}ms, "
            f"음량 {int(round(self.settings['volume'] * 100))}%"
        )

    def update_speed(self, speed: float, label: str) -> None:
        self.settings["speed"] = speed
        save_settings(self.settings)
        self.set_status(f"읽기 속도 변경: {label} ({self.settings_summary()})")

    def update_leading_silence(self, milliseconds: int, label: str) -> None:
        self.settings["leading_silence_ms"] = milliseconds
        save_settings(self.settings)
        self.set_status(f"시작 여유 변경: {label} ({self.settings_summary()})")

    def update_volume(self, volume: float, label: str) -> None:
        self.settings["volume"] = volume
        save_settings(self.settings)
        self.set_status(f"읽기 음량 변경: {label} ({self.settings_summary()})")

    def show_current_settings(self) -> None:
        self.set_status(f"현재 TTS 설정: {self.settings_summary()}")

    def speak_with_melotts_windows(self, title: str, cache_key: str) -> None:
        self.prune_old_wav_cache()
        settings_key = f"{cache_key}_s{str(self.settings['speed']).replace('.', '_')}_p{self.settings['leading_silence_ms']}"
        cache_path = self.get_cache_path(settings_key)
        playback_path = cache_path
        source_path_for_cleanup = cache_path
        if not cache_path.exists():
            self.ensure_worker()
            if not self.worker_process or not self.worker_process.stdin:
                raise RuntimeError("MeloTTS worker stdin을 사용할 수 없습니다.")
            request_id = uuid.uuid4().hex
            command = {
                "cmd": "synthesize",
                "text": title,
                "output_path": str(cache_path),
                "request_id": request_id,
                "speed": self.settings["speed"],
                "leading_silence_ms": self.settings["leading_silence_ms"],
            }
            safe_print(f"[APP] worker synth request: {title}")
            self.worker_process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            self.worker_process.stdin.flush()
            result = None
            deadline = time.time() + WORKER_COMMAND_TIMEOUT_SECONDS
            while time.time() < deadline:
                remaining = max(deadline - time.time(), WORKER_RESULT_POLL_INTERVAL_SECONDS)
                try:
                    candidate = self.worker_result_queue.get(timeout=min(WORKER_RESULT_POLL_INTERVAL_SECONDS, remaining))
                except queue.Empty:
                    continue
                candidate_request_id = str(candidate.get("request_id") or "").strip()
                candidate_output_path = str(candidate.get("output_path") or "").strip()
                if candidate_request_id == request_id:
                    result = candidate
                    break
                debug_log(
                    "worker result skipped: "
                    f"expected_request_id={request_id} got_request_id={candidate_request_id or '(none)'} "
                    f"output={candidate_output_path or '(none)'}"
                )
            if result is None:
                raise RuntimeError("MeloTTS worker 응답 시간이 초과되었습니다.")
            if not result.get("ok"):
                try:
                    cache_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise RuntimeError(str(result.get("error") or "melotts-win 실행에 실패했습니다."))
            result_output_path = str(result.get("output_path") or "").strip()
            playback_path = Path(result_output_path) if result_output_path else cache_path
            file_deadline = time.time() + WORKER_OUTPUT_WAIT_SECONDS
            while time.time() < file_deadline:
                if playback_path.exists() and playback_path.stat().st_size > 0:
                    break
                time.sleep(WORKER_RESULT_POLL_INTERVAL_SECONDS)
            if not playback_path.exists():
                raise RuntimeError(f"합성 완료 응답 후 wav 파일이 없습니다: {playback_path}")
            source_path_for_cleanup = playback_path

        volume = float(self.settings.get("volume", DEFAULT_TTS_VOLUME))
        if abs(volume - 1.0) > 0.001:
            volume_percent = int(round(volume * 100))
            adjusted_path = self.get_cache_path(f"{settings_key}_v{volume_percent}")
            if not adjusted_path.exists():
                build_volume_adjusted_wav(playback_path, adjusted_path, volume)
            playback_path = adjusted_path

        play_wav_file(playback_path)
        if source_path_for_cleanup != cache_path:
            try:
                source_path_for_cleanup.unlink(missing_ok=True)
            except Exception:
                pass

    def shutdown_worker(self) -> None:
        process = self.worker_process
        if not process:
            return
        try:
            if process.stdin and process.poll() is None:
                process.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            process.terminate()
        except Exception:
            pass

    def run(self) -> None:
        try:
            self.ensure_server()
            self.start_background_workers()
        except Exception as error:
            message = str(error)
            safe_print(f"[APP] startup failed: {message}")
            try:
                messagebox.showerror("tts_viewer 시작 실패", message)
            except Exception:
                pass
            raise
        window = webview.create_window(
            "Issue Tracker Dashboard (AI Voice Alerts)",
            self.web_url,
            width=1440,
            height=980,
        )

        def handle_closed() -> None:
            self.stop_event.set()
            self.tts_queue.put(None)
            winsound.PlaySound(None, winsound.SND_PURGE)
            self.shutdown_worker()

        def bind_reload_hotkey() -> None:
            window.evaluate_js(
                """
                (function () {
                    if (window.__issueTrackerF5Bound) {
                        return;
                    }
                    window.__issueTrackerF5Bound = true;
                    window.addEventListener('keydown', function (event) {
                        if (event.key === 'F5') {
                            event.preventDefault();
                            window.location.reload();
                        }
                    });
                }());
                """
            )

        window.events.closed += handle_closed
        window.events.loaded += bind_reload_hotkey
        menu = [
            Menu(
                "TTS",
                [
                    MenuAction("현재 카드 읽기", self.read_current_card),
                    MenuAction("상위 3개 카드 읽기", self.read_top_three_cards),
                    MenuAction("첫 카드 다시 읽기", self.read_first_visible_card_again),
                ],
            ),
            Menu(
                "설정",
                [
                    Menu(
                        "읽기 속도",
                        [
                            MenuAction("느리게 (0.90)", lambda: self.update_speed(0.90, "느리게")),
                            MenuAction("보통 (1.00)", lambda: self.update_speed(1.00, "보통")),
                            MenuAction("빠르게 (1.10)", lambda: self.update_speed(1.10, "빠르게")),
                        ],
                    ),
                    Menu(
                        "시작 여유",
                        [
                            MenuAction("짧게 (300ms)", lambda: self.update_leading_silence(300, "짧게")),
                            MenuAction("보통 (420ms)", lambda: self.update_leading_silence(420, "보통")),
                            MenuAction("길게 (600ms)", lambda: self.update_leading_silence(600, "길게")),
                        ],
                    ),
                    Menu(
                        "읽기 음량",
                        [
                            MenuAction("작게 (70%)", lambda: self.update_volume(0.70, "작게")),
                            MenuAction("보통 (100%)", lambda: self.update_volume(1.00, "보통")),
                            MenuAction("크게 (130%)", lambda: self.update_volume(1.30, "크게")),
                            MenuAction("아주 크게 (160%)", lambda: self.update_volume(1.60, "아주 크게")),
                        ],
                    ),
                    MenuAction("현재 설정 보기", self.show_current_settings),
                ],
            ),
        ]
        webview.start(storage_path=str(WEBVIEW_STORAGE_DIR), private_mode=False, menu=menu)


if __name__ == "__main__":
    viewer = DashboardTTSViewer()
    viewer.run()
