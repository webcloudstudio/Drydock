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
import json
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
# Gate geometry. Cards are drawn from their left edge, so the gate is offset by
# half a card to straddle the card that is converting under it. GATE_HALF is the
# half-distance between the two posts.
GATE_DX = 121
GATE_HALF = 79
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

# Narration pacing: each sentence is synthesized separately and joined with
# these silences. Adjust the constants, or use a cue in voiceover_script.txt:
# `(pause)` adds PAUSE_UNIT wherever it appears (repeat it for a longer beat);
# a paragraph of `[pause 1.5]` sets an exact gap at that point.
SENTENCE_GAP = 0.55
PARAGRAPH_GAP = 1.05
PAUSE_UNIT = 0.35

VOICE_NAME = "en-US-AvaMultilingualNeural"
VOICE_RATE = "+0%"
VOICE_PITCH = "+0Hz"

# Gantry sync. The lead input card (belt position 840) finishes converting this
# long after its command is named, so the machine engages on the word and its
# outputs stream out while the narrator describes them. RIDE_IN is how long a
# dropped input rides the belt before it reaches the machine.
CONVERT_OFFSET = 0.35
RIDE_IN = 5.4

# The delivery build. The refit sentence names both commands ("conformed with
# drydock refit, and delivered with drydock build"), so the narration carries a
# single mark for it. The second build gate engages this long after the refit
# gate, which is where "delivered with drydock build" lands in the read.
REFIT_TO_DELIVER = 3.4

# The opening "Meet Drydock" title holds for its own sentence and fades out as
# the narrator starts the next one ("Drydock works with larger specifications"),
# handing the screen to the belt. It tracks the spoken word, not a machine, so
# MARK_OFFSETS does not drag the title around.

# Per-command timing nudges (seconds), applied on top of the narration marks.
# Negative moves a beat earlier ("back"); positive moves it later. Each nudge
# moves that machine together with its headline and wall panel.
# import, analyze, plan, manifest, quarterdeck, build, refit, truths, cta.
MARK_OFFSETS = {
    "import": 2.1,
    "analyze": 3.6,
    "plan": 2.3,
    "manifest": -1.2,
    "quarterdeck": -0.3,
    "build": 2.2,
    "refit": 0.5,
}

VOICE_FALLBACK = """Meet Drydock: a complete delivery system for specification-driven developers.

Drydock works with larger specifications, including multi-file specs and imports from other tools.

Drydock import brings in specifications, notes, and other material.

Drydock analyze proposes an Agile plan with features, stories, questions, blockers, and acceptance criteria.

Drydock plan converts your specifications into governed Blueprints. Each Blueprint carries Test-Driven Development tests. Plan also builds the Manifest: a graph database relating your stories, your stack, and your branding.

Then shape the build in the QuarterDeck web server: group stories into blocks of Blueprints and set the build order.

Drydock also supports enterprise branding and stack rules, so applications keep consistent look, behavior, and documentation.

Drydock build walks the graph block by block, verifying each story against its tests and producing working software.

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


MARKS_PATH = AUDIO / "narration_marks.json"


def load_marks() -> dict | None:
    """Return per-command narration timestamps written by the last synthesis."""
    if MARKS_PATH.exists():
        try:
            return json.loads(MARKS_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
    return None


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


def composite(frame: Image.Image, layer: Image.Image, x: int, y: int):
    """Alpha-composite a layer onto the frame, clipped to the frame bounds."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(WIDTH, x + layer.width), min(HEIGHT, y + layer.height)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + layer.width, y + layer.height):
        layer = layer.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    frame.alpha_composite(layer, (x0, y0))


def paste_logo(frame: Image.Image, center, size, alpha=1.0):
    logo = LOGO_IMG.copy()
    logo.thumbnail((size, size), Image.Resampling.LANCZOS)
    if alpha < 1.0:
        a = logo.getchannel("A").point(lambda v: int(v * alpha))
        logo.putalpha(a)
    composite(frame, logo, int(center[0] - logo.width / 2), int(center[1] - logo.height / 2))


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class Timeline:
    """All world positions and event times, scaled to the narration length."""

    def __init__(self, duration: float, marks: dict | None = None):
        self.duration = duration
        s = duration / BASE_END
        self.s = s
        sc = lambda x: x * s  # noqa: E731

        # Narration marks (video-time seconds) drive every machine so each
        # command engages as it is spoken. Real marks come from voice synthesis
        # (audio/narration_marks.json); absent that, base timing stands in.
        fallback = {
            "specs": sc(6.5),
            "import": sc(11.5),
            "analyze": sc(21.0),
            "plan": sc(30.0),
            "manifest": sc(38.0),
            "quarterdeck": sc(48.0),
            "build": sc(64.5),
            "refit": sc(75.0),
            "truths": sc(78.0),
            "cta": sc(82.0),
        }
        if marks is None:
            marks = load_marks()
        mk = dict(fallback)
        if marks:
            for key, value in marks.items():
                if key in mk and isinstance(value, (int, float)):
                    mk[key] = float(value)
        # The title clears as the second sentence begins, before the nudges.
        intro_end = mk["specs"]
        for key, delta in MARK_OFFSETS.items():
            if key in mk:
                mk[key] += delta
        # The delivery build has no spoken mark of its own; it trails refit by a
        # fixed gap, and follows refit whenever refit moves.
        mk["deliver"] = mk["refit"] + REFIT_TO_DELIVER + MARK_OFFSETS.get("deliver", 0.0)
        self.marks = mk
        mi, ma, mp = mk["import"], mk["analyze"], mk["plan"]
        mman, mqd = mk["manifest"], mk["quarterdeck"]
        mb, mr = mk["build"], mk["refit"]
        mc = mk["cta"]

        # A gantry arrival puts its lead input (belt position 840) at the machine
        # center; that card finishes converting CONVERT_OFFSET after the command
        # word, so outputs stream out as the narrator describes them.
        def arrival(mark: float) -> float:
            return mark + CONVERT_OFFSET - (GANTRY_SX - 840) / V

        t_import = arrival(mi)
        t_analyze = arrival(ma)
        t_plan = arrival(mp)
        t_build = arrival(mb)
        t_refit = arrival(mr)
        t_deliver = arrival(mk["deliver"])

        # Camera: locked to belt speed, then eased to a stop for the closer.
        self.t_stop = mc + 0.2
        self.stop_len = 3.0
        self.cam_final = V * self.t_stop + V * self.stop_len / 2

        # Headlines track the marks: a section's headline rises ~2.5s before its
        # command is named and clears as the next section begins. The closer
        # beats hold on fixed video-time seconds so they pace the long tail.
        mt = mk["truths"]
        # The tail sections hang off the "engineering truths" mark, like every
        # other beat. They used to sit on fixed video-time seconds, which drifted
        # the moment the narration changed length.
        refit_end = mt - 6.0  # refit headline stops here
        decompose_end = mt - 1.0  # "decomposes" section runs refit_end -> here
        truths_end = self.t_stop + 1.0  # "engineering truths" holds until the closer banner
        self.scenes = [
            ("intro", 0.0, intro_end, "", ""),
            ("import", intro_end, ma - 2.5, "Import your Project", ""),
            ("analyze", ma - 2.5, mp - 2.5, "Agile Story Planning", ""),
            ("plan", mp - 2.5, mman - 0.3, "Test Driven Development", ""),
            ("manifest", mman - 0.3, mqd - 2.0, "A Graph Build Database", ""),
            ("quarterdeck", mqd - 2.0, mb - 2.5, "", ""),
            ("build", mb - 2.5, mr - 2.5, "Build steps verified", ""),
            (
                "refit",
                mr - 2.5,
                refit_end,
                "",
                "",
            ),
            (
                "decompose",
                refit_end,
                decompose_end,
                "Uses Existing Best Practices",
                "",
            ),
            ("truths", decompose_end, truths_end, "Built on engineering truths", ""),
            ("cta", truths_end, duration, "", ""),
        ]

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
            sections=None,
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
                    sections=sections,
                )
            )

        # Every machine's outputs reuse the belt positions of the inputs they
        # replace, so each output emerges the instant its input converts —
        # no dead time inside a gantry.
        # Inputs drop onto the belt and ride RIDE_IN seconds into IMPORT.
        for label, color, wx0 in [
            ("Specification", BLUE2, 840),
            ("Notes", GREEN, 520),
            ("Material", AMBER, 200),
        ]:
            cin = c(t_import, wx0)
            td = cin - RIDE_IN
            card("card", label, color, wx0, td, cin, drop=(td, td + 0.8), drop_from=390)
        # IMPORT output: same cards, imported, at the same positions.
        for label, color, wx0 in [
            ("Imported Specification", BLUE2, 840),
            ("Imported Notes", GREEN, 520),
            ("Imported Material", AMBER, 200),
        ]:
            card("card", label, color, wx0, c(t_import, wx0), c(t_analyze, wx0), badge=True)
        # ANALYZE output: the Agile plan, spread across the input span.
        for label, color, wx0, ticks in [
            ("Stories", GREEN, 840, True),
            ("Questions", AMBER, 595, False),
            ("Blockers", RED, 350, False),
            ("Acceptance Criteria", BLUE2, 105, True),
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
        card(
            "card",
            "Blueprints",
            GREEN,
            840,
            c(t_plan, 840),
            c(t_build, 840),
            ticks=True,
            sections=["Behavior", "Acceptance", "Guardrails"],
        )
        card("card", "Manifest", BLUE2, 580, c(t_plan, 580), c(t_build, 580))
        # BUILD output: a Working Software crate. It rides into REFIT.
        card("crate", "", GREEN, 840, c(t_build, 840), c(t_refit, 840))
        # Change tickets drop in behind the working software and follow it
        # into REFIT.
        for wx0 in [580, 430, 280]:
            cin = c(t_refit, wx0)
            td = cin - 3.0
            card("ticket", "CHANGE", AMBER, wx0, td, cin, drop=(td, td + 0.7), drop_from=430)
        # REFIT output: a conformed Blueprint and Manifest, exactly what PLAN
        # emits, riding on into the delivery BUILD.
        card(
            "card",
            "Blueprint",
            GREEN,
            840,
            c(t_refit, 840),
            c(t_deliver, 840),
            ticks=True,
            sections=["Behavior", "Acceptance", "Guardrails"],
        )
        card("card", "Manifest", BLUE2, 580, c(t_refit, 580), c(t_deliver, 580))
        # DELIVERY BUILD output: one Working Software crate, riding to the end
        # of the line.
        card("crate", "", GREEN, 840, c(t_deliver, 840), duration + 10)

        self.gantries = []
        for cmd, t_arr in [
            ("drydock import", t_import),
            ("drydock analyze", t_analyze),
            ("drydock plan", t_plan),
            ("drydock build", t_build),
            ("drydock refit", t_refit),
            ("drydock build", t_deliver),
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

        # Wall panels above the belt, centered on screen as they are narrated.
        mpanel_w = 1180
        self.manifest_panel = dict(
            wx=960 - mpanel_w / 2 + V * (mman + 2.0), w=mpanel_w, anim=(mman, mman + 5.0)
        )
        qd_w = 960
        self.qd_panel = dict(
            wx=960 - qd_w / 2 + V * (mqd + 3.5), w=qd_w, swap=(mqd + 1.0, mqd + 4.5)
        )
        # The floating truth chips ride with the "engineering truths" headline.
        self.truths_window = (decompose_end, truths_end)
        self.truths = [
            ("Agile planning", 150, 300),
            ("Test-Driven Development", 780, 300),
            ("Build Graph", 150, 392),
            ("Context Optimization", 780, 392),
        ]
        # Both builds raise the same "Tests Passing" chip over the crate they
        # produce.
        self.tests_chips = [(c(t, 840) + 0.5, c(t, 840) + 2.8, 840) for t in (t_build, t_deliver)]

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


def paper_card(draw, x, y, title, color, scale=1.0, ticks=False, badge=False, sections=None):
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
    rows = sections if sections else [None, None, None]
    for item in rows:
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
        if item:
            draw.text(
                (x0, yy), item, font=font(max(15, int(21 * scale)), False), fill=MUTED, anchor="lm"
            )
        else:
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
    """A slim gate: two posts, a signed header, and a light curtain.

    The gate is a scanner, not an enclosure. A card converts as its center
    crosses the curtain, and the curtain flares to white at that instant, so the
    swap is covered by light rather than by a solid shroud.
    """
    if sx < -520 or sx > WIDTH + 520:
        return
    gx = int(sx) + GATE_DX  # gate center sits on the card center at conversion
    glow = ease(active)
    lit = glow > 0.3
    accent = GREEN2 if lit else (110, 132, 156)
    # Posts: thin steel columns just clear of the passing card.
    for lx in (gx - GATE_HALF - 14, gx + GATE_HALF):
        draw.rectangle((lx, 352, lx + 14, 1004), fill=STEEL, outline=(116, 134, 152), width=1)
        draw.rectangle((lx - 6, 996, lx + 20, 1006), fill=STEEL_DARK)
        draw.rectangle((lx - 3, 366, lx + 17, 374), fill=(116, 134, 152))
    # Header beam.
    draw.rounded_rectangle(
        (gx - GATE_HALF - 22, 330, gx + GATE_HALF + 22, 358),
        8,
        fill=(214, 224, 233),
        outline=STEEL,
        width=2,
    )
    # Command sign hanging above the beam.
    sign_w = 200
    sign = (gx - sign_w, 258, gx + sign_w, 322)
    if glow > 0.05:
        draw.rounded_rectangle(
            (sign[0] - 7, sign[1] - 7, sign[2] + 7, sign[3] + 7),
            16,
            fill=(67, 210, 143, int(110 * glow)),
        )
    draw.rounded_rectangle(sign, 12, fill=NAVY, outline=GREEN2 if lit else BLUE2, width=3)
    draw.text((gx + 24, 290), cmd, font=FONT_CMD, fill=(255, 255, 255), anchor="mm")
    paste_logo(frame, (gx - sign_w + 44, 290), 40)
    draw.line((gx, 322, gx, 330), fill=STEEL_DARK, width=4)
    # Status lamp on the beam.
    draw.ellipse(
        (gx + GATE_HALF + 4, 336, gx + GATE_HALF + 26, 358),
        fill=GREEN2 if lit else (120, 138, 156),
        outline=(90, 106, 122),
        width=2,
    )
    # Light curtain from the beam to the belt: a translucent standing beam that
    # flares white as the card under it converts. Composited as its own layer;
    # ImageDraw alpha fills do not blend onto an RGBA frame.
    top, bottom = 358, BELT_Y - 2
    curtain = Image.new("RGBA", (2 * GATE_HALF, bottom - top), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(curtain)
    cw, ch = curtain.size
    cdraw.rectangle((0, 0, cw, ch), fill=(67, 210, 143, int(26 + 60 * glow)))
    for ly in range(12, ch, 44):
        cdraw.line((0, ly, cw, ly), fill=(67, 210, 143, int(34 + 80 * glow)), width=2)
    flare = glow * glow
    if flare > 0.02:
        cdraw.rectangle((0, 0, cw, ch), fill=(244, 255, 249, int(240 * flare)))
    cdraw.line((0, 0, 0, ch), fill=accent + (255,), width=6)
    cdraw.line((cw - 1, 0, cw - 1, ch), fill=accent + (255,), width=6)
    composite(frame, curtain, gx - GATE_HALF, top)
    # Scanner head: a small gear under the beam, spinning up as a card converts.
    cx, cy, pr = gx, 392, 30
    draw.ellipse((cx - pr, cy - pr, cx + pr, cy + pr), fill=NAVY, outline=STEEL, width=3)
    gr = 20
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
            fill=accent,
            width=4,
        )
    draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=accent)
    # Hazard strip on the belt under the gate.
    for hx in range(gx - GATE_HALF, gx + GATE_HALF - 16, 34):
        draw.polygon(
            [(hx, BELT_Y + 8), (hx + 17, BELT_Y + 8), (hx + 5, BELT_Y - 2), (hx - 12, BELT_Y - 2)],
            fill=AMBER,
        )
    draw.rectangle((gx - GATE_HALF, BELT_Y + 8, gx + GATE_HALF, BELT_Y + 14), fill=NAVY)
    # Conversion sparks at the exit side.
    if glow > 0.25:
        ex, ey = gx + GATE_HALF + 6, BELT_Y - 30
        for k in range(6):
            a = -0.9 + k * 0.36
            ln = 16 + 24 * glow
            draw.line(
                (
                    ex + 8 * math.cos(a),
                    ey + 8 * math.sin(a),
                    ex + (8 + ln) * math.cos(a),
                    ey + (8 + ln) * math.sin(a),
                ),
                fill=AMBER,
                width=4,
            )


def block_frame(draw, x, y, w, h, label, color):
    """A build block: kids-block frame with a labeled band and white interior."""
    draw.rounded_rectangle((x + 8, y + 10, x + w + 8, y + h + 10), 18, fill=(199, 210, 221))
    draw.rounded_rectangle((x, y, x + w, y + h), 18, fill=color, outline=(30, 44, 58), width=4)
    draw.rounded_rectangle((x + 12, y + 46, x + w - 12, y + h - 12), 12, fill=(255, 255, 255))
    f = fit_font(draw, label, w - 32, 27)
    draw.text((x + w / 2, y + 25), label, font=f, fill=(255, 255, 255), anchor="mm")


def _arrow(draw, x1, y1, x2, y2, color, width=6):
    draw.line((x1, y1, x2 - 14, y2), fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - 14 - x1)
    draw.polygon(
        [
            (x2, y2),
            (x2 - 22 * math.cos(ang - 0.42), y2 - 22 * math.sin(ang - 0.42)),
            (x2 - 22 * math.cos(ang + 0.42), y2 - 22 * math.sin(ang + 0.42)),
        ],
        fill=color,
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
    a0, a1 = panel["anim"]
    p = ease((t - a0) / max(0.001, a1 - a0))
    light = (203, 219, 233)
    dark = (151, 171, 190)
    # Stack and Rigging feed every block: light arrows, drawn behind.
    feeds = [
        (258, 145, 330, 220),
        (258, 145, 690, 120),
        (258, 375, 330, 300),
        (258, 375, 690, 410),
    ]
    for i, (ax, ay, bx, by) in enumerate(feeds):
        if p >= (i + 1) / 7:
            _arrow(draw, x0 + ax, y0 + ay, x0 + bx, y0 + by, light)
    paper_card(
        draw,
        x0 + 30,
        y0 + 70,
        "Stack",
        NAVY,
        scale=0.8,
        sections=["Database", "Web", "Technology"],
    )
    paper_card(draw, x0 + 30, y0 + 300, "Rigging", BLUE, scale=0.8, sections=["Branding", "Rules"])
    # Blocks group the stories; stories link to each other across blocks.
    block_frame(draw, x0 + 330, y0 + 150, 290, 220, "Block 1", BLUE2)
    paper_card(draw, x0 + 381, y0 + 216, "Story 1", BLUE2, scale=0.66, ticks=True)
    block_frame(draw, x0 + 690, y0 + 50, 420, 400, "Block 2", GREEN)
    paper_card(draw, x0 + 806, y0 + 114, "Story 2", BLUE2, scale=0.66, ticks=True)
    paper_card(draw, x0 + 806, y0 + 290, "Story 3", BLUE2, scale=0.66, ticks=True)
    for i, (ax, ay, bx, by) in enumerate([(569, 278, 806, 176), (569, 278, 806, 352)]):
        if p >= (i + 5) / 7:
            _arrow(draw, x0 + ax, y0 + ay, x0 + bx, y0 + by, dark)


def block_tile(draw, x, y, label, color):
    """A build block: kids-block frame holding the block's Blueprints."""
    bw, bh = 240, 170
    draw.rounded_rectangle((x + 8, y + 10, x + bw + 8, y + bh + 10), 18, fill=(199, 210, 221))
    draw.rounded_rectangle((x, y, x + bw, y + bh), 18, fill=color, outline=(30, 44, 58), width=4)
    draw.rounded_rectangle((x + 12, y + 44, x + bw - 12, y + bh - 12), 12, fill=(255, 255, 255))
    f = fit_font(draw, label, bw - 28, 26)
    draw.text((x + bw / 2, y + 24), label, font=f, fill=(255, 255, 255), anchor="mm")
    # Two mini Blueprint cards inside the block, showing their sections.
    for k in range(2):
        mx = x + 24 + k * 102
        my = y + 58
        draw.rounded_rectangle((mx, my, mx + 92, my + 96), 8, fill=PAPER, outline=LINE, width=2)
        draw.rectangle((mx, my, mx + 92, my + 22), fill=color)
        draw.text(
            (mx + 46, my + 11), "Story", font=font(13, True), fill=(255, 255, 255), anchor="mm"
        )
        for j, sec in enumerate(["Behavior", "Accepts", "Guards"]):
            draw.text(
                (mx + 10, my + 38 + j * 21), sec, font=font(14, False), fill=MUTED, anchor="lm"
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
        ("Feature 1", GREEN),
        ("Feature 2", AMBER),
        ("User Interface", BLUE),
        ("Documentation", GREEN2),
    ]
    slots = [(60, 58), (360, 58), (660, 58), (60, 278), (360, 278), (660, 278)]
    for sy in (58, 278):
        draw.rectangle((x0 + 60, y0 + sy + 180, x0 + w - 60, y0 + sy + 194), fill=(210, 222, 234))
    draw.rounded_rectangle((x0 + 28, y0 + 470, x0 + 322, y0 + 516), 12, fill=NAVY)
    draw.text(
        (x0 + 175, y0 + 493), "QUARTERDECK", font=font(26, True), fill=(255, 255, 255), anchor="mm"
    )
    # Feature 1 and Feature 2 start nudged out into the corner aisle beside
    # their slots; the cursor slides each into build order in turn (Feature 1
    # first, then Feature 2).
    w0, w1 = panel["swap"]
    span = max(0.001, w1 - w0)
    p1 = ease(min(1.0, (t - w0) / (span * 0.5))) if t > w0 else 0.0
    p2 = ease(min(1.0, (t - w0 - span * 0.5) / (span * 0.5))) if t > w0 + span * 0.5 else 0.0
    # Per-block starting offset (dx, dy), removed as the block is dragged home.
    nudge = {2: (54, -50), 3: (-54, 72)}
    progress = {2: p1, 3: p2}
    cursor_at = None
    for i, (label, color) in enumerate(blocks):
        tx, ty = slots[i]
        x, y = x0 + tx, y0 + ty
        if i in nudge:
            dx, dy = nudge[i]
            pr = progress[i]
            x += int(dx * (1 - pr))
            y += int(dy * (1 - pr))
            if 0.03 < pr < 0.97:
                cursor_at = (x, y)
        block_tile(draw, x, y, label, color)
    if cursor_at:
        cursor_arrow(draw, cursor_at[0] + 214, cursor_at[1] - 30)


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
                sections=cd["sections"],
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
    # Sits just below the header divider (y=118), clear of the gantry signs.
    draw.text((120, 134), headline, font=FONT_H1, fill=col)
    if sub:
        draw.text((120, 217), sub, font=FONT_BODY, fill=MUTED + (int(255 * a),))


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
        "A complete delivery system for specification-driven applications",
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
    for t0, t1, wx0 in tl.tests_chips:
        if not (t0 <= t <= t1):
            continue
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


PAUSE_CUE = re.compile(r"\(\s*pause\s*\)", re.IGNORECASE)


def narration_segments(text: str):
    """Split the script into ("speak", sentence) and ("gap", seconds) segments.

    Blank lines separate paragraphs (PARAGRAPH_GAP before the next one).
    Sentences within a paragraph are separated by SENTENCE_GAP. Each `(pause)`
    cue adds PAUSE_UNIT on top of the gap already in force at that point, so
    repeating the cue lengthens the beat. A paragraph consisting only of
    `[pause 1.5]` sets an exact gap instead.
    """
    # Pass one: flatten the script into sentences and the gap cues between them.
    items = []
    for paragraph in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        directive = re.fullmatch(r"\[pause\s+([\d.]+)\]", paragraph, re.IGNORECASE)
        if directive:
            items.append(("exact", float(directive.group(1))))
            continue
        chunks = PAUSE_CUE.split(paragraph)
        for i, chunk in enumerate(chunks):
            for sentence in re.split(r"(?<=[.!?])\s+", chunk.strip()):
                if sentence:
                    items.append(("speak", sentence))
            if i < len(chunks) - 1:
                items.append(("cue", PAUSE_UNIT))
        items.append(("paragraph", PARAGRAPH_GAP))

    # Pass two: resolve the gap before each sentence. The natural gap is the
    # sentence or paragraph break; cues add to it; `[pause N]` replaces it.
    segments = []
    natural, cues, exact = 0.0, 0, None
    for kind, value in items:
        if kind == "cue":
            cues += 1
        elif kind == "paragraph":
            natural = max(natural, value)
        elif kind == "exact":
            natural, cues, exact = 0.0, 0, value
        else:
            gap = exact if exact is not None else natural + cues * PAUSE_UNIT
            if segments and gap > 0:
                segments.append(("gap", round(gap, 3)))
            segments.append(("speak", value))
            natural, cues, exact = SENTENCE_GAP, 0, None
    return segments


def _trim_silence(samples: np.ndarray, sample_rate: int, threshold: int = 260) -> np.ndarray:
    """Cut edge-tts's inconsistent leading/trailing silence off a segment."""
    loud = np.where(np.abs(samples.astype(np.int32)) > threshold)[0]
    if len(loud) == 0:
        return samples
    lo = max(0, int(loud[0]) - int(0.04 * sample_rate))
    hi = min(len(samples), int(loud[-1]) + int(0.10 * sample_rate))
    return samples[lo:hi]


def save_marks(spoken, voice_duration: float):
    """Write per-command narration timestamps from the synthesized sentences.

    `spoken` is a list of (start_seconds, sentence_text). The video clock and the
    voice clock share an origin, so these start times are the moments each
    command is named — exactly what the timeline anchors machines to.
    """

    def find(phrase: str):
        for start, text in spoken:
            if phrase.lower() in text.lower():
                return round(start, 3)
        return None

    marks = {
        # The sentence after the "Meet Drydock" line: the title clears on it.
        "specs": find("works with larger specifications"),
        "import": find("drydock import"),
        "analyze": find("drydock analyze"),
        "plan": find("drydock plan"),
        "manifest": find("Manifest is a graph database"),
        "quarterdeck": find("QuarterDeck"),
        "build": find("drydock build"),
        "refit": find("drydock refit"),
        "truths": find("engineering truths"),
        "cta": find("Take it for a sail"),
        "voice_duration": round(voice_duration, 3),
    }
    marks = {k: v for k, v in marks.items() if v is not None}
    MARKS_PATH.write_text(json.dumps(marks, indent=2), encoding="utf-8")


async def write_voice(path: Path):
    import edge_tts

    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 24000
    exe = ffmpeg_exe()
    tmp = path.parent / "_segments"
    tmp.mkdir(exist_ok=True)
    pieces = []
    spoken = []  # (start_seconds, sentence_text) for each synthesized sentence
    clock = 0.0
    for i, (kind, value) in enumerate(narration_segments(voice_text())):
        if kind == "gap":
            n = int(sample_rate * value)
            pieces.append(np.zeros(n, dtype=np.int16))
            clock += n / sample_rate
            continue
        seg_mp3 = tmp / f"seg_{i:03d}.mp3"
        communicator = edge_tts.Communicate(
            value, voice=VOICE_NAME, rate=VOICE_RATE, pitch=VOICE_PITCH, volume="+0%"
        )
        await communicator.save(str(seg_mp3))
        decoded = subprocess.run(
            [exe, "-i", str(seg_mp3), "-f", "s16le", "-ar", str(sample_rate), "-ac", "1", "-"],
            capture_output=True,
            check=True,
        )
        samples = _trim_silence(np.frombuffer(decoded.stdout, dtype=np.int16), sample_rate)
        spoken.append((clock, value))
        pieces.append(samples)
        clock += len(samples) / sample_rate
    data = np.concatenate(pieces)
    subprocess.run(
        [
            exe,
            "-y",
            "-f",
            "s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-i",
            "-",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(path),
        ],
        input=data.tobytes(),
        check=True,
    )
    shutil.rmtree(tmp)
    save_marks(spoken, clock)


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
        # apad/atrim let a supplied track that is shorter than the video run to
        # the end on silence instead of cutting the bed off mid-video; for the
        # generated beds, which are cut to length, they do nothing.
        f"[1:a]volume=1.15[a1];"
        f"[2:a]volume=0.18,apad,atrim=0:{duration},"
        f"afade=t=out:st={duration - 3}:d=3[a2];"
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
    mk = tl.marks
    times = [2.5]  # intro
    # Each machine: entering just before the word, converting on the word, and
    # streaming its outputs just after.
    for key in ("import", "analyze", "plan", "build", "refit", "deliver"):
        m = mk[key]
        times += [m - 0.8, m + 0.7, m + 2.4]
    # Wall panels and closer, centered on their narration.
    times += [mk["manifest"] + 2.0, mk["quarterdeck"] + 3.5]
    # Closer beats: the "decomposes" section, the "engineering truths" hold,
    # and the call to action.
    times += [mk["truths"] - 3.5, mk["truths"] + 2.0, mk["cta"] + 2.0]
    times = sorted(t for t in times if 0.0 <= t < tl.duration)
    for t in times:
        t = min(t, tl.duration - 0.05)
        frame_at(t, tl).save(STILLS / f"still_{int(round(t)):02d}.png")
    print(f"Wrote {len(times)} stills to {STILLS}")


def resolve_music(value: str, generated: list[Path]) -> Path:
    """Turn a --music value into the bed to mux: an option number, or a file."""
    if value in ("1", "2", "3"):
        return generated[int(value) - 1]
    path = Path(value).expanduser()
    if not path.is_file():
        raise SystemExit(f"--music: not 1, 2, or 3, and not a file: {value}")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stills", action="store_true", help="render review stills only")
    parser.add_argument("--no-voice", action="store_true", help="reuse the existing narration file")
    parser.add_argument(
        "--music",
        default="1",
        metavar="1|2|3|FILE",
        help="music bed to mux: a generated option, or a path to an audio file (default: 1)",
    )
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
    music = resolve_music(args.music, music_paths)

    write_stills(tl)
    silent = RENDERS / "drydock-announcement-silent.mp4"
    final = RENDERS / "drydock-announcement-first-cut.mp4"
    render_silent_video(silent, tl)
    mux_audio(silent, voice, music, final, duration)
    print(f"Wrote {final}")
    print(f"Music bed: {music.name}")


if __name__ == "__main__":
    main()
