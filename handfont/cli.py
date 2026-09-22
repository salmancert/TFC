"""Command line for the handwriting-font pipeline."""

from __future__ import annotations

import argparse
import glob
import logging
import os
import sys

LOGGER = logging.getLogger("handfont")


def _print_specimen(font_path: str, out_path: str) -> str:
    from PIL import Image, ImageDraw, ImageFont

    lines = [
        ("The quick brown fox jumps over the lazy dog", 34),
        ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 30),
        ("abcdefghijklmnopqrstuvwxyz", 30),
        ("0123456789   $ 1,234.56   (987.65)   £ € ¥", 30),
        ("Bank Reconciliation - 22 matched, 8 still open", 28),
    ]
    image = Image.new("RGB", (1120, 60 + sum(s + 34 for _, s in lines)), "white")
    draw = ImageDraw.Draw(image)
    y = 26
    for text, size in lines:
        draw.text((30, y), text, font=ImageFont.truetype(font_path, size), fill=(20, 20, 20))
        y += size + 34
    image.save(out_path)
    return out_path


def command_template(args) -> int:
    from .charset import DEFAULT_SET, pages_needed
    from .layout import PageLayout
    from .template import write_template

    layout = PageLayout(paper=args.paper)
    characters = list(args.chars) if args.chars else DEFAULT_SET
    path = write_template(args.output, characters, layout)
    pages = pages_needed(characters, per_page=layout.per_page)
    print(f"Template written to {path}")
    print(f"  {len(characters)} characters across {pages} page(s), {args.paper.upper()}")
    print("  Print at 100% scale (no 'fit to page'), fill it in, then scan or photograph it.")
    return 0


def command_build(args) -> int:
    from PIL import Image

    from .build import FontInfo, build_font
    from .charset import DEFAULT_SET, build_slots
    from .layout import PageLayout
    from .scan import read_page
    from .trace import trace_glyph

    paths: list[str] = []
    for pattern in args.scans:
        matched = sorted(glob.glob(pattern))
        paths.extend(matched or ([pattern] if os.path.exists(pattern) else []))
    if not paths:
        LOGGER.error("No scans found matching: %s", " ".join(args.scans))
        return 2

    layout = PageLayout(paper=args.paper)
    characters = list(args.chars) if args.chars else DEFAULT_SET
    slots = build_slots(characters, per_page=layout.per_page)
    by_page: dict[int, dict[int, str]] = {}
    for slot in slots:
        by_page.setdefault(slot.page, {})[slot.index_on_page] = slot.character

    traced = {}
    for path in paths:
        try:
            page = read_page(Image.open(path), layout)
        except Exception as error:  # noqa: BLE001 - reported per file
            LOGGER.error("Could not read %s: %s", os.path.basename(path), error)
            continue
        mapping = by_page.get(page.page)
        if mapping is None:
            LOGGER.warning(
                "%s says it is page %d, which is not in this character set - skipping.",
                os.path.basename(path), page.page + 1,
            )
            continue
        written = 0
        for index, glyph in page.glyphs.items():
            character = mapping.get(index)
            if character is None:
                continue
            result = trace_glyph(
                character, glyph, side_bearing=args.spacing, smooth=args.smooth
            )
            if not result.is_blank:
                traced[character] = result
                written += 1
        print(f"  {os.path.basename(path)}: page {page.page + 1}, {written} characters")

    if not traced:
        LOGGER.error("Nothing could be read from those scans.")
        return 1

    info = FontInfo(
        family=args.name,
        designer=args.designer or args.name,
        version=args.version,
    )
    if args.license:
        info.license = args.license

    report = build_font(traced, args.output, info, expected=characters)
    print(f"\n{report.summary()}")

    if report.missing:
        print("  Blank boxes are simply left out; write them in and re-run to fill the gaps.")

    if args.preview:
        print(f"  Specimen: {_print_specimen(args.output, args.preview)}")

    if args.install:
        from .install import install_font

        target, preference = install_font(args.output, args.name)
        print(f"  Installed to {target}")
        if preference:
            print(f"  Recorded as your preferred handwriting font in {preference}")
    return 0


def command_preview(args) -> int:
    print(f"Specimen: {_print_specimen(args.font, args.output)}")
    return 0


def command_demo(args) -> int:
    """Run the whole pipeline on generated pages, to prove it works."""
    from .build import FontInfo, build_font
    from .charset import DEFAULT_SET, build_slots
    from .layout import PageLayout
    from .scan import read_page
    from .synthetic import fill_page, photograph
    from .trace import trace_glyph

    layout = PageLayout()
    slots = build_slots(DEFAULT_SET, per_page=layout.per_page)
    by_page: dict[int, dict[int, str]] = {}
    for slot in slots:
        by_page.setdefault(slot.page, {})[slot.index_on_page] = slot.character

    traced = {}
    for page_number in sorted(by_page):
        image = photograph(fill_page(page_number), seed=page_number + 1)
        page = read_page(image, layout)
        for index, glyph in page.glyphs.items():
            character = by_page[page.page].get(index)
            if character:
                traced[character] = trace_glyph(character, glyph)
        print(f"  simulated page {page.page + 1}: {len(page.glyphs)} boxes read")

    report = build_font(traced, args.output, FontInfo(family="Demo Hand"), DEFAULT_SET)
    print(report.summary())
    if args.preview:
        print(f"Specimen: {_print_specimen(args.output, args.preview)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handfont",
        description="Turn your handwriting into a font you own outright.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    template = sub.add_parser("template", help="Make the sheets to print and fill in")
    template.add_argument("-o", "--output", default="handwriting-template.pdf")
    template.add_argument("--paper", choices=("a4", "letter"), default="a4")
    template.add_argument("--chars", help="Characters to ask for (default: the full set)")
    template.set_defaults(func=command_template)

    build = sub.add_parser("build", help="Turn filled-in scans into a font")
    build.add_argument("scans", nargs="+", help="Scanned or photographed pages")
    build.add_argument("-o", "--output", default="MyHandwriting.ttf")
    build.add_argument("-n", "--name", default="My Handwriting", help="Font family name")
    build.add_argument("--designer", default="")
    build.add_argument("--version", default="1.000")
    build.add_argument("--license", help="Licence text to embed (default: all rights reserved)")
    build.add_argument("--paper", choices=("a4", "letter"), default="a4")
    build.add_argument("--chars", help="The character set the template was made with")
    build.add_argument("--spacing", type=int, default=40,
                       help="Side bearing in font units; raise for airier text")
    build.add_argument("--smooth", type=int, default=1,
                       help="Smoothing passes over the scan (0 keeps every wobble)")
    build.add_argument("--preview", help="Also render a specimen image here")
    build.add_argument("--install", action="store_true",
                       help="Install the font for your user and prefer it in the sketch theme")
    build.set_defaults(func=command_build)

    preview = sub.add_parser("preview", help="Render a specimen from a font file")
    preview.add_argument("font")
    preview.add_argument("-o", "--output", default="specimen.png")
    preview.set_defaults(func=command_preview)

    demo = sub.add_parser("demo", help="Run the pipeline on generated pages")
    demo.add_argument("-o", "--output", default="DemoHand.ttf")
    demo.add_argument("--preview", help="Also render a specimen image here")
    demo.set_defaults(func=command_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s"
    )
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
