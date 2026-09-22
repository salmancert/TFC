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
    sketch: bool = False        # draw hand-drawn wobbly outlines instead of clean ones
    canvas: str = "#FFFFFF"   # the window behind the cards
    card: str = "#000000"            # card surface
    card_border: str = "#000000"     # hairline around a card
    field: str = "#000000"           # entry / combobox interior
    field_border: str = "#000000"
    text: str = "#000000"            # primary text
    muted: str = "#000000"           # secondary text
    subtle: str = "#000000"          # tertiary text, placeholders
    accent: str = "#000000"          # primary action
    accent_hover: str = "#000000"
    accent_text: str = "#000000"     # text on the accent
    ghost_hover: str = "#000000"     # secondary button hover
    selection: str = "#000000"       # selected row
    stripe: str = "#000000"          # zebra row
    header: str = "#000000"          # table header background
    ok: str = "#000000"
    ok_fill: str = "#000000"
    info: str = "#000000"
    info_fill: str = "#000000"
    warn: str = "#000000"
    warn_fill: str = "#000000"
    bad: str = "#000000"
    bad_fill: str = "#000000"


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

# Paper and ink. xkcd is near-monochrome, so affordance comes from line
# weight and from a handful of crayon fills rather than from a colour system.
SKETCH = Palette(
    name="sketch",
    sketch=True,
    canvas="#FBFBF7",
    card="#FFFFFF",
    card_border="#1A1A1A",
    field="#FFFFFF",
    field_border="#1A1A1A",
    text="#1A1A1A",
    muted="#4A4A4A",
    subtle="#7A7A7A",
    accent="#1A1A1A",
    accent_hover="#000000",
    accent_text="#FFFFFF",
    ghost_hover="#EFEFE9",
    selection="#E4E9F5",
    stripe="#F7F7F2",
    header="#F2F2EC",
    ok="#1F5C33", ok_fill="#CDEBD6",
    info="#1B4A73", info_fill="#CFE2F3",
    warn="#7A5510", warn_fill="#FBEBC2",
    bad="#8C2128", bad_fill="#F6D3D5",
)

PALETTES = {"light": LIGHT, "dark": DARK, "sketch": SKETCH}

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
    def build(cls, root: tk.Misc, sketch: bool = False) -> "Typography":
        if sketch:
            from .fonts import resolve_sketch_family

            family, _genuine = resolve_sketch_family(root)
            return cls(
                # Handwriting faces run small, so the sketch scale is bumped.
                title=tkfont.Font(root=root, family=family, size=24, weight="bold"),
                subtitle=tkfont.Font(root=root, family=family, size=13),
                section=tkfont.Font(root=root, family=family, size=15, weight="bold"),
                body=tkfont.Font(root=root, family=family, size=13),
                body_bold=tkfont.Font(root=root, family=family, size=13, weight="bold"),
                caption=tkfont.Font(root=root, family=family, size=12),
                mono=tkfont.Font(root=root, family=family, size=12),
            )
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
    border_width = 2 if p.sketch else 1
    style.configure(
        "TEntry",
        fieldbackground=p.field, background=p.field, foreground=p.text,
        bordercolor=p.field_border, lightcolor=p.field_border, darkcolor=p.field_border,
        insertcolor=p.text, borderwidth=border_width, relief="flat",
        padding=8 if p.sketch else 7,
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
        arrowcolor=p.muted, borderwidth=border_width, relief="flat",
        padding=7 if p.sketch else 6,
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
        borderwidth=0, relief="flat",
        rowheight=32 if p.sketch else 27, font=t.body,
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

    # Inside a hand-drawn box the widget must not draw a border of its own.
    style.configure(
        "Sketch.TEntry",
        fieldbackground=p.field, background=p.field, foreground=p.text,
        bordercolor=p.field, lightcolor=p.field, darkcolor=p.field,
        insertcolor=p.text, borderwidth=0, relief="flat", padding=2,
    )
    style.configure(
        "Sketch.TCombobox",
        fieldbackground=p.field, background=p.field, foreground=p.text,
        bordercolor=p.field, lightcolor=p.field, darkcolor=p.field,
        arrowcolor=p.text, borderwidth=0, relief="flat", padding=2,
    )
    style.map(
        "Sketch.TCombobox",
        fieldbackground=[("readonly", p.field)],
        background=[("readonly", p.field)],
    )
    return style


# --------------------------------------------------------------------------
# Containers and controls that ttk cannot express
# --------------------------------------------------------------------------
class Card(tk.Frame):
    """A flat surface with a border, the app's main container.

    In sketch mode the border is drawn on a canvas stacked behind the
    content, because a hand-drawn box cannot be expressed as a widget
    border.
    """

    def __init__(self, master, palette: Palette, amplitude: float = 1.9,
                 overshoot: float = 4.0, line_width: float = 2.2, **kwargs):
        super().__init__(
            master,
            background=palette.card,
            highlightbackground=palette.card_border,
            highlightcolor=palette.card_border,
            highlightthickness=0 if palette.sketch else 1,
            bd=0,
            **kwargs,
        )
        self.palette = palette
        self._amplitude = amplitude
        self._overshoot = overshoot
        self._line_width = line_width
        self._frame_canvas: tk.Canvas | None = None
        if palette.sketch:
            # Created first so later siblings stack above it.
            self._frame_canvas = tk.Canvas(
                self, background=palette.card, bd=0, highlightthickness=0, takefocus=0
            )
            self._frame_canvas.place(x=0, y=0, relwidth=1, relheight=1)
            self.bind("<Configure>", self._draw_frame)

    def _draw_frame(self, _event=None) -> None:
        if self._frame_canvas is None:
            return
        self._frame_canvas.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 8 or height < 8:
            return
        draw_sketch_rect(
            self._frame_canvas, 4, 4, width - 5, height - 5,
            seed=shape_seed(self, "card"),
            fill=self.palette.card, outline=self.palette.card_border,
            width=self._line_width, amplitude=self._amplitude,
            overshoot=self._overshoot,
        )

    def body(self, padx: int = 18, pady: int = 16) -> ttk.Frame:
        """An inner frame carrying the card's padding."""
        if self.palette.sketch:
            padx, pady = padx + 4, pady + 4
        inner = ttk.Frame(self, style="Card.TFrame")
        inner.pack(fill="both", expand=True, padx=padx, pady=pady)
        return inner


# --------------------------------------------------------------------------
# Hand-drawn line work
# --------------------------------------------------------------------------
def _jitter_rng(seed: int) -> "random.Random":
    import random

    return random.Random(seed)


def sketch_segment(
    x1: float, y1: float, x2: float, y2: float,
    seed: int, amplitude: float = 1.7, step: float = 14.0,
) -> list[float]:
    """A straight line redrawn as if by hand.

    The line is cut into short pieces and each interior joint is nudged
    perpendicular to the direction of travel, which is what gives a stroke
    its wobble.  The offsets come from a seeded generator so a widget looks
    identical every time it repaints - unseeded noise would make the whole
    interface shimmer on hover and resize.
    """
    import math

    length = math.hypot(x2 - x1, y2 - y1)
    if length < 1e-6:
        return [x1, y1, x2, y2]

    rng = _jitter_rng(seed)
    pieces = max(2, int(length / step))
    nx, ny = -(y2 - y1) / length, (x2 - x1) / length     # unit normal

    points: list[float] = []
    for index in range(pieces + 1):
        t = index / pieces
        # Ends stay put so corners meet; the middle wanders most.
        taper = math.sin(math.pi * t)
        offset = rng.uniform(-amplitude, amplitude) * taper
        points.extend([
            x1 + (x2 - x1) * t + nx * offset,
            y1 + (y2 - y1) * t + ny * offset,
        ])
    return points


def draw_sketch_rect(
    canvas: tk.Canvas,
    x1: float, y1: float, x2: float, y2: float,
    seed: int,
    fill: str | None = None,
    outline: str = "#1A1A1A",
    width: float = 1.8,
    amplitude: float = 1.7,
    overshoot: float = 2.5,
    tags: str = "",
) -> None:
    """A rectangle drawn the way a person draws one.

    Each side is a separate wobbly stroke that slightly overshoots its
    corner, because hand-drawn boxes never close cleanly.
    """
    rng = _jitter_rng(seed)
    if fill:
        canvas.create_polygon(
            [x1, y1, x2, y1, x2, y2, x1, y2],
            fill=fill, outline="", tags=tags,
        )
    corners = [
        (x1, y1, x2, y1),
        (x2, y1, x2, y2),
        (x2, y2, x1, y2),
        (x1, y2, x1, y1),
    ]
    for index, (ax, ay, bx, by) in enumerate(corners):
        over_a = rng.uniform(0, overshoot)
        over_b = rng.uniform(0, overshoot)
        dx, dy = bx - ax, by - ay
        length = max((dx ** 2 + dy ** 2) ** 0.5, 1e-6)
        ux, uy = dx / length, dy / length
        canvas.create_line(
            sketch_segment(
                ax - ux * over_a, ay - uy * over_a,
                bx + ux * over_b, by + uy * over_b,
                seed=seed * 7 + index, amplitude=amplitude,
            ),
            fill=outline, width=width, capstyle="round", joinstyle="round",
            smooth=True, tags=tags,
        )


def draw_sketch_line(
    canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
    seed: int, fill: str = "#1A1A1A", width: float = 1.6, tags: str = "",
) -> None:
    canvas.create_line(
        sketch_segment(x1, y1, x2, y2, seed=seed),
        fill=fill, width=width, capstyle="round", smooth=True, tags=tags,
    )


def draw_sketch_oval(
    canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
    seed: int, fill: str | None = None, outline: str = "#1A1A1A",
    width: float = 1.8, tags: str = "",
) -> None:
    """A circle with a hand's worth of wobble in its radius."""
    import math

    rng = _jitter_rng(seed)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = abs(x2 - x1) / 2, abs(y2 - y1) / 2
    points: list[float] = []
    steps = 22
    for index in range(steps):
        angle = 2 * math.pi * index / steps
        wobble = rng.uniform(-0.9, 0.9)
        points.extend([
            cx + (rx + wobble) * math.cos(angle),
            cy + (ry + wobble) * math.sin(angle),
        ])
    canvas.create_polygon(
        points, fill=fill or "", outline=outline, width=width,
        smooth=True, tags=tags,
    )


def shape_seed(widget: tk.Misc, role: str = "") -> int:
    """A stable seed per widget, so a repaint reproduces the same wobble."""
    return (hash((str(widget), role)) & 0x7FFFFFFF) or 1


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
        if self.palette.sketch:
            draw_sketch_rect(
                self, 3, 3, width - 3, height - 3,
                seed=shape_seed(self, "button"),
                fill=fill,
                outline=self.palette.text if self._state != "disabled" else self.palette.subtle,
                width=2.0,
            )
        else:
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


class Chip(tk.Canvas):
    """A small pill of colour used for the legend.

    Drawn rather than labelled so the sketch theme can give it a scribbled
    outline instead of a clean rectangle.
    """

    def __init__(self, master, text: str, fill: str, foreground: str,
                 type_scale: Typography, palette: Palette = LIGHT,
                 surface: str | None = None, **kwargs):
        self.palette = palette
        self._text = text
        self._fill = fill
        self._foreground = foreground
        self._font = type_scale.caption
        self._surface = surface or palette.card

        width = self._font.measure(text) + (26 if palette.sketch else 18)
        height = 28 if palette.sketch else 24
        super().__init__(
            master, width=width, height=height,
            background=self._surface, bd=0, highlightthickness=0, **kwargs,
        )
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = _measured(self, "width", 80)
        height = _measured(self, "height", 24)
        if self.palette.sketch:
            draw_sketch_rect(
                self, 3, 3, width - 3, height - 3,
                seed=shape_seed(self, "chip"),
                fill=self._fill, outline=self.palette.text,
                width=1.5, amplitude=1.1, overshoot=2.0,
            )
        else:
            self.create_polygon(
                _rounded_points(0, 0, width, height, 5),
                smooth=True, splinesteps=16, fill=self._fill, outline=self._fill,
            )
        self.create_text(
            width / 2, height / 2, text=self._text,
            fill=self._foreground, font=self._font,
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
        gap = 46 if palette.sketch else 34
        width = sum(self._font.measure(label) + gap for _, label in options) + 6
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
        if p.sketch:
            draw_sketch_rect(
                self, 3, 3, width - 3, height - 3,
                seed=shape_seed(self, "segments"),
                fill=p.field, outline=p.field_border, width=1.8,
            )
        else:
            self.create_polygon(
                _rounded_points(1, 1, width - 1, height - 1, self.radius),
                smooth=True, splinesteps=24,
                fill=p.field, outline=p.field_border, width=1,
            )
        current = self.variable.get()
        for index, (value, label) in enumerate(self.options):
            left, right = self._bounds(index)
            selected = value == current
            if selected and p.sketch:
                draw_sketch_rect(
                    self, left + 4, 7, right - 4, height - 7,
                    seed=shape_seed(self, f"seg{index}"),
                    fill=p.accent, outline=p.accent,
                    width=1.4, amplitude=0.8, overshoot=1.0,
                )
            elif selected:
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

        knob = self._track_height - 6
        knob_left = (self._track_width - knob - 3) if on else 4
        if p.sketch:
            draw_sketch_rect(
                self, 2, top, self._track_width - 1, bottom,
                seed=shape_seed(self, "track"),
                fill=p.accent if on else p.card,
                outline=p.text, width=1.8, amplitude=1.2, overshoot=1.5,
            )
            draw_sketch_oval(
                self, knob_left, top + 3, knob_left + knob, top + 3 + knob,
                seed=shape_seed(self, "knob"),
                fill=p.card if on else p.text, outline=p.text, width=1.6,
            )
        else:
            self.create_polygon(
                _rounded_points(1, top, self._track_width, bottom, self._track_height / 2),
                smooth=True, splinesteps=24,
                fill=p.accent if on else p.field_border,
                outline=p.accent if on else p.field_border,
            )
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


class SketchSeparator(tk.Canvas):
    """A horizontal rule with a hand's wobble in it."""

    def __init__(self, master, palette: Palette, height: int = 12, **kwargs):
        super().__init__(
            master, height=height, background=palette.card,
            bd=0, highlightthickness=0, takefocus=0, **kwargs,
        )
        self.palette = palette
        self.bind("<Configure>", lambda _e: self._draw())

    def _draw(self) -> None:
        self.delete("all")
        width = _measured(self, "width", 400)
        height = _measured(self, "height", 12)
        draw_sketch_line(
            self, 2, height / 2, width - 2, height / 2,
            seed=shape_seed(self, "rule"),
            fill=self.palette.card_border, width=1.8,
        )


def separator(master, palette: Palette, style: str = "Sep.TSeparator"):
    """A rule that matches the active theme."""
    if palette.sketch:
        return SketchSeparator(master, palette)
    return ttk.Separator(master, orient="horizontal", style=style)


def framed_entry(master, palette: Palette, textvariable, type_scale: Typography,
                 values: list[str] | None = None, readonly: bool = False):
    """An entry or combobox, boxed by hand when the sketch theme is on.

    Returns ``(outer, inner)``: grid the outer widget, read state from the
    inner one.  ttk cannot draw a wobbly border, so in sketch mode the
    control loses its own border and sits inside a drawn box instead.
    """
    if values is not None:
        make = lambda parent, style: ttk.Combobox(  # noqa: E731
            parent, textvariable=textvariable, values=values,
            state="readonly", style=style,
        )
    else:
        make = lambda parent, style: ttk.Entry(  # noqa: E731
            parent, textvariable=textvariable, style=style,
        )

    if not palette.sketch:
        widget = make(master, "TCombobox" if values is not None else "TEntry")
        return widget, widget

    box = Card(master, palette, amplitude=1.0, overshoot=1.8, line_width=1.8)
    inner = make(box, "Sketch.TCombobox" if values is not None else "Sketch.TEntry")
    # The hand-drawn border is inset 4px and wanders about a pixel either
    # way, so the content has to start clear of it or the line crosses text.
    inner.pack(fill="both", expand=True, padx=10, pady=8)
    return box, inner
