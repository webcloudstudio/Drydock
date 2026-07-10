#!/usr/bin/env python3
"""Generate the Drydock announcement video from local assets.

The video is one continuous world: a single always-running conveyor belt.
The camera dollies along the belt at belt speed, so cards riding the belt
hold their screen position while gantry machines (import, analyze, plan,
build, refit) sweep past and transform them. The belt ends at a delivery
platform where Working Software crates stack up under the closing call to
action.

This script intentionally avoids paid or API-key-backed services. It uses:
- Pillow for 2D animation frames
- edge-tts for a free neural narration voice
- generated WAV music beds
- imageio_ffmpeg's bundled ffmpeg binary for rendering
"""

from __future__ import annotations

import argparse
import asyncio
import math
import multiprocessing
import re
import shutil
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
DOCS = ROOT.parent
LOGO = DOCS / "drydock_logo.png"
AUDIO = ROOT / "audio"
RENDERS = ROOT / "renders"
STILLS = RENDERS / "stills"

WIDTH = 1920
HEIGHT = 1080
FPS = 24

# World mechanics. The belt surface moves at V world px/s. During the main
# run the camera is locked to the belt surface, so riding cards keep a
# constant screen x while world-fixed structures sweep right-to-left.
V = 220.0
BELT_Y = 760  # belt top surface
GANTRY_SX = 880  # screen x where a gantry center sits at its arrival time
BASE_END = 88.0  # base timeline length; scaled to the narration

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
STEEL = (150, 168, 187)
STEEL_DARK = (84, 103, 124)

VOICE_FALLBACK = """Meet Drydock: a complete delivery system for specification-driven developers.

Drydock works with larger specifications, including multi-file specs and material imported from other tools.

Start with drydock import: bring in specifications, notes, or existing project material.

Run drydock analyze, and Drydock proposes an Agile plan with features, stories, questions, blockers, and acceptance criteria.

Run drydock plan, and your specifications become governed Blueprints. Each Blueprint carries Test-Driven Development tests. Plan also builds the Manifest: a graph database relating your stories, your stack, and your branding.

Then shape the build in the QuarterDeck web server: group stories into blocks of Blueprints and set the build order.

Drydock also supports enterprise branding and stack rules, so applications keep consistent look, behavior, and documentation.

Run drydock build, and Drydock walks the graph block by block, verifying each story against its tests and producing working software.

Agile software never stops changing. Working software plus change tickets go through drydock refit and come out as more working software.

Drydock is built on simple engineering truths: engineers decompose big problems; Agile and Test-Driven Development are proven practices; and a graph plus context compression makes specification-driven builds reproducible with your Sonnet or Codex subscription.

Drydock is free, MIT-licensed software, now in stable alpha.

Take it for a sail. Contributors wanted.

WebCloudStudio.com."""


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
        "/mnt/c/Windows/Fonts/segoeuib.ttf" if bold else "/mnt/c/Windows/Fonts/segoeui.ttf",
        "/mnt/c/Windows/Fonts/arialbd.ttf" if bold else "/mnt/c/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = font(92, True)
FONT_H1 = font(62, True)
FONT_H2 = font(43, True)
FONT_BODY = font(33, False)
FONT_SMALL = font(26, False)
FONT_CMD = font(34, True)
FONT_TINY = font(21, False)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def lerp(a: float, b: float, x: float) -> float:
    return a + (b - a) * x


def load_logo() -> Image.Image:
    if not LOGO.exists():
        img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((30, 30, 370, 370), 48, fill=BLUE)
        d.text((200, 200), "D", font=font(210, True), fill=(255, 255, 255), anchor="mm")
        return img
    logo = Image.open(LOGO).convert("RGBA")
    logo.thumbnail((420, 420), Image.Resampling.LANCZOS)
    return logo


LOGO_IMG = load_logo()


def paste_logo(frame: Image.Image, center, size, alpha=1.0):
    logo = LOGO_IMG.copy()
    logo.thumbnail((size, size), Image.Resampling.LANCZOS)
    if alpha < 1.0:
        a = logo.getchannel("A").point(lambda v: int(v * alpha))
        logo.putalpha(a)
    x = int(center[0] - logo.width / 2)
    y = int(center[1] - logo.height / 2)
    frame.alpha_composite(logo, (x, y))


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class Timeline:
    """All world positions and event times, scaled to the narration length."""

    def __init__(self, duration: float):
        self.duration = duration
        s = duration / BASE_END
        self.s = s
        sc = lambda x: x * s  # noqa: E731

        # Camera: locked to belt speed, then eased to a stop for the closer.
        self.t_stop = sc(82.0)
        self.stop_len = 3.0
        self.cam_final = V * self.t_stop + V * self.stop_len / 2

        self.scenes = [
            ("intro", 0.0, sc(5), "", ""),
            (
                "import",
                sc(5),
                sc(17),
                "Start with a specification",
                "Specifications, notes, and project material drop onto the line.",
            ),
            ("analyze", sc(17), sc(26), "Analyze into governed Agile work", ""),
            ("plan", sc(26), sc(36), "Plan the reproducible build", ""),
            ("manifest", sc(36), sc(46), "The Manifest is a graph database", ""),
            ("quarterdeck", sc(46), sc(54), "Shape the build", ""),
            ("rigging", sc(54), sc(61), "Rigging travels with every build", ""),
            ("build", sc(61), sc(70), "Build with Test-Driven evidence", ""),
            ("refit", sc(70), sc(78), "Refit change tickets", ""),
            ("truths", sc(78), sc(82), "Built on engineering truths", ""),
            ("cta", sc(82), duration, "", ""),
        ]

        t_import = sc(12.5)
        t_analyze = sc(22.0)
        t_plan = sc(31.0)
        t_build = sc(65.0)
        t_refit = sc(75.5)

        def conv(t_arr: float, wx0: float) -> float:
            return t_arr + (GANTRY_SX - wx0) / V

        c = conv
        self.cards = []

        def card(
            kind,
            label,
            color,
            wx0,
            t_show,
            t_hide,
            scale=0.85,
            drop=None,
            drop_from=-80,
            ticks=False,
            badge=False,
        ):
            self.cards.append(
                dict(
                    kind=kind,
                    label=label,
                    color=color,
                    wx0=wx0,
                    t_show=t_show,
                    t_hide=t_hide,
                    scale=scale,
                    drop=drop,
                    drop_from=drop_from,
                    ticks=ticks,
                    badge=badge,
                )
            )

        # Inputs drop onto the belt, ride into IMPORT.
        for label, color, wx0, td in [
            ("Specification", BLUE2, 840, sc(5.5)),
            ("Notes", GREEN, 520, sc(6.4)),
            ("Project Material", AMBER, 200, sc(7.3)),
        ]:
            card(
                "card", label, color, wx0, td, c(t_import, wx0), drop=(td, td + 0.8), drop_from=390
            )
        # IMPORT output: same cards, imported.
        for label, color, wx0 in [
            ("Imported Specification", BLUE2, 840),
            ("Imported Notes", GREEN, 520),
            ("Imported Material", AMBER, 200),
        ]:
            card("card", label, color, wx0, c(t_import, wx0), c(t_analyze, wx0), badge=True)
        # ANALYZE output: the Agile plan.
        for label, color, wx0, ticks in [
            ("Stories", GREEN, 900, True),
            ("Questions", AMBER, 610, False),
            ("Blockers", RED, 320, False),
            ("Acceptance Criteria", BLUE2, 30, True),
        ]:
            card(
                "card",
                label,
                color,
                wx0,
                c(t_analyze, wx0),
                c(t_plan, wx0),
                scale=0.82,
                ticks=ticks,
            )
        # PLAN output: Blueprints and the Manifest ride on toward BUILD.
        card("card", "Blueprints", GREEN, 350, c(t_plan, 350), c(t_build, 350), ticks=True)
        card("card", "Manifest", BLUE2, 100, c(t_plan, 100), c(t_build, 100))
        # RIGGING drops Stack and Voice onto the belt; they ride into BUILD.
        self.rig_bin_wx = 1150 + V * sc(56.5)
        self.rig_drops = [("Stack", NAVY, 1150, sc(56.5)), ("Branding", BLUE, 820, sc(58.0))]
        for label, color, wx0, td in self.rig_drops:
            card(
                "card",
                label,
                color,
                wx0,
                td,
                c(t_build, wx0),
                scale=0.8,
                drop=(td, td + 0.7),
                drop_from=540,
            )
        # BUILD output: a Working Software crate. It rides into REFIT with the
        # change tickets.
        card("crate", "", GREEN, 700, c(t_build, 700), c(t_refit, 700))
        # Change tickets drop, ride into REFIT.
        for wx0, td in [(1450, sc(70.6)), (1300, sc(71.4)), (1150, sc(72.2))]:
            card("ticket", "CHANGE", AMBER, wx0, td, c(t_refit, wx0), drop=(td, td + 0.7))
        # REFIT output: more working software, emerging where each ticket
        # vanished, riding to the end of the line.
        for wx0 in [1452, 1302, 1152]:
            card("crate", "", GREEN, wx0, c(t_refit, wx0), duration + 10)

        self.gantries = []
        for cmd, t_arr in [
            ("drydock import", t_import),
            ("drydock analyze", t_analyze),
            ("drydock plan", t_plan),
            ("drydock build", t_build),
            ("drydock refit", t_refit),
        ]:
            wx = GANTRY_SX + V * t_arr
            # A gantry is active when any card converts at it.
            own = [
                cd["t_hide"]
                for cd in self.cards
                if abs(conv(t_arr, cd["wx0"]) - cd["t_hide"]) < 0.01
            ] + [
                cd["t_show"]
                for cd in self.cards
                if abs(conv(t_arr, cd["wx0"]) - cd["t_show"]) < 0.01
            ]
            self.gantries.append(dict(cmd=cmd, t_arr=t_arr, wx=wx, events=sorted(own)))

        # Belt end and delivery platform.
        self.wx_end = self.cam_final + 1280
        # Crates that survive to the end tip off and stack on the platform.
        slots = [(130, 995), (350, 995), (240, 862)]
        crate_cards = [cd for cd in self.cards if cd["kind"] == "crate" and cd["t_hide"] > duration]
        crate_cards.sort(key=lambda cd: (self.wx_end - cd["wx0"]) / V)
        for cd, (dx, y_bottom) in zip(crate_cards, slots):
            cd["t_off"] = (self.wx_end - 40 - cd["wx0"]) / V
            cd["slot"] = (self.wx_end + dx, y_bottom)

        # Wall panels above the belt.
        self.manifest_panel = dict(wx=1920 + V * sc(36), w=1700, anim=(sc(37.0), sc(43.0)))
        self.qd_panel = dict(wx=1920 + V * sc(46), w=1300, swap=(sc(48.0), sc(51.5)))
        self.truths_window = (sc(78.0), sc(82.0))
        self.truths = [
            ("Decompose big problems", 150, 300),
            ("Agile planning", 780, 300),
            ("Test-Driven Development", 150, 392),
            ("Graph + context compression", 780, 392),
        ]
        self.tests_chip = (c(t_build, 700) + 0.6, c(t_build, 350) + 1.2, 700)

    def cam(self, t: float) -> float:
        if t <= self.t_stop:
            return V * t
        u = min(t - self.t_stop, self.stop_len)
        return V * self.t_stop + V * (u - u * u / (2 * self.stop_len))

    def scene_at(self, t: float):
        for scene in self.scenes:
            if scene[1] <= t < scene[2]:
                return scene
        return self.scenes[-1]


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------


def fit_font(draw, text, max_w, size, bold=True):
    while size > 14:
        f = font(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font(size, bold)


def paper_card(draw, x, y, title, color, scale=1.0, ticks=False, badge=False):
    """The one card style used everywhere: title bar plus rule lines."""
    w = int(285 * scale)
    h = int(188 * scale)
    draw.rounded_rectangle(
        (x + 8, y + 10, x + w + 8, y + h + 10), int(18 * scale), fill=(203, 214, 224)
    )
    draw.rounded_rectangle((x, y, x + w, y + h), int(18 * scale), fill=PAPER, outline=LINE, width=2)
    bar_h = int(48 * scale)
    draw.rounded_rectangle((x, y, x + w, y + bar_h + 12), int(18 * scale), fill=color)
    draw.rectangle((x, y + bar_h - 6, x + w, y + bar_h + 12), fill=PAPER)
    draw.rectangle((x, y + int(bar_h * 0.4), x + w, y + bar_h), fill=color)
    pad = int(16 * scale)
    title_w = w - 2 * pad - (int(34 * scale) if badge else 0)
    f = fit_font(draw, title, title_w, int(25 * scale))
    draw.text((x + pad, y + bar_h // 2), title, font=f, fill=(255, 255, 255), anchor="lm")
    if badge:
        r = int(13 * scale)
        cx, cy = x + w - pad - r, y + bar_h // 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))
        draw.line((cx - r * 0.45, cy, cx - r * 0.1, cy + r * 0.4), fill=GREEN, width=3)
        draw.line((cx - r * 0.1, cy + r * 0.4, cx + r * 0.5, cy - r * 0.4), fill=GREEN, width=3)
    yy = y + bar_h + int(30 * scale)
    for i in range(3):
        x0 = x + int(24 * scale)
        x1 = x + w - int(26 * scale)
        if ticks:
            tx = x0
            draw.line(
                (tx, yy - 2, tx + int(7 * scale), yy + int(5 * scale)),
                fill=GREEN,
                width=max(2, int(3 * scale)),
            )
            draw.line(
                (
                    tx + int(7 * scale),
                    yy + int(5 * scale),
                    tx + int(16 * scale),
                    yy - int(8 * scale),
                ),
                fill=GREEN,
                width=max(2, int(3 * scale)),
            )
            x0 += int(28 * scale)
        draw.line((x0, yy, x1, yy), fill=(173, 190, 204), width=max(1, int(3 * scale)))
        yy += int(36 * scale)


def crate_box(draw, cx, y_bottom):
    w, h = 210, 135
    x, y = int(cx - w / 2), int(y_bottom - h)
    draw.rounded_rectangle((x + 7, y + 9, x + w + 7, y + h + 9), 16, fill=(203, 214, 224))
    draw.rounded_rectangle((x, y, x + w, y + h), 16, fill=GREEN, outline=(17, 112, 73), width=4)
    draw.rounded_rectangle((x + 10, y + 10, x + w - 10, y + 44), 10, fill=GREEN2)
    cx, cy = x + w / 2, y + 27
    draw.line((cx - 12, cy, cx - 3, cy + 9), fill=(255, 255, 255), width=5)
    draw.line((cx - 3, cy + 9, cx + 13, cy - 9), fill=(255, 255, 255), width=5)
    draw.text(
        (x + w / 2, y + 72), "WORKING", font=font(27, True), fill=(255, 255, 255), anchor="mm"
    )
    draw.text(
        (x + w / 2, y + 104), "SOFTWARE", font=font(27, True), fill=(255, 255, 255), anchor="mm"
    )


def ticket_slip(draw, cx, y_bottom):
    w, h = 132, 72
    x, y = int(cx - w / 2), int(y_bottom - h)
    draw.rounded_rectangle((x + 4, y + 5, x + w + 4, y + h + 5), 8, fill=(206, 216, 226))
    draw.rounded_rectangle((x, y, x + w, y + h), 8, fill=(255, 251, 240), outline=AMBER, width=3)
    draw.text((x + w / 2, y + 24), "CHANGE", font=font(19, True), fill=INK, anchor="mm")
    draw.line((x + 16, y + 46, x + w - 16, y + 46), fill=(212, 195, 160), width=3)
    draw.line((x + 16, y + 58, x + w - 34, y + 58), fill=(212, 195, 160), width=3)


def toy_block(draw, x, y, label, color, size=150):
    """A kids' letter block: colored cube face, white inset, bold letter."""
    draw.rounded_rectangle((x + 9, y + 11, x + size + 9, y + size + 11), 18, fill=(199, 210, 221))
    draw.rounded_rectangle(
        (x, y, x + size, y + size), 18, fill=color, outline=(30, 44, 58), width=4
    )
    inset = int(size * 0.16)
    draw.rounded_rectangle(
        (x + inset, y + inset, x + size - inset, y + size - inset), 12, fill=(255, 255, 255)
    )
    draw.text(
        (x + size / 2, y + size / 2 + 2),
        label,
        font=font(int(size * 0.34), True),
        fill=color,
        anchor="mm",
    )


def cursor_arrow(draw, x, y):
    pts = [
        (x, y),
        (x, y + 46),
        (x + 12, y + 36),
        (x + 20, y + 54),
        (x + 29, y + 50),
        (x + 21, y + 32),
        (x + 36, y + 31),
    ]
    draw.polygon(pts, fill=(255, 255, 255), outline=(30, 44, 58))
    draw.polygon(pts, outline=(30, 44, 58))


# ---------------------------------------------------------------------------
# World drawing
# ---------------------------------------------------------------------------


def draw_background(draw, cam):
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=BG)
    shift = int((cam * 0.35) % 120)
    for x in range(-120, WIDTH + 240, 120):
        draw.line((x - shift, 0, x - shift, HEIGHT), fill=(232, 239, 245), width=1)
    for y in range(0, HEIGHT, 120):
        draw.line((0, y, WIDTH, y), fill=(232, 239, 245), width=1)


def draw_header(draw):
    draw.rectangle((0, 0, WIDTH, 118), fill=(255, 255, 255))
    draw.line((0, 118, WIDTH, 118), fill=(218, 227, 235), width=2)
    draw.text((70, 58), "Drydock", font=FONT_H2, fill=NAVY, anchor="lm")
    draw.text((315, 60), "Specification-Driven Delivery", font=FONT_SMALL, fill=MUTED, anchor="lm")
    draw.rounded_rectangle((1510, 30, 1810, 86), 16, fill=(234, 247, 240), outline=GREEN, width=2)
    draw.text((1660, 58), "MIT Licensed", font=FONT_SMALL, fill=GREEN, anchor="mm")


def draw_floor(draw, cam):
    draw.rectangle((0, 1004, WIDTH, HEIGHT), fill=(230, 237, 243))
    draw.line((0, 1004, WIDTH, 1004), fill=(203, 214, 224), width=3)


def draw_belt(draw, t, tl):
    cam = tl.cam(t)
    end_sx = tl.wx_end - cam
    right = min(WIDTH + 60, int(end_sx))
    y = BELT_Y
    # Support legs (world-fixed, sweep past the camera).
    leg_w0 = int(cam // 450) * 450
    for wx in range(leg_w0 - 450, leg_w0 + WIDTH + 900, 450):
        if wx > tl.wx_end - 90:
            continue
        sx = int(wx - cam)
        if -60 < sx < WIDTH + 60:
            draw.polygon(
                [(sx - 26, y + 104), (sx + 26, y + 104), (sx + 40, 1004), (sx - 40, 1004)],
                fill=(196, 208, 219),
            )
    # Belt body.
    draw.rectangle((0, y, right, y + 104), fill=(40, 55, 72))
    draw.rectangle((0, y - 6, right, y + 14), fill=(69, 91, 114))
    draw.rectangle((0, y + 88, right, y + 104), fill=(32, 45, 59))
    # End cap and platform.
    if end_sx < WIDTH + 80:
        ex = int(end_sx)
        draw.ellipse(
            (ex - 52, y - 6, ex + 52, y + 104), fill=(40, 55, 72), outline=(120, 140, 160), width=4
        )
        draw.ellipse((ex - 20, y + 27, ex + 20, y + 71), fill=STEEL_DARK)
        # Delivery platform.
        px0 = ex + 40
        draw.rounded_rectangle((px0, 995, px0 + 560, 1004), 4, fill=(178, 192, 205))
        draw.polygon([(px0 + 30, 995), (px0 + 60, 1004), (px0, 1004)], fill=(160, 175, 190))
    # Rollers (world-fixed frame, spokes spin with the belt surface).
    r = 30
    roll_w0 = int(cam // 150) * 150
    spin = t * V / r
    for wx in range(roll_w0 - 150, roll_w0 + WIDTH + 300, 150):
        if wx > tl.wx_end - 60:
            continue
        sx = wx - cam
        if sx < -40 or sx > WIDTH + 40:
            continue
        cx, cy = int(sx), y + 52
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r), fill=STEEL_DARK, outline=(120, 140, 160), width=3
        )
        for k in range(3):
            a = spin + k * math.pi * 2 / 3
            draw.line(
                (
                    cx - r * 0.72 * math.cos(a),
                    cy - r * 0.72 * math.sin(a),
                    cx + r * 0.72 * math.cos(a),
                    cy + r * 0.72 * math.sin(a),
                ),
                fill=(130, 150, 170),
                width=4,
            )
        draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=(160, 178, 196))
    # Tread ticks move with the belt surface: static while the camera is
    # locked, visibly running once the camera stops for the closer.
    for k in range(-2, WIDTH // 130 + 4):
        sx = int(k * 130 + ((V * t - cam) % 130))
        if 0 <= sx <= right:
            draw.line((sx, y - 4, sx + 26, y + 10), fill=(56, 74, 94), width=4)


def draw_gantry(frame, draw, sx, cmd, active, t):
    if sx < -420 or sx > WIDTH + 420:
        return
    sx = int(sx)
    glow = ease(active)
    # Legs down to the floor, straddling the belt.
    for lx in (sx - 224, sx + 180):
        draw.rectangle((lx, 400, lx + 44, 1004), fill=STEEL, outline=(116, 134, 152), width=2)
        draw.rectangle((lx + 8, 430, lx + 36, 442), fill=(116, 134, 152))
        draw.rectangle((lx + 8, 950, lx + 36, 962), fill=(116, 134, 152))
    # Crossbeam and command sign.
    draw.rounded_rectangle(
        (sx - 264, 342, sx + 264, 424), 18, fill=(214, 224, 233), outline=STEEL, width=3
    )
    sign = (sx - 240, 354, sx + 240, 412)
    if glow > 0.05:
        draw.rounded_rectangle(
            (sign[0] - 8, sign[1] - 8, sign[2] + 8, sign[3] + 8),
            18,
            fill=(67, 210, 143, int(110 * glow)),
        )
    draw.rounded_rectangle(sign, 12, fill=NAVY, outline=GREEN2 if glow > 0.3 else BLUE2, width=3)
    draw.text((sx + 12, 383), cmd, font=FONT_CMD, fill=(255, 255, 255), anchor="mm")
    paste_logo(frame, (sx - 196, 383), 44)
    # Status lamp.
    lamp = GREEN2 if glow > 0.3 else (120, 138, 156)
    draw.ellipse((sx + 216, 330, sx + 244, 358), fill=lamp, outline=(90, 106, 122), width=2)
    # Shroud the cards pass through.
    draw.rounded_rectangle(
        (sx - 180, 424, sx + 180, 872), 14, fill=(230, 238, 245), outline=STEEL, width=4
    )
    # Porthole with a working gear.
    cx, cy, pr = sx, 596, 84
    draw.ellipse((cx - pr, cy - pr, cx + pr, cy + pr), fill=NAVY, outline=STEEL, width=5)
    gr = 52
    a0 = t * (2.2 + 5.5 * glow)
    for k in range(8):
        a = a0 + k * math.pi / 4
        draw.line(
            (
                cx + gr * 0.45 * math.cos(a),
                cy + gr * 0.45 * math.sin(a),
                cx + gr * math.cos(a),
                cy + gr * math.sin(a),
            ),
            fill=GREEN2 if glow > 0.3 else (110, 132, 156),
            width=9,
        )
    draw.ellipse(
        (cx - 22, cy - 22, cx + 22, cy + 22), fill=GREEN2 if glow > 0.3 else (110, 132, 156)
    )
    # Hazard band above the belt opening.
    for hx in range(sx - 176, sx + 176, 36):
        draw.polygon([(hx, 862), (hx + 18, 862), (hx + 4, 838), (hx - 14, 838)], fill=AMBER)
    draw.rectangle((sx - 180, 862, sx + 180, 872), fill=NAVY)
    # Conversion sparks at the exit side.
    if glow > 0.25:
        ex, ey = sx + 186, BELT_Y - 22
        for k in range(6):
            a = -0.9 + k * 0.36
            ln = 18 + 26 * glow
            draw.line(
                (
                    ex + 10 * math.cos(a),
                    ey + 10 * math.sin(a),
                    ex + (10 + ln) * math.cos(a),
                    ey + (10 + ln) * math.sin(a),
                ),
                fill=AMBER,
                width=5,
            )


def draw_manifest_panel(draw, sx_left, t, tl):
    panel = tl.manifest_panel
    w = panel["w"]
    if sx_left > WIDTH or sx_left + w < 0:
        return
    x0, y0 = int(sx_left), 150
    draw.rounded_rectangle(
        (x0, y0, x0 + w, y0 + 560), 26, fill=(255, 255, 255), outline=(142, 160, 180), width=4
    )
    draw.rounded_rectangle((x0 + 28, y0 + 486, x0 + 262, y0 + 536), 12, fill=NAVY)
    draw.text(
        (x0 + 145, y0 + 511), "MANIFEST", font=font(28, True), fill=(255, 255, 255), anchor="mm"
    )
    scale = 0.62
    cw, ch = int(285 * scale), int(188 * scale)
    nodes = {
        "Branding": (95, 116, BLUE, False),
        "Stack": (95, 330, NAVY, False),
        "Story 1": (430, 223, BLUE2, True),
        "Story 2": (775, 92, BLUE2, True),
        "Story 3": (775, 356, BLUE2, True),
        "Story 4": (1120, 223, BLUE2, True),
    }
    links = [
        ("Branding", "Story 1"),
        ("Stack", "Story 1"),
        ("Stack", "Story 3"),
        ("Story 1", "Story 2"),
        ("Story 1", "Story 3"),
        ("Story 2", "Story 4"),
        ("Story 3", "Story 4"),
    ]
    a0, a1 = panel["anim"]
    p = ease((t - a0) / max(0.001, a1 - a0))
    for i, (src, dst) in enumerate(links):
        if p < (i + 1) / (len(links) + 1):
            continue
        sxn, syn = nodes[src][0], nodes[src][1]
        dxn, dyn = nodes[dst][0], nodes[dst][1]
        x1, y1 = x0 + sxn + cw, y0 + syn + ch // 2
        x2, y2 = x0 + dxn, y0 + dyn + ch // 2
        draw.line((x1, y1, x2 - 16, y2), fill=(151, 171, 190), width=6)
        ang = math.atan2(y2 - y1, x2 - 16 - x1)
        draw.polygon(
            [
                (x2, y2),
                (x2 - 24 * math.cos(ang - 0.42), y2 - 24 * math.sin(ang - 0.42)),
                (x2 - 24 * math.cos(ang + 0.42), y2 - 24 * math.sin(ang + 0.42)),
            ],
            fill=(151, 171, 190),
        )
    for label, (nx, ny, color, ticks) in nodes.items():
        paper_card(draw, x0 + nx, y0 + ny, label, color, scale=scale, ticks=ticks)


def block_tile(draw, x, y, label, color):
    """A build block: kids-block frame holding the block's Blueprints."""
    bw, bh = 240, 170
    draw.rounded_rectangle((x + 8, y + 10, x + bw + 8, y + bh + 10), 18, fill=(199, 210, 221))
    draw.rounded_rectangle((x, y, x + bw, y + bh), 18, fill=color, outline=(30, 44, 58), width=4)
    draw.rounded_rectangle((x + 12, y + 44, x + bw - 12, y + bh - 12), 12, fill=(255, 255, 255))
    f = fit_font(draw, label, bw - 28, 26)
    draw.text((x + bw / 2, y + 24), label, font=f, fill=(255, 255, 255), anchor="mm")
    # Two mini Blueprint cards inside the block.
    for k in range(2):
        mx = x + 24 + k * 102
        my = y + 58
        draw.rounded_rectangle((mx, my, mx + 92, my + 96), 8, fill=PAPER, outline=LINE, width=2)
        draw.rectangle((mx, my, mx + 92, my + 22), fill=color)
        for j in range(3):
            draw.line(
                (mx + 10, my + 40 + j * 18, mx + 82, my + 40 + j * 18),
                fill=(173, 190, 204),
                width=2,
            )


def draw_qd_panel(draw, sx_left, t, tl):
    panel = tl.qd_panel
    w = panel["w"]
    if sx_left > WIDTH or sx_left + w < 0:
        return
    x0, y0 = int(sx_left), 170
    draw.rounded_rectangle(
        (x0, y0, x0 + w, y0 + 530), 26, fill=(255, 255, 255), outline=(142, 160, 180), width=4
    )
    # Blocks group stories in build order, read shelf by shelf.
    blocks = [
        ("Foundation", NAVY),
        ("Persistence", BLUE2),
        ("Search", GREEN),
        ("Reports", AMBER),
        ("User Interface", BLUE),
        ("Documentation", GREEN2),
    ]
    slots = [(230, 58), (530, 58), (830, 58), (230, 278), (530, 278), (830, 278)]
    for sy in (58, 278):
        draw.rectangle((x0 + 60, y0 + sy + 180, x0 + w - 60, y0 + sy + 194), fill=(210, 222, 234))
    draw.rounded_rectangle((x0 + 28, y0 + 470, x0 + 322, y0 + 516), 12, fill=NAVY)
    draw.text(
        (x0 + 175, y0 + 493), "QUARTERDECK", font=font(26, True), fill=(255, 255, 255), anchor="mm"
    )
    # Persistence and User Interface start in each other's slots; the cursor
    # drags them straight up and down into the correct build order.
    w0, w1 = panel["swap"]
    p = ease((t - w0) / max(0.001, w1 - w0)) if t > w0 else 0.0
    arc = math.sin(math.pi * min(1.0, p))
    start = {1: 4, 4: 1}
    cursor_at = None
    for i, (label, color) in enumerate(blocks):
        sx_slot, sy_slot = slots[start.get(i, i)]
        tx_slot, ty_slot = slots[i]
        x = x0 + int(lerp(sx_slot, tx_slot, p))
        y = y0 + int(lerp(sy_slot, ty_slot, p))
        if i == 1:
            x -= int(150 * arc)
            cursor_at = (x, y)
        elif i == 4:
            x += int(150 * arc)
        block_tile(draw, x, y, label, color)
    if 0.02 < p < 0.98 and cursor_at:
        cursor_arrow(draw, cursor_at[0] + 214, cursor_at[1] - 30)


def draw_rigging_bin(draw, sx, t, tl):
    if sx < -450 or sx > WIDTH + 450:
        return
    sx = int(sx)
    for lx in (sx - 232, sx + 192):
        draw.rectangle((lx, 500, lx + 40, 1004), fill=STEEL, outline=(116, 134, 152), width=2)
    draw.rounded_rectangle((sx - 260, 292, sx + 260, 456), 20, fill=NAVY, outline=STEEL, width=4)
    draw.text((sx, 344), "RIGGING", font=font(40, True), fill=(255, 255, 255), anchor="mm")
    draw.polygon(
        [(sx - 120, 456), (sx + 120, 456), (sx + 64, 522), (sx - 64, 522)], fill=(38, 58, 82)
    )
    # Cards still waiting inside the bin.
    slot_y = 404
    waiting = [d for d in tl.rig_drops if t < d[3]]
    for i, (label, color, _, _) in enumerate(waiting):
        bx = sx - 128 + i * 136
        draw.rounded_rectangle(
            (bx, slot_y, bx + 124, slot_y + 34), 8, fill=color, outline=(255, 255, 255), width=2
        )
        draw.text(
            (bx + 62, slot_y + 17), label, font=font(19, True), fill=(255, 255, 255), anchor="mm"
        )


def draw_truths(draw, t, tl):
    t0, t1 = tl.truths_window
    if not (t0 <= t <= t1):
        return
    f = font(30, True)
    for i, (label, x, y) in enumerate(tl.truths):
        a = ease(min((t - t0 - i * 0.45) / 0.4, (t1 - t) / 0.5))
        if a <= 0:
            continue
        w = 60 + int(f.getlength(label))
        aa = int(255 * a)
        draw.rounded_rectangle(
            (x, y, x + w, y + 66), 33, fill=(255, 255, 255, aa), outline=BLUE2 + (aa,), width=3
        )
        draw.ellipse((x + 16, y + 22, x + 38, y + 44), fill=GREEN + (aa,))
        draw.text((x + 52, y + 33), label, font=f, fill=NAVY + (aa,), anchor="lm")


# ---------------------------------------------------------------------------
# Cards on the belt
# ---------------------------------------------------------------------------


def draw_cards(draw, t, tl):
    cam = tl.cam(t)
    for cd in tl.cards:
        if not (cd["t_show"] <= t < cd["t_hide"]):
            continue
        kind = cd["kind"]
        # Position: cards fall straight down in camera frame, then ride.
        sx = cd["wx0"] + V * t - cam
        y_bottom = BELT_Y - 2
        drop = cd["drop"]
        if drop and t < drop[1]:
            q = (t - drop[0]) / (drop[1] - drop[0])
            y0 = cd["drop_from"]
            y_bottom = y0 + (BELT_Y - 2 - y0) * q * q
        elif drop and t < drop[1] + 0.35:
            q = (t - drop[1]) / 0.35
            y_bottom = BELT_Y - 2 - 16 * math.sin(math.pi * q)
        if kind == "crate":
            t_off = cd.get("t_off")
            if t_off is not None and t > t_off:
                slot_wx, slot_y = cd["slot"]
                q = min(1.0, (t - t_off) / 0.7)
                wx = lerp(tl.wx_end - 40, slot_wx, ease(q))
                sx = wx - cam
                y_bottom = BELT_Y - 2 + (slot_y - BELT_Y + 2) * q * q
                if q >= 1.0:
                    sx = slot_wx - cam
                    y_bottom = slot_y
            if -260 < sx < WIDTH + 260:
                crate_box(draw, sx, y_bottom)
            continue
        if sx < -340 or sx > WIDTH + 340:
            continue
        if kind == "ticket":
            ticket_slip(draw, sx + 66, y_bottom)
        else:
            h = int(188 * cd["scale"])
            paper_card(
                draw,
                int(sx),
                int(y_bottom - h),
                cd["label"],
                cd["color"],
                scale=cd["scale"],
                ticks=cd["ticks"],
                badge=cd["badge"],
            )


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------


def draw_headline(draw, t, tl):
    name, s, e, headline, sub = tl.scene_at(t)
    if not headline:
        return
    a = ease(min((t - s) / 0.5, (e - t) / 0.5))
    if a <= 0:
        return
    col = NAVY + (int(255 * a),)
    draw.text((120, 185), headline, font=FONT_H1, fill=col)
    if sub:
        draw.text((120, 268), sub, font=FONT_BODY, fill=MUTED + (int(255 * a),))


def draw_intro(frame, draw, t, tl):
    _, s, e, _, _ = tl.scenes[0]
    if t >= e:
        return
    a = ease(min(1.0, (e - t) / 0.6))
    pulse = 1 + 0.03 * math.sin(t * 6)
    paste_logo(frame, (WIDTH // 2, 300), int(270 * pulse), alpha=a)
    draw.text(
        (WIDTH // 2, 520), "Meet Drydock", font=FONT_TITLE, fill=NAVY + (int(255 * a),), anchor="mm"
    )
    draw.text(
        (WIDTH // 2, 615),
        "A complete delivery system for specification-driven developers",
        font=FONT_H2,
        fill=BLUE + (int(255 * a),),
        anchor="mm",
    )
    draw.rounded_rectangle(
        (700, 662, 1220, 716),
        20,
        fill=(235, 248, 241, int(255 * a)),
        outline=GREEN + (int(255 * a),),
        width=3,
    )
    draw.text(
        (960, 689),
        "Stable Alpha · Contributors Wanted",
        font=FONT_SMALL,
        fill=GREEN + (int(255 * a),),
        anchor="mm",
    )


def draw_tests_chip(draw, t, tl):
    t0, t1, wx0 = tl.tests_chip
    if not (t0 <= t <= t1):
        return
    a = ease(min((t - t0) / 0.4, (t1 - t) / 0.4))
    sx = wx0 + V * t - tl.cam(t)
    x, y = int(sx - 40), 520
    draw.rounded_rectangle(
        (x, y, x + 290, y + 64),
        18,
        fill=(226, 248, 238, int(255 * a)),
        outline=GREEN + (int(255 * a),),
        width=3,
    )
    draw.text(
        (x + 145, y + 32),
        "Tests Passing",
        font=font(30, True),
        fill=GREEN + (int(255 * a),),
        anchor="mm",
    )


def draw_cta(frame, draw, t, tl):
    t0 = tl.t_stop + 1.0
    if t < t0:
        return
    a = ease((t - t0) / 1.2)
    draw.rounded_rectangle(
        (230, 138, 1690, 620),
        30,
        fill=(255, 255, 255, int(242 * a)),
        outline=(198, 212, 224, int(255 * a)),
        width=3,
    )
    paste_logo(frame, (960, 258), 170, alpha=a)
    draw.text(
        (960, 400), "Take it for a sail.", font=FONT_TITLE, fill=NAVY + (int(255 * a),), anchor="mm"
    )
    draw.text(
        (960, 492),
        "WebCloudStudio.com",
        font=font(58, True),
        fill=BLUE + (int(255 * a),),
        anchor="mm",
    )
    draw.text(
        (960, 570),
        "Stable Alpha  ·  MIT Licensed  ·  Contributors Wanted",
        font=FONT_BODY,
        fill=GREEN + (int(255 * a),),
        anchor="mm",
    )


# ---------------------------------------------------------------------------
# Frame assembly
# ---------------------------------------------------------------------------


def frame_at(t: float, tl: Timeline) -> Image.Image:
    frame = Image.new("RGBA", (WIDTH, HEIGHT), BG + (255,))
    draw = ImageDraw.Draw(frame, "RGBA")
    cam = tl.cam(t)
    draw_background(draw, cam)
    draw_floor(draw, cam)
    # Wall panels and structures behind the belt line.
    draw_manifest_panel(draw, tl.manifest_panel["wx"] - cam, t, tl)
    draw_qd_panel(draw, tl.qd_panel["wx"] - cam, t, tl)
    draw_rigging_bin(draw, tl.rig_bin_wx - cam, t, tl)
    draw_belt(draw, t, tl)
    draw_cards(draw, t, tl)
    # Gantries on top, so cards pass through them.
    for g in tl.gantries:
        active = 0.0
        for ev in g["events"]:
            active = max(active, 1.0 - abs(t - ev) / 0.5)
        draw_gantry(frame, draw, g["wx"] - cam, g["cmd"], max(0.0, active), t)
    draw_tests_chip(draw, t, tl)
    draw_header(draw)
    draw_headline(draw, t, tl)
    draw_truths(draw, t, tl)
    draw_intro(frame, draw, t, tl)
    draw_cta(frame, draw, t, tl)
    draw.rectangle((0, HEIGHT - 14, int(WIDTH * min(1, t / tl.duration)), HEIGHT), fill=GREEN)
    return frame.convert("RGB")


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def write_music(path: Path, option: int, duration: float, sample_rate: int = 44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    total = int(duration * sample_rate)
    t = np.arange(total, dtype=np.float64) / sample_rate
    bpm = [108, 124, 96][option - 1]
    beat = 60.0 / bpm
    step = (t / (beat / 2)).astype(np.int64)
    env = np.exp(-(t % (beat / 2)) * 9)
    if option == 1:
        tone = np.sin(2 * np.pi * 176 * t) * env * 0.16
        click = np.sin(2 * np.pi * 1200 * t) * np.exp(-(t % beat) * 45) * 0.08
    elif option == 2:
        freqs = np.array([220, 277, 330, 440, 554, 660], dtype=np.float64)
        f = freqs[step % len(freqs)]
        tone = np.sin(2 * np.pi * f * t) * env * 0.17
        tone += np.sin(2 * np.pi * (f * 2) * t) * env * 0.05
        click = np.sin(2 * np.pi * 920 * t) * np.exp(-(t % (beat / 2)) * 38) * 0.09
    else:
        f = np.where(step % 4 == 0, 247.0, 196.0)
        tone = np.sin(2 * np.pi * f * t) * env * 0.12
        click = np.sin(2 * np.pi * 700 * t) * np.exp(-(t % beat) * 28) * 0.06
    pad = np.sin(2 * np.pi * 82.4 * t) * 0.035
    data = tone + click + pad
    fade = int(sample_rate * 1.2)
    data[:fade] *= np.linspace(0, 1, fade)
    data[-fade:] *= np.linspace(1, 0, fade)
    data = np.clip(data, -0.7, 0.7)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes((data * 32767).astype("<i2").tobytes())


async def write_voice(path: Path):
    import edge_tts

    path.parent.mkdir(parents=True, exist_ok=True)
    communicator = edge_tts.Communicate(
        voice_text(),
        voice="en-US-AvaMultilingualNeural",
        rate="+0%",
        volume="+0%",
    )
    await communicator.save(str(path))


def probe_duration(path: Path) -> float:
    result = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
    if not match:
        raise RuntimeError(f"could not probe duration of {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_WORKER_TL: Timeline | None = None


def _init_worker(duration: float):
    global _WORKER_TL
    _WORKER_TL = Timeline(duration)


def _render_frame_bytes(frame_no: int) -> bytes:
    assert _WORKER_TL is not None
    return frame_at(frame_no / FPS, _WORKER_TL).tobytes()


def render_silent_video(path: Path, tl: Timeline):
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
    frames = int(tl.duration * FPS)
    workers = max(2, (multiprocessing.cpu_count() or 4) - 1)
    with multiprocessing.Pool(workers, _init_worker, (tl.duration,)) as pool:
        for frame_no, data in enumerate(pool.imap(_render_frame_bytes, range(frames), chunksize=8)):
            proc.stdin.write(data)
            if frame_no % (FPS * 10) == 0:
                print(f"  frame {frame_no}/{frames}")
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg video render failed with exit code {rc}")


def mux_audio(video: Path, voice: Path, music: Path, out: Path, duration: float):
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
        f"[1:a]volume=1.15[a1];[2:a]volume=0.18,afade=t=out:st={duration - 3}:d=3[a2];"
        f"[a1][a2]amix=inputs=2:duration=longest:dropout_transition=0[a]",
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


def write_stills(tl: Timeline):
    STILLS.mkdir(parents=True, exist_ok=True)
    for old in STILLS.glob("still_*.png"):
        old.unlink()
    base_times = [
        2.5,
        7,
        10,
        13,
        15.5,
        20,
        22.5,
        25,
        31,
        34,
        40,
        44,
        49.5,
        52,
        57,
        59,
        64,
        66.5,
        71.5,
        74,
        78.5,
        80.5,
        83.5,
        86.5,
    ]
    for bt in base_times:
        t = min(bt * tl.s, tl.duration - 0.05)
        frame_at(t, tl).save(STILLS / f"still_{int(bt):02d}.png")
    print(f"Wrote {len(base_times)} stills to {STILLS}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stills", action="store_true", help="render review stills only")
    parser.add_argument("--no-voice", action="store_true", help="reuse the existing narration file")
    args = parser.parse_args()

    AUDIO.mkdir(exist_ok=True)
    RENDERS.mkdir(exist_ok=True)

    voice = AUDIO / "voiceover_ava_neural.mp3"
    if not args.no_voice and not args.stills:
        asyncio.run(write_voice(voice))
    duration = probe_duration(voice) + 3.0 if voice.exists() else 96.0
    tl = Timeline(duration)
    print(f"Narration-scaled duration: {duration:.1f}s (scale {tl.s:.3f})")

    if args.stills:
        write_stills(tl)
        return

    music_paths = [
        AUDIO / "music_option_1_clean_pulse.wav",
        AUDIO / "music_option_2_bright_ditty.wav",
        AUDIO / "music_option_3_minimal_drive.wav",
    ]
    for idx, path in enumerate(music_paths, start=1):
        write_music(path, idx, duration)

    write_stills(tl)
    silent = RENDERS / "drydock-announcement-silent.mp4"
    final = RENDERS / "drydock-announcement-first-cut.mp4"
    render_silent_video(silent, tl)
    mux_audio(silent, voice, music_paths[0], final, duration)
    print(f"Wrote {final}")
    print(f"Music options: {', '.join(str(p) for p in music_paths)}")


if __name__ == "__main__":
    main()
