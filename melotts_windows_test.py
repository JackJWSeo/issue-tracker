import os
import subprocess
import sys
import winsound
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "tts_cache"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "melotts_windows_test.wav"
MELOTTS_WINDOWS_ENV = "melotts-win"
TEST_TEXT = "백악관 직원들은 예측 시장에 베팅하지 말라고 경고하는 이메일을 받았다고 관리들이 밝혔습니다."
PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in PROXY_ENV_KEYS:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def synthesize_with_melotts() -> None:
    script = (
        "from melo.api import TTS; "
        "model = TTS(language='KR', device='cpu'); "
        "speaker_ids = model.hps.data.spk2id; "
        f"model.tts_to_file({TEST_TEXT!r}, speaker_ids['KR'], r'{str(OUTPUT_PATH)}', speed=1.0)"
    )
    command = [
        "conda",
        "run",
        "-n",
        MELOTTS_WINDOWS_ENV,
        "python",
        "-u",
        "-c",
        script,
    ]
    print("[TEST] running command:")
    print(" ".join(command[:5]) + " ...")
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        env=build_env(),
        timeout=300,
    )
    print("[TEST] returncode:", completed.returncode)
    if completed.returncode != 0:
        raise RuntimeError("MeloTTS-Windows 합성 실패")


def main() -> int:
    print(f"[TEST] output path: {OUTPUT_PATH}")
    synthesize_with_melotts()
    if not OUTPUT_PATH.exists():
        print("[TEST] wav 파일이 생성되지 않았습니다.")
        return 1
    print(f"[TEST] wav 생성 완료: {OUTPUT_PATH}")
    winsound.PlaySound(str(OUTPUT_PATH), winsound.SND_FILENAME)
    print("[TEST] 재생 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
