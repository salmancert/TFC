"""Which characters the template asks for, and in what order."""

from __future__ import annotations

from dataclasses import dataclass

UPPERCASE = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
LOWERCASE = [chr(c) for c in range(ord("a"), ord("z") + 1)]
DIGITS = [chr(c) for c in range(ord("0"), ord("9") + 1)]

PUNCTUATION = list(".,:;!?'\"()[]{}-/\\&@#%+=<>*_|~^")
CURRENCY = list("$£€¥")

# A few glyphs are worth writing twice: the pipeline keeps the better of the
# two, and a second attempt costs one box.
DEFAULT_SET: list[str] = UPPERCASE + LOWERCASE + DIGITS + PUNCTUATION + CURRENCY


@dataclass(frozen=True)
class Slot:
    """One box on the template: which character, on which page, where."""

    character: str
    page: int
    index_on_page: int

    @property
    def codepoint(self) -> int:
        return ord(self.character)

    @property
    def glyph_name(self) -> str:
        return glyph_name_for(self.character)


# Names that a TTF's post table will accept, for the characters that cannot
# simply be called by themselves.
SPECIAL_NAMES = {
    " ": "space", "!": "exclam", '"': "quotedbl", "#": "numbersign",
    "$": "dollar", "%": "percent", "&": "ampersand", "'": "quotesingle",
    "(": "parenleft", ")": "parenright", "*": "asterisk", "+": "plus",
    ",": "comma", "-": "hyphen", ".": "period", "/": "slash",
    ":": "colon", ";": "semicolon", "<": "less", "=": "equal",
    ">": "greater", "?": "question", "@": "at",
    "[": "bracketleft", "\\": "backslash", "]": "bracketright",
    "^": "asciicircum", "_": "underscore", "`": "grave",
    "{": "braceleft", "|": "bar", "}": "braceright", "~": "asciitilde",
    "£": "sterling", "€": "Euro", "¥": "yen", "¢": "cent",
}


def glyph_name_for(character: str) -> str:
    if character in SPECIAL_NAMES:
        return SPECIAL_NAMES[character]
    if character.isascii() and character.isalnum():
        return character if not character.isdigit() else _DIGIT_NAMES[character]
    return f"uni{ord(character):04X}"


_DIGIT_NAMES = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}


def build_slots(characters: list[str] | None = None, per_page: int = 56) -> list[Slot]:
    """Lay the character set out across as many pages as it needs."""
    characters = characters or DEFAULT_SET
    slots: list[Slot] = []
    for position, character in enumerate(characters):
        page, index = divmod(position, per_page)
        slots.append(Slot(character=character, page=page, index_on_page=index))
    return slots


def pages_needed(characters: list[str] | None = None, per_page: int = 56) -> int:
    characters = characters or DEFAULT_SET
    return max(1, -(-len(characters) // per_page))
