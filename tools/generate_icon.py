"""根据界面左上角品牌标志生成 Windows 多尺寸 ICO。"""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "world_relay.ico"
CANVAS_SIZE = 1024
ICON_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]


def scaled(value: int) -> int:
    return value * CANVAS_SIZE // 256


def main() -> None:
    image = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (scaled(12), scaled(12), scaled(244), scaled(244)),
        radius=scaled(20),
        fill="#17241f",
    )
    draw.rounded_rectangle(
        (scaled(23), scaled(23), scaled(233), scaled(233)),
        radius=scaled(10),
        outline="#75a99b",
        width=scaled(10),
    )

    squares = (
        (48, 48, 122, 122, "#4e9c91"),
        (134, 48, 208, 122, "#305a52"),
        (48, 134, 122, 208, "#305a52"),
        (134, 134, 208, 208, "#4e9c91"),
    )
    for left, top, right, bottom, color in squares:
        draw.rectangle(
            (scaled(left), scaled(top), scaled(right), scaled(bottom)),
            fill=color,
        )

    preview = image.resize((256, 256), Image.Resampling.LANCZOS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    preview.save(OUTPUT, format="ICO", sizes=ICON_SIZES)
    print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()
