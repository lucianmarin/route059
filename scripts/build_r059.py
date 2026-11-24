#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["fonttools"]
# ///
"""Step 4b: Build Route 059 (limited) and Route 059 Extended (monospace) OTF fonts from SVGs."""

import xml.etree.ElementTree as ET
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.svgLib.path import SVGPath
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Identity

ROOT = Path(__file__).resolve().parent.parent
SVG_ROOT = ROOT / "svg"
DIST = ROOT / "dist"

VARIANTS = [
    ("route059", "Route 059", "Route059", "R059"),
    ("route059-ext", "Route 059 Extended", "Route059Ext", "R059E"),
]

STYLES = [
    ("Regular", "Regular", False, False),
    ("Bold", "Bold", True, False),
    ("Italic", "Italic", False, True),
    ("BoldItalic", "Bold Italic", True, True),
]

UPM = 2048
ADVANCE = 1233
BASELINE = 1600


def build_style(
    svg_family: str,
    family_name: str,
    ps_prefix: str,
    uid_prefix: str,
    style_key: str,
    style_label: str,
    is_bold: bool,
    is_italic: bool,
) -> Path:
    svg_dir = SVG_ROOT / svg_family / style_key
    svg_files = sorted(svg_dir.glob("*.svg"))
    if not svg_files:
        raise FileNotFoundError(f"No SVGs found in {svg_dir}; run scripts/reshape_r059.py first.")

    glyph_order = [".notdef"]
    cmap = {}
    charstrings = {}
    metrics = {}

    notdef_pen = T2CharStringPen(ADVANCE, None)
    notdef_pen.moveTo((120, 0))
    notdef_pen.lineTo((120, 1493))
    notdef_pen.lineTo((1113, 1493))
    notdef_pen.lineTo((1113, 0))
    notdef_pen.closePath()
    notdef_pen.moveTo((240, 120))
    notdef_pen.lineTo((993, 120))
    notdef_pen.lineTo((993, 1373))
    notdef_pen.lineTo((240, 1373))
    notdef_pen.closePath()
    charstrings[".notdef"] = notdef_pen.getCharString()
    metrics[".notdef"] = (ADVANCE, 120)

    unflip = Identity.translate(0, BASELINE).scale(1, -1)

    for svg_path in svg_files:
        root = ET.parse(svg_path).getroot()
        gn = root.attrib["data-glyph"]
        cp_str = root.attrib.get("data-unicode", "")
        advance = int(root.attrib["data-advance"])
        cp = int(cp_str[2:], 16) if cp_str.startswith("U+") else None

        if gn in charstrings:
            gn = f"uni{cp:04X}" if cp is not None else f"{gn}_dup"
            if gn in charstrings:
                continue

        glyph_order.append(gn)
        if cp is not None:
            cmap[cp] = gn

        path_elem = root.find("{http://www.w3.org/2000/svg}path")
        d = path_elem.attrib.get("d", "").strip() if path_elem is not None else ""

        t2_pen = T2CharStringPen(advance, None)
        bp = BoundsPen(None)
        if d:
            svg_obj = SVGPath.fromstring(
                f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>'
            )
            svg_obj.draw(TransformPen(t2_pen, unflip))
            svg_obj.draw(TransformPen(bp, unflip))

        lsb = round(bp.bounds[0]) if bp.bounds else 0
        charstrings[gn] = t2_pen.getCharString()
        metrics[gn] = (advance, lsb)

    ps_name = f"{ps_prefix}-{style_key}"
    full_name = f"{family_name} {style_label}" if style_label != "Regular" else family_name

    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)
    fb.setupCFF(
        psName=ps_name,
        fontInfo={"FullName": full_name, "FamilyName": family_name},
        charStringsDict=charstrings,
        privateDict={},
    )
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=1901, descent=-483, lineGap=0)
    fb.setupNameTable(
        {
            "familyName": family_name,
            "styleName": style_label,
            "uniqueFontIdentifier": f"1.000;{uid_prefix};{ps_name}",
            "fullName": full_name,
            "version": "Version 1.000",
            "psName": ps_name,
        }
    )

    fs_selection = 0
    mac_style = 0
    if is_bold:
        fs_selection |= 1 << 5
        mac_style |= 1 << 0
    if is_italic:
        fs_selection |= 1 << 0
        mac_style |= 1 << 1
    if not is_bold and not is_italic:
        fs_selection |= 1 << 6

    fb.setupHead(unitsPerEm=UPM, macStyle=mac_style)
    fb.setupOS2(
        sTypoAscender=1556,
        sTypoDescender=-492,
        sTypoLineGap=410,
        usWinAscent=1901,
        usWinDescent=483,
        sxHeight=1120,
        sCapHeight=1493,
        usWeightClass=700 if is_bold else 400,
        fsSelection=fs_selection,
        xAvgCharWidth=ADVANCE,
    )
    fb.font["OS/2"].panose.bProportion = 9  # Monospaced
    fb.setupPost(
        isFixedPitch=1,
        italicAngle=-12.0 if is_italic else 0.0,
    )

    DIST.mkdir(parents=True, exist_ok=True)
    out_path = DIST / f"{ps_name}.otf"
    fb.save(out_path)
    return out_path


def main():
    for svg_family, family_name, ps_prefix, uid_prefix in VARIANTS:
        for style_key, style_label, is_bold, is_italic in STYLES:
            out = build_style(svg_family, family_name, ps_prefix, uid_prefix, style_key, style_label, is_bold, is_italic)
            print(f"Built {out.name} from svg/{svg_family}/{style_key}/")


if __name__ == "__main__":
    main()
