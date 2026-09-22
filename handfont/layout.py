"""Page geometry shared by the template writer and the scan reader.

Both halves of the pipeline must agree on exactly where every box sits, so
the numbers live here once.  Everything is in millimetres; :func:`px`
converts at whatever resolution is being rendered or read.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- paper ----------------------------------------------------------------
PAPER = {
    "a4": (210.0, 297.0),
    "letter": (215.9, 279.4),
}
DEFAULT_PAPER = "a4"
RENDER_DPI = 300

MARGIN = 12.0
HEADER_HEIGHT = 34.0        # title, instructions and the page code
FOOTER_HEIGHT = 8.0

# --- registration marks ---------------------------------------------------
# Three large squares and one small one: the large ones give the homography
# solid corners, and the odd one out fixes the orientation, so a page fed in
# upside down still lands the right way up.
MARKER_LARGE = 8.0
MARKER_SMALL = 5.0
MARKER_INSET = 6.0          # centre offset from the paper edge

# --- cells ----------------------------------------------------------------
CELL_WIDTH = 24.0
CELL_HEIGHT = 27.0
LABEL_HEIGHT = 6.0          # printed prompt sits above the writing area
CELL_GAP = 1.0

# Writing guides, as a fraction of the writing area's height, measured down
# from its top. These fix how a glyph maps onto the em square later.
ASCENDER_AT = 0.16
XHEIGHT_AT = 0.45
BASELINE_AT = 0.76
DESCENDER_AT = 0.96


@dataclass(frozen=True)
class Cell:
    """Where one character's box sits on the page, in millimetres."""

    index: int
    row: int
    column: int
    x: float
    y: float
    width: float = CELL_WIDTH
    height: float = CELL_HEIGHT

    @property
    def write_top(self) -> float:
        return self.y + LABEL_HEIGHT

    @property
    def write_height(self) -> float:
        return self.height - LABEL_HEIGHT

    def guide(self, fraction: float) -> float:
        """Absolute y of a guide line given as a fraction of the write area."""
        return self.write_top + self.write_height * fraction

    @property
    def baseline(self) -> float:
        return self.guide(BASELINE_AT)


@dataclass(frozen=True)
class PageLayout:
    """The grid for one sheet of paper."""

    paper: str = DEFAULT_PAPER

    @property
    def size(self) -> tuple[float, float]:
        return PAPER[self.paper]

    @property
    def columns(self) -> int:
        width = self.size[0] - 2 * MARGIN
        return max(1, int((width + CELL_GAP) // (CELL_WIDTH + CELL_GAP)))

    @property
    def rows(self) -> int:
        height = self.size[1] - 2 * MARGIN - HEADER_HEIGHT - FOOTER_HEIGHT
        return max(1, int((height + CELL_GAP) // (CELL_HEIGHT + CELL_GAP)))

    @property
    def per_page(self) -> int:
        return self.columns * self.rows

    @property
    def grid_origin(self) -> tuple[float, float]:
        """Top-left of the grid, centred in the space left over."""
        page_width, _ = self.size
        used = self.columns * CELL_WIDTH + (self.columns - 1) * CELL_GAP
        x = (page_width - used) / 2
        return x, MARGIN + HEADER_HEIGHT

    def cell(self, index_on_page: int) -> Cell:
        row, column = divmod(index_on_page, self.columns)
        origin_x, origin_y = self.grid_origin
        return Cell(
            index=index_on_page,
            row=row,
            column=column,
            x=origin_x + column * (CELL_WIDTH + CELL_GAP),
            y=origin_y + row * (CELL_HEIGHT + CELL_GAP),
        )

    def cells(self) -> list[Cell]:
        return [self.cell(i) for i in range(self.per_page)]

    def markers(self) -> list[tuple[float, float, float]]:
        """(x, y, size) centres of the registration marks.

        Order is top-left, top-right, bottom-left, bottom-right; the last is
        deliberately smaller so orientation can be recovered.
        """
        width, height = self.size
        near, far_x, far_y = MARKER_INSET, width - MARKER_INSET, height - MARKER_INSET
        return [
            (near, near, MARKER_LARGE),
            (far_x, near, MARKER_LARGE),
            (near, far_y, MARKER_LARGE),
            (far_x, far_y, MARKER_SMALL),
        ]


def px(millimetres: float, dpi: int = RENDER_DPI) -> int:
    """Millimetres to pixels at a given resolution."""
    return int(round(millimetres * dpi / 25.4))


def pxf(millimetres: float, dpi: int = RENDER_DPI) -> float:
    return millimetres * dpi / 25.4
