"""Make a font from your own handwriting.

Print a template, fill it in with a pen, scan it, and get back a TrueType
font that is yours outright - no licence to read, nothing to attribute.

    python -m handfont template -o template.pdf
    python -m handfont build scans/*.jpg -n "My Hand" -o MyHand.ttf --install
"""

from .build import BuildReport, FontInfo, build_font
from .charset import DEFAULT_SET, build_slots
from .layout import PageLayout
from .scan import GlyphImage, ScannedPage, read_page, rectify
from .template import render_all, write_template
from .trace import TracedGlyph, trace_glyph

__version__ = "1.0.0"

__all__ = [
    "BuildReport", "DEFAULT_SET", "FontInfo", "GlyphImage", "PageLayout",
    "ScannedPage", "TracedGlyph", "build_font", "build_slots", "read_page",
    "rectify", "render_all", "trace_glyph", "write_template",
]
