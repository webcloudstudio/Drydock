#!/usr/bin/env bash
# Render the Drydock announcement video.
#
#   ./run.sh                 full render: new voice, video, music option 1
#   ./run.sh --no-voice      reuse the existing voice + marks (faster)
#   ./run.sh --stills        review PNGs only (seconds)
#   ./run.sh --music 2       override the music bed
#
# Any arguments given are passed through to make_release_video.py; the defaults
# below only apply when not overridden.
set -euo pipefail

cd "$(dirname "$0")"

args=("$@")
case " ${args[*]} " in
    *" --music "*) ;;
    *) args+=(--music 1) ;;
esac

uv run --python 3.12 \
    --with edge-tts --with imageio-ffmpeg --with numpy --with pillow \
    python make_release_video.py "${args[@]}"
