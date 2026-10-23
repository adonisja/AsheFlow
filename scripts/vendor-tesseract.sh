#!/usr/bin/env bash
# Copies the Tesseract engine into frontend/public/tesseract/ so the walker log
# can OCR a label with NO INTERNET.
#
# WHY. tesseract.js defaults workerPath/corePath/langPath to jsdelivr, so the
# first scan silently required a working connection — exactly what a walker in
# the field on a hotspot with no data does not have. Served from our own origin
# these load over the hotspot's local link instead.
#
# WHICH CORE. All three LSTM variants are copied, not one. The runtime probes
# the browser for SIMD support and picks among them, and which it lands on is
# not knowable up front: shipping only simd-lstm failed on a browser that
# supports RELAXED simd, with "failed to load
# tesseract-core-relaxedsimd-lstm.wasm.js". The non-LSTM variants are the legacy
# engine and are not selected, so they are skipped.
#
# The output is gitignored (22MB of wasm) — run this after a fresh `npm ci`.
# CI runs it before every frontend build (ADR-579), so deploys carry the engine.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC_JS="frontend/node_modules/tesseract.js/dist"
SRC_CORE="frontend/node_modules/tesseract.js-core"
DEST="frontend/public/tesseract"

[ -d "$SRC_CORE" ] || { echo "Run 'npm install' in frontend/ first."; exit 1; }

mkdir -p "$DEST"
cp "$SRC_JS/worker.min.js" "$DEST/"
cp "$SRC_CORE"/tesseract-core-lstm.wasm{,.js} "$DEST/"
cp "$SRC_CORE"/tesseract-core-simd-lstm.wasm{,.js} "$DEST/"
cp "$SRC_CORE"/tesseract-core-relaxedsimd-lstm.wasm{,.js} "$DEST/"

# Language data is NOT in node_modules — it ships separately and is the one
# piece that must be downloaded once, while you still have internet.
#
# PINNED by checksum (ADR-579). CI runs this on every deploy, so the download is
# a build input fetched from a public CDN: without the check, whatever that URL
# returns is shipped to every walker's phone. A mismatch fails the build.
LANG="$DEST/eng.traineddata.gz"
LANG_SHA256="45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91"
if [ ! -f "$LANG" ]; then
  echo "Downloading English language data…"
  curl -fsSL -o "$LANG" \
    "https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng@1.0.0/4.0.0_best_int/eng.traineddata.gz"
fi
GOT="$(shasum -a 256 "$LANG" | cut -d' ' -f1)"
if [ "$GOT" != "$LANG_SHA256" ]; then
  echo "eng.traineddata.gz checksum mismatch: got $GOT, expected $LANG_SHA256" >&2
  rm -f "$LANG"
  exit 1
fi

echo "Vendored $(du -sh "$DEST" | cut -f1) into $DEST"
