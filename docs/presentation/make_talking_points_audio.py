#!/usr/bin/env python3
"""Generate an audio track from the Drydock presentation teleprompter script.

This uses the same free Edge TTS voice selected by docs/release-video:
en-US-AvaMultilingualNeural. It does not use API keys or paid generation.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import subprocess
from array import array
from pathlib import Path

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - exercised when system ffmpeg exists
    imageio_ffmpeg = None


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "teleprompter.md"
DEFAULT_OUTPUT = ROOT / "audio" / "teleprompter_ava_multilingual.mp3"
DEFAULT_VOICE = "en-US-AvaMultilingualNeural"
SAMPLE_RATE = 24000
LINE_GAP = 0.35
PAUSE_GAP = 0.35


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    if imageio_ffmpeg is not None:
        return imageio_ffmpeg.get_ffmpeg_exe()
    raise RuntimeError("ffmpeg was not found. Install ffmpeg or run with --with imageio-ffmpeg.")


def teleprompter_segments(markdown: str) -> list[tuple[str, str | float]]:
    """Apply the teleprompter cue contract to Markdown lines.

    Headers, separators, and ADVANCE markers are stage directions. Non-empty
    non-cue lines are spoken as written. Each new spoken line gets a breath.
    """
    segments: list[tuple[str, str | float]] = []
    in_fence = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.startswith("#"):
            continue
        if line == "---":
            continue
        if line.startswith(">> ADVANCE"):
            continue
        if re.fullmatch(r"\(\s*pause\s*\)", line, flags=re.IGNORECASE):
            if segments and segments[-1][0] == "gap":
                previous_gap = float(segments[-1][1])
                segments[-1] = ("gap", previous_gap + PAUSE_GAP)
            else:
                segments.append(("gap", PAUSE_GAP))
            continue
        segments.append(("speak", line))
        segments.append(("gap", LINE_GAP))
    while segments and segments[-1][0] == "gap":
        segments.pop()
    return segments


def spoken_text(segments: list[tuple[str, str | float]]) -> str:
    lines: list[str] = []
    for kind, value in segments:
        if kind == "speak":
            lines.append(str(value))
        elif value:
            lines.append(f"[pause {float(value):.2f}]")
    return "\n".join(lines)


def trim_silence(raw_audio: bytes, threshold: int = 260) -> bytes:
    samples = array("h")
    samples.frombytes(raw_audio)
    loud = [i for i, sample in enumerate(samples) if abs(sample) > threshold]
    if not loud:
        return raw_audio
    start = max(0, loud[0] - int(0.04 * SAMPLE_RATE))
    stop = min(len(samples), loud[-1] + int(0.10 * SAMPLE_RATE))
    return samples[start:stop].tobytes()


async def synthesize_audio(
    *,
    segments: list[tuple[str, str | float]],
    output: Path,
    voice: str,
    rate: str,
    volume: str,
    keep_text: bool,
) -> None:
    import edge_tts

    output.parent.mkdir(parents=True, exist_ok=True)
    if keep_text:
        output.with_suffix(".txt").write_text(spoken_text(segments) + "\n", encoding="utf-8")

    exe = ffmpeg_exe()
    tmp = output.parent / "_talking_points_segments"
    tmp.mkdir(exist_ok=True)
    raw_pieces: list[bytes] = []
    try:
        for index, (kind, value) in enumerate(segments):
            if kind == "gap":
                raw_pieces.append(b"\0\0" * int(SAMPLE_RATE * float(value)))
                continue
            segment_mp3 = tmp / f"segment_{index:03d}.mp3"
            communicator = edge_tts.Communicate(str(value), voice=voice, rate=rate, volume=volume)
            await communicator.save(str(segment_mp3))
            decoded = subprocess.run(
                [
                    exe,
                    "-i",
                    str(segment_mp3),
                    "-f",
                    "s16le",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-ac",
                    "1",
                    "-",
                ],
                capture_output=True,
                check=True,
            )
            raw_pieces.append(trim_silence(decoded.stdout))
        subprocess.run(
            [
                exe,
                "-y",
                "-f",
                "s16le",
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                "-i",
                "-",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "96k",
                str(output),
            ],
            input=b"".join(raw_pieces),
            check=True,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate MP3 narration from docs/presentation/teleprompter.md."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--volume", default="+0%")
    parser.add_argument("--line-gap", type=float, default=LINE_GAP)
    parser.add_argument("--pause", type=float, default=PAUSE_GAP)
    parser.add_argument(
        "--print-text",
        action="store_true",
        help="print the exact spoken text without generating audio",
    )
    parser.add_argument(
        "--keep-text",
        action="store_true",
        help="also write the exact spoken text next to the MP3",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    global LINE_GAP, PAUSE_GAP
    LINE_GAP = args.line_gap
    PAUSE_GAP = args.pause
    markdown = args.input.read_text(encoding="utf-8")
    segments = teleprompter_segments(markdown)
    if not any(kind == "speak" for kind, _ in segments):
        raise RuntimeError(f"no speakable text found in {args.input}")
    if args.print_text:
        print(spoken_text(segments))
        return 0
    asyncio.run(
        synthesize_audio(
            segments=segments,
            output=args.output,
            voice=args.voice,
            rate=args.rate,
            volume=args.volume,
            keep_text=args.keep_text,
        )
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
