"""Assemble traced glyphs into a real, installable TrueType font."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

from .charset import glyph_name_for
from .trace import (
    ASCENDER_UNITS,
    DESCENDER_UNITS,
    UNITS_PER_EM,
    TracedGlyph,
)

LOGGER = logging.getLogger(__name__)

CURVE_ERROR = 1.0          # font units allowed when turning cubics into quadratics


@dataclass
class FontInfo:
    """What goes in the name table."""

    family: str = "My Handwriting"
    style: str = "Regular"
    version: str = "1.000"
    designer: str = ""
    # It is the user's own hand, so the default says exactly that rather
    # than inventing a licence for them.
    license: str = (
        "Made from the author's own handwriting. "
        "All rights reserved by the author unless stated otherwise."
    )
    license_url: str = ""

    @property
    def postscript_name(self) -> str:
        family = "".join(ch for ch in self.family if ch.isalnum())
        style = "".join(ch for ch in self.style if ch.isalnum())
        return f"{family}-{style}"[:63] or "MyHandwriting-Regular"


def _draw(traced: TracedGlyph) -> "object":
    """Render one traced glyph into a TrueType glyph."""
    pen = TTGlyphPen(None)
    # TrueType stores quadratics, potrace produces cubics.
    converter = Cu2QuPen(pen, CURVE_ERROR)
    for contour in traced.contours:
        for command in contour:
            name = command[0]
            if name == "moveTo":
                converter.moveTo(command[1])
            elif name == "lineTo":
                converter.lineTo(command[1])
            elif name == "curveTo":
                converter.curveTo(command[1], command[2], command[3])
            elif name == "closePath":
                converter.closePath()
    return pen.glyph()


def _notdef(width: int = 600) -> "object":
    """A hollow box, the conventional "no such glyph" mark."""
    pen = TTGlyphPen(None)
    inset, top, bottom = 60, 700, 0
    for box in (
        [(inset, bottom), (width - inset, bottom), (width - inset, top), (inset, top)],
        [(inset + 50, bottom + 50), (inset + 50, top - 50),
         (width - inset - 50, top - 50), (width - inset - 50, bottom + 50)],
    ):
        pen.moveTo(box[0])
        for point in box[1:]:
            pen.lineTo(point)
        pen.closePath()
    return pen.glyph()


@dataclass
class BuildReport:
    """What made it into the font."""

    glyphs: int = 0
    characters: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    path: str = ""

    def summary(self) -> str:
        line = f"{self.glyphs} glyphs written to {os.path.basename(self.path)}"
        if self.missing:
            preview = "".join(self.missing[:12])
            line += f"; {len(self.missing)} still blank: {preview}"
            if len(self.missing) > 12:
                line += "..."
        return line


def build_font(
    traced: dict[str, TracedGlyph],
    path: str,
    info: FontInfo | None = None,
    expected: list[str] | None = None,
) -> BuildReport:
    """Write a TTF from traced glyphs, keyed by the character they draw."""
    info = info or FontInfo()

    usable = {
        character: glyph for character, glyph in traced.items()
        if not glyph.is_blank and character != " "
    }
    if not usable:
        raise ValueError(
            "No written characters were found. Check that the scans are the "
            "right way up and that the pen is dark enough to read."
        )

    names: dict[str, str] = {}
    for character in usable:
        name = glyph_name_for(character)
        # Two characters must never claim the same glyph name.
        suffix = 1
        while name in names.values():
            name = f"{glyph_name_for(character)}.{suffix}"
            suffix += 1
        names[character] = name

    order = [".notdef", "space"] + [names[c] for c in usable]
    glyphs = {".notdef": _notdef(), "space": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (600, 60), "space": (int(0.28 * UNITS_PER_EM), 0)}

    for character, glyph in usable.items():
        name = names[character]
        glyphs[name] = _draw(glyph)
        metrics[name] = (glyph.advance, glyph.left_side_bearing)

    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(
        {ord(" "): "space", **{ord(c): names[c] for c in usable}}
    )
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(
        ascent=ASCENDER_UNITS,
        descent=DESCENDER_UNITS,
        lineGap=int(0.12 * UNITS_PER_EM),
    )
    builder.setupNameTable({
        "familyName": info.family,
        "styleName": info.style,
        "uniqueFontIdentifier": f"{info.family}:{info.style}:{info.version}",
        "fullName": f"{info.family} {info.style}".strip(),
        "psName": info.postscript_name,
        "version": info.version,
        "designer": info.designer or info.family,
        "licenseDescription": info.license,
        "licenseInfoURL": info.license_url,
    })
    builder.setupOS2(
        sTypoAscender=ASCENDER_UNITS,
        sTypoDescender=DESCENDER_UNITS,
        sTypoLineGap=int(0.12 * UNITS_PER_EM),
        usWinAscent=ASCENDER_UNITS,
        usWinDescent=abs(DESCENDER_UNITS),
        sxHeight=int(0.5 * UNITS_PER_EM),
        sCapHeight=int(0.7 * UNITS_PER_EM),
        achVendID="HAND",
    )
    builder.setupPost(isFixedPitch=0)

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    builder.save(path)

    written = sorted(usable)
    missing = (
        [c for c in (expected or []) if c not in usable and c != " "] if expected else []
    )
    report = BuildReport(
        glyphs=len(usable), characters=written, missing=missing, path=path
    )
    LOGGER.debug("%s", report.summary())
    return report
