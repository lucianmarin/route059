#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Step 1: Export source SVGs (Route 159, Hack)"
"$SCRIPT_DIR/export_sources_svg.py"

echo "==> Step 3a: Extend Route 159 SVGs to match Hack glyph set"
"$SCRIPT_DIR/extend_route159.py"

echo "==> Step 3b: Morph Hack with Route 159 -> Route 059 SVGs"
"$SCRIPT_DIR/reshape_r059.py"

echo "==> Step 4b: Build Route 038 OTFs"
"$SCRIPT_DIR/build_r059.py"

echo "==> Step 5: Build specimen SVGs (route059-repr.svg)"
"$SCRIPT_DIR/build_repr_svg.py"

echo "==> Pipeline complete."
