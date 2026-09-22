"""Make the bundled handwriting font usable without installing it globally.

Tk can only render font families that the platform's font system knows
about, and a ``.ttf`` sitting in the package directory is not one of them.
Each platform has its own way to register a font file for the current
process, so this module tries the private route first and only falls back
to dropping the file in the user's font directory.

If none of that works the app still runs - the sketch theme just borrows
whatever the most handwriting-like installed face is.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

# Best first. The real xkcd faces are preferred when the machine already has
# them - they are not bundled, because they are licensed non-commercially.
SKETCH_FAMILIES = (
    "xkcd Script",
    "Humor Sans",
    "xkcd",
    "Comic Sans MS",       # ubiquitous on Windows and macOS
    "Chalkboard SE",       # macOS
    "Bradley Hand",        # macOS
    "Patrick Hand",        # bundled
    "Comic Neue",          # bundled
)

BUNDLED = {
    "Patrick Hand": "PatrickHand-Regular.ttf",
    "Comic Neue": "ComicNeue-Bold.ttf",
}


def installed_families(root) -> set[str]:
    from tkinter import font as tkfont

    return {name.lower() for name in tkfont.families(root)}


def _register_windows(path: Path) -> bool:
    try:
        import ctypes

        FR_PRIVATE = 0x10
        added = ctypes.windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0)
        return bool(added)
    except Exception as error:  # noqa: BLE001 - best effort
        LOGGER.debug("private font registration failed on Windows: %s", error)
        return False


def _register_macos(path: Path) -> bool:
    try:
        import ctypes
        import ctypes.util

        core = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))
        foundation = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        foundation.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
        text = foundation.CFStringCreateWithCString(
            None, str(path).encode("utf-8"), 0x08000100  # kCFStringEncodingUTF8
        )
        url = foundation.CFURLCreateWithFileSystemPath(None, ctypes.c_void_p(text), 0, False)
        # kCTFontManagerScopeProcess == 1
        return bool(core.CTFontManagerRegisterFontsForURL(ctypes.c_void_p(url), 1, None))
    except Exception as error:  # noqa: BLE001 - best effort
        LOGGER.debug("private font registration failed on macOS: %s", error)
        return False


def _install_for_user_linux(path: Path) -> bool:
    """Last resort on X11: Tk has no private font API there."""
    try:
        target_dir = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        ) / "fonts"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        if not target.exists():
            shutil.copyfile(path, target)
            LOGGER.info("Installed %s into %s for the sketch theme.", path.name, target_dir)
        if shutil.which("fc-cache"):
            subprocess.run(
                ["fc-cache", "-f", str(target_dir)],
                check=False, capture_output=True, timeout=60,
            )
        return True
    except Exception as error:  # noqa: BLE001 - best effort
        LOGGER.debug("could not install the font for this user: %s", error)
        return False


def register_bundled_fonts(root) -> None:
    """Try to make the bundled faces visible to Tk for this session."""
    available = installed_families(root)
    for family, filename in BUNDLED.items():
        if family.lower() in available:
            continue
        path = FONT_DIR / filename
        if not path.exists():
            continue
        if sys.platform.startswith("win"):
            _register_windows(path)
        elif sys.platform == "darwin":
            _register_macos(path)
        else:
            _install_for_user_linux(path)


def preferred_family() -> str | None:
    """The user's own handwriting font, if they have made one.

    ``handfont build --install`` records the family name it installed, and
    the sketch theme puts that ahead of everything else - your own hand is
    always the better answer than a bundled approximation.
    """
    try:
        from handfont.install import read_preferred_family

        return read_preferred_family()
    except Exception as error:  # noqa: BLE001 - the tool is optional
        LOGGER.debug("no personal font preference available: %s", error)
        return None


def resolve_sketch_family(root) -> tuple[str, bool]:
    """Pick the handwriting family to draw with.

    Returns the family name and whether it is genuinely a handwriting face
    (False means nothing suitable was found and the caller is getting a
    plain fallback).
    """
    register_bundled_fonts(root)
    available = installed_families(root)

    personal = preferred_family()
    if personal and personal.lower() in available:
        return personal, True

    for family in SKETCH_FAMILIES:
        if family.lower() in available:
            return family, True

    from tkinter import font as tkfont

    for fallback in ("DejaVu Sans", "Verdana", "Segoe UI"):
        if fallback.lower() in available:
            return fallback, False
    return tkfont.nametofont("TkDefaultFont").actual("family"), False
