"""Turning a question into the query that settles it.

A question is text; a scorer needs SQL. Nothing in this package makes that leap on your behalf,
because deciding what a question means is exactly the guess that produces confident wrong verdicts.
What it offers instead is a seam and one drafter that does not guess.

`TemplateDrafter` fills a query you wrote from a value it finds in the question. It covers the shape
that dominates real traffic -- "how is <thing> doing", where the thing is an identifier -- and it
either finds that identifier or declines. A model-backed drafter handling the rest is a function you
supply, and whatever it produces still has to survive the review gate.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ..mining.source import MinedQuestion
from .review import Draft

QueryDrafter = Callable[[MinedQuestion], Draft | None | Awaitable[Draft | None]]
"""Propose a query for one question, or None when this drafter has nothing to offer.

Returning None is a first-class answer. A drafter that always produces something produces nonsense
for the questions it does not understand, and nonsense that runs is the failure this package is
built to avoid.
"""


@dataclass(frozen=True, slots=True)
class TemplateDrafter:
    """Fills one query you wrote, using a value pulled out of the question by a pattern.

    Deterministic, offline and free, which makes it the right first choice wherever it applies: a
    template you reviewed once is more trustworthy than a model's output reviewed every time.

    `sql` uses `:name` parameters. `pattern` must capture exactly one group, and whatever it captures
    becomes `parameter`. A question the pattern does not match gets no draft at all.
    """

    sql: str
    pattern: str
    parameter: str
    fields: Mapping[str, str]
    required: Sequence[str] = ()
    name: str = "template"

    def __post_init__(self) -> None:
        if re.compile(self.pattern).groups != 1:
            raise ValueError("pattern must capture exactly one value, which becomes the parameter")
        if not self.fields:
            raise ValueError("a draft with no fields to check could never score anything")

    def __call__(self, question: MinedQuestion) -> Draft | None:
        found = re.search(self.pattern, question.question)
        if not found:
            return None
        return Draft(
            case_id=question.trace_id,
            question=question.question,
            sql=self.sql,
            parameters={self.parameter: found.group(1)},
            fields=dict(self.fields),
            required=list(self.required),
        )


@dataclass(frozen=True, slots=True)
class FirstMatch:
    """Try each drafter in turn and take the first that offers something.

    Order is the policy: put the templates you trust ahead of anything that guesses, so a model is
    only reached for the questions nothing cheaper could handle.
    """

    drafters: Sequence[QueryDrafter] = field(default_factory=tuple)

    async def __call__(self, question: MinedQuestion) -> Draft | None:
        for drafter in self.drafters:
            drafted = drafter(question)
            if isinstance(drafted, Awaitable):
                drafted = await drafted
            if drafted is not None:
                return drafted
        return None


__all__ = ["FirstMatch", "QueryDrafter", "TemplateDrafter"]
