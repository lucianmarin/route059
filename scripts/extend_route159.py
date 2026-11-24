#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["fonttools"]
# ///
"""Extend svg/route159/ to match the exact glyph set of svg/hack/ before morphing Route 059."""

import math
import sys
import unicodedata
from pathlib import Path
from fontTools.svgLib.path import SVGPath
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Identity

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morph_svg import load_svg_dir, style_transfer_extend_bezier

ROOT = Path(__file__).resolve().parent.parent
SVG_ROOT = ROOT / "svg"

UPRIGHT_STYLES = ["Regular", "Bold"]
ITALIC_PAIRS = [("Regular", "Italic"), ("Bold", "BoldItalic")]
ITALIC_ANGLE = 12.0
ITALIC_PIVOT_Y = 260.0
UPM = 1000
BASELINE = 800

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


def transform_svg_path(root, font_transform=Identity):
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


def try_compose_from_r138(cp: int, r138_map: dict):
    """Compose a precomposed Latin glyph from Route 138's own base + accent if available."""
    decomp = unicodedata.decomposition(chr(cp))
    if not decomp or decomp.startswith("<"):
        return None
    parts = [int(x, 16) for x in decomp.split()]
    if len(parts) != 2:
        return None
    base_cp, comb_cp = parts
    if base_cp == ord("i") and 0x0131 in r138_map:
        base_cp = 0x0131
    accent_cp = COMBINING_TO_SPACING.get(comb_cp, comb_cp)
    if base_cp not in r138_map or accent_cp not in r138_map:
        return None

    _, base_root = r138_map[base_cp]
    _, acc_root = r138_map[accent_cp]
    base_d, base_b = transform_svg_path(base_root)
    acc_d_raw, acc_b = transform_svg_path(acc_root)
    if not base_d or not acc_d_raw or not base_b or not acc_b:
        return None

    dx = ((base_b[0] + base_b[2]) / 2.0) - ((acc_b[0] + acc_b[2]) / 2.0)
    if comb_cp in (0x0327, 0x0328):
        dy = base_b[1] - acc_b[3] + 20.0
    else:
        dy = (base_b[3] + 45.0) - acc_b[1]

    acc_d, _ = transform_svg_path(acc_root, Identity.translate(dx, dy))
    adv = int(base_root.attrib["data-advance"])
    return f"{base_d} {acc_d}".strip(), adv


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
    hack_scale = 740.0 / 1493.0
    hack_t = Identity.scale(hack_scale, hack_scale)

    for style_key in UPRIGHT_STYLES:
        r138_dir = SVG_ROOT / "route159" / style_key
        r138_map = load_svg_dir(r138_dir)
        hack_map = load_svg_dir(SVG_ROOT / "hack" / style_key)

        composed = 0
        scaled = 0
        for cp, (_, h_root) in sorted(hack_map.items()):
            if cp in r138_map:
                continue
            gn = h_root.attrib["data-glyph"]
            res = try_compose_from_r138(cp, r138_map)
            if res is not None:
                d, adv = res
                write_svg(r138_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"r159-composed/{style_key}")
                composed += 1
            else:
                is_box = (0x2500 <= cp <= 0x259F) or (0xE0A0 <= cp <= 0xE0D4)
                sx = 1.0 if is_box else 0.94
                tension = 1.0 if is_box else 1.04
                _, bounds = style_transfer_extend_bezier(h_root, hack_t, baseline=BASELINE, sx=sx, tension=tension)
                if bounds:
                    ink_w = bounds[2] - bounds[0]
                    sb = 0 if is_box else 45
                    adv = round(ink_w + 2 * sb)
                    dx = sb - bounds[0]
                    d, _ = style_transfer_extend_bezier(
                        h_root,
                        Identity.translate(dx, 0).scale(hack_scale, hack_scale),
                        baseline=BASELINE,
                        sx=sx,
                        tension=tension,
                    )
                else:
                    adv = round(int(h_root.attrib["data-advance"]) * hack_scale)
                    d = ""
                write_svg(r138_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"hack-style-transferred/{style_key}")
                scaled += 1

        final_count = len(load_svg_dir(r138_dir))
        print(
            f"Extended svg/route159/{style_key}: {final_count} glyphs "
            f"(covers all {len(hack_map)} Hack glyphs: +{composed} composed from R138, +{scaled} scaled from Hack)"
        )

    # Mirror extended upright glyphs into Italic / BoldItalic via oblique shear
    shear_t = (
        Identity.translate(0, ITALIC_PIVOT_Y)
        .skew(math.radians(ITALIC_ANGLE), 0)
        .translate(0, -ITALIC_PIVOT_Y)
    )
    for src_style, dst_style in ITALIC_PAIRS:
        src_map = load_svg_dir(SVG_ROOT / "route159" / src_style)
        dst_dir = SVG_ROOT / "route159" / dst_style
        dst_map = load_svg_dir(dst_dir)
        added = 0
        for cp, (_, root) in sorted(src_map.items()):
            if cp in dst_map:
                continue
            gn = root.attrib["data-glyph"]
            adv = int(root.attrib["data-advance"])
            d, _ = transform_svg_path(root, shear_t)
            write_svg(dst_dir / f"U+{cp:04X}_{gn}.svg", gn, cp, adv, d, f"oblique({src_style},{ITALIC_ANGLE}deg)")
            added += 1
        print(f"Extended svg/route159/{dst_style}: {len(dst_map) + added} glyphs (+{added} oblique from {src_style})")


if __name__ == "__main__":
    main()
