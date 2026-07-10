#!/usr/bin/env python3
"""Generate a Drydock announcement video from local assets.

This script intentionally avoids paid or API-key-backed services. It uses:
- Pillow for 2D animation frames
- edge-tts for a free neural narration voice
- generated WAV music beds
- imageio_ffmpeg's bundled ffmpeg binary for rendering
"""

from __future__ import annotations

import asyncio
import math
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
DOCS = ROOT.parent
LOGO = DOCS / "drydock_logo.png"
AUDIO = ROOT / "audio"
RENDERS = ROOT / "renders"

WIDTH = 1920
HEIGHT = 1080
FPS = 15
DURATION = 86.0

NAVY = (12, 25, 40)
BLUE = (30, 84, 140)
BLUE2 = (48, 122, 191)
GREEN = (27, 169, 111)
GREEN2 = (67, 210, 143)
AMBER = (238, 170, 53)
RED = (206, 78, 78)
INK = (26, 36, 48)
MUTED = (92, 108, 125)
PAPER = (249, 251, 252)
LINE = (198, 212, 224)
BG = (244, 248, 251)

VOICE_FALLBACK = """Meet Drydock: a complete delivery system for specification-driven developers.

Drydock works with larger specifications, including multi-file specs and material imported from other tools.

Start with drydock import: bring in specifications, notes, or existing project material.

Run drydock analyze, and Drydock proposes an Agile plan with features, stories, questions, blockers, and acceptance criteria.

Run drydock plan, and your specifications become governed Blueprints. Each Blueprint carries Test-Driven Development tests. Plan also builds the Manifest: a graph of stories, dependencies, stack rules, and build order.

You review and control the build in QuarterDeck.

Drydock also supports enterprise branding and stack rules, so applications keep consistent look, behavior, and documentation.

Run drydock build, and Drydock walks the graph block by block, verifying each story against its tests and producing working software.

Agile software never stops changing. Update the specification or add change tickets. drydock refit updates the Manifest so changes move through the normal build process.

Drydock is built on simple engineering truths: engineers decompose big problems; Agile and Test-Driven Development are proven practices; and a graph plus context compression makes specification-driven builds reproducible with your Sonnet or Codex subscription.

Drydock is free, MIT-licensed software, now in stable alpha.

Take it for a sail. Contributors wanted.

WebCloudStudio.com."""


@dataclass
class Scene:
    start: float
    end: float
    name: str

    def progress(self, t: float) -> float:
        if t <= self.start:
            return 0.0
        if t >= self.end:
            return 1.0
        return (t - self.start) / (self.end - self.start)


SCENES = [
    Scene(0, 5, "intro"),
    Scene(5, 17, "spec_in"),
    Scene(17, 26, "analyze"),
    Scene(26, 36, "plan"),
    Scene(36, 46, "manifest"),
    Scene(46, 54, "quarterdeck"),
    Scene(54, 61, "rigging"),
    Scene(61, 70, "build"),
    Scene(70, 78, "refit"),
    Scene(78, 82, "truths"),
    Scene(82, 86, "cta"),
]


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    return imageio_ffmpeg.get_ffmpeg_exe()


def voice_text() -> str:
    script_path = ROOT / "voiceover_script.txt"
    if script_path.exists():
        text = script_path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return VOICE_FALLBACK


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = font(86, True)
FONT_H1 = font(64, True)
FONT_H2 = font(43, True)
FONT_BODY = font(33, False)
FONT_SMALL = font(26, False)
FONT_CMD = font(36, True)
FONT_TINY = font(21, False)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def lerp(a: float, b: float, x: float) -> float:
    return a + (b - a) * x


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text_center(draw, xy, text, fnt, fill=INK, anchor="mm"):
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def draw_background(draw: ImageDraw.ImageDraw, t: float):
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=BG)
    for x in range(-120, WIDTH + 120, 120):
        xx = x + int((t * 16) % 120)
        draw.line((xx, 0, xx, HEIGHT), fill=(232, 239, 245), width=1)
    for y in range(0, HEIGHT, 120):
        draw.line((0, y, WIDTH, y), fill=(232, 239, 245), width=1)
    draw.rectangle((0, 0, WIDTH, 118), fill=(255, 255, 255))
    draw.line((0, 118, WIDTH, 118), fill=(218, 227, 235), width=2)


def load_logo() -> Image.Image:
    if not LOGO.exists():
        img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        rounded(d, (30, 30, 370, 370), 48, BLUE)
        text_center(d, (200, 200), "D", font(210, True), (255, 255, 255))
        return img
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((420, 420), Image.Resampling.LANCZOS)
    return logo


LOGO_IMG = load_logo()


def paste_logo(frame: Image.Image, center, size):
    logo = LOGO_IMG.copy()
    logo.thumbnail((size, size), Image.Resampling.LANCZOS)
    x = int(center[0] - logo.width / 2)
    y = int(center[1] - logo.height / 2)
    frame.alpha_composite(logo, (x, y))


def draw_header(draw: ImageDraw.ImageDraw):
    draw.text((70, 42), "Drydock", font=FONT_H2, fill=NAVY, anchor="lm")
    draw.text((315, 42), "Specification-Driven Delivery", font=FONT_SMALL, fill=MUTED, anchor="lm")
    rounded(draw, (1510, 30, 1810, 86), 16, (234, 247, 240), GREEN, 2)
    text_center(draw, (1660, 58), "MIT Licensed", FONT_SMALL, GREEN)


def draw_conveyor(draw: ImageDraw.ImageDraw, t: float):
    y = 760
    rounded(draw, (150, y, 1770, y + 98), 34, (40, 55, 72), None)
    for x in range(190, 1740, 120):
        cx = x + int((t * 80) % 120)
        draw.ellipse(
            (cx - 25, y + 24, cx + 25, y + 74),
            fill=(84, 103, 124),
            outline=(120, 140, 160),
            width=3,
        )
    draw.rectangle((170, y - 8, 1750, y + 18), fill=(69, 91, 114))
    draw.rectangle((170, y + 80, 1750, y + 106), fill=(32, 45, 59))


def paper_card(draw, x, y, title, lines=None, color=BLUE, scale=1.0):
    w = int(285 * scale)
    h = int(188 * scale)
    rounded(draw, (x, y, x + w, y + h), int(18 * scale), PAPER, LINE, 2)
    draw.rectangle((x, y, x + w, y + int(46 * scale)), fill=color)
    draw.text(
        (x + int(18 * scale), y + int(23 * scale)),
        title,
        font=font(int(24 * scale), True),
        fill=(255, 255, 255),
        anchor="lm",
    )
    lines = lines or ["Feature behavior", "Inputs and outputs", "Acceptance criteria"]
    yy = y + int(74 * scale)
    for line in lines:
        draw.line(
            (x + int(22 * scale), yy, x + w - int(24 * scale), yy),
            fill=(173, 190, 204),
            width=max(1, int(3 * scale)),
        )
        draw.text(
            (x + int(24 * scale), yy + int(18 * scale)),
            line,
            font=font(int(18 * scale)),
            fill=MUTED,
            anchor="lm",
        )
        yy += int(37 * scale)


def command_button(draw, x, y, label, active=0.0):
    glow = int(28 * active)
    if glow:
        draw.rounded_rectangle(
            (x - glow, y - glow, x + 440 + glow, y + 95 + glow), 24 + glow, fill=(226, 246, 237)
        )
    rounded(draw, (x, y, x + 440, y + 95), 22, NAVY, GREEN2 if active > 0.5 else BLUE2, 4)
    draw.text((x + 220, y + 47), label, font=FONT_CMD, fill=(255, 255, 255), anchor="mm")


def machine(draw, x, y, label="DRYDOCK"):
    rounded(draw, (x, y, x + 500, y + 310), 36, (230, 238, 245), (150, 168, 187), 4)
    rounded(draw, (x + 38, y + 42, x + 462, y + 112), 16, NAVY)
    draw.text((x + 250, y + 77), label, font=FONT_H2, fill=(255, 255, 255), anchor="mm")
    for i, c in enumerate([GREEN, AMBER, BLUE2]):
        draw.ellipse((x + 70 + i * 70, y + 165, x + 112 + i * 70, y + 207), fill=c)
    draw.arc((x + 312, y + 145, x + 430, y + 245), 20, 340, fill=BLUE, width=8)
    draw.polygon([(x + 430, y + 195), (x + 405, y + 180), (x + 407, y + 210)], fill=BLUE)
    draw.text(
        (x + 250, y + 265),
        "Agile + TDD + Controlled Context",
        font=FONT_SMALL,
        fill=INK,
        anchor="mm",
    )


def artifact(draw, x, y, label, color=GREEN, w=285):
    rounded(draw, (x, y, x + w, y + 72), 18, (255, 255, 255), color, 3)
    draw.text((x + w / 2, y + 36), label, font=FONT_SMALL, fill=INK, anchor="mm")


def graph_block(draw, x, y, label, color=BLUE2):
    rounded(draw, (x, y, x + 190, y + 78), 14, (255, 255, 255), color, 4)
    draw.text((x + 95, y + 39), label, font=FONT_TINY, fill=INK, anchor="mm")


def toy_block(draw, x, y, label, color=BLUE2, size=116, tilt=0):
    shadow = (x + 12, y + 14, x + size + 12, y + size + 14)
    rounded(draw, shadow, 14, (196, 207, 218))
    rounded(draw, (x, y, x + size, y + size), 14, color, (72, 91, 110), 4)
    draw.rectangle((x + 9, y + 9, x + size - 9, y + 38), fill=(255, 255, 255, 70))
    draw.text((x + size / 2, y + size / 2 + 7), label, font=FONT_SMALL, fill=(255, 255, 255), anchor="mm")
    if tilt:
        draw.line((x + 18, y + size - 18, x + size - 18, y + 18), fill=(255, 255, 255), width=2)


def cartoon_finger(draw, x, y, pointing="down"):
    skin = (244, 190, 148)
    outline = (150, 103, 75)
    if pointing == "down":
        rounded(draw, (x, y, x + 52, y + 138), 25, skin, outline, 3)
        draw.ellipse((x - 10, y + 94, x + 62, y + 166), fill=skin, outline=outline, width=3)
        draw.polygon([(x + 26, y + 154), (x - 2, y + 204), (x + 54, y + 204)], fill=skin, outline=outline)
    else:
        rounded(draw, (x, y, x + 138, y + 52), 25, skin, outline, 3)
        draw.ellipse((x - 28, y - 10, x + 44, y + 62), fill=skin, outline=outline, width=3)
        draw.polygon([(x + 128, y + 26), (x + 176, y - 2), (x + 176, y + 54)], fill=skin, outline=outline)


def draw_intro(frame, draw, t, p):
    pulse = 1 + 0.03 * math.sin(t * 6)
    paste_logo(frame, (WIDTH // 2, 335), int(285 * pulse))
    draw.text((WIDTH // 2, 585), "Meet Drydock", font=FONT_TITLE, fill=NAVY, anchor="mm")
    draw.text(
        (WIDTH // 2, 675),
        "A complete delivery system for specification-driven developers",
        font=FONT_H2,
        fill=BLUE,
        anchor="mm",
    )
    rounded(draw, (700, 750, 1220, 820), 20, (235, 248, 241), GREEN, 3)
    text_center(draw, (960, 785), "Stable Alpha · Contributors Wanted", FONT_SMALL, GREEN)


def draw_spec_in(frame, draw, t, p):
    draw.text((120, 205), "Start with a specification", font=FONT_H1, fill=NAVY)
    draw.text(
        (120, 275),
        "Ask your LLM to write the idea clearly, then import it.",
        font=FONT_BODY,
        fill=MUTED,
    )
    draw_conveyor(draw, t)
    machine(draw, 1070, 390)
    for i, title in enumerate(["Idea", "Specification", "Notes"]):
        offset = ease((p + i * 0.18) % 1.0)
        x = int(40 + offset * 870 - i * 130)
        y = 505 + i * 14
        paper_card(draw, x, y, title, color=[AMBER, BLUE2, GREEN][i])


def draw_analyze(frame, draw, t, p):
    draw.text((120, 190), "Analyze into governed Agile work", font=FONT_H1, fill=NAVY)
    command_button(draw, 125, 290, "drydock analyze", active=math.sin(p * math.pi))
    machine(draw, 710, 270)
    labels = [
        ("Stories", GREEN),
        ("Questions", AMBER),
        ("Blockers", RED),
        ("Acceptance Criteria", BLUE2),
    ]
    for i, (label, color) in enumerate(labels):
        x = int(1260 + ease(max(0, p - i * 0.09) / 0.55) * 120)
        y = 255 + i * 100
        artifact(draw, x, y, label, color=color, w=360)
    draw_conveyor(draw, t)


def draw_plan(frame, draw, t, p):
    draw.text((120, 190), "Plan the reproducible build", font=FONT_H1, fill=NAVY)
    command_button(draw, 125, 290, "drydock plan", active=math.sin(p * math.pi))
    machine(draw, 700, 265)
    bx = int(1220 + 80 * ease(p))
    paper_card(draw, bx, 245, "Blueprints", ["Typed specs", "Interfaces", "Tests"], GREEN, 0.95)
    paper_card(
        draw,
        bx + 315,
        245,
        "Manifest",
        ["Dependency graph", "Runnable steps", "Evidence"],
        BLUE2,
        0.95,
    )
    draw.text(
        (1230, 560), "Blueprints + Manifest become the build contract.", font=FONT_BODY, fill=INK
    )
    draw_conveyor(draw, t)


def draw_manifest(frame, draw, t, p):
    draw.text((120, 170), "The Manifest is a build graph", font=FONT_H1, fill=NAVY)
    draw.text(
        (120, 238),
        "Stories, tests, stack rules, voice, build steps, and evidence snap into place.",
        font=FONT_BODY,
        fill=MUTED,
    )
    blocks = [
        ("SPEC", 260, 405, AMBER),
        ("STORY", 480, 330, BLUE2),
        ("TEST", 480, 520, GREEN),
        ("STACK", 730, 405, NAVY),
        ("VOICE", 960, 330, BLUE),
        ("BUILD", 960, 520, GREEN2),
        ("EVID", 1210, 405, RED),
        ("SHIP", 1440, 405, GREEN),
    ]
    links = [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (3, 5), (4, 6), (5, 6), (6, 7)]
    positions = [(label, x, y + 25 * math.sin(t * 3 + idx) * (1 - ease(p)), color) for idx, (label, x, y, color) in enumerate(blocks)]
    for a, b in links:
        _, x1, y1, _ = positions[a]
        _, x2, y2, _ = positions[b]
        draw.line((x1 + 116, y1 + 58, x2, y2 + 58), fill=(151, 171, 190), width=5)
        draw.polygon(
            [(x2 - 2, y2 + 58), (x2 - 22, y2 + 46), (x2 - 22, y2 + 70)], fill=(151, 171, 190)
        )
    for idx, (label, x, y, color) in enumerate(positions):
        toy_block(draw, int(x), int(y), label, color, tilt=idx % 2)
    draw_conveyor(draw, t)


def draw_quarterdeck(frame, draw, t, p):
    draw.text((120, 170), "QuarterDeck lets you shape the build", font=FONT_H1, fill=NAVY)
    draw.text((120, 238), "Swap, review, and approve the blocks before build execution.", font=FONT_BODY, fill=MUTED)
    rounded(draw, (300, 300, 1620, 690), 28, (255, 255, 255), (142, 160, 180), 5)
    draw.rectangle((300, 300, 1620, 365), fill=(231, 239, 247))
    draw.text((355, 333), "QuarterDeck Review Scaffold", font=FONT_H2, fill=NAVY, anchor="lm")
    lanes = [430, 565]
    for y in lanes:
        draw.line((370, y + 72, 1540, y + 72), fill=(210, 222, 234), width=5)
    start_positions = [(430, 420), (650, 420), (870, 420), (1090, 420), (1310, 420)]
    target_positions = [(430, 555), (650, 555), (870, 555), (1090, 555), (1310, 555)]
    labels = [("STORY", BLUE2), ("TEST", GREEN), ("BUILD", GREEN2), ("STACK", NAVY), ("EVID", RED)]
    swap = ease(p)
    for idx, ((label, color), start, target) in enumerate(zip(labels, start_positions, target_positions, strict=True)):
        tx, ty = target
        sx, sy = start
        if idx in (1, 2):
            sx, sy = start_positions[2 if idx == 1 else 1]
        x = int(lerp(sx, tx, swap))
        y = int(lerp(sy, ty, swap))
        toy_block(draw, x, y, label, color, size=104)
    cartoon_finger(draw, int(700 + 260 * math.sin(p * math.pi)), 245)
    cartoon_finger(draw, int(970 - 220 * math.sin(p * math.pi)), 250)
    if p > 0.78:
        rounded(draw, (1260, 610, 1515, 665), 16, (230, 249, 240), GREEN, 3)
        text_center(draw, (1387, 638), "APPROVED", FONT_SMALL, GREEN)
    draw_conveyor(draw, t)


def draw_rigging(frame, draw, t, p):
    draw.text((120, 170), "Rigging joins the Manifest", font=FONT_H1, fill=NAVY)
    draw.text((120, 238), "Branding and engineering rules travel with every build.", font=FONT_BODY, fill=MUTED)
    draw.line((480, 505, 1415, 505), fill=(151, 171, 190), width=6)
    base = [("STORY", 520, BLUE2), ("TEST", 740, GREEN), ("BUILD", 960, GREEN2), ("EVID", 1180, RED)]
    for label, x, color in base:
        toy_block(draw, x, 445, label, color)
    rigging = [
        ("BRAND", int(80 + 360 * ease(p)), 325, AMBER),
        ("RULES", int(80 + 360 * ease(max(0, p - 0.18) / 0.82)), 575, NAVY),
    ]
    for label, x, y, color in rigging:
        toy_block(draw, x, y, label, color)
        draw.line((x + 116, y + 58, 520, 505), fill=(151, 171, 190), width=4)
    artifact(draw, 1395, 360, "Consistent Look", GREEN, 330)
    artifact(draw, 1395, 470, "Consistent Behavior", BLUE2, 330)
    artifact(draw, 1395, 580, "Consistent Docs", AMBER, 330)
    draw_conveyor(draw, t)


def draw_build(frame, draw, t, p):
    draw.text((120, 170), "Build with Test-Driven evidence", font=FONT_H1, fill=NAVY)
    command_button(draw, 125, 270, "drydock build", active=math.sin(p * math.pi))
    rounded(draw, (680, 215, 1580, 650), 24, (18, 28, 40), (72, 98, 124), 4)
    draw.text((725, 270), "$ drydock build", font=FONT_CMD, fill=GREEN2)
    lines = [
        "reading MANIFEST.md",
        "selecting runnable block",
        "stacking minimal context",
        "running acceptance tests",
        "writing evidence ledger",
    ]
    for i, line in enumerate(lines):
        visible = p > i * 0.13
        color = GREEN2 if visible else (80, 95, 110)
        prefix = "✓" if visible else "·"
        draw.text((735, 335 + i * 55), f"{prefix} {line}", font=FONT_BODY, fill=color)
    if p > 0.72:
        rounded(draw, (1140, 520, 1500, 600), 20, (226, 248, 238), GREEN, 4)
        text_center(draw, (1320, 560), "Tests Passing", FONT_H2, GREEN)
    draw_conveyor(draw, t)


def draw_refit(frame, draw, t, p):
    draw.text((120, 170), "Refit change tickets", font=FONT_H1, fill=NAVY)
    draw.text(
        (120, 238),
        "Tickets become new Manifest blocks.",
        font=FONT_BODY,
        fill=MUTED,
    )
    draw_conveyor(draw, t)
    for idx in range(9):
        fall = ease((p + idx * 0.08) % 1.0)
        x = 120 + (idx % 5) * 105 + int(30 * math.sin(t * 2 + idx))
        y = int(315 + fall * 260)
        rounded(draw, (x, y, x + 90, y + 58), 8, (255, 255, 255), AMBER, 2)
        draw.text((x + 45, y + 29), "TICKET", font=FONT_TINY, fill=INK, anchor="mm")
    machine(draw, 780, 385, "REFIT")
    for i in range(7):
        a = p * math.pi * 2 + i
        x1 = int(700 + math.cos(a) * (210 - i * 12))
        y1 = int(515 + math.sin(a) * (130 - i * 8))
        draw.arc((x1, y1, x1 + 180, y1 + 90), 15, 320, fill=BLUE2, width=4)
    draw.polygon([(750, 520), (705, 485), (705, 555)], fill=BLUE2)
    command_button(draw, 735, 285, "drydock refit", active=math.sin(p * math.pi))
    for i, (label, color) in enumerate([("NEW", BLUE2), ("BUILD", GREEN), ("EVID", RED)]):
        toy_block(draw, 1280 + i * 155, 455 + int(35 * math.sin(p * math.pi + i)), label, color, size=108)
    artifact(draw, 1275, 640, "Updated Manifest Blocks", GREEN, 455)


def draw_truths(frame, draw, t, p):
    draw.text((120, 170), "Engineering truths", font=FONT_H1, fill=NAVY)
    truths = [
        ("Decompose big problems", BLUE2),
        ("Agile planning", GREEN),
        ("Test-Driven Development", AMBER),
        ("Graph + context compression", NAVY),
    ]
    for idx, (label, color) in enumerate(truths):
        x = 260 + idx * 380
        y = 440 + int(18 * math.sin(t * 3 + idx))
        toy_block(draw, x, y, label.split()[0].upper()[:5], color, size=126)
        draw.text((x + 63, y + 165), label, font=FONT_SMALL, fill=INK, anchor="mm")
    draw_conveyor(draw, t)


def draw_cta(frame, draw, t, p):
    paste_logo(frame, (960, 260), 230)
    draw.text((960, 455), "Drydock", font=FONT_TITLE, fill=NAVY, anchor="mm")
    draw.text(
        (960, 540),
        "Reproducible AI-assisted software delivery",
        font=FONT_H2,
        fill=BLUE,
        anchor="mm",
    )
    rounded(draw, (390, 625, 1530, 705), 22, (255, 255, 255), GREEN, 4)
    text_center(
        draw, (960, 665), "Stable Alpha · MIT Licensed · Contributors Wanted", FONT_BODY, GREEN
    )
    draw.text((960, 795), "Take it for a sail.", font=FONT_H1, fill=NAVY, anchor="mm")
    draw.text((960, 880), "WebCloudStudio.com", font=FONT_H2, fill=BLUE, anchor="mm")


DRAWERS = {
    "intro": draw_intro,
    "spec_in": draw_spec_in,
    "analyze": draw_analyze,
    "plan": draw_plan,
    "manifest": draw_manifest,
    "quarterdeck": draw_quarterdeck,
    "rigging": draw_rigging,
    "build": draw_build,
    "refit": draw_refit,
    "truths": draw_truths,
    "cta": draw_cta,
}


def frame_at(t: float) -> Image.Image:
    frame = Image.new("RGBA", (WIDTH, HEIGHT), BG + (255,))
    draw = ImageDraw.Draw(frame)
    draw_background(draw, t)
    draw_header(draw)
    scene = next(s for s in SCENES if s.start <= t < s.end or (t >= s.end and s is SCENES[-1]))
    DRAWERS[scene.name](frame, draw, t, scene.progress(t))
    draw.rectangle((0, HEIGHT - 18, int(WIDTH * min(1, t / DURATION)), HEIGHT), fill=GREEN)
    return frame.convert("RGB")


def write_music(path: Path, option: int, duration: float = DURATION, sample_rate: int = 44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    total = int(duration * sample_rate)
    data = np.zeros(total, dtype=np.float32)
    bpm = [108, 124, 96][option - 1]
    beat = 60.0 / bpm
    freqs = [220, 277, 330, 440, 554, 660]
    for i in range(total):
        t = i / sample_rate
        step = int(t / (beat / 2))
        env = math.exp(-((t % (beat / 2)) * 9))
        if option == 1:
            tone = math.sin(2 * math.pi * 176 * t) * env * 0.16
            click = math.sin(2 * math.pi * 1200 * t) * math.exp(-((t % beat) * 45)) * 0.08
        elif option == 2:
            f = freqs[step % len(freqs)]
            tone = math.sin(2 * math.pi * f * t) * env * 0.17
            tone += math.sin(2 * math.pi * (f * 2) * t) * env * 0.05
            click = math.sin(2 * math.pi * 920 * t) * math.exp(-((t % (beat / 2)) * 38)) * 0.09
        else:
            f = 196 if step % 4 else 247
            tone = math.sin(2 * math.pi * f * t) * env * 0.12
            click = math.sin(2 * math.pi * 700 * t) * math.exp(-((t % beat) * 28)) * 0.06
        pad = math.sin(2 * math.pi * 82.4 * t) * 0.035
        data[i] = tone + click + pad
    fade = int(sample_rate * 1.2)
    data[:fade] *= np.linspace(0, 1, fade)
    data[-fade:] *= np.linspace(1, 0, fade)
    data = np.clip(data, -0.7, 0.7)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for value in data:
            wav.writeframes(struct.pack("<h", int(value * 32767)))


async def write_voice(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    communicator = edge_tts.Communicate(
        voice_text(),
        voice="en-US-AvaMultilingualNeural",
        rate="+18%",
        volume="+0%",
    )
    await communicator.save(str(path))


def render_silent_video(path: Path):
    exe = ffmpeg_exe()
    cmd = [
        exe,
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-pix_fmt",
        "rgb24",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "23",
        "-preset",
        "ultrafast",
        str(path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    frames = int(DURATION * FPS)
    for frame_no in range(frames):
        img = frame_at(frame_no / FPS)
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg video render failed with exit code {rc}")


def mux_audio(video: Path, voice: Path, music: Path, out: Path):
    exe = ffmpeg_exe()
    cmd = [
        exe,
        "-y",
        "-i",
        str(video),
        "-i",
        str(voice),
        "-i",
        str(music),
        "-filter_complex",
        f"[1:a]volume=1.15[a1];[2:a]volume=0.18,afade=t=out:st={DURATION - 3}:d=3[a2];[a1][a2]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def main():
    AUDIO.mkdir(exist_ok=True)
    RENDERS.mkdir(exist_ok=True)
    (ROOT / "voiceover_script.txt").write_text(voice_text() + "\n", encoding="utf-8")

    music_paths = [
        AUDIO / "music_option_1_clean_pulse.wav",
        AUDIO / "music_option_2_bright_ditty.wav",
        AUDIO / "music_option_3_minimal_drive.wav",
    ]
    for idx, path in enumerate(music_paths, start=1):
        if not path.exists():
            write_music(path, idx)

    voice = AUDIO / "voiceover_ava_neural.mp3"
    asyncio.run(write_voice(voice))

    silent = RENDERS / "drydock-announcement-silent.mp4"
    final = RENDERS / "drydock-announcement-first-cut.mp4"
    render_silent_video(silent)
    mux_audio(silent, voice, music_paths[0], final)
    print(f"Wrote {final}")
    print(f"Music options: {', '.join(str(p) for p in music_paths)}")


if __name__ == "__main__":
    main()
