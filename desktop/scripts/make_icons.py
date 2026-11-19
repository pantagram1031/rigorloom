"""Generate the Tauri icon set and the favicon from the drawing of record.

    python desktop/scripts/make_icons.py

Reads the 16-px cut desktop/src/assets/logo-16.svg,
draws the mark in white on a 쪽빛 (#2A48A4) tile and writes
desktop/src-tauri/icons/* and desktop/public/favicon.ico.
Needs Python Playwright with a Chromium build and Pillow; it is a developer
tool, not part of the build.
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

DESKTOP = Path(__file__).resolve().parents[1]
ASSETS = DESKTOP / "src" / "assets"
ICONS = DESKTOP / "src-tauri" / "icons"
FAVICON = DESKTOP / "public" / "favicon.ico"
INDIGO = "#2A48A4"

PNGS = {
    "32x32.png": 32, "64x64.png": 64, "128x128.png": 128, "128x128@2x.png": 256,
    "icon.png": 512, "Square30x30Logo.png": 30, "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71, "Square89x89Logo.png": 89, "Square107x107Logo.png": 107,
    "Square142x142Logo.png": 142, "Square150x150Logo.png": 150,
    "Square284x284Logo.png": 284, "Square310x310Logo.png": 310, "StoreLogo.png": 50,
}
ICO_SIZES = [16, 24, 32, 48, 64, 256]
ICNS_SIZE = 1024


def path_and_width(svg: Path) -> tuple[str, str]:
    text = svg.read_text(encoding="utf-8")
    d = re.search(r'<path d="([^"]+)"', text).group(1)
    w = re.search(r'stroke-width="([^"]+)"', text).group(1)
    return d, w


def tile(size: int) -> str:
    small = size <= 24
    # Tiles use the 16-px cut at every size: white on 쪽빛 needs its heavier
    # stroke to hold up. At 24 px and below it is drawn at a whole multiple of
    # 16 px so each unit lands on whole pixels; mid sizes give the mark more of
    # the tile than large ones.
    d, w = path_and_width(ASSETS / "logo-16.svg")
    mark = 16 * (size // 16) if small else round(size * (0.72 if size <= 64 else 0.6))
    off = (size - mark) / 2
    radius = size * (0.16 if small else 0.225)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
        f'<rect width="{size}" height="{size}" rx="{radius}" fill="{INDIGO}"/>'
        f'<svg x="{off}" y="{off}" width="{mark}" height="{mark}" viewBox="0 0 16 16">'
        f'<path d="{d}" fill="none" stroke="#fff" stroke-width="{w}" '
        f'stroke-linecap="butt" stroke-linejoin="miter"/></svg></svg>'
    )


async def render(sizes: set[int]) -> dict[int, Image.Image]:
    out: dict[int, Image.Image] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(device_scale_factor=1)
        for size in sorted(sizes):
            await page.set_viewport_size({"width": size, "height": size})
            await page.set_content(
                f'<body style="margin:0;background:transparent">{tile(size)}</body>'
            )
            png = await page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
            out[size] = Image.open(io.BytesIO(png)).convert("RGBA")
        await browser.close()
    return out


def main() -> int:
    sizes = set(PNGS.values()) | set(ICO_SIZES) | {ICNS_SIZE}
    images = asyncio.run(render(sizes))
    for name, size in PNGS.items():
        images[size].save(ICONS / name)
    ico = [images[s] for s in ICO_SIZES]
    ico[-1].save(ICONS / "icon.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=ico[:-1])
    fav = [images[s] for s in (16, 24, 32, 48)]
    fav[-1].save(FAVICON, sizes=[(s, s) for s in (16, 24, 32, 48)], append_images=fav[:-1])
    images[ICNS_SIZE].save(ICONS / "icon.icns")
    print(f"wrote {len(PNGS)} PNGs, icon.ico, icon.icns and favicon.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
