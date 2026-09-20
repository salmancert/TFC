"""A small, self-contained design system for the desktop app.

Tk's stock widgets look like 1995, and the usual fixes are third-party
theme packages.  This module gets a modern look out of the standard
library alone: a flat restyle of the ``clam`` ttk theme, a light and a
dark palette, a typographic scale, card containers with hairline borders,
and canvas-drawn rounded buttons for the things ttk cannot round.

Nothing here knows about reconciliation - it is purely presentation.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk


@dataclass(frozen=True)
class Palette:
    """Every colour the app uses, in one place per mode."""

    name: str
    canvas: str          # the window behind the cards
    card: str            # card surface
    card_border: str     # hairline around a card
    field: str           # entry / combobox interior
    field_border: str
    text: str            # primary text
    muted: str           # secondary text
    subtle: str          # tertiary text, placeholders
    accent: str          # primary action
    accent_hover: str
    accent_text: str     # text on the accent
    ghost_hover: str     # secondary button hover
    selection: str       # selected row
    stripe: str          # zebra row
    header: str          # table header background
    ok: str
    ok_fill: str
    info: str
    info_fill: str
    warn: str
    warn_fill: str
    bad: str
    bad_fill: str


LIGHT = Palette(
    name="light",
    canvas="#F4F5F7",
    card="#FFFFFF",
    card_border="#E4E7EC",
    field="#FFFFFF",
    field_border="#D5D9E0",
    text="#1B1F27",
    muted="#5B6472",
    subtle="#8A93A2",
    accent="#4F46E5",
    accent_hover="#4338CA",
    accent_text="#FFFFFF",
    ghost_hover="#F0F1F4",
    selection="#E8E7FC",
    stripe="#FAFBFC",
    header="#F7F8FA",
    ok="#12703A", ok_fill="#DCF5E6",
    info="#14507F", info_fill="#DCEBFA",
    warn="#8A5A00", warn_fill="#FCF0D2",
    bad="#9B1C25", bad_fill="#FBE0E2",
)

DARK = Palette(
    name="dark",
    canvas="#14161B",
    card="#1C1F26",
    card_border="#2C313B",
    field="#23272F",
    field_border="#3A4049",
    text="#E9ECF1",
    muted="#A3ACBA",
    subtle="#78828F",
    accent="#6366F1",
    accent_hover="#7C7FF3",
    accent_text="#FFFFFF",
    ghost_hover="#262A33",
    selection="#2E2F52",
    stripe="#1F232A",
    header="#232830",
    ok="#6EE7A0", ok_fill="#14361F",
    info="#8CC5F5", info_fill="#12314C",
    warn="#F5CE7A", warn_fill="#3D2F0E",
    bad="#F5A3A8", bad_fill="#421317",
)

PALETTES = {"light": LIGHT, "dark": DARK}

# Preferred UI faces per platform, most wanted first.
FONT_STACK = (
    "Segoe UI Variable Text", "Segoe UI",          # Windows
    "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue",  # macOS
    "Inter", "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans",  # Linux
)


def resolve_family(root: tk.Misc) -> str:
    """The first font in the stack this machine actually has."""
    available = {name.lower() for name in tkfont.families(root)}
    for family in FONT_STACK:
        if family.lower() in available:
            return family
    return "TkDefaultFont"


@dataclass
class Typography:
    """A small type scale, built once per window."""

    title: tkfont.Font
    subtitle: tkfont.Font
    section: tkfont.Font
    body: tkfont.Font
    body_bold: tkfont.Font
    caption: tkfont.Font
    mono: tkfont.Font

    @classmethod
    def build(cls, root: tk.Misc) -> "Typography":
        family = resolve_family(root)
        mono_available = {n.lower() for n in tkfont.families(root)}
        mono_family = next(
            (f for f in ("Cascadia Mono", "SF Mono", "Consolas", "Menlo",
                         "Ubuntu Mono", "DejaVu Sans Mono")
             if f.lower() in mono_available),
            "TkFixedFont",
        )
        return cls(
            title=tkfont.Font(root=root, family=family, size=17, weight="bold"),
            subtitle=tkfont.Font(root=root, family=family, size=10),
            section=tkfont.Font(root=root, family=family, size=11, weight="bold"),
            body=tkfont.Font(root=root, family=family, size=10),
            body_bold=tkfont.Font(root=root, family=family, size=10, weight="bold"),
            caption=tkfont.Font(root=root, family=family, size=9),
            mono=tkfont.Font(root=root, family=mono_family, size=9),
        )


def apply_theme(root: tk.Misc, palette: Palette, type_scale: Typography) -> ttk.Style:
    """Flatten ttk's ``clam`` theme into the given palette."""
    style = ttk.Style(root)
    style.theme_use("clam")
    p, t = palette, type_scale

    root.configure(background=p.canvas)

    style.configure(".", background=p.card, foreground=p.text, font=t.body,
                    borderwidth=0, focuscolor=p.accent)

    style.configure("Canvas.TFrame", background=p.canvas)
    style.configure("Card.TFrame", background=p.card)

    style.configure("TLabel", background=p.card, foreground=p.text, font=t.body)
    style.configure("Canvas.TLabel", background=p.canvas, foreground=p.text, font=t.body)
    style.configure("Title.TLabel", background=p.canvas, foreground=p.text, font=t.title)
    style.configure("Subtitle.TLabel", background=p.canvas, foreground=p.muted, font=t.subtitle)
    style.configure("Section.TLabel", background=p.card, foreground=p.text, font=t.section)
    style.configure("Caption.TLabel", background=p.card, foreground=p.muted, font=t.caption)
    style.configure("Muted.TLabel", background=p.card, foreground=p.muted, font=t.body)
    style.configure("Status.TLabel", background=p.canvas, foreground=p.muted, font=t.caption)
    style.configure("FieldLabel.TLabel", background=p.card, foreground=p.muted, font=t.caption)

    # --- text inputs ------------------------------------------------------
    style.configure(
        "TEntry",
        fieldbackground=p.field, background=p.field, foreground=p.text,
        bordercolor=p.field_border, lightcolor=p.field_border, darkcolor=p.field_border,
        insertcolor=p.text, borderwidth=1, relief="flat", padding=7,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", p.accent)],
        lightcolor=[("focus", p.accent)],
        darkcolor=[("focus", p.accent)],
    )

    style.configure(
        "TCombobox",
        fieldbackground=p.field, background=p.field, foreground=p.text,
        bordercolor=p.field_border, lightcolor=p.field_border, darkcolor=p.field_border,
        arrowcolor=p.muted, borderwidth=1, relief="flat", padding=6,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", p.field)],
        bordercolor=[("focus", p.accent), ("hover", p.accent)],
        lightcolor=[("focus", p.accent)],
        darkcolor=[("focus", p.accent)],
        arrowcolor=[("hover", p.accent)],
    )
    # The dropdown list is a plain Tk listbox behind the scenes.
    root.option_add("*TCombobox*Listbox.background", p.field)
    root.option_add("*TCombobox*Listbox.foreground", p.text)
    root.option_add("*TCombobox*Listbox.selectBackground", p.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", p.accent_text)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    # --- choices ----------------------------------------------------------
    for widget in ("TRadiobutton", "TCheckbutton"):
        style.configure(
            widget,
            background=p.card, foreground=p.text, font=t.body,
            indicatorcolor=p.field, indicatorbackground=p.field,
            bordercolor=p.field_border, focuscolor=p.card, padding=3,
        )
        style.map(
            widget,
            background=[("active", p.card)],
            foreground=[("disabled", p.subtle)],
            indicatorcolor=[("selected", p.accent), ("pressed", p.accent_hover)],
            bordercolor=[("selected", p.accent)],
        )

    # --- tables -----------------------------------------------------------
    style.configure(
        "Treeview",
        background=p.card, fieldbackground=p.card, foreground=p.text,
        borderwidth=0, relief="flat", rowheight=27, font=t.body,
    )
    style.configure(
        "Treeview.Heading",
        background=p.header, foreground=p.muted, font=t.caption,
        relief="flat", borderwidth=0, padding=(10, 8),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", p.header)],
        foreground=[("active", p.text)],
    )
    style.map(
        "Treeview",
        background=[("selected", p.selection)],
        foreground=[("selected", p.text)],
    )
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # drop the frame

    # --- scrollbars -------------------------------------------------------
    style.configure(
        "Vertical.TScrollbar",
        background=p.card_border, troughcolor=p.card, bordercolor=p.card,
        arrowcolor=p.muted, borderwidth=0, relief="flat", arrowsize=12,
    )
    style.map("Vertical.TScrollbar", background=[("active", p.subtle)])

    # --- progress ---------------------------------------------------------
    style.configure(
        "Thin.Horizontal.TProgressbar",
        background=p.accent, troughcolor=p.card_border,
        bordercolor=p.card_border, lightcolor=p.accent, darkcolor=p.accent,
        borderwidth=0, thickness=4,
    )

    style.configure("Sep.TSeparator", background=p.card_border)
    return style


# --------------------------------------------------------------------------
# Containers and controls that ttk cannot express
# --------------------------------------------------------------------------
class Card(tk.Frame):
    """A flat surface with a hairline border, the app's main container."""

    def __init__(self, master, palette: Palette, **kwargs):
        super().__init__(
            master,
            background=palette.card,
            highlightbackground=palette.card_border,
            highlightcolor=palette.card_border,
            highlightthickness=1,
            bd=0,
            **kwargs,
        )
        self.palette = palette

    def body(self, padx: int = 18, pady: int = 16) -> ttk.Frame:
        """An inner frame carrying the card's padding."""
        inner = ttk.Frame(self, style="Card.TFrame")
        inner.pack(fill="both", expand=True, padx=padx, pady=pady)
        return inner


def _measured(widget: tk.Misc, dimension: str, fallback: int) -> int:
    """Actual pixel size of a widget, or its configured size before mapping.

    Tk reports 1 for an unmapped widget, and ``winfo_height() or default``
    silently accepts that 1 because it is truthy - which draws the whole
    control into a single pixel.
    """
    value = widget.winfo_height() if dimension == "height" else widget.winfo_width()
    if value > 1:
        return value
    try:
        return int(widget[dimension])
    except (tk.TclError, ValueError):
        return fallback


def _rounded_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    """Corner points for a rounded rectangle drawn as a smoothed polygon."""
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class RoundedButton(tk.Canvas):
    """A flat, rounded button.

    ttk cannot round a corner, and square grey buttons are the single
    strongest "old application" signal, so the button is drawn by hand.
    It mimics enough of the ttk button API (``invoke``, ``configure`` and
    ``["state"]``) to be a drop-in for callers and tests.
    """

    def __init__(
        self,
        master,
        text: str,
        command=None,
        palette: Palette = LIGHT,
        type_scale: Typography | None = None,
        kind: str = "accent",          # accent | ghost
        height: int = 38,
        min_width: int = 0,
        surface: str | None = None,
        radius: int = 9,
    ) -> None:
        self.palette = palette
        self.kind = kind
        self.radius = radius
        self._surface = surface or (palette.card if kind == "ghost" else palette.canvas)
        self._font = (type_scale or Typography.build(master)).body_bold
        self._text = text
        self._command = command
        self._state = "normal"
        self._hover = False

        width = max(min_width, self._font.measure(text) + 34)
        super().__init__(
            master, width=width, height=height,
            highlightthickness=0, bd=0, background=self._surface,
        )
        self._shape = None
        self._label = None
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    # -- appearance ------------------------------------------------------
    def _colours(self) -> tuple[str, str, str | None]:
        p = self.palette
        if self._state == "disabled":
            return (
                (p.card_border, p.subtle, None) if self.kind == "accent"
                else (self._surface, p.subtle, p.card_border)
            )
        if self.kind == "accent":
            return (p.accent_hover if self._hover else p.accent), p.accent_text, None
        return (p.ghost_hover if self._hover else self._surface), p.text, p.card_border

    def _draw(self) -> None:
        self.delete("all")
        fill, text_colour, outline = self._colours()
        width = _measured(self, "width", 120)
        height = _measured(self, "height", 38)
        self._shape = self.create_polygon(
            _rounded_points(1, 1, width - 1, height - 1, self.radius),
            smooth=True, splinesteps=24,
            fill=fill, outline=outline or fill, width=1,
        )
        self._label = self.create_text(
            width / 2, height / 2 + 1, text=self._text,
            fill=text_colour, font=self._font,
        )

    # -- behaviour -------------------------------------------------------
    def _on_enter(self, _event=None) -> None:
        if self._state != "disabled":
            self._hover = True
            self.configure(cursor="hand2")
            self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self.configure(cursor="")
        self._draw()

    def _on_press(self, _event=None) -> None:
        if self._state != "disabled":
            self.move(self._label, 0, 1)

    def _on_release(self, _event=None) -> None:
        if self._state == "disabled":
            return
        self._draw()
        self.invoke()

    def invoke(self):
        """Run the command, as a ttk button would."""
        if self._state != "disabled" and self._command is not None:
            return self._command()
        return None

    # -- a ttk-like surface so callers and tests need not special-case it --
    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        state = kwargs.pop("state", None)
        text = kwargs.pop("text", None)
        if state is not None:
            self._state = str(state)
            if self._state == "disabled":
                self._hover = False
        if text is not None:
            self._text = text
        result = super().configure(cnf, **kwargs) if (cnf or kwargs) else None
        if state is not None or text is not None:
            self._draw()
        return result

    config = configure

    def cget(self, key):  # type: ignore[override]
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        return super().cget(key)

    def __getitem__(self, key):
        if key in ("state", "text"):
            return self.cget(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if key in ("state", "text"):
            self.configure(**{key: value})
        else:
            super().__setitem__(key, value)


class Chip(tk.Label):
    """A small pill of colour used for the legend and for status."""

    def __init__(self, master, text: str, fill: str, foreground: str,
                 type_scale: Typography, **kwargs):
        super().__init__(
            master, text=f" {text} ", background=fill, foreground=foreground,
            font=type_scale.caption, padx=8, pady=3, bd=0, **kwargs,
        )


class SegmentedControl(tk.Canvas):
    """An iOS/Windows-11 style segmented picker bound to a ``StringVar``.

    Replaces a row of radio buttons, whose stock Tk indicators are the
    most dated-looking control in the toolkit.
    """

    def __init__(
        self,
        master,
        variable: tk.StringVar,
        options: list[tuple[str, str]],      # (value, label)
        palette: Palette,
        type_scale: Typography,
        command=None,
        height: int = 34,
        surface: str | None = None,
        radius: int = 8,
    ) -> None:
        self.palette = palette
        self.type_scale = type_scale
        self.variable = variable
        self.options = options
        self.command = command
        self.radius = radius
        self._surface = surface or palette.card
        self._hover_index: int | None = None

        self._font = type_scale.body
        width = sum(self._font.measure(label) + 34 for _, label in options) + 6
        super().__init__(
            master, width=width, height=height,
            highlightthickness=0, bd=0, background=self._surface,
        )
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._trace = variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _bounds(self, index: int) -> tuple[float, float]:
        width = _measured(self, "width", 260) - 6
        step = width / len(self.options)
        return 3 + index * step, 3 + (index + 1) * step

    def _index_at(self, x: float) -> int | None:
        for index in range(len(self.options)):
            left, right = self._bounds(index)
            if left <= x <= right:
                return index
        return None

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        p = self.palette
        width = _measured(self, "width", 260)
        height = _measured(self, "height", 34)
        self.create_polygon(
            _rounded_points(1, 1, width - 1, height - 1, self.radius),
            smooth=True, splinesteps=24,
            fill=p.field, outline=p.field_border, width=1,
        )
        current = self.variable.get()
        for index, (value, label) in enumerate(self.options):
            left, right = self._bounds(index)
            selected = value == current
            if selected:
                self.create_polygon(
                    _rounded_points(left, 3, right, height - 3, self.radius - 2),
                    smooth=True, splinesteps=24, fill=p.accent, outline=p.accent,
                )
            elif self._hover_index == index:
                self.create_polygon(
                    _rounded_points(left, 3, right, height - 3, self.radius - 2),
                    smooth=True, splinesteps=24,
                    fill=p.ghost_hover, outline=p.ghost_hover,
                )
            self.create_text(
                (left + right) / 2, height / 2,
                text=label,
                fill=p.accent_text if selected else p.muted,
                font=self.type_scale.body_bold if selected else self._font,
            )

    def _on_motion(self, event) -> None:
        index = self._index_at(event.x)
        if index != self._hover_index:
            self._hover_index = index
            self.configure(cursor="hand2" if index is not None else "")
            self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover_index = None
        self.configure(cursor="")
        self._draw()

    def _on_click(self, event) -> None:
        index = self._index_at(event.x)
        if index is None:
            return
        value = self.options[index][0]
        if value != self.variable.get():
            self.variable.set(value)
            self._draw()
            if self.command is not None:
                self.command()


class ToggleSwitch(tk.Canvas):
    """A sliding on/off switch bound to a ``BooleanVar``."""

    def __init__(
        self,
        master,
        variable: tk.BooleanVar,
        palette: Palette,
        type_scale: Typography,
        text: str = "",
        command=None,
        surface: str | None = None,
    ) -> None:
        self.palette = palette
        self.type_scale = type_scale
        self.variable = variable
        self.command = command
        self.text = text
        self._surface = surface or palette.card
        self._font = type_scale.body

        self._track_width, self._track_height = 38, 20
        width = self._track_width + (8 + self._font.measure(text) if text else 0) + 4
        super().__init__(
            master, width=width, height=max(self._track_height + 6, 26),
            highlightthickness=0, bd=0, background=self._surface,
        )
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda _e: self.configure(cursor="hand2"))
        self.bind("<Leave>", lambda _e: self.configure(cursor=""))
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        p = self.palette
        on = bool(self.variable.get())
        height = _measured(self, "height", 26)
        top = (height - self._track_height) / 2
        bottom = top + self._track_height

        self.create_polygon(
            _rounded_points(1, top, self._track_width, bottom, self._track_height / 2),
            smooth=True, splinesteps=24,
            fill=p.accent if on else p.field_border,
            outline=p.accent if on else p.field_border,
        )
        knob = self._track_height - 6
        knob_left = (self._track_width - knob - 3) if on else 4
        self.create_oval(
            knob_left, top + 3, knob_left + knob, top + 3 + knob,
            fill="#FFFFFF", outline="",
        )
        if self.text:
            self.create_text(
                self._track_width + 8, height / 2,
                text=self.text, anchor="w", fill=p.text, font=self._font,
            )

    def _on_click(self, _event=None) -> None:
        self.variable.set(not self.variable.get())
        self._draw()
        if self.command is not None:
            self.command()


class CollapsibleCard(Card):
    """A card whose body can be folded away.

    Settings that most people never change should not cost a third of the
    window, so the matching rules ship collapsed.
    """

    def __init__(
        self,
        master,
        palette: Palette,
        type_scale: Typography,
        title: str,
        caption: str = "",
        expanded: bool = False,
        on_toggle=None,
        **kwargs,
    ):
        super().__init__(master, palette, **kwargs)
        self.type_scale = type_scale
        self._expanded = expanded
        self._on_toggle = on_toggle

        header = tk.Frame(self, background=palette.card, cursor="hand2")
        header.pack(fill="x", padx=18, pady=(14, 0))
        self._chevron = tk.Label(
            header, text="▾" if expanded else "▸",
            background=palette.card, foreground=palette.muted,
            font=type_scale.body, bd=0,
        )
        self._chevron.pack(side="left", padx=(0, 8))
        titles = tk.Frame(header, background=palette.card)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles, text=title, background=palette.card, foreground=palette.text,
            font=type_scale.section, bd=0, anchor="w",
        ).pack(fill="x")
        if caption:
            tk.Label(
                titles, text=caption, background=palette.card,
                foreground=palette.muted, font=type_scale.caption, bd=0, anchor="w",
            ).pack(fill="x")

        self.content = ttk.Frame(self, style="Card.TFrame")
        for widget in (header, self._chevron, titles, *titles.winfo_children()):
            widget.bind("<Button-1>", self._toggle)

        self._spacer = tk.Frame(self, background=palette.card, height=14)
        self._spacer.pack(fill="x")
        if expanded:
            self._show()

    def _show(self) -> None:
        self.content.pack(fill="both", expand=True, padx=18, pady=(12, 16), before=self._spacer)
        self._spacer.pack_forget()

    def _hide(self) -> None:
        self.content.pack_forget()
        self._spacer.pack(fill="x")

    def _toggle(self, _event=None) -> None:
        self._expanded = not self._expanded
        self._chevron.configure(text="▾" if self._expanded else "▸")
        self._show() if self._expanded else self._hide()
        if self._on_toggle is not None:
            self._on_toggle(self._expanded)

    @property
    def expanded(self) -> bool:
        return self._expanded


def flatten_scrollbar(style: ttk.Style, palette: Palette) -> None:
    """Drop the stepper arrows, which are the last skeuomorphic detail."""
    style.layout(
        "Flat.Vertical.TScrollbar",
        [("Vertical.Scrollbar.trough",
          {"sticky": "ns", "children": [
              ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
          ]})],
    )
    style.configure(
        "Flat.Vertical.TScrollbar",
        background=palette.card_border, troughcolor=palette.card,
        bordercolor=palette.card, borderwidth=0, relief="flat", width=8,
    )
    style.map("Flat.Vertical.TScrollbar", background=[("active", palette.subtle)])


class AutoHideScrollbar(ttk.Scrollbar):
    """A scrollbar that disappears when everything already fits.

    A permanently visible track on a three-row table is pure visual noise.
    """

    def set(self, first, last):  # type: ignore[override]
        try:
            covers_everything = float(first) <= 0.0 and float(last) >= 1.0
        except (TypeError, ValueError):
            covers_everything = False
        if covers_everything:
            self.grid_remove()
        elif self.grid_info() == {} and getattr(self, "_grid_options", None):
            self.grid(**self._grid_options)
        super().set(first, last)

    def grid(self, **kwargs):  # type: ignore[override]
        if kwargs:
            self._grid_options = kwargs
        return super().grid(**(kwargs or getattr(self, "_grid_options", {})))


class ScrollableFrame(tk.Frame):
    """A vertically scrolling container for the window's cards.

    Form content grows with the data - more sheets, expanded settings - and
    a fixed window cannot show all of it.  Rather than clipping whatever
    falls off the bottom, the content scrolls, so the layout survives a
    small laptop screen as well as a large monitor.
    """

    def __init__(self, master, palette: Palette, **kwargs):
        super().__init__(master, background=palette.canvas, bd=0,
                         highlightthickness=0, **kwargs)
        self.palette = palette

        self.canvas = tk.Canvas(
            self, background=palette.canvas, bd=0, highlightthickness=0, takefocus=0
        )
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
            style="Flat.Vertical.TScrollbar",
        )
        self.canvas.configure(yscrollcommand=self._on_scroll)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.body = tk.Frame(self.canvas, background=palette.canvas, bd=0,
                             highlightthickness=0)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_wheel(self)

    def _on_scroll(self, first, last):
        """Hide the bar when the content already fits."""
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid()
        self.scrollbar.set(first, last)

    def _on_body_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    # -- mouse wheel, across the three conventions Tk reports it with ------
    def _bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind_all("<MouseWheel>", self._on_wheel, add="+")      # Windows / macOS
        widget.bind_all("<Button-4>", self._on_wheel, add="+")        # X11 up
        widget.bind_all("<Button-5>", self._on_wheel, add="+")        # X11 down

    def _on_wheel(self, event) -> None:
        if not self.canvas.winfo_exists():
            return
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return                       # nothing to scroll
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")
