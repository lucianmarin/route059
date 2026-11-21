#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["fonttools"]
# ///
"""Step 1: Export raw SVGs from Route 159, Vegur, and Hack (Latin + symbols, no other scripts)."""

from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.misc.transform import Identity

ROOT = Path(__file__).resolve().parent.parent
INSPIRATION = ROOT / "inspiration"
SVG_ROOT = ROOT / "svg"

# Non-Latin script ranges to exclude from Hack
NON_LATIN_RANGES = [
    (0x0370, 0x03FF),  # Greek and Coptic
    (0x0400, 0x052F),  # Cyrillic + Cyrillic Supplement
    (0x0530, 0x058F),  # Armenian
    (0x0E00, 0x0E7F),  # Thai (e.g. Baht)
    (0x10A0, 0x10FF),  # Georgian
    (0x1F00, 0x1FFF),  # Greek Extended
]


def is_excluded_script(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in NON_LATIN_RANGES)


def export_font(font_path: Path, out_dir: Path, exclude_non_latin: bool = False):
    font = TTFont(font_path)
    upm = font["head"].unitsPerEm
    baseline = round(upm * 0.8)  # 800 for 1000 UPM, 1638 for 2048 UPM
    is_ttf = "glyf" in font
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    flip = Identity.translate(0, baseline).scale(1, -1)

    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for cp, gn in sorted(cmap.items()):
        if exclude_non_latin and is_excluded_script(cp):
            continue
        adv = font["hmtx"][gn][0]
        pen = SVGPathPen(gs)
        if is_ttf:
            gs[gn].draw(Qu2CuPen(TransformPen(pen, flip), max_err=1.0, all_cubic=True))
        else:
            gs[gn].draw(TransformPen(pen, flip))
        d = pen.getCommands()

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max(adv, 100)} {upm}" '
            f'data-glyph="{gn}" data-unicode="U+{cp:04X}" data-advance="{adv}" '
            f'data-upm="{upm}" data-baseline="{baseline}" data-source="{font_path.name}">\n'
            f'  <path d="{d}" fill="currentColor"/>\n'
            f'</svg>\n'
        )
        (out_dir / f"U+{cp:04X}_{gn}.svg").write_text(svg, encoding="utf-8")
        count += 1

    print(f"Exported {count:4d} SVGs from {font_path.name:<28} -> {out_dir.relative_to(ROOT)}")


def main():
    for style in ("Regular", "Bold"):
        export_font(INSPIRATION / f"Route159-{style}.otf", SVG_ROOT / "route159" / style)
    for style in ("Regular", "Bold"):
        export_font(INSPIRATION / f"Vegur-{style}.otf", SVG_ROOT / "vegur" / style)
    for style in ("Regular", "Bold"):
        export_font(INSPIRATION / f"Hack-{style}.ttf", SVG_ROOT / "hack" / style, exclude_non_latin=True)


if __name__ == "__main__":
    main()
