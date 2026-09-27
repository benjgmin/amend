#!/usr/bin/env bash
# Render the promo end to end:
#   picture    -> headless Chromium, frame-by-frame, motion-blurred (render.mjs)
#   soundtrack -> numpy synth on the same beat grid (audio/synth.py)
#   mux        -> H.264 High / AAC, BT.709, faststart (amend-promo.mp4)
# dataset/ is prebuilt; see README.md to refresh it from history/.
set -euo pipefail
cd "$(dirname "$0")"

npm install --silent --no-audit --no-fund
mkdir -p build

python3 audio/synth.py build/soundtrack.wav
node render.mjs video --jobs "${JOBS:-3}" --out build/master.mkv

ffmpeg -hide_banner -loglevel warning -y \
  -i build/master.mkv -i build/soundtrack.wav \
  -vf "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p" \
  -c:v libx264 -preset slow -crf "${CRF:-20}" -profile:v high -level 4.2 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  -c:a aac -b:a 256k -ar 48000 \
  -movflags +faststart -shortest \
  amend-promo.mp4

echo "wrote amend-promo.mp4"
