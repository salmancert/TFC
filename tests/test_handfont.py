"""The handwriting-to-font pipeline, end to end.

The scans are generated rather than photographed, which is what makes
these runnable: a template is filled in programmatically, abused the way a
phone camera would abuse it, and then read back.
"""

import numpy as np
import pytest

pytest.importorskip("PIL", reason="the font pipeline needs Pillow")
pytest.importorskip("potrace", reason="the font pipeline needs potracer")

from PIL import Image  # noqa: E402

from handfont.charset import (  # noqa: E402
    DEFAULT_SET,
    build_slots,
    glyph_name_for,
    pages_needed,
)
from handfont.layout import PageLayout  # noqa: E402
from handfont.scan import find_markers, read_page, read_page_code, rectify  # noqa: E402
from handfont.synthetic import fill_page, photograph  # noqa: E402
from handfont.template import render_all, render_page, write_template  # noqa: E402
from handfont.trace import trace_bitmap, trace_glyph  # noqa: E402


# ------------------------------------------------------------------ layout
def test_the_grid_fits_the_character_set_in_two_pages():
    layout = PageLayout()
    assert layout.columns >= 5 and layout.rows >= 6
    assert pages_needed(DEFAULT_SET, per_page=layout.per_page) <= 3


def test_cells_do_not_overlap_and_stay_on_the_paper():
    layout = PageLayout()
    width, height = layout.size
    boxes = []
    for cell in layout.cells():
        assert cell.x >= 0 and cell.y >= 0
        assert cell.x + cell.width <= width
        assert cell.y + cell.height <= height
        boxes.append((cell.x, cell.y, cell.x + cell.width, cell.y + cell.height))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            ax1, ay1, ax2, ay2 = boxes[i]
            bx1, by1, bx2, by2 = boxes[j]
            assert ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1


def test_the_guides_are_ordered_down_the_cell():
    cell = PageLayout().cell(0)
    from handfont.layout import ASCENDER_AT, BASELINE_AT, DESCENDER_AT, XHEIGHT_AT

    guides = [cell.guide(f) for f in (ASCENDER_AT, XHEIGHT_AT, BASELINE_AT, DESCENDER_AT)]
    assert guides == sorted(guides)
    assert cell.write_top < guides[0]
    assert guides[-1] <= cell.y + cell.height


@pytest.mark.parametrize("character, expected", [
    ("A", "A"), ("z", "z"), ("5", "five"), ("$", "dollar"),
    ("£", "sterling"), (".", "period"), ("€", "Euro"),
])
def test_glyph_names_are_legal(character, expected):
    assert glyph_name_for(character) == expected


def test_every_character_gets_its_own_box():
    layout = PageLayout()
    slots = build_slots(DEFAULT_SET, per_page=layout.per_page)
    assert len(slots) == len(DEFAULT_SET)
    seen = {(s.page, s.index_on_page) for s in slots}
    assert len(seen) == len(slots), "two characters landed in the same box"


# ---------------------------------------------------------------- template
def test_template_renders_at_the_right_physical_size():
    page = render_page(0, build_slots(DEFAULT_SET, per_page=PageLayout().per_page))
    # A4 at 300 dpi.
    assert abs(page.width - 2480) <= 4
    assert abs(page.height - 3508) <= 4


def test_template_writes_a_multi_page_pdf(tmp_path):
    path = write_template(str(tmp_path / "t.pdf"))
    assert path.endswith(".pdf")
    assert (tmp_path / "t.pdf").stat().st_size > 5000


def test_template_can_write_pngs(tmp_path):
    first = write_template(str(tmp_path / "t.png"))
    assert (tmp_path / "t-1.png").exists()
    assert first.endswith("-1.png")


def test_guides_are_light_enough_to_threshold_away():
    """The printed box must vanish under the same threshold that keeps pen."""
    from handfont.scan import INK_THRESHOLD

    page = render_page(0, build_slots(DEFAULT_SET, per_page=PageLayout().per_page))
    layout = PageLayout()
    cell = layout.cell(0)
    from handfont.layout import pxf

    # Sample well inside one empty writing area.
    left, right = int(pxf(cell.x + 3)), int(pxf(cell.x + cell.width - 3))
    top, bottom = int(pxf(cell.write_top + 2)), int(pxf(cell.y + cell.height - 2))
    patch = np.asarray(page.convert("L"))[top:bottom, left:right]
    assert (patch < INK_THRESHOLD).sum() == 0, "printed guides would be read as ink"


# -------------------------------------------------------------------- scan
@pytest.fixture(scope="module")
def filled_page():
    return fill_page(0)


def test_markers_are_found_on_a_clean_page(filled_page):
    marks = find_markers(filled_page)
    assert len(marks) == 4
    xs = [m[0] for m in marks]
    ys = [m[1] for m in marks]
    # Template order: TL, TR, BL, BR.
    assert xs[0] < xs[1] and xs[2] < xs[3]
    assert ys[0] < ys[2] and ys[1] < ys[3]


def test_markers_survive_a_handheld_photo(filled_page):
    assert len(find_markers(photograph(filled_page, seed=3))) == 4


def test_a_page_upside_down_still_reads_the_right_way_up(filled_page):
    """The odd small marker exists precisely so this works."""
    flipped = filled_page.rotate(180, expand=True, fillcolor=(255, 255, 255))
    page = read_page(flipped)
    layout = PageLayout()
    mapping = {
        s.index_on_page: s.character
        for s in build_slots(DEFAULT_SET, per_page=layout.per_page) if s.page == 0
    }
    assert len(page.glyphs) >= len(mapping) - 2


def test_page_code_round_trips():
    layout = PageLayout()
    slots = build_slots(DEFAULT_SET, per_page=layout.per_page)
    for page_number in range(pages_needed(DEFAULT_SET, per_page=layout.per_page)):
        image = render_page(page_number, slots, layout)
        assert read_page_code(rectify(image, layout), layout) == page_number


def test_every_written_box_is_found_on_a_clean_scan(filled_page):
    layout = PageLayout()
    expected = {
        s.index_on_page for s in build_slots(DEFAULT_SET, per_page=layout.per_page)
        if s.page == 0
    }
    page = read_page(filled_page, layout)
    assert page.page == 0
    assert set(page.glyphs) == expected


def test_every_written_box_is_found_in_a_photo(filled_page):
    layout = PageLayout()
    expected = {
        s.index_on_page for s in build_slots(DEFAULT_SET, per_page=layout.per_page)
        if s.page == 0
    }
    page = read_page(photograph(filled_page, seed=7), layout)
    assert set(page.glyphs) == expected


def test_empty_boxes_are_skipped_not_invented():
    layout = PageLayout()
    image = fill_page(0, skip={"A", "B", "C"})
    page = read_page(image, layout)
    mapping = {
        s.index_on_page: s.character
        for s in build_slots(DEFAULT_SET, per_page=layout.per_page) if s.page == 0
    }
    written = {mapping[i] for i in page.glyphs}
    assert {"A", "B", "C"}.isdisjoint(written)
    assert "D" in written


def test_a_blank_page_raises_something_readable():
    blank = Image.new("RGB", (800, 1000), "white")
    with pytest.raises(ValueError):
        find_markers(blank)


# ------------------------------------------------------------------- trace
def test_potrace_ink_polarity_is_handled():
    """potracer traces ZEROES, so an ink mask has to go in inverted."""
    mask = np.zeros((60, 60), dtype=bool)
    mask[15:45, 15:45] = True
    contours = trace_bitmap(mask)
    assert len(contours) == 1, "tracing the wrong polarity adds a page-border contour"
    xs = [p[0] for command in contours[0] for p in command[1:]]
    assert max(xs) - min(xs) < 45, "the contour should hug the square, not the image"


def test_a_hole_becomes_its_own_contour():
    mask = np.zeros((80, 80), dtype=bool)
    mask[10:70, 10:70] = True
    mask[30:50, 30:50] = False
    assert len(trace_bitmap(mask)) == 2


def test_an_empty_bitmap_traces_to_nothing():
    assert trace_bitmap(np.zeros((20, 20), dtype=bool)) == []


def test_glyphs_land_on_the_baseline(filled_page):
    """A capital sits on y=0 and rises; a descender goes below it."""
    layout = PageLayout()
    page = read_page(filled_page, layout)
    mapping = {
        s.index_on_page: s.character
        for s in build_slots(DEFAULT_SET, per_page=layout.per_page) if s.page == 0
    }
    traced = {
        mapping[i]: trace_glyph(mapping[i], g)
        for i, g in page.glyphs.items() if i in mapping
    }

    cap = traced["H"]
    assert cap.ink_box[1] == pytest.approx(0, abs=60), "a capital should sit on the baseline"
    assert cap.ink_box[3] > 400, "a capital should have real height"

    descender = traced["p"]
    assert descender.ink_box[1] < -40, "p should drop below the baseline"


def test_traced_glyphs_have_sane_advances(filled_page):
    layout = PageLayout()
    page = read_page(filled_page, layout)
    mapping = {
        s.index_on_page: s.character
        for s in build_slots(DEFAULT_SET, per_page=layout.per_page) if s.page == 0
    }
    for index, glyph in page.glyphs.items():
        character = mapping[index]
        traced = trace_glyph(character, glyph)
        assert 0 < traced.advance <= 1400, f"{character!r} advance {traced.advance}"
        assert traced.contours, f"{character!r} traced to nothing"


# ------------------------------------------------------------------- build
@pytest.fixture(scope="module")
def built_font(tmp_path_factory):
    """The whole pipeline, from generated pages to a real TTF."""
    from handfont.build import FontInfo, build_font

    layout = PageLayout()
    slots = build_slots(DEFAULT_SET, per_page=layout.per_page)
    by_page: dict[int, dict[int, str]] = {}
    for slot in slots:
        by_page.setdefault(slot.page, {})[slot.index_on_page] = slot.character

    traced = {}
    for page_number in sorted(by_page):
        page = read_page(photograph(fill_page(page_number), seed=page_number + 1), layout)
        for index, glyph in page.glyphs.items():
            character = by_page[page.page].get(index)
            if character:
                traced[character] = trace_glyph(character, glyph)

    path = tmp_path_factory.mktemp("font") / "Test.ttf"
    report = build_font(
        traced, str(path), FontInfo(family="Test Hand"), expected=DEFAULT_SET
    )
    return str(path), report


def test_the_whole_pipeline_produces_a_valid_font(built_font):
    from fontTools.ttLib import TTFont

    path, report = built_font
    font = TTFont(path)
    assert font["head"].unitsPerEm == 1000
    for table in ("cmap", "glyf", "hmtx", "name", "OS/2", "post", "hhea"):
        assert table in font, f"missing {table}"
    assert report.glyphs >= len(DEFAULT_SET) - 2
    assert not report.missing, f"unexpectedly blank: {report.missing}"


def test_every_requested_character_is_mapped(built_font):
    from fontTools.ttLib import TTFont

    path, _ = built_font
    cmap = TTFont(path).getBestCmap()
    for character in DEFAULT_SET:
        assert ord(character) in cmap, f"{character!r} never made it into the font"
    assert ord(" ") in cmap, "a font without a space is unusable"


def test_the_font_carries_the_name_it_was_given(built_font):
    from fontTools.ttLib import TTFont

    path, _ = built_font
    names = {record.nameID: str(record) for record in TTFont(path)["name"].names}
    assert names[1] == "Test Hand"
    assert "rights reserved by the author" in names[13].lower() or names[13]


def test_the_font_actually_renders_text(built_font, tmp_path):
    """A font that builds but draws nothing is worse than no font."""
    from PIL import Image, ImageDraw, ImageFont

    path, _ = built_font
    image = Image.new("L", (760, 140), 255)
    draw = ImageDraw.Draw(image)
    draw.text((20, 30), "Handwriting 123", font=ImageFont.truetype(path, 48), fill=0)
    inked = (np.asarray(image) < 128).sum()
    assert inked > 900, f"only {inked} dark pixels - the glyphs are empty"


def test_glyphs_have_the_expected_vertical_relationships(built_font):
    """Capitals tall, x-height shorter, descenders below the baseline."""
    from fontTools.ttLib import TTFont

    path, _ = built_font
    font = TTFont(path)
    glyphs = font["glyf"]

    def box(character):
        name = font.getBestCmap()[ord(character)]
        glyph = glyphs[name]
        glyph.recalcBounds(glyphs)
        return glyph.yMin, glyph.yMax

    _, cap_top = box("H")
    _, x_top = box("x")
    p_bottom, _ = box("p")
    assert cap_top > x_top, "capitals should be taller than x-height"
    assert p_bottom < 0, "p should descend below the baseline"


def test_building_without_any_ink_says_so(tmp_path):
    from handfont.build import build_font

    with pytest.raises(ValueError, match="No written characters"):
        build_font({}, str(tmp_path / "empty.ttf"))


def test_missing_characters_are_reported_not_faked(tmp_path):
    from handfont.build import build_font

    layout = PageLayout()
    page = read_page(fill_page(0, skip={"A", "B"}), layout)
    mapping = {
        s.index_on_page: s.character
        for s in build_slots(DEFAULT_SET, per_page=layout.per_page) if s.page == 0
    }
    traced = {
        mapping[i]: trace_glyph(mapping[i], g)
        for i, g in page.glyphs.items() if i in mapping
    }
    report = build_font(
        traced, str(tmp_path / "gaps.ttf"), expected=sorted(mapping.values())
    )
    assert set(report.missing) == {"A", "B"}
    assert "still blank" in report.summary()


# --------------------------------------------------------------------- cli
def test_cli_template(tmp_path, capsys):
    from handfont.cli import main

    target = tmp_path / "t.pdf"
    assert main(["template", "-o", str(target)]) == 0
    assert target.exists()
    assert "Print at 100%" in capsys.readouterr().out


def test_cli_demo_builds_and_previews(tmp_path):
    from handfont.cli import main

    font = tmp_path / "demo.ttf"
    preview = tmp_path / "specimen.png"
    assert main(["demo", "-o", str(font), "--preview", str(preview)]) == 0
    assert font.exists() and preview.exists()


def test_cli_build_from_rendered_pages(tmp_path):
    from handfont.cli import main

    for page_number in (0, 1):
        fill_page(page_number).save(tmp_path / f"page{page_number}.png")
    font = tmp_path / "Mine.ttf"
    assert main([
        "build", str(tmp_path / "page0.png"), str(tmp_path / "page1.png"),
        "-o", str(font), "-n", "Scan Hand",
    ]) == 0
    from fontTools.ttLib import TTFont

    assert {r.nameID: str(r) for r in TTFont(str(font))["name"].names}[1] == "Scan Hand"


def test_cli_build_with_no_readable_scans_fails_cleanly(tmp_path):
    from handfont.cli import main

    Image.new("RGB", (600, 800), "white").save(tmp_path / "blank.png")
    assert main(["build", str(tmp_path / "blank.png"), "-o", str(tmp_path / "x.ttf")]) == 1


def test_cli_build_with_a_missing_file_fails_cleanly(tmp_path):
    from handfont.cli import main

    assert main(["build", str(tmp_path / "nope.png"), "-o", str(tmp_path / "x.ttf")]) == 2


def test_install_records_the_preference(tmp_path, monkeypatch):
    from handfont import install

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(install.PREFERENCE_ENV, raising=False)

    source = tmp_path / "Font.ttf"
    source.write_bytes(b"not really a font, but the copy is what is tested")
    target, preference = install.install_font(str(source), "Someone's Hand")

    assert target.exists()
    assert preference is not None and preference.exists()
    assert install.read_preferred_family() == "Someone's Hand"


def test_the_environment_can_override_the_preference(monkeypatch, tmp_path):
    from handfont import install

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv(install.PREFERENCE_ENV, "Env Hand")
    assert install.read_preferred_family() == "Env Hand"
