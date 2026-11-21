#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["fonttools"]
# ///
"""Step 2: Reshape svg/route159/ via Bezier midpoint morphing with svg/vegur/ + svg/hack/ -> svg/route138/."""

import math
import shutil
import sys
from pathlib import Path
from fontTools.svgLib.path import SVGPath
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Identity

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morph_svg import load_svg_dir, morph_contours, contours_to_svg_path

ROOT = Path(__file__).resolve().parent.parent
SVG_ROOT = ROOT / "svg"

UPRIGHT_STYLES = ["Regular", "Bold"]
ITALIC_PAIRS = [("Regular", "Italic"), ("Bold", "BoldItalic")]
ITALIC_ANGLE = 12.0
ITALIC_PIVOT_Y = 260.0

# Topology-different signature Vegur glyphs to adopt directly into Route 138
VEGUR_ADOPT_DIRECT = {ord("g"), ord("K"), ord("k")}
MORPH_ALPHA = 0.50


def is_lowercase_cp(cp: int) -> bool:
    ch = chr(cp)
    return ch.islower()

SHARED_HACK_RANGES = [
    (0x0020, 0x007E),
    (0x00A0, 0x00FF),
    (0x0100, 0x017F),
    (0x2000, 0x206F),
    (0x2070, 0x209F),
    (0x20A0, 0x20CF),
    (0x2150, 0x218F),
    (0x2190, 0x2199),
    (0x21B5, 0x21B5),
    (0x2200, 0x2265),
]

UPM = 1000
BASELINE = 800


def in_ranges(cp: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def transform_svg_path(root, font_transform):
    path_elem = root.find("{http://www.w3.org/2000/svg}path")
    d = path_elem.attrib.get("d", "").strip() if path_elem is not None else ""
    if not d:
        return "", None
    src_baseline = int(root.attrib.get("data-baseline", "800"))
    unflip = Identity.translate(0, src_baseline).scale(1, -1)
    reflip = Identity.translate(0, BASELINE).scale(1, -1)
    svg_obj = SVGPath.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>')
    to_font = font_transform.transform(unflip)
    bp = BoundsPen(None)
    svg_obj.draw(TransformPen(bp, to_font))
    pen = SVGPathPen(None)
    svg_obj.draw(TransformPen(pen, reflip.transform(to_font)))
    return pen.getCommands(), bp.bounds


def write_svg(out_path: Path, gn: str, cp: int, advance: int, d: str, source: str):
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max(advance, 100)} {UPM}" '
        f'data-glyph="{gn}" data-unicode="U+{cp:04X}" data-advance="{advance}" '
        f'data-upm="{UPM}" data-baseline="{BASELINE}" data-source="{source}">\n'
        f'  <path d="{d}" fill="currentColor"/>\n'
        f'</svg>\n'
    )
    out_path.write_text(svg, encoding="utf-8")


def main():
    scale_upper = 740.0 / 688.0
    scale_lower = 520.0 / 478.0

    for style_key in UPRIGHT_STYLES:
        r159_map = load_svg_dir(SVG_ROOT / "route159" / style_key)
        vegur_map = load_svg_dir(SVG_ROOT / "vegur" / style_key)

        out_dir = SVG_ROOT / "route138" / style_key
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        morphed_count = 0
        for cp, (r_path, r_root) in sorted(r159_map.items()):
            gn = r_root.attrib["data-glyph"]
            if cp in vegur_map:
                _, v_root = vegur_map[cp]
                s = scale_lower if is_lowercase_cp(cp) else scale_upper
                t = Identity.scale(s, s)

                if cp in VEGUR_ADOPT_DIRECT:
                    d, _ = transform_svg_path(v_root, t)
                    adv = round(int(v_root.attrib["data-advance"]) * s)
                    write_svg(out_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"vegur/{style_key}")
                    morphed_count += 1
                else:
                    morphed = morph_contours(r_root, v_root, t, alpha=MORPH_ALPHA)
                    if morphed is not None:
                        d = contours_to_svg_path(morphed, BASELINE)
                        r_adv = int(r_root.attrib["data-advance"])
                        v_adv = round(int(v_root.attrib["data-advance"]) * s)
                        adv = round((1.0 - MORPH_ALPHA) * r_adv + MORPH_ALPHA * v_adv)
                        write_svg(out_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"morph(r159,vegur,{MORPH_ALPHA})")
                        morphed_count += 1
                    else:
                        shutil.copy2(r_path, out_dir / r_path.name)
            else:
                shutil.copy2(r_path, out_dir / r_path.name)
            count += 1

        print(f"Reshaped {count} SVGs ({morphed_count} morphed with Vegur) -> {out_dir.relative_to(ROOT)}")

    # Derive Italic and BoldItalic from morphed Regular and Bold via oblique shear
    shear_t = (
        Identity.translate(0, ITALIC_PIVOT_Y)
        .skew(math.radians(ITALIC_ANGLE), 0)
        .translate(0, -ITALIC_PIVOT_Y)
    )
    for src_style, dst_style in ITALIC_PAIRS:
        src_map = load_svg_dir(SVG_ROOT / "route138" / src_style)
        out_dir = SVG_ROOT / "route138" / dst_style
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for cp, (_, root) in sorted(src_map.items()):
            gn = root.attrib["data-glyph"]
            adv = int(root.attrib["data-advance"])
            d, _ = transform_svg_path(root, shear_t)
            write_svg(out_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"oblique({src_style},{ITALIC_ANGLE}deg)")
        print(f"Derived {len(src_map)} oblique SVGs ({ITALIC_ANGLE}°) -> {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
