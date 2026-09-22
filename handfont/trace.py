"""Turn a written character's pixels into outlines on the em square.

The template's baseline is what makes this possible: every box was written
against a printed baseline and x-height, so a glyph's pixels can be placed
on the em square directly rather than guessed at from its own bounding box.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .scan import GlyphImage

UNITS_PER_EM = 1000
ASCENDER_UNITS = 800            # where the template's ascender guide lands
DESCENDER_UNITS = -200
DEFAULT_SIDE_BEARING = 40       # font units of air either side of the ink

# Drawing commands, ready for a fontTools pen.
Command = tuple


@dataclass
class TracedGlyph:
    """One character as outlines, in font units with the baseline at y=0."""

    character: str
    contours: list[list[Command]]
    advance: int
    left_side_bearing: int
    ink_box: tuple[float, float, float, float]

    @property
    def is_blank(self) -> bool:
        return not self.contours


def _pad(mask: np.ndarray, amount: int = 2) -> np.ndarray:
    return np.pad(mask, amount, mode="constant", constant_values=False)


def _smooth(mask: np.ndarray, strength: int = 1) -> np.ndarray:
    """Knock the stair-steps off a scan without losing the pen's character."""
    if strength <= 0:
        return mask
    from scipy import ndimage

    smoothed = ndimage.median_filter(mask.astype(np.uint8), size=2 * strength + 1)
    return smoothed.astype(bool)


def trace_bitmap(
    mask: np.ndarray, alphamax: float = 1.0, turdsize: int = 3, opttolerance: float = 0.25
) -> list[list[Command]]:
    """Vectorise a boolean ink mask into closed contours (in pixel space)."""
    from potrace import Bitmap

    if not mask.any():
        return []
    padded = _pad(mask)
    # potracer treats ZERO as the shape to trace, which is the opposite of
    # how an ink mask reads, so the mask goes in inverted.
    path = Bitmap(~padded).trace(
        turdsize=turdsize, alphamax=alphamax, opttolerance=opttolerance
    )

    contours: list[list[Command]] = []
    for curve in path.curves:
        start = curve.start_point
        commands: list[Command] = [("moveTo", (start.x, start.y))]
        for segment in curve.segments:
            end = segment.end_point
            if segment.is_corner:
                commands.append(("lineTo", (segment.c.x, segment.c.y)))
                commands.append(("lineTo", (end.x, end.y)))
            else:
                commands.append((
                    "curveTo",
                    (segment.c1.x, segment.c1.y),
                    (segment.c2.x, segment.c2.y),
                    (end.x, end.y),
                ))
        commands.append(("closePath",))
        contours.append(commands)
    return contours


def _contour_area(commands: list[Command]) -> float:
    """Signed area via the shoelace formula over the on-curve points."""
    points: list[tuple[float, float]] = []
    for command in commands:
        if command[0] == "moveTo":
            points.append(command[1])
        elif command[0] == "lineTo":
            points.append(command[1])
        elif command[0] == "curveTo":
            points.append(command[3])
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def trace_glyph(
    character: str,
    glyph: GlyphImage,
    side_bearing: int = DEFAULT_SIDE_BEARING,
    smooth: int = 1,
    alphamax: float = 1.0,
) -> TracedGlyph:
    """Place one scanned character onto the em square."""
    if glyph.is_empty:
        return TracedGlyph(character, [], int(0.28 * UNITS_PER_EM), 0, (0, 0, 0, 0))

    mask = _smooth(glyph.bitmap, smooth)
    contours = trace_bitmap(mask, alphamax=alphamax)
    if not contours:
        return TracedGlyph(character, [], int(0.28 * UNITS_PER_EM), 0, (0, 0, 0, 0))

    # The template's guides fix the scale: ascender-to-baseline is 800 units.
    span = glyph.baseline_y - glyph.ascender_y
    scale = ASCENDER_UNITS / span if span > 1e-6 else 1.0

    pad = 2                       # trace_bitmap padded the mask by this much
    origin_x, origin_y = glyph.origin

    def to_font(point: tuple[float, float]) -> tuple[float, float]:
        x = (origin_x - pad + point[0])
        y = (origin_y - pad + point[1])
        return (x * scale, (glyph.baseline_y - y) * scale)

    placed: list[list[Command]] = []
    for commands in contours:
        converted: list[Command] = []
        for command in commands:
            if command[0] == "closePath":
                converted.append(command)
            else:
                converted.append((command[0], *[to_font(p) for p in command[1:]]))
        placed.append(converted)

    xs, ys = [], []
    for commands in placed:
        for command in commands:
            for point in command[1:]:
                xs.append(point[0])
                ys.append(point[1])
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Slide the ink so it starts at the left side bearing.
    shift = side_bearing - min_x
    shifted: list[list[Command]] = []
    for commands in placed:
        shifted.append([
            command if command[0] == "closePath"
            else (command[0], *[(x + shift, y) for (x, y) in command[1:]])
            for command in commands
        ])

    # TrueType fills by non-zero winding: the outer contour must run the
    # opposite way to the holes inside it. Sort by area and orient from there.
    outer_sign = None
    oriented: list[list[Command]] = []
    for commands in sorted(shifted, key=lambda c: -abs(_contour_area(c))):
        area = _contour_area(commands)
        if outer_sign is None:
            outer_sign = 1.0 if area > 0 else -1.0
        oriented.append(commands)

    width = max_x - min_x
    advance = int(round(width + 2 * side_bearing))
    return TracedGlyph(
        character=character,
        contours=oriented,
        advance=max(advance, int(0.12 * UNITS_PER_EM)),
        left_side_bearing=side_bearing,
        ink_box=(side_bearing, min_y, side_bearing + width, max_y),
    )
