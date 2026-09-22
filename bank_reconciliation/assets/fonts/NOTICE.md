# Bundled fonts

The sketch theme needs a handwriting face. These two are bundled because
both are under the **SIL Open Font License 1.1** (`OFL.txt`), which permits
redistribution and commercial use.

| Font | Copyright | Upstream |
|---|---|---|
| Patrick Hand | Copyright (c) 2012 Patrick Wagesreiter (mail@patrickwagesreiter.at) | <https://fonts.google.com/specimen/Patrick+Hand> |
| Comic Neue Bold | Copyright 2014 The Comic Neue Project Authors | <https://github.com/crozynski/comicneue> |

## Why not the real xkcd font?

The actual xkcd handwriting font ("xkcd Script", and the derived "Humor
Sans") is licensed **CC BY-NC** - non-commercial only. Shipping it inside a
company's accounting tool would breach that, so it is not bundled here.

The app still *prefers* it at runtime: if "xkcd Script", "Humor Sans" or
"Comic Sans MS" is already installed on the machine, the sketch theme uses
it and falls back to Patrick Hand otherwise. Installing xkcd Script for
your own use is your call, not something this repository does for you.
