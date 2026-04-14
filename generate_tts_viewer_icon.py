from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
GENERATED_DIR = ROOT / "build" / "generated"
PNG_PATH = ASSETS_DIR / "tts_viewer_icon.png"
DEFAULT_ICO_PATH = GENERATED_DIR / "tts_viewer_icon.ico"
SIZE = 512
PADDING_RATIO = 0.04


def build_icon(output_path: Path | None = None) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    if not PNG_PATH.exists():
        raise FileNotFoundError(f"아이콘 PNG를 찾을 수 없습니다: {PNG_PATH}")

    ico_path = output_path or DEFAULT_ICO_PATH

    source = Image.open(PNG_PATH).convert("RGBA")
    bbox = source.getbbox()
    if bbox is None:
        raise RuntimeError("원본 이미지에 보이는 내용이 없습니다.")

    cropped = source.crop(bbox)
    inner_size = int(round(SIZE * (1.0 - PADDING_RATIO * 2)))
    resized = cropped.resize((inner_size, inner_size), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    offset = ((SIZE - inner_size) // 2, (SIZE - inner_size) // 2)
    canvas.alpha_composite(resized, offset)
    canvas.save(ico_path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])


if __name__ == "__main__":
    build_icon(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
