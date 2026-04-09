import asyncio
import threading
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import font as tkfont, messagebox, ttk

from app import monitor_loop
from ui_settings import UISettings, load_ui_settings, save_ui_settings


MAX_UI_LOG_LINES = 500


class MonitorUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Trump Monitor Control")
        self.root.geometry("880x640")

        self.log_buffer: deque[str] = deque(maxlen=MAX_UI_LOG_LINES)
        self.log_lock = threading.Lock()
        self.displayed_log_count = 0
        self.monitor_thread: threading.Thread | None = None
        self.stop_event = threading.Event()

        self.settings = load_ui_settings()
        self.telegram_enabled_var = tk.BooleanVar(value=self.settings.telegram_enabled)
        self.use_recent_hours_filter_var = tk.BooleanVar(value=self.settings.use_recent_hours_filter)
        self.recent_hours_var = tk.IntVar(value=self.settings.recent_hours)
        self.exclude_keywords_var = tk.StringVar(value=self.settings.exclude_keywords)
        self.include_topic_var = tk.BooleanVar(value=self.settings.include_topic)
        self.include_source_var = tk.BooleanVar(value=self.settings.include_source)
        self.include_time_var = tk.BooleanVar(value=self.settings.include_time)
        self.include_title_var = tk.BooleanVar(value=self.settings.include_title)
        self.include_content_var = tk.BooleanVar(value=self.settings.include_content)
        self.include_link_var = tk.BooleanVar(value=self.settings.include_link)

        self.status_var = tk.StringVar(value="대기 중")
        self.preview_var = tk.StringVar(value=self.build_preview_text())

        self.build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self.flush_logs)

    def build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(3, weight=1)

        subtitle = ttk.Label(
            container,
            text="텔레그램 전송 여부와 메시지 구성 요소를 체크박스로 제어할 수 있습니다.",
            justify="left",
        )
        subtitle.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        controls = ttk.LabelFrame(container, text="메시지 설정", padding=12)
        controls.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        side_panel = ttk.Frame(container)
        side_panel.grid(row=1, column=1, sticky="nsew", pady=(0, 12))
        side_panel.columnconfigure(0, weight=1)

        time_filter_frame = ttk.LabelFrame(side_panel, text="수집 시간 범위", padding=12)
        time_filter_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        time_filter_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            time_filter_frame,
            text="최근 N시간 내 컨텐츠만 가져오기",
            variable=self.use_recent_hours_filter_var,
            command=self.on_setting_changed,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(time_filter_frame, text="최근 시간:").grid(row=1, column=0, sticky="w", padx=(0, 6))
        hours_spin = ttk.Spinbox(
            time_filter_frame,
            from_=1,
            to=168,
            textvariable=self.recent_hours_var,
            width=8,
            command=self.on_setting_changed,
        )
        hours_spin.grid(row=1, column=1, sticky="w")
        ttk.Label(time_filter_frame, text="시간").grid(row=1, column=2, sticky="w", padx=(6, 0))
        hours_spin.bind("<KeyRelease>", lambda _event: self.on_setting_changed())

        ttk.Label(time_filter_frame, text="제외 키워드:").grid(row=2, column=0, sticky="nw", padx=(0, 6), pady=(10, 0))
        exclude_entry = ttk.Entry(time_filter_frame, textvariable=self.exclude_keywords_var)
        exclude_entry.grid(row=2, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        exclude_entry.bind("<KeyRelease>", lambda _event: self.on_setting_changed())

        checkboxes = [
            ("텔레그램으로 메시지 전송", self.telegram_enabled_var),
            ("분류 포함", self.include_topic_var),
            ("출처 포함", self.include_source_var),
            ("시각 포함", self.include_time_var),
            ("제목 포함", self.include_title_var),
            ("내용 포함", self.include_content_var),
            ("링크 포함", self.include_link_var),
        ]

        for index, (label, var) in enumerate(checkboxes):
            ttk.Checkbutton(
                controls,
                text=label,
                variable=var,
                command=self.on_setting_changed,
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 18), pady=6)

        button_row = ttk.LabelFrame(side_panel, text="실행 제어", padding=12)
        button_row.grid(row=1, column=0, sticky="ew", pady=(0, 12))

        ttk.Button(button_row, text="설정 저장", command=self.save_settings).pack(side="left")
        ttk.Button(button_row, text="모니터 시작", command=self.start_monitoring).pack(side="left", padx=8)
        ttk.Button(button_row, text="모니터 중지", command=self.stop_monitoring).pack(side="left")

        status_frame = ttk.LabelFrame(side_panel, text="상태", padding=12)
        status_frame.grid(row=2, column=0, sticky="ew")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor="w")

        preview_frame = ttk.LabelFrame(container, text="메시지 미리보기", padding=12)
        preview_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(preview_frame, textvariable=self.preview_var, justify="left").pack(anchor="w")

        log_frame = ttk.LabelFrame(container, text="실행 로그", padding=12)
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")

        self.log_text = tk.Text(log_frame, wrap="word", height=18)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.configure(state="disabled")

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def build_settings(self) -> UISettings:
        return UISettings(
            telegram_enabled=self.telegram_enabled_var.get(),
            use_recent_hours_filter=self.use_recent_hours_filter_var.get(),
            recent_hours=max(1, int(self.recent_hours_var.get() or 24)),
            exclude_keywords=self.exclude_keywords_var.get().strip(),
            include_topic=self.include_topic_var.get(),
            include_source=self.include_source_var.get(),
            include_time=self.include_time_var.get(),
            include_title=self.include_title_var.get(),
            include_content=self.include_content_var.get(),
            include_link=self.include_link_var.get(),
        )

    def build_preview_text(self) -> str:
        settings = self.build_settings()
        lines = []
        lines.append("텔레그램 전송: 켜짐" if settings.telegram_enabled else "텔레그램 전송: 꺼짐")
        if settings.include_topic:
            lines.append("분류: 이란 전쟁 관련")
        if settings.include_source:
            lines.append("출처: google_news:Donald Trump")
        if settings.include_time:
            lines.append("시각: 2026-04-08 15:30:00 UTC")
        if settings.include_title:
            lines.append("제목: 번역된 제목 예시")
        if settings.include_content:
            lines.append("내용: 번역된 본문 예시")
        if settings.include_link:
            lines.append("링크: https://example.com")
        return "\n".join(lines)

    def on_setting_changed(self) -> None:
        if self.recent_hours_var.get() < 1:
            self.recent_hours_var.set(1)
        self.preview_var.set(self.build_preview_text())

    def save_settings(self) -> None:
        self.settings = self.build_settings()
        save_ui_settings(self.settings)
        self.preview_var.set(self.build_preview_text())
        self.append_log("[UI] 설정 저장 완료")

    def start_monitoring(self) -> None:
        if self.monitor_thread and self.monitor_thread.is_alive():
            messagebox.showinfo("실행 중", "모니터가 이미 실행 중입니다.")
            return

        self.save_settings()
        self.stop_event = threading.Event()
        self.monitor_thread = threading.Thread(target=self.run_monitor, daemon=True)
        self.monitor_thread.start()
        self.status_var.set("모니터 실행 중")
        self.append_log("[UI] 모니터 시작")

    def run_monitor(self) -> None:
        asyncio.run(
            monitor_loop(
                stop_event=self.stop_event,
                log=self.append_log,
                settings=self.build_settings(),
            )
        )
        self.append_log("[UI] 모니터 스레드 종료")
        self.root.after(0, lambda: self.status_var.set("대기 중"))

    def stop_monitoring(self) -> None:
        if not self.monitor_thread or not self.monitor_thread.is_alive():
            self.status_var.set("대기 중")
            self.append_log("[UI] 중지할 실행 중 모니터가 없음")
            return

        self.stop_event.set()
        self.status_var.set("중지 요청됨")
        self.append_log("[UI] 모니터 중지 요청")

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.log_lock:
            self.log_buffer.append(f"[{timestamp}] {message}")

    def flush_logs(self) -> None:
        with self.log_lock:
            messages = list(self.log_buffer)
            self.log_buffer.clear()

        for message in messages:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.displayed_log_count += 1
            overflow = self.displayed_log_count - MAX_UI_LOG_LINES
            if overflow > 0:
                self.log_text.delete("1.0", f"{overflow + 1}.0")
                self.displayed_log_count = MAX_UI_LOG_LINES
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(200, self.flush_logs)

    def on_close(self) -> None:
        self.save_settings()
        self.stop_event.set()
        self.root.destroy()


def launch_main_ui() -> None:
    root = tk.Tk()
    default_font = tkfont.nametofont("TkDefaultFont")
    default_font.configure(family="Segoe UI", size=10)
    text_font = tkfont.nametofont("TkTextFont")
    text_font.configure(family="Segoe UI", size=10)
    MonitorUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_main_ui()
