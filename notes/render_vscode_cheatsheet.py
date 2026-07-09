"""Render the one-page VS Code workflow reference as a print-ready landscape PDF."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT_DIR = Path(__file__).parent
PDF = OUT_DIR / "VscodeCheatSHeat.pdf"
PNG = OUT_DIR / "VscodeCheatSHeat.preview.png"

INK = "#17233A"
NAVY = "#102A43"
TEAL = "#256C7B"
PALE_BLUE = "#EAF3F7"
BORDER = "#D4E1E8"
MUTED = "#607489"
GOLD = "#B56B12"


def card(ax, x, top, width, height, title, rows, *, accent=TEAL, note=None):
    """Draw one shortcut card using normalized figure coordinates."""
    bottom = top - height
    ax.add_patch(
        FancyBboxPatch(
            (x, bottom),
            width,
            height,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            linewidth=0.8,
            edgecolor=BORDER,
            facecolor="#FCFEFF",
        )
    )
    header_h = 0.038
    ax.add_patch(
        FancyBboxPatch(
            (x, top - header_h),
            width,
            header_h,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            linewidth=0,
            facecolor=PALE_BLUE,
        )
    )
    ax.text(
        x + 0.012,
        top - header_h / 2,
        title,
        va="center",
        ha="left",
        fontsize=9.3,
        fontweight="bold",
        color="#183B56",
    )

    y = top - header_h - 0.011
    row_h = 0.027
    for label, key in rows:
        ax.text(x + 0.012, y - row_h / 2, label, va="center", ha="left", fontsize=7.55, color=INK)
        key_width = min(width * 0.54, 0.0082 * len(key) + 0.028)
        key_x = x + width - key_width - 0.010
        ax.add_patch(
            FancyBboxPatch(
                (key_x, y - row_h * 0.79),
                key_width,
                row_h * 0.61,
                boxstyle="round,pad=0.002,rounding_size=0.004",
                linewidth=0.6,
                edgecolor="#AEBFCB",
                facecolor="#FFFFFF",
            )
        )
        ax.text(
            key_x + key_width / 2,
            y - row_h / 2,
            key,
            va="center",
            ha="center",
            fontsize=6.85,
            family="DejaVu Sans Mono",
            fontweight="bold",
            color="#12304A",
        )
        y -= row_h
    if note:
        note_h = max(0.050, height - (top - y) - 0.012)
        ax.add_patch(
            FancyBboxPatch(
                (x + 0.009, bottom + 0.009),
                width - 0.018,
                note_h,
                boxstyle="round,pad=0.004,rounding_size=0.006",
                linewidth=0,
                facecolor=note[0],
            )
        )
        ax.text(
            x + 0.017,
            bottom + 0.009 + note_h / 2,
            note[1],
            va="center",
            ha="left",
            fontsize=7.0,
            color=note[2],
            wrap=True,
        )


def main():
    fig = plt.figure(figsize=(11, 8.5), dpi=220, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(
        FancyBboxPatch(
            (0.03, 0.885),
            0.94,
            0.083,
            boxstyle="round,pad=0.004,rounding_size=0.016",
            linewidth=0,
            facecolor=NAVY,
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (0.56, 0.885),
            0.41,
            0.083,
            boxstyle="round,pad=0.004,rounding_size=0.016",
            linewidth=0,
            facecolor=TEAL,
            alpha=0.82,
        )
    )
    ax.text(
        0.055, 0.938, "VS Code Workflow", fontsize=20, color="white", fontweight="bold", va="center"
    )
    ax.text(
        0.056,
        0.907,
        "A practical, Vim-friendly reference for navigating, testing, and staying oriented.",
        fontsize=8.0,
        color="#DBEAFE",
        va="center",
    )
    ax.text(
        0.918,
        0.926,
        "WINDOWS + WSL",
        fontsize=7.6,
        color="#E8FFFF",
        va="center",
        ha="center",
        fontweight="bold",
        bbox={"boxstyle": "round,pad=0.42", "fc": "none", "ec": "#A7E4E4", "lw": 0.8},
    )

    x1, x2, x3, width = 0.03, 0.353, 0.676, 0.294
    card(
        ax,
        x1,
        0.862,
        width,
        0.294,
        "Navigate the codebase",
        [
            ("Open any file", "Ctrl+P"),
            ("Command Palette", "Ctrl+Shift+P"),
            ("Search the whole project", "Ctrl+Shift+F"),
            ("Symbols in this file", "Ctrl+Shift+O"),
            ("Symbols in workspace", "Ctrl+T"),
            ("Go back / forward", "Alt+Left / Right"),
            ("Go to definition", "F12"),
            ("Rename symbol", "F2"),
            ("Code action / quick fix", "Ctrl+."),
        ],
    )
    card(
        ax,
        x1,
        0.555,
        width,
        0.205,
        "Window and views",
        [
            ("Toggle Explorer sidebar", "Ctrl+B"),
            ("Toggle bottom panel", "Ctrl+J"),
            ("Explorer / Search / Git", "Ctrl+Shift+E / F / G"),
            ("Run and Debug / Extensions", "Ctrl+Shift+D / X"),
            ("Split editor", "Ctrl+\\"),
            ("Format current file", "Shift+Alt+F"),
        ],
    )
    card(
        ax,
        x1,
        0.340,
        width,
        0.230,
        "Explorer and Outline",
        [
            ("Focus Explorer", "Ctrl+Shift+E"),
            ("Expand / collapse a tree", "Right / Left"),
            ("Move through a tree", "Up / Down"),
            ("Filter the current tree", "Palette → Filter"),
        ],
        note=(
            "#ECF9F6",
            "Use Outline for headings and symbols. Use breadcrumbs for path + symbol context.",
            "#15594F",
        ),
    )

    card(
        ax,
        x2,
        0.862,
        width,
        0.267,
        "Test and terminal: your bindings",
        [
            ("Show or hide terminal", "Ctrl+Alt+T"),
            ("New terminal", "Ctrl+Shift+`"),
            ("Run the entire test suite", "Ctrl+Alt+A"),
            ("Run tests in this file", "Ctrl+Alt+F"),
            ("Run test at cursor", "Ctrl+Alt+R"),
            ("Debug test at cursor", "Ctrl+Alt+D"),
            ("Start debugging", "F5"),
            ("Toggle breakpoint", "F9"),
        ],
    )
    card(
        ax,
        x2,
        0.585,
        width,
        0.205,
        "Editing, copy, and Vim",
        [
            ("Save / save all", "Ctrl+S / Ctrl+K S"),
            ("Close / reopen editor", "Ctrl+W / Ctrl+Shift+T"),
            ("Copy and paste editor text", "Ctrl+C / V"),
            ("Safe terminal copy / paste", "Ctrl+Shift+C / V"),
            ("Vim redo after u", "Esc, Ctrl+R"),
            ("Fallback editor redo", "Ctrl+Y"),
        ],
    )
    ax.add_patch(
        FancyBboxPatch(
            (x2, 0.265),
            width,
            0.103,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            linewidth=0.7,
            edgecolor="#F0D29D",
            facecolor="#FFF8E8",
        )
    )
    ax.text(
        x2 + 0.014, 0.334, "TERMINAL RULE", fontsize=8.3, color=GOLD, fontweight="bold", va="center"
    )
    ax.text(
        x2 + 0.014,
        0.304,
        "You are WSL-first. Use the integrated Ubuntu terminal\nfor project commands; it starts at the workspace folder.",
        fontsize=7.5,
        color="#68450E",
        va="center",
    )

    card(
        ax,
        x3,
        0.862,
        width,
        0.172,
        "Codex composer",
        [
            ("Send a request", "Enter or Ctrl+Enter"),
            ("Insert a new line", "Shift+Enter"),
        ],
        note=(
            "#FFF8E8",
            "Before changing Codex WSL settings: save editor work. VS Code reloads and recent chat UI state can disappear.",
            "#68450E",
        ),
    )
    card(
        ax,
        x3,
        0.680,
        width,
        0.218,
        "Three habits worth keeping",
        [
            ("1. Find, do not browse", "Ctrl+P"),
            ("2. Jump, do not hunt", "Alt+Left / Right"),
            ("3. Focus the project", "Multi-root workspace"),
        ],
        note=(
            "#F2F7FA",
            "For a focused workspace, add only the folders you need as separate top-level folders.",
            MUTED,
        ),
    )
    card(
        ax,
        x3,
        0.452,
        width,
        0.190,
        "Learn next: everyday defaults",
        [
            ("Open Settings", "Ctrl+,"),
            ("Open Keyboard Shortcuts", "Ctrl+K Ctrl+S"),
            ("Go to a line", "Ctrl+G"),
            ("Find all references", "Shift+F12"),
            ("Open the Problems panel", "Ctrl+Shift+M"),
        ],
    )

    ax.text(0.03, 0.020, "Personal reference", fontsize=7.1, color=MUTED, va="center")
    ax.text(
        0.97,
        0.020,
        "Print at 100% • US Letter landscape",
        fontsize=7.1,
        color=MUTED,
        va="center",
        ha="right",
    )
    fig.savefig(PDF, format="pdf", bbox_inches="tight", pad_inches=0)
    fig.savefig(PNG, format="png", dpi=220, bbox_inches="tight", pad_inches=0)


if __name__ == "__main__":
    main()
