"""What this library needs from a database: run this statement, give me back rows.

One alias, because that is genuinely the whole contract. Everything that reads a table takes an
`SqlExecutor` and never learns which database is behind it, which is how the package keeps working
with Databricks, Postgres or a file on disk without importing any of them.

Parameters are named (`:since`, not `?`), because every adapter here can accept that form and string
formatting into SQL is how injection happens. An adapter whose driver wants another paramstyle
rewrites it; callers write one thing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

SqlExecutor = Callable[[str, Mapping[str, Any]], Awaitable[list[dict[str, Any]]]]
"""Run one statement with named parameters and return its rows as dictionaries.

Async because a warehouse query is network-bound and an evaluation runs many of them at once. An
adapter over a blocking driver wraps it in `asyncio.to_thread` rather than making callers care.
"""


class AdapterNotInstalled(ImportError):
    """An adapter was asked for whose driver is not installed, naming the extra that provides it."""
