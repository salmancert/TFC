"""The design system: palettes and the hand-drawn controls."""

import os

import pytest

# theme.py is the only module that needs Tk at import time; everything else
# in the package works headlessly, so skip the whole file rather than break
# collection on a Python built without tkinter.
pytest.importorskip("tkinter", reason="the design system needs tkinter")

from bank_reconciliation.theme import DARK, LIGHT, PALETTES  # noqa: E402


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


def test_both_palettes_define_every_colour():
    assert set(PALETTES) == {"light", "dark"}
    for palette in (LIGHT, DARK):
        for field, value in vars(palette).items():
            if field == "name":
                continue
            assert isinstance(value, str) and value.startswith("#"), field


def test_light_and_dark_are_actually_different():
    assert LIGHT.canvas != DARK.canvas
    assert LIGHT.text != DARK.text


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
