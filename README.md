# Route 159 Extended & Route 059

![repr](route059-repr.svg)

Font family specifications and build pipeline for **Route 159 Extended** (proportional sans-serif) and **Route 059** (monospace, both limited and extended glyph sets).

## Inspiration Sources (`inspiration/`)

| Font | Format | UPM | Glyphs (cmap) | Styles Available | x-Height | Cap Height | Ascent / Descent (`hhea`) |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| **Route 159** | OTF (CFF) | 1000 | 346 (334) | Regular, Bold | 520 | 740 | 970 / -230 |
| **Hack** | TTF | 2048 | 1573 (1548) | Regular, Bold | 1120 (547 @ 1000) | 1493 (729 @ 1000) | 1901 / -483 |

---

## Route 159 Extended (Sans-Serif)

- **Role:** Extended proportional sans-serif based on **Route 159**, expanded to cover Hack's Latin + symbol glyph set.
- **UPM:** 1000 (matching Route 159)
- **Vertical metrics (matching Route 159):**
  - `hhea` Ascent / Descent / LineGap: `970` / `-230` / `0`
  - `OS/2` TypoAscender / TypoDescender / TypoLineGap: `770` / `-230` / `100`
  - `OS/2` WinAscent / WinDescent: `970` / `230`
  - Cap Height: `740`
  - x-Height: `520`
- **Glyph set:** Route 159's original 334 Unicode glyphs plus accented Latin composed from Route 159's own base + accent glyphs and remaining symbols/terminal glyphs style-transferred from Hack.
- **Styles:** Regular, Bold, Italic, Bold Italic (4 styles; oblique `12°` derived from upright).
- **Output format:** OTF (CFF) in `dist/Route159Ext-*.otf`.

---

## Route 059 & Route 059 Extended (Monospace)

- **Role:** Code-editor-ready monospace companion to Route 159, built by morphing **Hack** with **Route 159** at `α = 0.45`.
- **Two glyph-set variants:**
  - **Route 059 (limited):** Limited to Route 159's original 334-glyph Unicode set (`dist/Route059-*.otf`).
  - **Route 059 Extended:** Covers Hack's full Latin + symbols + terminal glyph set, including Box Drawing, Block Elements, and Powerline PUA glyphs preserved 1:1 from Hack (`dist/Route059Ext-*.otf`).
- **Exact metric compatibility with Hack:**
  - **UPM:** `2048` (matching Hack exactly so advance width `1233` is an exact integer without rounding drift)
  - **Advance width (all glyphs):** `1233`
  - **Cap Height:** `1493`
  - **x-Height:** `1120`
  - **`hhea` Ascent / Descent / LineGap:** `1901` / `-483` / `0`
  - **`OS/2` TypoAscender / TypoDescender / TypoLineGap:** `1556` / `-492` / `410`
  - **`OS/2` WinAscent / WinDescent:** `1901` / `483`
- **Styles:** Regular, Bold, Italic, Bold Italic (4 styles; `12°` oblique derived from upright, keeping Box Drawing / Block Elements / Powerline upright).

---

## Morphing & Style-Transfer Algorithm (`scripts/morph_svg.py`)

Upright **Regular** and **Bold** native Bézier (`L`/`C`) outlines are morphed (`Hack + Route 159 → Route 059` at `α = 0.45`), then **Italic** and **Bold Italic** are derived afterward via a `12°` oblique shear pivoted at half x-height (`y = 260` for Route 159 Extended, `y = 560` for Route 059, keeping Box Drawing / Block Elements / Powerline glyphs upright).

Each glyph pair goes through the following stages:

1. **Native Bézier Extraction (`svg_to_bezier_contours`):** Parses source SVG paths directly into closed loops of cubic Bézier segments `(p0, p1, p2, p3)` (elevating `L` segments to exact 1/3–2/3 cubics and `Q` to exact cubics) with no polyline resampling.
2. **Automatic Topology-Mismatch Guard (`_max_chamfer_distance`):** Checks three criteria before morphing:
   - Mean unit-box normalized Chamfer distance across outer contours (`> 0.09`).
   - Relative inner-counter centroid shift (`> 0.14`).
   - **Hausdorff distance** (`> 0.22`) to catch local structural mismatches (e.g., spur-only `G` vs. crossbar `G`).
   - **Incompatible topologies** (e.g., `G`, Hack's serifed `I`/`i`/`l`/`1`, or fused monospace `@`) automatically route to **native `L`/`C` style transfer** (`style_transfer_bezier_contours`), which applies a smooth 2D proportion warp directly to the source's native Bézier control points while preserving exact `L`/`C` structure.
3. **Contour Pairing:** Contours are paired by `(outer/hole winding role, nearest centroid)` after horizontal center-alignment so multi-counter glyphs (`B`, `8`, `=`) never swap counters.
4. **Native Bézier-Segment Interpolation (`morph_bezier_contour`):**
   - Detects sharp corners directly from adjacent segment tangents (`_bezier_corners`) and aligns them via circular Needleman-Wunsch dynamic programming.
   - Slices matched spans at the exact union of their normalized arc-length breakpoints using de Casteljau subdivision (`_slice_cubic`), then linearly interpolates `(p0, p1, p2, p3)` directly.
   - Emits clean `L` commands for straight segments (`_seg_is_line`) and `C` commands for curves (`bezier_contours_to_svg_path`).
5. **Per-Contour Self-Intersection & Area Guard (`_bezier_contour_self_intersects`):** Verifies every morphed contour has zero strict self-intersections and preserves area (`0.60×–1.65×` source area); any failing glyph automatically falls back to `style_transfer_bezier_contours`.
6. **Native `L`/`C` Style Transfer for Glyph-Range Extension (`style_transfer_extend_bezier`):** When `extend_route159.py` extends missing non-decomposable glyphs (symbols, math, arrows), it applies horizontal proportion scaling (`sx`) and subtle cubic handle tension directly to Hack's native `L`/`C` control points (keeping Box Drawing, Block Elements, and Powerline glyphs untouched).

---

## Build Pipeline (SVG-First)

Run the entire 5-step pipeline with:
```bash
./scripts/pipeline.sh
```

1. **Step 1 (`export_sources_svg.py`):** Export upright `Regular` and `Bold` source SVGs from `inspiration/` into `svg/{route159,hack}/`.
2. **Step 2 (`extend_route159.py`):** Copy `svg/route159/` and extend it to cover 100% of `svg/hack/` into `svg/route159-ext/{Regular,Bold}/`, then derive `12°` oblique `Italic` and `BoldItalic`.
3. **Step 3 (`reshape_r059.py`):** Morph `Hack + Route 159` into both `svg/route059/` (limited to Route 159's original glyph set) and `svg/route059-ext/` (full Hack glyph set), then derive `12°` oblique `Italic` and `BoldItalic` (keeping Box Drawing, Block Elements, and Powerline upright).
4. **Step 4a / 4b (`build_r159_ext.py`, `build_r059.py`):** Compile SVGs directly to OTF (CFF) fonts in `dist/`.
5. **Step 5 (`build_repr_svg.py`):** Compose pure-vector specimen poster (`route059-repr.svg`) directly from `sample.txt` and the generated glyph SVGs.

Outputs are written to `dist/`:
- `Route159Ext-Regular.otf`, `Route159Ext-Bold.otf`, `Route159Ext-Italic.otf`, `Route159Ext-BoldItalic.otf`
- `Route059-Regular.otf`, `Route059-Bold.otf`, `Route059-Italic.otf`, `Route059-BoldItalic.otf`
- `Route059Ext-Regular.otf`, `Route059Ext-Bold.otf`, `Route059Ext-Italic.otf`, `Route059Ext-BoldItalic.otf`

---

## Status

- [x] Inspect inspiration fonts (`Route 159`, `Hack`) and record metrics.
- [x] Extend Route 159 to cover Hack's Latin + symbol glyph set.
- [x] Build Route 159 Extended, Route 059 (limited), and Route 059 Extended OTFs via `./scripts/pipeline.sh`.
