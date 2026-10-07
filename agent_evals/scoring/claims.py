"""Finding the figures an agent stated, in the prose it wrote.

Comparing an answer against a table needs the answer's own number for each field, and an agent writes
"spend was $18,450" rather than returning a row. This reads numbers out of text and no further: it
understands separators, currency, percent signs and `1.2M` shorthand, and it finds a number sitting
near a label you name.

It deliberately does not learn vocabulary. The campaign's judge needed roughly 340 lines of metric
aliases, qualifier rejection and windowed search to do this well for one domain, and almost all of it
encodes what ad-tech words mean. A library that guessed on your behalf would be wrong in ways you
could not see, so a case says which label to look for, and the supported path for anything harder is
to have your agent return its figures as data alongside the prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The magnitude's word boundary sits inside the alternation rather than after the whole number: as a
# trailing \b it fell between the last digit and any following letter, where there is no boundary, so
# the engine backtracked away the decimal and read "1.31x" as a silently truncated 1. Keeping it here
# still stops "5kb" being read as five thousand.
_NUMBER = re.compile(
    r"(?P<currency>[$£€])?\s*"
    r"(?P<number>-?\d[\d,]*(?:\.\d+)?)"
    r"\s*(?:(?P<magnitude>thousand|million|billion|k|m|bn|b)\b)?"
    r"\s*(?P<percent>%)?",
    re.IGNORECASE,
)
_MAGNITUDES = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "million": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
}
DEFAULT_WINDOW = 60


@dataclass(frozen=True, slots=True)
class StatedNumber:
    """One figure an answer stated, and how it was written.

    `value` is the number as written, with any magnitude word expanded. A percentage keeps its face
    value: "0.42%" is 0.42, not 0.0042, because whether your table stores a rate as a percentage or a
    fraction is yours to know and not ours to guess. `percent` tells you which it was so you can
    convert. `abbreviated` marks shorthand like "1.2M", which has rounded before you saw it.
    """

    value: float
    abbreviated: bool = False
    percent: bool = False
    currency: bool = False


def _stated(match: re.Match[str]) -> StatedNumber:
    value = float(match.group("number").replace(",", ""))
    magnitude = match.group("magnitude")
    if magnitude:
        value *= _MAGNITUDES[magnitude.casefold()]
    return StatedNumber(
        value=value,
        abbreviated=magnitude is not None,
        percent=match.group("percent") is not None,
        currency=match.group("currency") is not None,
    )


def numbers_in_text(text: str) -> list[StatedNumber]:
    """Every number the text states, in the order it states them."""

    return [_stated(match) for match in _NUMBER.finditer(text) if match.group("number")]


def number_near(text: str, label: str, *, window: int = DEFAULT_WINDOW) -> StatedNumber | None:
    """The figure stated nearest to `label`, or None when the label or a number beside it is absent.

    Each mention of the label is searched outward to `window` characters, nearest number first, so
    "spend was $18,450" and "$18,450 of spend" both resolve. Returning None rather than guessing is
    the point: a caller can then say it found no figure for that field, which is a different thing
    from the agent getting it wrong.
    """

    if not label.strip():
        raise ValueError("label must be non-empty")
    for start in _mentions(text, label):
        offset, end = _whole_numbers(text, max(0, start - window), min(len(text), start + len(label) + window))
        around = text[offset:end]
        after = start + len(label)
        found = [
            (match.start() + offset, _stated(match)) for match in _NUMBER.finditer(around) if match.group("number")
        ]
        # Prefer a figure stated after the label ("spend was $18,450"), because the nearest number
        # overall is often the previous field's: in "clicks were 900, spend was 400" the 900 sits
        # closer to "spend" than its own figure does. Fall back to one before for "$18,450 of spend".
        following = [pair for pair in found if pair[0] >= after]
        if following:
            return min(following, key=lambda pair: pair[0] - after)[1]
        if found:
            return min(found, key=lambda pair: start - pair[0])[1]
    return None


def _mentions(text: str, label: str) -> list[int]:
    """Where `label` appears as a word of its own.

    Matched on word boundaries, so asking for "clicks" does not find "unique clicks" and report its
    figure instead. A wrong figure read confidently is worse than no figure at all.
    """

    pattern = re.compile(rf"(?<!\w){re.escape(label)}(?!\w)", re.IGNORECASE)
    return [match.start() for match in pattern.finditer(text)]


_NUMERIC = "0123456789,."


def _whole_numbers(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a slice until neither edge sits inside a number.

    Cutting "18,450" in the middle leaves the parser a fragment it reads as a perfectly good figure:
    the window used to turn 18,450 into 1845 with nothing to show anything had gone wrong.
    """

    while start > 0 and text[start - 1] in _NUMERIC and text[start] in _NUMERIC:
        start -= 1
    while end < len(text) and text[end] in _NUMERIC and text[end - 1] in _NUMERIC:
        end += 1
    return start, end
