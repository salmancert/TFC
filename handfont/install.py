"""Put a finished font where the rest of the system can find it."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

PREFERENCE_ENV = "HANDFONT_FAMILY"


def user_font_dir() -> Path:
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Microsoft" / "Windows" / "Fonts"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Fonts"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "fonts"


def preference_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "handfont" / "preference.json"


def read_preferred_family() -> str | None:
    """The family name the user wants apps to prefer, if they set one."""
    from_env = os.environ.get(PREFERENCE_ENV)
    if from_env:
        return from_env
    try:
        path = preference_path()
        if path.exists():
            value = json.loads(path.read_text()).get("family")
            return str(value) if value else None
    except (OSError, ValueError) as error:
        LOGGER.debug("could not read the font preference: %s", error)
    return None


def write_preferred_family(family: str) -> Path:
    path = preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"family": family}, indent=2))
    return path


def install_font(ttf_path: str, family: str | None = None) -> tuple[Path, Path | None]:
    """Copy a font into the user's font directory and record the preference."""
    source = Path(ttf_path)
    if not source.exists():
        raise FileNotFoundError(ttf_path)

    target_dir = user_font_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copyfile(source, target)

    if not sys.platform.startswith("win") and sys.platform != "darwin":
        if shutil.which("fc-cache"):
            subprocess.run(
                ["fc-cache", "-f", str(target_dir)],
                check=False, capture_output=True, timeout=60,
            )

    preference = write_preferred_family(family) if family else None
    LOGGER.info("Installed %s", target)
    return target, preference
