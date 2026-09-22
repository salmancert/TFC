"""Read a filled-in template back off a scan or a photograph.

The page is found by its four registration marks, straightened with a
perspective transform, and then sliced using the same geometry the
template was drawn with.  Printed guides are light grey by design, so a
threshold keeps the pen and drops the box.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .layout import (
    BASELINE_AT,
    DESCENDER_AT,
    ASCENDER_AT,
    MARGIN,
    PageLayout,
    pxf,
)

LOGGER = logging.getLogger(__name__)

READ_DPI = 200               # what the page is rectified to before slicing
INK_THRESHOLD = 150          # darker than this is pen, not printed guide
MIN_SPECK = 14               # pixels; anything smaller is scanner dust


@dataclass
class GlyphImage:
    """One character as written, with the guides it was written against."""

    index_on_page: int
    bitmap: np.ndarray          # bool, True where there is ink
    origin: tuple[int, int]     # bitmap's top-left within the cell's write area
    cell_size: tuple[int, int]  # the write area's size in pixels
    baseline_y: float           # within the write area
    ascender_y: float
    descender_y: float

    @property
    def is_empty(self) -> bool:
        return not self.bitmap.any()


@dataclass
class ScannedPage:
    page: int
    glyphs: dict[int, GlyphImage]
    rectified: Image.Image


def _to_gray(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.uint8)


def _otsu(gray: np.ndarray) -> int:
    """Otsu's threshold, so exposure differences between scans do not matter."""
    histogram = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = histogram.sum()
    if total == 0:
        return 128
    omega = np.cumsum(histogram) / total
    mu = np.cumsum(histogram * np.arange(256)) / total
    mu_t = mu[-1]
    denominator = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma = np.where(denominator > 0, (mu_t * omega - mu) ** 2 / denominator, 0.0)
    return int(np.argmax(sigma))


def _components(mask: np.ndarray):
    from scipy import ndimage

    labels, count = ndimage.label(mask)
    return labels, count


def find_markers(image: Image.Image) -> list[tuple[float, float]]:
    """Locate the four registration squares, in template order.

    Returns their centres as (x, y) in the image's own pixels, ordered
    top-left, top-right, bottom-left, bottom-right in *template* space -
    so a page scanned upside down still comes back the right way round.
    """
    from scipy import ndimage

    gray = _to_gray(image)
    threshold = min(_otsu(gray), 170)
    dark = gray < threshold
    labels, count = _components(dark)
    if count == 0:
        raise ValueError("No dark shapes at all - is the page blank?")

    height, width = dark.shape
    page_area = float(height * width)
    candidates: list[tuple[float, float, float]] = []   # x, y, area
    objects = ndimage.find_objects(labels)
    for index, bounds in enumerate(objects, start=1):
        if bounds is None:
            continue
        ys, xs = bounds
        box_h, box_w = ys.stop - ys.start, xs.stop - xs.start
        if box_h < 6 or box_w < 6:
            continue
        aspect = box_w / box_h
        if not 0.65 <= aspect <= 1.55:
            continue
        area = float((labels[bounds] == index).sum())
        fill = area / float(box_h * box_w)
        if fill < 0.72:                       # a square is solid; letters are not
            continue
        share = area / page_area
        if not 2e-5 <= share <= 6e-3:         # plausible marker size
            continue
        candidates.append(((xs.start + xs.stop) / 2.0, (ys.start + ys.stop) / 2.0, area))

    if len(candidates) < 4:
        raise ValueError(
            f"Found {len(candidates)} registration marks, need 4. "
            "Make sure all four corner squares are in frame and in focus."
        )

    # Keep the four that sit furthest apart: the corner marks.
    candidates.sort(key=lambda c: -c[2])
    pool = candidates[:12]
    best, best_spread = None, -1.0
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            for k in range(j + 1, len(pool)):
                for m in range(k + 1, len(pool)):
                    quad = [pool[i], pool[j], pool[k], pool[m]]
                    xs = [p[0] for p in quad]
                    ys = [p[1] for p in quad]
                    spread = (max(xs) - min(xs)) * (max(ys) - min(ys))
                    areas = [p[2] for p in quad]
                    # Three matching large marks and one clearly smaller.
                    ordered = sorted(areas)
                    if ordered[0] > 0.8 * ordered[1]:
                        continue
                    if spread > best_spread:
                        best, best_spread = quad, spread
    if best is None:
        best = candidates[:4]

    return _order_markers(best)


def _order_markers(quad: list[tuple[float, float, float]]) -> list[tuple[float, float]]:
    """Put the four marks into template order using the odd small one."""
    areas = [p[2] for p in quad]
    small_index = int(np.argmin(areas))
    small = quad[small_index]
    others = [p for index, p in enumerate(quad) if index != small_index]

    # The mark diagonally opposite the small one is the template's top-left.
    distances = [((p[0] - small[0]) ** 2 + (p[1] - small[1]) ** 2) for p in others]
    top_left = others[int(np.argmax(distances))]
    remaining = [p for p in others if p is not top_left]

    # Of the two adjacent marks, the further from top-left is bottom-left,
    # because the page is taller than it is wide.
    span = [((p[0] - top_left[0]) ** 2 + (p[1] - top_left[1]) ** 2) for p in remaining]
    bottom_left = remaining[int(np.argmax(span))]
    top_right = remaining[1 - int(np.argmax(span))]
    return [
        (top_left[0], top_left[1]),
        (top_right[0], top_right[1]),
        (bottom_left[0], bottom_left[1]),
        (small[0], small[1]),
    ]


def _perspective_coefficients(
    target: list[tuple[float, float]], source: list[tuple[float, float]]
) -> list[float]:
    """Coefficients mapping output pixels back to input pixels, for PIL."""
    rows = []
    values = []
    for (tx, ty), (sx, sy) in zip(target, source):
        rows.append([tx, ty, 1, 0, 0, 0, -sx * tx, -sx * ty])
        values.append(sx)
        rows.append([0, 0, 0, tx, ty, 1, -sy * tx, -sy * ty])
        values.append(sy)
    solution, *_ = np.linalg.lstsq(np.asarray(rows, dtype=float),
                                   np.asarray(values, dtype=float), rcond=None)
    return solution.tolist()


def rectify(
    image: Image.Image, layout: PageLayout | None = None, dpi: int = READ_DPI
) -> Image.Image:
    """Straighten a scan into template coordinates at ``dpi``."""
    layout = layout or PageLayout()
    found = find_markers(image)
    target = [(pxf(x, dpi), pxf(y, dpi)) for x, y, _size in layout.markers()]
    width = int(pxf(layout.size[0], dpi))
    height = int(pxf(layout.size[1], dpi))
    coefficients = _perspective_coefficients(target, found)
    return image.convert("L").transform(
        (width, height), Image.Transform.PERSPECTIVE, coefficients,
        resample=Image.Resampling.BICUBIC, fillcolor=255,
    )


def read_page_code(
    rectified: Image.Image, layout: PageLayout | None = None,
    dpi: int = READ_DPI, bits: int = 4,
) -> int:
    """Recover the page number from the little binary strip."""
    layout = layout or PageLayout()
    gray = _to_gray(rectified)
    width, _ = layout.size
    size, gap = 3.0, 2.0
    total = bits * size + (bits - 1) * gap
    start_x = (width - total) / 2
    y = MARGIN + 1.0

    page = 0
    for bit in range(bits):
        left = int(pxf(start_x + bit * (size + gap) + 0.8, dpi))
        top = int(pxf(y + 0.8, dpi))
        right = int(pxf(start_x + bit * (size + gap) + size - 0.8, dpi))
        bottom = int(pxf(y + size - 0.8, dpi))
        patch = gray[top:bottom, left:right]
        if patch.size and patch.mean() < 140:
            page |= 1 << bit
    return page


def _despeckle(mask: np.ndarray, minimum: int = MIN_SPECK) -> np.ndarray:
    from scipy import ndimage

    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = ndimage.sum(mask, labels, range(1, count + 1))
    keep = np.zeros(count + 1, dtype=bool)
    keep[1:] = sizes >= minimum
    return keep[labels]


def extract_cell(
    rectified: Image.Image, index_on_page: int,
    layout: PageLayout | None = None, dpi: int = READ_DPI,
    threshold: int = INK_THRESHOLD,
) -> GlyphImage:
    """Pull one character out of a straightened page."""
    layout = layout or PageLayout()
    cell = layout.cell(index_on_page)
    gray = _to_gray(rectified)

    # Inset a little so the printed cell border never counts as ink.
    inset = pxf(1.2, dpi)
    left = int(pxf(cell.x, dpi) + inset)
    right = int(pxf(cell.x + cell.width, dpi) - inset)
    top = int(pxf(cell.write_top, dpi) + inset * 0.4)
    bottom = int(pxf(cell.y + cell.height, dpi) - inset * 0.4)

    patch = gray[top:bottom, left:right]
    mask = _despeckle(patch < threshold)

    write_height = bottom - top
    write_width = right - left
    baseline = (pxf(cell.baseline, dpi) - top)
    ascender = (pxf(cell.guide(ASCENDER_AT), dpi) - top)
    descender = (pxf(cell.guide(DESCENDER_AT), dpi) - top)

    if not mask.any():
        return GlyphImage(
            index_on_page, np.zeros((0, 0), dtype=bool), (0, 0),
            (write_width, write_height), baseline, ascender, descender,
        )

    rows = np.where(mask.any(axis=1))[0]
    columns = np.where(mask.any(axis=0))[0]
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    x0, x1 = int(columns[0]), int(columns[-1]) + 1
    return GlyphImage(
        index_on_page, mask[y0:y1, x0:x1], (x0, y0),
        (write_width, write_height), baseline, ascender, descender,
    )


def read_page(
    image: Image.Image, layout: PageLayout | None = None, dpi: int = READ_DPI
) -> ScannedPage:
    """Rectify a scan and pull every written character out of it."""
    layout = layout or PageLayout()
    rectified = rectify(image, layout, dpi)
    page = read_page_code(rectified, layout, dpi)
    glyphs: dict[int, GlyphImage] = {}
    for index in range(layout.per_page):
        glyph = extract_cell(rectified, index, layout, dpi)
        if not glyph.is_empty:
            glyphs[index] = glyph
    LOGGER.info("Page %d: found %d written boxes.", page + 1, len(glyphs))
    return ScannedPage(page=page, glyphs=glyphs, rectified=rectified)
