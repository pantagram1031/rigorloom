"""Assemble sequential PNG frames into docs/demo/desktop/demo.gif.

Keeps 1280x800, aims for <= 8 MB. Duration is 1.5 s per frame (the capture
script already dwells ~1.2 s on each state).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image


MAX_BYTES = 8 * 1024 * 1024
SIZE = (1280, 800)
DURATION_MS = 1500


def load(path: Path, colors: int) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    if image.size != SIZE:
        image = image.resize(SIZE, Image.Resampling.LANCZOS)
    # GIF has no alpha; flatten onto the app's light page colour.
    bg = Image.new("RGB", SIZE, (247, 245, 240))
    bg.paste(image, mask=image.split()[-1])
    return bg.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)


def save(frames: list[Image.Image], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("frames", nargs="+")
    args = parser.parse_args()
    paths = [Path(p) for p in args.frames]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print(f"missing frames: {missing}", file=sys.stderr)
        return 2
    out = Path(args.out)
    colors = 128
    while colors >= 32:
        frames = [load(p, colors) for p in paths]
        save(frames, out)
        size = out.stat().st_size
        seconds = (DURATION_MS / 1000) * len(frames)
        print(f"wrote {out}  {len(frames)} frames  {seconds:.1f}s  {size} B  {colors} colours")
        if size <= MAX_BYTES and seconds <= 90:
            return 0
        colors //= 2
    print(f"GIF still {out.stat().st_size} B after colour reduction", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
