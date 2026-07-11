#!/usr/bin/env python3
"""Generate an audio track from the Drydock presentation talking points.

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
DEFAULT_INPUT = ROOT / "talking_points.md"
DEFAULT_OUTPUT = ROOT / "audio" / "talking_points_ava_multilingual.mp3"
DEFAULT_VOICE = "en-US-AvaMultilingualNeural"
SAMPLE_RATE = 24000
SENTENCE_GAP = 0.45
BLOCK_GAP = 0.9


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    if imageio_ffmpeg is not None:
        return imageio_ffmpeg.get_ffmpeg_exe()
    raise RuntimeError("ffmpeg was not found. Install ffmpeg or run with --with imageio-ffmpeg.")


def markdown_to_spoken_text(markdown: str) -> str:
    """Convert cue-card Markdown into plain text that sounds natural aloud."""
    lines: list[str] = []
    in_fence = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            lines.append("")
            continue
        if line.startswith("# Drydock"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^\d+\.\s*", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"\*(.*?)\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", line)
        line = line.replace("—", ". ")
        line = line.replace("→", " to ")
        line = line.replace(" + ", " plus ")
        line = line.replace("&", " and ")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    text = "\n\n".join(line for line in lines if line)
    text = re.sub(r"\bvs\.", "versus", text, flags=re.IGNORECASE)
    text = text.replace("Q&A", "Q and A")
    text = text.replace("SDD", "S D D")
    text = text.replace("CLI", "C L I")
    text = text.replace("TDD", "T D D")
    text = text.replace("LLM", "L L M")
    return text.strip()


def speech_segments(text: str) -> list[tuple[str, str | float]]:
    segments: list[tuple[str, str | float]] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for paragraph in paragraphs:
        for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", paragraph)):
            sentence = sentence.strip()
            if not sentence:
                continue
            if index:
                segments.append(("gap", SENTENCE_GAP))
            segments.append(("speak", sentence))
        segments.append(("gap", BLOCK_GAP))
    while segments and segments[-1][0] == "gap":
        segments.pop()
    return segments


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
    text: str,
    output: Path,
    voice: str,
    rate: str,
    volume: str,
    keep_text: bool,
) -> None:
    import edge_tts

    output.parent.mkdir(parents=True, exist_ok=True)
    if keep_text:
        output.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")

    exe = ffmpeg_exe()
    tmp = output.parent / "_talking_points_segments"
    tmp.mkdir(exist_ok=True)
    raw_pieces: list[bytes] = []
    try:
        for index, (kind, value) in enumerate(speech_segments(text)):
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
        description="Generate MP3 narration from docs/presentation/talking_points.md."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--volume", default="+0%")
    parser.add_argument(
        "--keep-text",
        action="store_true",
        help="also write the normalized narration text next to the MP3",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    markdown = args.input.read_text(encoding="utf-8")
    text = markdown_to_spoken_text(markdown)
    if not text:
        raise RuntimeError(f"no speakable text found in {args.input}")
    asyncio.run(
        synthesize_audio(
            text=text,
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
