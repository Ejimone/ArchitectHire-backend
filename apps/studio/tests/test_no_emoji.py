"""The Studio interface ships no emoji.

A design-system rule with teeth. Studio's icon language is Material Symbols — a
typeface, sized and coloured with the rest of the UI. Emoji render as someone else's
artwork at someone else's scale, in a different style on every platform, and are the
fastest way to make a paid product look unfinished.

Scoped to the admin UI: `seeds/` and `design/` hold frontend copy, where a checkmark
or star is a deliberate typographic choice rather than an interface icon.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

# Written entirely in escape sequences so this file does not trip its own check.
EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # emoticons, pictographs, transport, symbols, supplemental
    "\u2600-\u27bf"  # misc symbols and dingbats (checkmarks, stars, sparkles)
    "\u2b00-\u2bff"  # arrows and geometric shapes used as emoji
    "\ufe0f"  # variation selector-16, which forces emoji presentation
    "]"
)

SCANNED = [
    ROOT / "apps" / "studio",
    ROOT / "apps" / "cms" / "admin.py",
    ROOT / "apps" / "cms" / "admin_editorial.py",
]
SUFFIXES = {".py", ".html", ".css", ".js", ".svg"}


def _files():
    for target in SCANNED:
        if target.is_file():
            yield target
        else:
            yield from (p for p in target.rglob("*") if p.suffix in SUFFIXES)


@pytest.mark.parametrize("path", sorted(_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_emoji_in_the_studio_interface(path):
    offenders = [
        f"{path.relative_to(ROOT)}:{number}: {match.group()!r}"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if (match := EMOJI.search(line))
    ]

    assert not offenders, "Use a Material Symbols icon instead:\n" + "\n".join(offenders)
