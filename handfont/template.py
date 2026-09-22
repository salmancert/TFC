"""Draw the sheets you print, fill in by hand, and scan back.

Everything the reader needs to find later - the registration marks, the
page code, the grid - is drawn from :mod:`handfont.layout`, so the two
halves cannot drift apart.

Guides are printed in a light grey that a normal threshold removes, which
is why the instructions ask for a dark pen: the ink survives, the printed
box does not.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from .charset import DEFAULT_SET, Slot, build_slots, pages_needed
from .layout import (
    ASCENDER_AT,
    BASELINE_AT,
    DESCENDER_AT,
    LABEL_HEIGHT,
    MARGIN,
    RENDER_DPI,
    XHEIGHT_AT,
    PageLayout,
    pxf,
)

INK = (0, 0, 0)
GUIDE = (203, 203, 203)          # light enough to threshold away
GUIDE_STRONG = (176, 176, 176)   # the baseline, still removable
LABEL = (140, 140, 140)
HINT = (120, 120, 120)

LABEL_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)


def _load_font(candidates: tuple[str, ...], size: int):
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_markers(draw: ImageDraw.ImageDraw, layout: PageLayout, dpi: int) -> None:
    for x, y, size in layout.markers():
        half = pxf(size, dpi) / 2
        cx, cy = pxf(x, dpi), pxf(y, dpi)
        draw.rectangle([cx - half, cy - half, cx + half, cy + half], fill=INK)


def _draw_page_code(
    draw: ImageDraw.ImageDraw, layout: PageLayout, dpi: int, page: int, bits: int = 4
) -> None:
    """A little binary strip so a scan announces which page it is."""
    width, _ = layout.size
    size = 3.0
    gap = 2.0
    total = bits * size + (bits - 1) * gap
    start_x = (width - total) / 2
    y = MARGIN + 1.0
    for bit in range(bits):
        filled = bool(page & (1 << bit))
        left = pxf(start_x + bit * (size + gap), dpi)
        top = pxf(y, dpi)
        right, bottom = left + pxf(size, dpi), top + pxf(size, dpi)
        draw.rectangle(
            [left, top, right, bottom],
            fill=INK if filled else None,
            outline=INK,
            width=max(1, int(pxf(0.3, dpi))),
        )


def _draw_header(
    draw: ImageDraw.ImageDraw, layout: PageLayout, dpi: int, page: int, total_pages: int
) -> None:
    title = _load_font(BOLD_FONT_CANDIDATES, int(pxf(5.0, dpi)))
    body = _load_font(LABEL_FONT_CANDIDATES, int(pxf(3.0, dpi)))
    x = pxf(MARGIN + 6, dpi)
    y = pxf(MARGIN + 6.0, dpi)

    draw.text((x, y), "Handwriting font template", font=title, fill=INK)
    y += pxf(6.5, dpi)
    lines = [
        "Write ONE character per box, using the printed character above each box as the prompt.",
        "Use a black or dark blue pen with a medium-to-thick nib. Sit letters ON the solid baseline.",
        "Keep inside the box, don't trace the grey guides, and leave a box empty to skip that character.",
        "When every page is done, scan or photograph each one flat, in good light, and keep all four corner squares in frame.",
    ]
    for line in lines:
        draw.text((x, y), line, font=body, fill=HINT)
        y += pxf(3.8, dpi)

    label = f"Page {page + 1} of {total_pages}"
    right = _load_font(BOLD_FONT_CANDIDATES, int(pxf(3.4, dpi)))
    box = draw.textbbox((0, 0), label, font=right)
    draw.text(
        (pxf(layout.size[0] - MARGIN - 6, dpi) - (box[2] - box[0]), pxf(MARGIN + 7.0, dpi)),
        label, font=right, fill=HINT,
    )


def _draw_cell(
    draw: ImageDraw.ImageDraw, layout: PageLayout, dpi: int, slot: Slot, prompt_font
) -> None:
    cell = layout.cell(slot.index_on_page)
    left, top = pxf(cell.x, dpi), pxf(cell.y, dpi)
    right, bottom = pxf(cell.x + cell.width, dpi), pxf(cell.y + cell.height, dpi)
    hairline = max(1, int(pxf(0.25, dpi)))

    draw.rectangle([left, top, right, bottom], outline=GUIDE, width=hairline)

    # Prompt strip, kept clear of the writing area so nobody traces it.
    label_bottom = pxf(cell.y + LABEL_HEIGHT, dpi)
    draw.line([left, label_bottom, right, label_bottom], fill=GUIDE, width=hairline)
    text = slot.character
    box = draw.textbbox((0, 0), text, font=prompt_font)
    draw.text(
        (left + pxf(1.6, dpi), top + (label_bottom - top - (box[3] - box[1])) / 2 - box[1]),
        text, font=prompt_font, fill=LABEL,
    )

    # Writing guides. The baseline is the one that matters, so it is darkest.
    for fraction, colour, dash in (
        (ASCENDER_AT, GUIDE, True),
        (XHEIGHT_AT, GUIDE, True),
        (BASELINE_AT, GUIDE_STRONG, False),
        (DESCENDER_AT, GUIDE, True),
    ):
        y = pxf(cell.guide(fraction), dpi)
        if dash:
            step = pxf(1.6, dpi)
            x = left + pxf(1.0, dpi)
            while x < right - pxf(1.0, dpi):
                draw.line([x, y, min(x + step * 0.55, right - pxf(1.0, dpi)), y],
                          fill=colour, width=hairline)
                x += step
        else:
            draw.line([left + pxf(1.0, dpi), y, right - pxf(1.0, dpi), y],
                      fill=colour, width=max(1, int(pxf(0.35, dpi))))


def render_page(
    page: int,
    slots: list[Slot],
    layout: PageLayout | None = None,
    dpi: int = RENDER_DPI,
    total_pages: int | None = None,
) -> Image.Image:
    """Draw one template page as an image."""
    layout = layout or PageLayout()
    width_mm, height_mm = layout.size
    image = Image.new("RGB", (int(pxf(width_mm, dpi)), int(pxf(height_mm, dpi))), "white")
    draw = ImageDraw.Draw(image)

    total_pages = total_pages or (max(s.page for s in slots) + 1 if slots else 1)
    _draw_markers(draw, layout, dpi)
    _draw_page_code(draw, layout, dpi, page)
    _draw_header(draw, layout, dpi, page, total_pages)

    prompt_font = _load_font(LABEL_FONT_CANDIDATES, int(pxf(3.6, dpi)))
    for slot in slots:
        if slot.page == page:
            _draw_cell(draw, layout, dpi, slot, prompt_font)
    return image


def render_all(
    characters: list[str] | None = None,
    layout: PageLayout | None = None,
    dpi: int = RENDER_DPI,
) -> list[Image.Image]:
    layout = layout or PageLayout()
    characters = characters or DEFAULT_SET
    slots = build_slots(characters, per_page=layout.per_page)
    total = pages_needed(characters, per_page=layout.per_page)
    return [render_page(page, slots, layout, dpi, total) for page in range(total)]


def write_template(
    path: str = "handwriting-template.pdf",
    characters: list[str] | None = None,
    layout: PageLayout | None = None,
    dpi: int = RENDER_DPI,
) -> str:
    """Write the template as a PDF (or PNGs, if the path ends in .png)."""
    pages = render_all(characters, layout, dpi)
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    if path.lower().endswith(".png"):
        stem, extension = os.path.splitext(path)
        for index, page in enumerate(pages):
            page.save(f"{stem}-{index + 1}{extension}", dpi=(dpi, dpi))
        return f"{stem}-1{extension}"

    pages[0].save(
        path, "PDF", resolution=dpi, save_all=True, append_images=pages[1:],
    )
    return path
