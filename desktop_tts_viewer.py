import json
import os
import queue
import re
import subprocess
import threading
import time
import winsound
from pathlib import Path

import requests
import webview
from webview.menu import Menu, MenuAction

from config import BASE_DIR
from web_dashboard import DEFAULT_PORT, DEFAULT_WINDOW_MINUTES, run_server


APP_HOST = "192.168.2.11"
APP_POLL_SECONDS = 5
MELOTTS_WINDOWS_ENV = "melotts-win"
DEFAULT_MELO_SPEED = 1.0
DEFAULT_LEADING_SILENCE_MS = 420
WAV_CACHE_MAX_AGE_SECONDS = 60 * 60
WORKER_READY_TIMEOUT_SECONDS = 180
WORKER_COMMAND_TIMEOUT_SECONDS = 180
CACHE_DIR = BASE_DIR / "tts_cache"
WEBVIEW_STORAGE_DIR = Path.home() / "AppData" / "Local" / "IssueTrackerWebView"
WORKER_SCRIPT_PATH = BASE_DIR / "melotts_windows_worker.py"
SETTINGS_PATH = BASE_DIR / "tts_viewer_settings.json"
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


def clean_title_for_tts(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    separators = [" - ", " – ", " — ", " | "]
    for separator in separators:
        index = text.rfind(separator)
        if index > 15:
            text = text[:index].strip()
            break
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
        }
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return {
        "speed": float(data.get("speed") or DEFAULT_MELO_SPEED),
        "leading_silence_ms": int(data.get("leading_silence_ms") or DEFAULT_LEADING_SILENCE_MS),
    }


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


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
        CACHE_DIR.mkdir(exist_ok=True)
        WEBVIEW_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

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
        print(f"[APP] starting melotts worker: {' '.join(command)}")
        self.worker_ready_event.clear()
        self.worker_process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self.worker_reader_thread = threading.Thread(target=self.read_worker_output, daemon=True)
        self.worker_reader_thread.start()
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
                print(f"[APP] worker ready: {text}")
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
            print(f"[MELO] {text}")

    def start_background_workers(self) -> None:
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
                print(f"[APP] poll error: {error}")
                self.set_status(f"폴링 오류: {error}")
            except Exception as error:
                print(f"[APP] unexpected poll error: {error}")
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
                print(f"[APP] tts error: {error}")
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

    def play_issue(self, issue: dict) -> None:
        title = clean_title_for_tts(issue.get("translated_title") or issue.get("title") or "")
        if not title:
            return
        cache_key = f"melotts_windows_{build_issue_cache_key(issue)}"
        self.speak_with_melotts_windows(title, cache_key)
        print(f"[APP] melotts-windows played: {title}")
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
        print(f"[APP] {text}")
        self.last_status = text

    def prune_old_wav_cache(self) -> None:
        cutoff = time.time() - WAV_CACHE_MAX_AGE_SECONDS
        for wav_path in CACHE_DIR.glob("*.wav"):
            try:
                if wav_path.stat().st_mtime < cutoff:
                    wav_path.unlink()
                    print(f"[APP] 오래된 wav 삭제: {wav_path.name}")
            except FileNotFoundError:
                continue
            except OSError as error:
                print(f"[APP] wav 삭제 실패: {wav_path.name} / {error}")

    def settings_summary(self) -> str:
        return f"속도 {self.settings['speed']:.2f}, 시작 여유 {self.settings['leading_silence_ms']}ms"

    def update_speed(self, speed: float, label: str) -> None:
        self.settings["speed"] = speed
        save_settings(self.settings)
        self.set_status(f"읽기 속도 변경: {label} ({self.settings_summary()})")

    def update_leading_silence(self, milliseconds: int, label: str) -> None:
        self.settings["leading_silence_ms"] = milliseconds
        save_settings(self.settings)
        self.set_status(f"시작 여유 변경: {label} ({self.settings_summary()})")

    def show_current_settings(self) -> None:
        self.set_status(f"현재 TTS 설정: {self.settings_summary()}")

    def speak_with_melotts_windows(self, title: str, cache_key: str) -> None:
        self.prune_old_wav_cache()
        settings_key = f"{cache_key}_s{str(self.settings['speed']).replace('.', '_')}_p{self.settings['leading_silence_ms']}"
        cache_path = self.get_cache_path(settings_key)
        if not cache_path.exists():
            self.ensure_worker()
            if not self.worker_process or not self.worker_process.stdin:
                raise RuntimeError("MeloTTS worker stdin을 사용할 수 없습니다.")
            command = {
                "cmd": "synthesize",
                "text": title,
                "output_path": str(cache_path),
                "speed": self.settings["speed"],
                "leading_silence_ms": self.settings["leading_silence_ms"],
            }
            print(f"[APP] worker synth request: {title}")
            self.worker_process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            self.worker_process.stdin.flush()
            try:
                result = self.worker_result_queue.get(timeout=WORKER_COMMAND_TIMEOUT_SECONDS)
            except queue.Empty as error:
                raise RuntimeError("MeloTTS worker 응답 시간이 초과되었습니다.") from error
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "melotts-win 실행에 실패했습니다."))
        winsound.PlaySound(str(cache_path), winsound.SND_FILENAME)

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
        self.ensure_server()
        self.start_background_workers()
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

        window.events.closed += handle_closed
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
                    MenuAction("현재 설정 보기", self.show_current_settings),
                ],
            ),
        ]
        webview.start(storage_path=str(WEBVIEW_STORAGE_DIR), private_mode=False, menu=menu)


if __name__ == "__main__":
    viewer = DashboardTTSViewer()
    viewer.run()
