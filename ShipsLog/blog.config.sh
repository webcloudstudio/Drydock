# blog.config.sh — single place to configure the dev-blog framework.
# Sourced by every script in scripts/. Edit values here, not in the scripts.

# Absolute path to the source project whose commits/CHANGELOG feed the blog.
SOURCE_REPO="/mnt/c/Users/barlo/projects/Drydock"
SHIPS_LOG="/mnt/c/Users/barlo/projects/Drydock/logs/ships_log.jsonl"

# Package identity.
SITE_TITLE="Development Notes"
SITE_DESC="Short engineering notes generated from Ship's Log material."
AUTHOR="Ed Barlow"

# Default drafting agent for the automated path: claude | codex
AGENT="claude"

# --- Derived paths (do not edit) ---------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLOG_DIR="$ROOT/blog"
POSTS_DIR="$BLOG_DIR/posts"
MATERIAL_DIR="$BLOG_DIR/material"
GENERATION="$BLOG_DIR/GENERATION.md"
DISCLOSURE="$BLOG_DIR/DISCLOSURE.md"
# Voice/brand guidance is read live from Drydock's Rigging (the maintained
# source), not a local copy — a frozen copy would drift silently.
RIGGING_DIR="$SOURCE_REPO/Rigging"
BRANDING_POSTS="$RIGGING_DIR/BRANDING_POSTS.md"
BRANDING_MAIN="$RIGGING_DIR/BRANDING_MAIN.md"
# Brand logo copied next to rendered pages by scripts/render.py.
LOGO="$SOURCE_REPO/docs/drydock_logo.png"
