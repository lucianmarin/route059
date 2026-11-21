#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["fonttools"]
# ///
"""Extend svg/vegur/ to match the exact glyph set of svg/route159/ before morphing."""

import sys
import unicodedata
from pathlib import Path
from fontTools.svgLib.path import SVGPath
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Identity

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morph_svg import load_svg_dir

ROOT = Path(__file__).resolve().parent.parent
SVG_ROOT = ROOT / "svg"

VEGUR_UPM = 1000
VEGUR_BASELINE = 800

# Map Unicode combining marks to spacing equivalents present in Vegur
COMBINING_TO_SPACING = {
    0x0300: 0x0060,  # grave
    0x0301: 0x00B4,  # acute
    0x0302: 0x02C6,  # circumflex
    0x0303: 0x02DC,  # tilde
    0x0304: 0x00AF,  # macron
    0x0306: 0x02D8,  # breve
    0x0307: 0x02D9,  # dot above
    0x0308: 0x00A8,  # diaeresis
    0x030A: 0x02DA,  # ring above
    0x030B: 0x02DD,  # double acute
    0x030C: 0x02C7,  # caron
    0x0327: 0x00B8,  # cedilla
    0x0328: 0x02DB,  # ogonek
}


def get_path_and_bounds(root, transform=Identity):
    path_elem = root.find("{http://www.w3.org/2000/svg}path")
    d = path_elem.attrib.get("d", "").strip() if path_elem is not None else ""
    if not d:
        return "", None
    src_baseline = int(root.attrib.get("data-baseline", "800"))
    unflip = Identity.translate(0, src_baseline).scale(1, -1)
    reflip = Identity.translate(0, VEGUR_BASELINE).scale(1, -1)
    svg_obj = SVGPath.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>')
    to_font = transform.transform(unflip)
    bp = BoundsPen(None)
    svg_obj.draw(TransformPen(bp, to_font))
    pen = SVGPathPen(None)
    svg_obj.draw(TransformPen(pen, reflip.transform(to_font)))
    return pen.getCommands(), bp.bounds


def try_compose_from_vegur(cp: int, vegur_map: dict):
    """Compose a precomposed Latin glyph from Vegur's own base + accent if available."""
    decomp = unicodedata.decomposition(chr(cp))
    if not decomp or decomp.startswith("<"):
        return None
    parts = [int(x, 16) for x in decomp.split()]
    if len(parts) != 2:
        return None
    base_cp, comb_cp = parts
    # Use dotless i if available for accented i
    if base_cp == ord("i") and 0x0131 in vegur_map:
        base_cp = 0x0131
    accent_cp = COMBINING_TO_SPACING.get(comb_cp, comb_cp)
    if base_cp not in vegur_map or accent_cp not in vegur_map:
        return None

    _, base_root = vegur_map[base_cp]
    _, acc_root = vegur_map[accent_cp]
    base_d, base_b = get_path_and_bounds(base_root)
    acc_d_raw, acc_b = get_path_and_bounds(acc_root)
    if not base_d or not acc_d_raw or not base_b or not acc_b:
        return None

    # Center accent horizontally over base; adjust vertically above or below
    dx = ((base_b[0] + base_b[2]) / 2.0) - ((acc_b[0] + acc_b[2]) / 2.0)
    if comb_cp in (0x0327, 0x0328):  # below-base marks (cedilla, ogonek)
        dy = base_b[1] - acc_b[3] + 20.0
    else:
        dy = (base_b[3] + 45.0) - acc_b[1]

    acc_d, _ = get_path_and_bounds(acc_root, Identity.translate(dx, dy))
    adv = int(base_root.attrib["data-advance"])
    return f"{base_d} {acc_d}".strip(), adv


def write_svg(out_path: Path, gn: str, cp: int, advance: int, d: str, source: str):
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max(advance, 100)} {VEGUR_UPM}" '
        f'data-glyph="{gn}" data-unicode="U+{cp:04X}" data-advance="{advance}" '
        f'data-upm="{VEGUR_UPM}" data-baseline="{VEGUR_BASELINE}" data-source="{source}">\n'
        f'  <path d="{d}" fill="currentColor"/>\n'
        f'</svg>\n'
    )
    out_path.write_text(svg, encoding="utf-8")


def main():
    scale_upper = 688.0 / 740.0
    scale_lower = 478.0 / 520.0

    for style in ("Regular", "Bold"):
        r159_map = load_svg_dir(SVG_ROOT / "route159" / style)
        vegur_dir = SVG_ROOT / "vegur" / style
        vegur_map = load_svg_dir(vegur_dir)

        composed = 0
        fallback = 0
        for cp, (_, r_root) in sorted(r159_map.items()):
            if cp in vegur_map:
                continue
            gn = r_root.attrib["data-glyph"]
            res = try_compose_from_vegur(cp, vegur_map)
            if res is not None:
                d, adv = res
                write_svg(vegur_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"vegur-composed/{style}")
                composed += 1
            else:
                s = scale_lower if chr(cp).islower() else scale_upper
                d, _ = get_path_and_bounds(r_root, Identity.scale(s, s))
                adv = round(int(r_root.attrib["data-advance"]) * s)
                write_svg(vegur_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"route159-scaled/{style}")
                fallback += 1

        final_count = len(load_svg_dir(vegur_dir))
        print(
            f"Extended svg/vegur/{style}: {final_count}/{len(r159_map)} glyphs "
            f"(+{composed} composed from Vegur, +{fallback} scaled from Route 159)"
        )


if __name__ == "__main__":
    main()
