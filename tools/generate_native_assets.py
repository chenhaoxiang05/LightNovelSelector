from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "native" / "LightNovelSelector.WinUI" / "Assets"
BLUE = "#0F6CBD"
BLUE_DARK = "#084F91"
BLUE_LIGHT = "#DCEEFF"
AMBER = "#F0A320"
WHITE = "#FFFFFF"


def _polygon(points: list[tuple[float, float]], box: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    return [(round(left + x * width), round(top + y * height)) for x, y in points]


def draw_mark(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    plated: bool = True,
    light_glyph: bool = False,
) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    size = min(right - left, bottom - top)
    radius = round(size * 0.22)

    if plated:
        draw.rounded_rectangle(box, radius=radius, fill=BLUE)
        page_color = WHITE
        detail_color = BLUE_LIGHT
    else:
        page_color = WHITE if light_glyph else BLUE
        detail_color = "#BBDFFF" if light_glyph else BLUE_DARK

    left_page = _polygon([(0.20, 0.27), (0.46, 0.34), (0.46, 0.73), (0.20, 0.66)], box)
    right_page = _polygon([(0.54, 0.34), (0.80, 0.27), (0.80, 0.66), (0.54, 0.73)], box)
    draw.polygon(left_page, fill=page_color)
    draw.polygon(right_page, fill=page_color)

    line_width = max(1, round(size * 0.026))
    for y in (0.43, 0.53):
        draw.line(_polygon([(0.27, y), (0.40, y + 0.035)], box), fill=detail_color, width=line_width)
        draw.line(_polygon([(0.60, y + 0.035), (0.73, y)], box), fill=detail_color, width=line_width)

    badge_center = (round(left + size * 0.73), round(top + size * 0.70))
    badge_radius = round(size * 0.145)
    draw.ellipse(
        (
            badge_center[0] - badge_radius,
            badge_center[1] - badge_radius,
            badge_center[0] + badge_radius,
            badge_center[1] + badge_radius,
        ),
        fill=AMBER,
    )
    check_width = max(1, round(size * 0.038))
    draw.line(
        [
            (round(left + size * 0.665), round(top + size * 0.70)),
            (round(left + size * 0.715), round(top + size * 0.75)),
            (round(left + size * 0.80), round(top + size * 0.64)),
        ],
        fill=BLUE_DARK,
        width=check_width,
        joint="curve",
    )


def make_asset(
    size: tuple[int, int],
    mark_size: int,
    *,
    plated: bool = True,
    light_glyph: bool = False,
    supersample: int = 4,
) -> Image.Image:
    width, height = size
    canvas = Image.new("RGBA", (width * supersample, height * supersample), (0, 0, 0, 0))
    scaled_mark = mark_size * supersample
    left = (canvas.width - scaled_mark) // 2
    top = (canvas.height - scaled_mark) // 2
    draw_mark(
        canvas,
        (left, top, left + scaled_mark, top + scaled_mark),
        plated=plated,
        light_glyph=light_glyph,
    )
    return canvas.resize(size, Image.Resampling.LANCZOS)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    assets = {
        "LockScreenLogo.scale-200.png": make_asset((48, 48), 44),
        "SplashScreen.scale-200.png": make_asset((1240, 600), 208),
        "Square150x150Logo.scale-200.png": make_asset((300, 300), 268),
        "Square44x44Logo.scale-200.png": make_asset((88, 88), 78),
        "Square44x44Logo.targetsize-24_altform-unplated.png": make_asset(
            (24, 24), 23, plated=False, supersample=8
        ),
        "Square44x44Logo.targetsize-48_altform-lightunplated.png": make_asset(
            (48, 48), 46, plated=False, light_glyph=True, supersample=6
        ),
        "StoreLogo.png": make_asset((50, 50), 46),
        "Wide310x150Logo.scale-200.png": make_asset((620, 300), 208),
    }
    for name, image in assets.items():
        image.save(ASSET_DIR / name, optimize=True)

    icon = make_asset((256, 256), 236, supersample=4)
    icon.save(
        ASSET_DIR / "AppIcon.ico",
        format="ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
