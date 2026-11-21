#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["fonttools"]
# ///
"""Step 5: Build 1000x857 pure-vector specimen SVGs from sample.txt and actual letter SVGs."""

import sys
from pathlib import Path
from fontTools.svgLib.path import SVGPath
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Identity

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morph_svg import load_svg_dir

ROOT = Path(__file__).resolve().parent.parent
SVG_ROOT = ROOT / "svg"
SAMPLE_FILE = ROOT / "sample.txt"


def text_to_path_from_svgs(svg_map: dict, text: str, x: float, baseline_y: float, size: float) -> tuple[str, float]:
    """Compose `text` directly from individual letter SVGs in `svg_map`."""
    cmds = []
    cur_x = x
    for ch in text:
        entry = svg_map.get(ord(ch))
        if entry is None:
            continue
        _, root = entry
        upm = float(root.attrib.get("data-upm", "1000"))
        src_baseline = float(root.attrib.get("data-baseline", "800"))
        advance = float(root.attrib.get("data-advance", "500"))
        scale = size / upm

        path_elem = root.find("{http://www.w3.org/2000/svg}path")
        d = path_elem.attrib.get("d", "").strip() if path_elem is not None else ""
        if d:
            pen = SVGPathPen(None)
            # Letter SVGs are already Y-down with baseline at y=src_baseline
            t = Identity.translate(cur_x, baseline_y).scale(scale, scale).translate(0, -src_baseline)
            SVGPath.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>').draw(
                TransformPen(pen, t)
            )
            c = pen.getCommands()
            if c:
                cmds.append(c)
        cur_x += advance * scale
    return " ".join(cmds), cur_x


def build_specimen(out_path: Path, svg_family_dir: Path, display_name: str, sample_lines: list[str], size_scale: float = 1.0):
    """Build a 1000x857 specimen SVG from `sample.txt` lines using `svg/<family>/<Style>/*.svg`."""
    maps = {
        style: load_svg_dir(svg_family_dir / style)
        for style in ("Regular", "Bold", "Italic", "BoldItalic")
    }
    lines = [line.replace("{NAME}", display_name) for line in sample_lines]
    if " / " in lines[4]:
        left5, right5 = lines[4].split(" / ", 1)
        runs5 = [("Italic", 54 * size_scale, left5 + " / "), ("BoldItalic", 54 * size_scale, right5)]
    else:
        runs5 = [("Italic", 54 * size_scale, lines[4])]

    layout = [
        (46,  [("Regular",    46 * size_scale, lines[0])]),
        (242, [("BoldItalic", 230 * size_scale, lines[1])]),
        (318, [("Bold",       32 * size_scale, lines[2])]),
        (465, [("Italic",     138 * size_scale, lines[3])]),
        (565, runs5),
        (748, [("Regular",    185 * size_scale, lines[5])]),
        (844, [("Bold",       82 * size_scale, lines[6])]),
    ]

    all_cmds = []
    for baseline_y, runs in layout:
        cur_x = 12.0
        for style, size, text in runs:
            c, cur_x = text_to_path_from_svgs(maps[style], text, cur_x, baseline_y, size)
            if c:
                all_cmds.append(c)

    d = " ".join(all_cmds)
    svg = (
        '<svg height="857" viewBox="0 0 1000 857" width="1000" '
        'xmlns="http://www.w3.org/2000/svg">\n'
        f'  <path d="{d}" fill="currentColor"/>\n'
        '</svg>\n'
    )
    out_path.write_text(svg, encoding="utf-8")
    print(f"Generated {out_path.name} from {svg_family_dir.relative_to(ROOT)}/ ({out_path.stat().st_size // 1024} KB)")


def main():
    sample_lines = [line.rstrip("\n") for line in SAMPLE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    build_specimen(ROOT / "route138-repr.svg", SVG_ROOT / "route138", "Route 138", sample_lines, size_scale=1.0)
    build_specimen(ROOT / "route038-repr.svg", SVG_ROOT / "route038", "Route 038", sample_lines, size_scale=0.82)


if __name__ == "__main__":
    main()
