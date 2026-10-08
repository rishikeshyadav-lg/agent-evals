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
from collections.abc import Sequence
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


def numbers_by_label(text: str, labels: Sequence[str], *, window: int = DEFAULT_WINDOW) -> dict[str, StatedNumber]:
    """Each label's figure, resolved together so no field takes another's number.

    Asking for one label at a time cannot work: English puts the figure on either side of the word
    ("400 clicks", "clicks were 400"), so whichever side you prefer, the other reading steals a
    neighbour's number. In "400 clicks, a ctr of 0.42%" a rule preferring what follows "clicks"
    returns 0.42.

    Resolving them together removes the guess. Every number goes to the label it sits closest to,
    and each label then takes the nearest number that chose it. A label with no number of its own is
    absent from the result, which is how a caller tells "not stated" from "stated wrongly".
    """

    if any(not label.strip() for label in labels):
        raise ValueError("every label must be non-empty")
    mentions = [(label, start) for label in labels for start in _mentions(text, label)]
    if not mentions:
        return {}
    claimed: dict[str, tuple[int, StatedNumber]] = {}
    for match in _NUMBER.finditer(text):
        if not match.group("number"):
            continue
        at = match.start()
        label, distance = min(
            ((label, _distance(at, start, len(label))) for label, start in mentions),
            key=lambda pair: pair[1],
        )
        if distance > window:
            continue
        if label not in claimed or distance < claimed[label][0]:
            claimed[label] = (distance, _stated(match))
    return {label: stated for label, (_, stated) in claimed.items()}


def _distance(number_at: int, label_at: int, label_length: int) -> int:
    """How far a number sits from a label, counting zero when it touches either end of it."""

    if number_at < label_at:
        return label_at - number_at
    return max(0, number_at - (label_at + label_length))


def _mentions(text: str, label: str) -> list[int]:
    """Where `label` appears as a word of its own.

    Matched on word boundaries, so asking for "clicks" does not find "unique clicks" and report its
    figure instead. A wrong figure read confidently is worse than no figure at all.
    """

    pattern = re.compile(rf"(?<!\w){re.escape(label)}(?!\w)", re.IGNORECASE)
    return [match.start() for match in pattern.finditer(text)]
