#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Step 1: Export source SVGs (Route 159, Vegur, Hack)"
"$SCRIPT_DIR/export_sources_svg.py"

echo "==> Step 2a: Extend Vegur SVGs to match Route 159 glyph set"
"$SCRIPT_DIR/extend_vegur.py"

echo "==> Step 2b: Morph Route 159 with Vegur -> Route 138 SVGs"
"$SCRIPT_DIR/reshape_r138.py"

echo "==> Step 3a: Extend Route 138 SVGs to match Hack glyph set"
"$SCRIPT_DIR/extend_route138.py"

echo "==> Step 3b: Morph Hack with Route 138 -> Route 038 SVGs"
"$SCRIPT_DIR/reshape_r038.py"

echo "==> Step 4a: Build Route 138 OTFs"
"$SCRIPT_DIR/build_r138.py"

echo "==> Step 4b: Build Route 038 OTFs"
"$SCRIPT_DIR/build_r038.py"

echo "==> Step 5: Build specimen SVGs (route138-repr.svg, route038-repr.svg)"
"$SCRIPT_DIR/build_repr_svg.py"

echo "==> Pipeline complete."
