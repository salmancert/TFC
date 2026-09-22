# Make a font from your own handwriting

Print two sheets, fill them in with a pen, scan them, and get back a
TrueType font. It is your own hand, so there is no licence to read and
nothing to attribute — you own it outright.

```bash
pip install -r requirements-handfont.txt

python -m handfont template -o template.pdf          # 1. print this
#                                                      2. fill it in
python -m handfont build scans/*.jpg \
    -n "Your Name Hand" -o YourHand.ttf --install    # 3. and you have a font
```

`--install` puts the font in your user font directory and records it as
your preferred handwriting face, so the reconciler's sketch theme starts
using it straight away.

## 1. Print the template

```bash
python -m handfont template -o template.pdf            # A4
python -m handfont template --paper letter -o t.pdf    # US Letter
```

Two pages, 96 characters: A–Z, a–z, 0–9, punctuation and `$ £ € ¥`.

**Print at 100% scale.** Turn off "fit to page" / "shrink to fit" — the
reader relies on the printed geometry, and a scaled print still works but
gives the tracer less to go on.

## 2. Fill it in

Each box shows the character to write above a writing area with four
guides:

```
┌──────────────┐
│ A            │  ← the character to write (don't trace this)
├──────────────┤
│ ‑ ‑ ‑ ‑ ‑ ‑ ‑│  ← ascender:  tops of  b  d  h  k  l
│ ‑ ‑ ‑ ‑ ‑ ‑ ‑│  ← x-height:  tops of  a  c  e  o
│              │
│ ─────────────│  ← BASELINE: sit every letter on this line
│ ‑ ‑ ‑ ‑ ‑ ‑ ‑│  ← descender: tails of  g  j  p  q  y
└──────────────┘
```

What matters, in order:

1. **Sit each letter on the solid baseline.** This is the one that counts —
   it is how the tool knows where the letter belongs on the em square, so
   your text comes out sitting on a line instead of bobbing about.
2. **Use a dark pen**, black or dark blue, medium-to-thick nib. The guides
   are printed light grey precisely so they vanish and your ink survives.
   Pencil and fine liners come out thin and patchy.
3. **Keep inside the box** and don't touch the printed border.
4. Write naturally at a comfortable size, roughly filling the guides.

Leave a box empty to skip that character — it is simply left out of the
font, and you can write it in later and re-run to fill the gap.

## 3. Scan it

A flatbed scan at 300 dpi is ideal. A phone photo works too: lie the page
flat, get even light, avoid your own shadow, and **keep all four corner
squares in frame**. The reader finds those squares, straightens the page
from them, and works out which page it is from the little binary strip at
the top — so you can shoot the pages in any order, and even upside down.

```bash
python -m handfont build page1.jpg page2.jpg \
    -n "Your Name Hand" \
    -o YourHand.ttf \
    --preview specimen.png \
    --install
```

| Option | What it does |
|---|---|
| `-n`, `--name` | The font family name, as it appears in any app |
| `--preview` | Also render a specimen image so you can see the result |
| `--install` | Install for your user and prefer it in the sketch theme |
| `--spacing` | Side bearing in font units (default 40; raise for airier text) |
| `--smooth` | Smoothing passes over the scan; `0` keeps every wobble |
| `--license` | Licence text embedded in the font (default: all rights reserved, to you) |
| `--designer` | Your name, in the font's metadata |

To see what a finished font looks like without writing anything:

```bash
python -m handfont demo -o DemoHand.ttf --preview specimen.png
```

That fills a template in programmatically, distorts it like a handheld
photo, and runs the whole pipeline — a useful check that your install
works before you reach for a pen.

## How it works

**Template.** Geometry lives in `handfont/layout.py` and is shared by the
writer and the reader, so the two cannot drift apart. Three large corner
squares and one small one give a perspective transform four points and fix
the orientation — the odd small square is why an upside-down page still
comes out the right way up.

**Reading.** The page is thresholded with Otsu's method (so exposure does
not matter), the corner squares are found by connected components filtered
on squareness and fill, and a homography maps the photo back to template
coordinates. Each cell is then cropped at known offsets, thresholded to
separate pen from printed guide, and despeckled.

**Tracing.** Each character's ink is vectorised with potrace. The
template's baseline and ascender guides fix the scale: ascender-to-baseline
is always 800 units of a 1000-unit em, which is what puts every letter at a
consistent size and height without guessing from its own bounding box.
Cubic curves are converted to the quadratics TrueType stores.

**Assembly.** `fontTools` writes the `glyf`, `cmap`, `hmtx`, `name`, `OS/2`
and `post` tables. Advance widths come from each glyph's ink plus a side
bearing.

## Licensing

It is your handwriting, so the font is yours. By default the embedded
licence says exactly that — "Made from the author's own handwriting, all
rights reserved by the author" — and `--license` overrides it if you want
to release it under something specific.

This is why the tool exists: the sketch theme previously had to fall back
on bundled OFL faces, because the real xkcd font is CC BY-NC and could not
ship in a commercial repo. A font made from your own hand has no such
question hanging over it.

## Tests

```bash
python -m pytest tests/test_handfont.py -q
```

The tests fill a template in programmatically, abuse it the way a phone
camera would — rotation, perspective, vignetting, sensor noise — and then
read it back, so the whole pipeline is covered without needing a scanner.
