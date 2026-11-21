# Route 138 & Route 038

Font family specifications and design tracking for **Route 138** (proportional sans-serif) and **Route 038** (monospace).

## Inspiration Sources (`inspiration/`)

| Font | Format | UPM | Glyphs (cmap) | Styles Available | x-Height | Cap Height | Ascent / Descent (`hhea`) |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| **Route 159** | OTF (CFF) | 1000 | 346 (334) | UltraLight, Light, Regular, SemiBold, Bold, Heavy (+ Italics) | 520 | 740 | 970 / -230 |
| **Vegur** | OTF / SFD | 1000 | 215 (214) | Light, Regular, Bold | 478 | 688 | 965 / -235 |
| **Hack** | TTF | 2048 | 1573 (1548) | Regular, Bold, Italic, BoldItalic | 1120 (547 @ 1000) | 1493 (729 @ 1000) | 1901 / -483 |

---

## Route 138 (Sans-Serif)

- **Role:** Proportional sans-serif typeface.
- **Primary inspiration:** Route 159.
- **Distinctive character:** Incorporates the best letter shapes from **Vegur** (the earlier predecessor to Route 159) so Route 138 stands apart from Route 159 while retaining its humanist/geometric clarity.
- **UPM:** 1000 (matching Route 159 & Vegur)
- **Vertical metrics (target, based on Route 159):**
  - `hhea` Ascent / Descent / LineGap: `970` / `-230` / `0`
  - `OS/2` TypoAscender / TypoDescender / TypoLineGap: `770` / `-230` / `100`
  - `OS/2` WinAscent / WinDescent: `970` / `230`
  - Cap Height: `740`
  - x-Height: `520`
- **Glyph set:** 565 glyphs (553 Unicode codepoints) — Route 159's 346-glyph core plus Latin-1/Extended-A completions, print punctuation, currency, fractions, superscripts/subscripts, core math operators, and core arrows from Hack.
- **Styles:** Regular, Bold, Italic, Bold Italic (4 styles).
- **Output format:** OTF (CFF) in `dist/`.
- **Vegur-inspired letterforms adopted** (scaled/harmonized to Route 159's metrics and italic angle):
  - `g` (single-story)
  - `J` (descending tail)
  - `Q` (curved tail)
  - `R` (curved leg)
  - `K`, `k` (humanist join)
  - `a` (softer bowl)
  - `t` (curved foot)
  - `y` (curved tail)
  - `1`, `4` (humanist numerals)
  - `&` (humanist ampersand)
  - `?` (fluid curve)

---

## Route 038 (Monospace)

- **Role:** Code-editor-ready monospace companion to Route 138.
- **Design process (Hack-first):** Built directly on **Hack**'s proven monospace foundation (preserving Hack's stroke weight, rhythm, `0O1lI` legibility, punctuation, and terminal glyphs), subsetted to ~720 usable Latin/coding/terminal glyphs, and infused with **Route 138 / Vegur's signature humanist letterforms** (`g`, `a`, `k`, `t`, `y`, `J`, `Q`, `R`, `K`, `4`, `&`, `?`) scaled to Hack's exact x-height (`1120`) and cap-height (`1493`).
- **Exact metric compatibility with Hack:** Matches Hack's proven code-editor cell width and vertical metrics:
  - **UPM:** `2048` (matching Hack exactly so advance width `1233` is an exact integer without rounding drift)
  - **Advance width (all glyphs):** `1233`
  - **Cap Height:** `1493`
  - **x-Height:** `1120`
  - **`hhea` Ascent / Descent / LineGap:** `1901` / `-483` / `0`
  - **`OS/2` TypoAscender / TypoDescender / TypoLineGap:** `1556` / `-492` / `410`
  - **`OS/2` WinAscent / WinDescent:** `1901` / `483`
- **Glyph set:** 732 glyphs (720 Unicode codepoints) — all 565 Route 138 glyphs plus terminal-only Box Drawing (128), Block Elements (32), and Powerline PUA (7) glyphs pulled 1:1 from Hack.
- **Styles:** Regular, Bold, Italic, Bold Italic (4 styles, matching Hack).
- **Output format:** OTF (CFF) in `dist/`.

---

## Build Pipeline (SVG-First)

Every glyph is stored as an editable `.svg` file with metric metadata (`data-glyph`, `data-unicode`, `data-advance`, `data-upm`, `data-baseline`), so you can reshape any Bézier curve programmatically or in a vector editor and recompile directly to OTF.

### Step 1: Export Inspiration Sources to Raw SVGs
```bash
./scripts/export_sources_svg.py
```
Exports raw SVGs into:
- `svg/route159/{Regular,Bold,Italic,BoldItalic}/` (332–334 glyphs)
- `svg/vegur/{Regular,Bold}/` (214 glyphs)
- `svg/hack/{Regular,Bold,Italic,BoldItalic}/` (1,157–1,234 Latin + symbol/terminal glyphs; non-Latin scripts excluded)

### Step 2: Reshape & Build Route 138 (Sans) from SVGs
```bash
./scripts/reshape_r138.py      # Reshapes svg/route159/ + svg/vegur/ + svg/hack/ -> svg/route138/
./scripts/build_r138.py        # Compiles svg/route138/ -> dist/Route138-*.otf
```

### Step 3: Reshape & Build Route 038 (Monospace) from SVGs
```bash
./scripts/reshape_r038.py      # Reshapes svg/hack/ using svg/route138/ -> svg/route038/
./scripts/build_r038.py        # Compiles svg/route038/ -> dist/Route038-*.otf
```

Outputs are written to `dist/`:
- `Route138-Regular.otf`, `Route138-Bold.otf`, `Route138-Italic.otf`, `Route138-BoldItalic.otf`
- `Route038-Regular.otf`, `Route038-Bold.otf`, `Route038-Italic.otf`, `Route038-BoldItalic.otf`

---

## Status

- [x] Inspect inspiration fonts and record metrics.
- [x] Compare Route 159 vs. Vegur glyphs and select Vegur letterforms to adopt.
- [x] Finalize target styles (4 styles each) and output format (OTF).
- [x] Build Route 138 & Route 038 OTFs via `scripts/build.py` and visually verify.
