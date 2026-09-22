"""The design system: palettes and the hand-drawn controls."""

import os

import pytest

# theme.py is the only module that needs Tk at import time; everything else
# in the package works headlessly, so skip the whole file rather than break
# collection on a Python built without tkinter.
pytest.importorskip("tkinter", reason="the design system needs tkinter")

from bank_reconciliation.theme import (  # noqa: E402
    DARK, LIGHT, PALETTES, SKETCH, sketch_segment,
)


def _tk_available() -> bool:
    try:
        import tkinter
    except ImportError:
        return False
    if not (os.environ.get("DISPLAY") or os.name == "nt"):
        return False
    try:
        root = tkinter.Tk()
    except Exception:  # noqa: BLE001
        return False
    root.destroy()
    return True


tk_only = pytest.mark.skipif(not _tk_available(), reason="needs tkinter and a display")


def test_every_palette_defines_every_colour():
    assert set(PALETTES) == {"light", "dark", "sketch"}
    for palette in (LIGHT, DARK, SKETCH):
        for field, value in vars(palette).items():
            if field in ("name", "sketch"):
                continue
            assert isinstance(value, str) and value.startswith("#"), field


def test_light_and_dark_are_actually_different():
    assert LIGHT.canvas != DARK.canvas
    assert LIGHT.text != DARK.text


def test_only_the_sketch_palette_is_hand_drawn():
    assert SKETCH.sketch is True
    assert LIGHT.sketch is False and DARK.sketch is False


def test_sketch_stroke_is_stable_for_a_given_seed():
    """Unseeded jitter would make the whole interface shimmer on every repaint."""
    first = sketch_segment(0, 0, 100, 0, seed=42)
    assert first == sketch_segment(0, 0, 100, 0, seed=42)
    assert first != sketch_segment(0, 0, 100, 0, seed=43)


def test_sketch_stroke_keeps_its_endpoints():
    """Corners must still meet, however much the middle wanders."""
    points = sketch_segment(10, 20, 110, 20, seed=7)
    assert (points[0], points[1]) == (10, 20)
    assert (points[-2], points[-1]) == (110, 20)


def test_sketch_stroke_actually_wanders():
    points = sketch_segment(0, 0, 200, 0, seed=5)
    ys = points[1::2]
    assert max(abs(y) for y in ys) > 0.2, "a perfectly straight line is not hand-drawn"


def test_a_degenerate_stroke_does_not_divide_by_zero():
    assert sketch_segment(5, 5, 5, 5, seed=1) == [5, 5, 5, 5]


@pytest.fixture
def tk_root():
    import tkinter as tk

    root = tk.Tk()
    root.geometry("600x400")
    yield root
    root.destroy()


@pytest.fixture
def scale(tk_root):
    from bank_reconciliation.theme import Typography, apply_theme

    type_scale = Typography.build(tk_root)
    apply_theme(tk_root, LIGHT, type_scale)
    return type_scale


@tk_only
def test_rounded_button_behaves_like_a_ttk_button(tk_root, scale):
    from bank_reconciliation.theme import RoundedButton

    clicks = []
    button = RoundedButton(
        tk_root, text="Go", command=lambda: clicks.append(1),
        palette=LIGHT, type_scale=scale,
    )
    button.pack()
    tk_root.update()

    button.invoke()
    assert clicks == [1]
    assert str(button["state"]) == "normal"

    button.configure(state="disabled")
    assert str(button["state"]) == "disabled"
    button.invoke()
    assert clicks == [1], "a disabled button must not fire"

    button.configure(state="normal")
    button.invoke()
    assert clicks == [1, 1]


@tk_only
def test_toggle_switch_flips_its_variable(tk_root, scale):
    import tkinter as tk

    from bank_reconciliation.theme import ToggleSwitch

    variable = tk.BooleanVar(value=False)
    fired = []
    switch = ToggleSwitch(
        tk_root, variable=variable, palette=LIGHT, type_scale=scale,
        text="Enabled", command=lambda: fired.append(1),
    )
    switch.pack()
    tk_root.update()

    switch._on_click()
    assert variable.get() is True and fired == [1]
    switch._on_click()
    assert variable.get() is False


@tk_only
def test_toggle_switch_draws_at_full_size_not_one_pixel(tk_root, scale):
    """Tk reports height 1 before a widget is mapped, and 1 is truthy.

    Taking that at face value drew the whole control into a single pixel.
    """
    import tkinter as tk

    from bank_reconciliation.theme import ToggleSwitch

    switch = ToggleSwitch(
        tk_root, variable=tk.BooleanVar(value=True), palette=LIGHT,
        type_scale=scale, text="Match several ledger lines",
    )
    switch.pack()
    tk_root.update()
    tk_root.update_idletasks()

    assert switch.winfo_height() >= 20
    # Every drawn item must sit inside the widget, not squashed at the top.
    boxes = [switch.bbox(item) for item in switch.find_all()]
    assert boxes, "the switch drew nothing"
    assert max(box[3] for box in boxes if box) >= 15


@tk_only
def test_segmented_control_selects_a_value(tk_root, scale):
    import tkinter as tk

    from bank_reconciliation.theme import SegmentedControl

    variable = tk.StringVar(value="a")
    changed = []
    control = SegmentedControl(
        tk_root, variable=variable,
        options=[("a", "First"), ("b", "Second")],
        palette=LIGHT, type_scale=scale, command=lambda: changed.append(1),
    )
    control.pack()
    tk_root.update()

    left, right = control._bounds(1)
    control._on_click(type("E", (), {"x": (left + right) / 2, "y": 10})())
    assert variable.get() == "b" and changed == [1]


@tk_only
def test_collapsible_card_folds_and_reports_it(tk_root, scale):
    from bank_reconciliation.theme import CollapsibleCard

    toggles = []
    card = CollapsibleCard(
        tk_root, LIGHT, scale, title="Settings", caption="optional",
        expanded=False, on_toggle=lambda state: toggles.append(state),
    )
    card.pack(fill="x")
    tk_root.update()

    assert not card.expanded
    card._toggle()
    assert card.expanded and toggles == [True]
    card._toggle()
    assert not card.expanded and toggles == [True, False]


@tk_only
def test_auto_hide_scrollbar_disappears_when_everything_fits(tk_root, scale):
    from bank_reconciliation.theme import AutoHideScrollbar

    bar = AutoHideScrollbar(tk_root, orient="vertical")
    bar.grid(row=0, column=1, sticky="ns")
    tk_root.update()

    bar.set(0.0, 1.0)
    tk_root.update()
    assert bar.grid_info() == {}, "a scrollbar with nothing to scroll must hide"

    bar.set(0.0, 0.4)
    tk_root.update()
    assert bar.grid_info() != {}, "it must come back when the content overflows"


@tk_only
def test_theme_applies_in_both_modes(tk_root):
    from bank_reconciliation.theme import Typography, apply_theme

    scale = Typography.build(tk_root)
    for palette in (LIGHT, DARK):
        style = apply_theme(tk_root, palette, scale)
        assert style.lookup("TLabel", "background") == palette.card


# ------------------------------------------------------------------- sketch
@pytest.fixture
def sketch_scale(tk_root):
    from bank_reconciliation.theme import Typography, apply_theme

    type_scale = Typography.build(tk_root, sketch=True)
    apply_theme(tk_root, SKETCH, type_scale)
    return type_scale


@tk_only
def test_sketch_typography_uses_a_handwriting_face(tk_root, sketch_scale):
    from bank_reconciliation.fonts import SKETCH_FAMILIES, preferred_family

    family = sketch_scale.body.actual("family")
    acceptable = {name.lower() for name in SKETCH_FAMILIES}
    # A font the user made from their own handwriting outranks the list.
    personal = preferred_family()
    if personal:
        acceptable.add(personal.lower())
    assert family.lower() in acceptable, family


@tk_only
def test_a_sketch_card_draws_its_own_border(tk_root, sketch_scale):
    from bank_reconciliation.theme import Card

    card = Card(tk_root, SKETCH)
    card.pack(fill="both", expand=True)
    tk_root.update()
    tk_root.update_idletasks()

    assert card._frame_canvas is not None
    assert card._frame_canvas.find_all(), "the hand-drawn frame was never drawn"


@tk_only
def test_a_clean_card_uses_a_widget_border_not_a_canvas(tk_root, scale):
    from bank_reconciliation.theme import Card

    card = Card(tk_root, LIGHT)
    card.pack()
    tk_root.update()
    assert card._frame_canvas is None


@tk_only
def test_framed_entry_boxes_the_input_only_in_sketch_mode(tk_root, sketch_scale):
    import tkinter as tk

    from bank_reconciliation.theme import framed_entry

    variable = tk.StringVar(value="hello")
    outer, inner = framed_entry(tk_root, SKETCH, variable, sketch_scale)
    assert outer is not inner, "sketch mode wraps the entry in a drawn box"
    assert inner.get() == "hello"

    plain_outer, plain_inner = framed_entry(tk_root, LIGHT, variable, sketch_scale)
    assert plain_outer is plain_inner


@tk_only
def test_framed_combobox_keeps_its_values(tk_root, sketch_scale):
    import tkinter as tk

    from bank_reconciliation.theme import framed_entry

    variable = tk.StringVar(value="auto")
    _outer, inner = framed_entry(
        tk_root, SKETCH, variable, sketch_scale, values=["auto", "same", "flip"]
    )
    assert list(inner["values"]) == ["auto", "same", "flip"]
    assert str(inner["state"]) == "readonly"


@tk_only
def test_separator_is_drawn_by_hand_in_sketch_mode(tk_root, sketch_scale):
    from bank_reconciliation.theme import SketchSeparator, separator

    assert isinstance(separator(tk_root, SKETCH), SketchSeparator)
    assert not isinstance(separator(tk_root, LIGHT), SketchSeparator)


@tk_only
def test_sketch_controls_render_without_error(tk_root, sketch_scale):
    """Every hand-drawn control must actually put ink on its canvas."""
    import tkinter as tk

    from bank_reconciliation.theme import (
        Chip, RoundedButton, SegmentedControl, ToggleSwitch,
    )

    widgets = [
        RoundedButton(tk_root, text="Go", palette=SKETCH, type_scale=sketch_scale),
        SegmentedControl(
            tk_root, variable=tk.StringVar(value="a"),
            options=[("a", "One"), ("b", "Two")],
            palette=SKETCH, type_scale=sketch_scale,
        ),
        ToggleSwitch(
            tk_root, variable=tk.BooleanVar(value=True),
            palette=SKETCH, type_scale=sketch_scale, text="On",
        ),
        Chip(tk_root, "Matched", SKETCH.ok_fill, SKETCH.ok, sketch_scale, palette=SKETCH),
    ]
    for widget in widgets:
        widget.pack()
    tk_root.update()
    tk_root.update_idletasks()
    for widget in widgets:
        assert widget.find_all(), f"{type(widget).__name__} drew nothing"
