#!/usr/bin/env bash
# Vendor the PDF.js build the reader uses. Pinned so the viewer cannot change
# under us, and served same-origin because faa.gov sends no CORS headers.
set -euo pipefail
VERSION="4.10.38"
DEST="$(cd "$(dirname "$0")/.." && pwd)/vendor/pdfjs"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -sSfL --max-time 300 \
  "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-${VERSION}.tgz" -o "$TMP/pdfjs.tgz"
tar -xzf "$TMP/pdfjs.tgz" -C "$TMP"

rm -rf "$DEST"
mkdir -p "$DEST/cmaps" "$DEST/standard_fonts"
cp "$TMP/package/build/pdf.min.mjs"        "$DEST/pdf.min.mjs"
cp "$TMP/package/build/pdf.worker.min.mjs" "$DEST/pdf.worker.min.mjs"
cp -r "$TMP/package/cmaps/."               "$DEST/cmaps/"
cp -r "$TMP/package/standard_fonts/."      "$DEST/standard_fonts/"
echo "$VERSION" > "$DEST/VERSION"
echo "vendored pdf.js $VERSION -> $DEST"
du -sh "$DEST"
