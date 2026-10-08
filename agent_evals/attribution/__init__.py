"""Why a run went wrong, where its time went, and where its money went.

Separate from `scoring` because it answers a different question. A scorer says how good an answer
was; attribution says what to fix. The two are kept apart so a cause can never influence a score —
this package reads what scoring already decided and adds nothing to it.

It imports only `core` and `running`. `reporting` must not be imported from here, and
`reporting/report.py` must not import this: causes stay out of `Report` and the caller composes
them, so a report cannot start depending on a diagnosis.
"""

from .causes import (
    DEFAULT_RULES,
    Attribution,
    Cause,
    CauseCode,
    CauseRule,
    CriterionBelow,
    attribute,
    attribute_run,
)
from .facts import RunFacts, ToolCallFact, declared_empty, facts_of_result, facts_of_row

__all__ = [
    "DEFAULT_RULES",
    "Attribution",
    "Cause",
    "CauseCode",
    "CauseRule",
    "CriterionBelow",
    "RunFacts",
    "ToolCallFact",
    "attribute",
    "attribute_run",
    "declared_empty",
    "facts_of_result",
    "facts_of_row",
]
