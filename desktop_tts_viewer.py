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
MELO_SPEED = 1.0
WORKER_READY_TIMEOUT_SECONDS = 180
WORKER_COMMAND_TIMEOUT_SECONDS = 180
CACHE_DIR = BASE_DIR / "tts_cache"
WEBVIEW_STORAGE_DIR = Path.home() / "AppData" / "Local" / "IssueTrackerWebView"
WORKER_SCRIPT_PATH = BASE_DIR / "melotts_windows_worker.py"
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
                title = clean_title_for_tts(issue.get("translated_title") or issue.get("title") or "")
                if not title:
                    continue
                self.play_title(title)
                self.set_status(f"재생 완료: {title}")
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

    def get_cache_path(self, title: str) -> Path:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", title.strip())[:80].strip("_") or "tts"
        return CACHE_DIR / f"{safe_name}.wav"

    def play_title(self, title: str) -> None:
        self.speak_with_melotts_windows(title)
        print(f"[APP] melotts-windows played: {title}")

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

    def speak_with_melotts_windows(self, title: str) -> None:
        cache_path = self.get_cache_path(f"melotts_windows_{title}")
        if not cache_path.exists():
            self.ensure_worker()
            if not self.worker_process or not self.worker_process.stdin:
                raise RuntimeError("MeloTTS worker stdin을 사용할 수 없습니다.")
            command = {
                "cmd": "synthesize",
                "text": title,
                "output_path": str(cache_path),
                "speed": MELO_SPEED,
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
            )
        ]
        webview.start(storage_path=str(WEBVIEW_STORAGE_DIR), private_mode=False, menu=menu)


if __name__ == "__main__":
    viewer = DashboardTTSViewer()
    viewer.run()
