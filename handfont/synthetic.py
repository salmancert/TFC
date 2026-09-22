"""Fill a template in programmatically, to exercise the pipeline.

Waiting on a real scan to find out whether the reader works is a slow
loop, so this writes the boxes using an existing font and can then abuse
the result the way a phone camera would - rotate it, skew it, dim a
corner, add sensor noise.  It is what the tests run against.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .charset import DEFAULT_SET, build_slots
from .layout import BASELINE_AT, PageLayout, RENDER_DPI, pxf
from .template import LABEL_FONT_CANDIDATES, render_page

PEN = (14, 18, 46)          # dark blue-black, like a real pen


def _pen_font(size: int, path: str | None = None):
    for candidate in ([path] if path else []) + list(LABEL_FONT_CANDIDATES):
        if candidate and os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def fill_page(
    page: int,
    characters: list[str] | None = None,
    layout: PageLayout | None = None,
    dpi: int = RENDER_DPI,
    pen_font_path: str | None = None,
    skip: set[str] | None = None,
    jitter: float = 0.6,
    seed: int = 0,
) -> Image.Image:
    """Draw a template page and write every character into its box."""
    layout = layout or PageLayout()
    characters = characters or DEFAULT_SET
    slots = build_slots(characters, per_page=layout.per_page)
    image = render_page(page, slots, layout, dpi)
    draw = ImageDraw.Draw(image)
    rng = np.random.default_rng(seed)
    skip = skip or set()

    cap_height = pxf(9.0, dpi)
    font = _pen_font(int(cap_height), pen_font_path)

    for slot in slots:
        if slot.page != page or slot.character in skip:
            continue
        cell = layout.cell(slot.index_on_page)
        baseline = pxf(cell.baseline, dpi)
        centre = pxf(cell.x + cell.width / 2, dpi)

        # Anchor "ls" puts the text's baseline where we ask, which is the
        # whole point of printing a baseline on the template.
        wobble_x = rng.uniform(-jitter, jitter) * pxf(1.0, dpi)
        wobble_y = rng.uniform(-jitter, jitter) * pxf(0.6, dpi)
        box = draw.textbbox((0, 0), slot.character, font=font, anchor="ls")
        width = box[2] - box[0]
        draw.text(
            (centre - width / 2 + wobble_x, baseline + wobble_y),
            slot.character, font=font, fill=PEN, anchor="ls",
        )
    return image


def photograph(
    image: Image.Image,
    rotation: float = 1.4,
    perspective: float = 0.012,
    noise: float = 5.0,
    vignette: float = 0.18,
    blur: float = 0.6,
    scale: float = 0.55,
    seed: int = 0,
) -> Image.Image:
    """Abuse a clean page the way a handheld photo would."""
    from PIL import ImageFilter

    rng = np.random.default_rng(seed)
    working = image.convert("RGB")
    if scale != 1.0:
        working = working.resize(
            (int(working.width * scale), int(working.height * scale)),
            Image.Resampling.LANCZOS,
        )
    width, height = working.size

    if perspective:
        shift = perspective * width
        corners_to = [(0, 0), (width, 0), (width, height), (0, height)]
        corners_from = [
            (rng.uniform(0, shift), rng.uniform(0, shift)),
            (width - rng.uniform(0, shift), rng.uniform(0, shift)),
            (width - rng.uniform(0, shift), height - rng.uniform(0, shift)),
            (rng.uniform(0, shift), height - rng.uniform(0, shift)),
        ]
        rows, values = [], []
        for (tx, ty), (sx, sy) in zip(corners_to, corners_from):
            rows.append([tx, ty, 1, 0, 0, 0, -sx * tx, -sx * ty]); values.append(sx)
            rows.append([0, 0, 0, tx, ty, 1, -sy * tx, -sy * ty]); values.append(sy)
        coefficients, *_ = np.linalg.lstsq(
            np.asarray(rows, float), np.asarray(values, float), rcond=None
        )
        working = working.transform(
            (width, height), Image.Transform.PERSPECTIVE, coefficients.tolist(),
            resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255),
        )

    if rotation:
        working = working.rotate(
            rotation, resample=Image.Resampling.BICUBIC,
            expand=True, fillcolor=(255, 255, 255),
        )
    if blur:
        working = working.filter(ImageFilter.GaussianBlur(blur))

    array = np.asarray(working, dtype=np.float32)
    if vignette:
        h, w = array.shape[:2]
        ys = np.linspace(-1, 1, h)[:, None]
        xs = np.linspace(-1, 1, w)[None, :]
        falloff = 1.0 - vignette * (xs ** 2 + ys ** 2) / 2.0
        array *= falloff[:, :, None]
    if noise:
        array += rng.normal(0, noise, array.shape)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
