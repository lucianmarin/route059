#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["fonttools"]
# ///
"""Step 3: Reshape svg/hack/ via Bezier midpoint morphing with svg/route138/ -> svg/route038/."""

import math
import shutil
import sys
from pathlib import Path
from fontTools.svgLib.path import SVGPath
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Identity

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morph_svg import load_svg_dir, morph_contours, contours_to_svg_path

ROOT = Path(__file__).resolve().parent.parent
SVG_ROOT = ROOT / "svg"

HACK_UPM = 2048
HACK_ADVANCE = 1233
SVG_BASELINE = 1600

UPRIGHT_STYLES = ["Regular", "Bold"]
ITALIC_PAIRS = [("Regular", "Italic"), ("Bold", "BoldItalic")]
ITALIC_ANGLE = 12.0
ITALIC_PIVOT_Y = 560.0

MONO_ONLY_HACK_RANGES = [
    (0x2500, 0x257F),  # Box Drawing
    (0x2580, 0x259F),  # Block Elements
    (0xE0A0, 0xE0D4),  # Powerline PUA
]

MORPH_ALPHA = 0.45


def is_lowercase_cp(cp: int) -> bool:
    return chr(cp).islower()


def in_ranges(cp: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def rebaseline_svg_path(root) -> str:
    path_elem = root.find("{http://www.w3.org/2000/svg}path")
    d = path_elem.attrib.get("d", "").strip() if path_elem is not None else ""
    if not d:
        return ""
    src_baseline = int(root.attrib.get("data-baseline", "1638"))
    t = Identity.translate(0, SVG_BASELINE - src_baseline)
    svg_obj = SVGPath.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>')
    pen = SVGPathPen(None)
    svg_obj.draw(TransformPen(pen, t))
    return pen.getCommands()


def write_svg(out_path: Path, gn: str, cp: int, advance: int, d: str, source: str):
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max(advance, 100)} {HACK_UPM}" '
        f'data-glyph="{gn}" data-unicode="U+{cp:04X}" data-advance="{advance}" '
        f'data-upm="{HACK_UPM}" data-baseline="{SVG_BASELINE}" data-source="{source}">\n'
        f'  <path d="{d}" fill="currentColor"/>\n'
        f'</svg>\n'
    )
    out_path.write_text(svg, encoding="utf-8")


def transform_svg_path(root, font_transform) -> str:
    path_elem = root.find("{http://www.w3.org/2000/svg}path")
    d = path_elem.attrib.get("d", "").strip() if path_elem is not None else ""
    if not d:
        return ""
    src_baseline = int(root.attrib.get("data-baseline", str(SVG_BASELINE)))
    unflip = Identity.translate(0, src_baseline).scale(1, -1)
    reflip = Identity.translate(0, SVG_BASELINE).scale(1, -1)
    svg_obj = SVGPath.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>')
    pen = SVGPathPen(None)
    svg_obj.draw(TransformPen(pen, reflip.transform(font_transform.transform(unflip))))
    return pen.getCommands()


def main():
    scale_upper = 1493.0 / 740.0
    scale_lower = 1120.0 / 520.0

    for style_key in UPRIGHT_STYLES:
        hack_map = load_svg_dir(SVG_ROOT / "hack" / style_key)
        r138_map = load_svg_dir(SVG_ROOT / "route138" / style_key)

        out_dir = SVG_ROOT / "route038" / style_key
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        morphed_count = 0
        for cp, (_, h_root) in sorted(hack_map.items()):
            gn = h_root.attrib["data-glyph"]
            adv = int(h_root.attrib["data-advance"])

            if cp in r138_map and not in_ranges(cp, MONO_ONLY_HACK_RANGES):
                s = scale_lower if is_lowercase_cp(cp) else scale_upper
                morphed = morph_contours(h_root, r138_map[cp][1], Identity.scale(s, s), alpha=MORPH_ALPHA)
                if morphed is not None:
                    d = contours_to_svg_path(morphed, SVG_BASELINE)
                    write_svg(out_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"morph(hack,r138,{MORPH_ALPHA})")
                    count += 1
                    morphed_count += 1
                    continue

            d = rebaseline_svg_path(h_root)
            write_svg(out_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"hack/{style_key}")
            count += 1

        print(f"Reshaped {count} SVGs ({morphed_count} morphed with Route 138) -> {out_dir.relative_to(ROOT)}")

    # Derive Italic and BoldItalic from morphed Regular and Bold via oblique shear
    # (keeping Box Drawing, Block Elements, and Powerline glyphs upright)
    shear_t = (
        Identity.translate(0, ITALIC_PIVOT_Y)
        .skew(math.radians(ITALIC_ANGLE), 0)
        .translate(0, -ITALIC_PIVOT_Y)
    )
    for src_style, dst_style in ITALIC_PAIRS:
        src_map = load_svg_dir(SVG_ROOT / "route038" / src_style)
        out_dir = SVG_ROOT / "route038" / dst_style
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slanted = 0
        for cp, (src_path, root) in sorted(src_map.items()):
            gn = root.attrib["data-glyph"]
            adv = int(root.attrib["data-advance"])
            if in_ranges(cp, MONO_ONLY_HACK_RANGES):
                shutil.copy2(src_path, out_dir / src_path.name)
            else:
                d = transform_svg_path(root, shear_t)
                write_svg(out_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"oblique({src_style},{ITALIC_ANGLE}deg)")
                slanted += 1
        print(f"Derived {len(src_map)} SVGs ({slanted} oblique {ITALIC_ANGLE}°, {len(src_map) - slanted} upright box/powerline) -> {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
