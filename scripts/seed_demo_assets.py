from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
IMAGE_ROOT = ROOT / "demo_assets" / "images"


def make_image(path: Path, title: str, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (960, 540), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 920, 500), outline=(255, 255, 255), width=4)
    draw.text((80, 240), title, fill=(255, 255, 255))
    image.save(path, format="JPEG", quality=90)


def main() -> None:
    samples = [
        ("visible/sample_001.jpg", "Visible / Day / Urban", (46, 125, 50)),
        ("visible/sample_002.jpg", "Visible / Night / Rural", (21, 101, 192)),
        ("infrared/sample_001.jpg", "Infrared / Night / Urban", (183, 28, 28)),
    ]
    for relative_path, title, color in samples:
        make_image(IMAGE_ROOT / relative_path, title, color)
    print(f"Generated {len(samples)} demo images under {IMAGE_ROOT}")


if __name__ == "__main__":
    main()
