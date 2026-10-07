"""SQLite, from the standard library, so this works before you have installed anything.

It exists for two jobs. It is the honest default for small ground-truth tables kept beside a project,
and it is what the examples and tests use, so none of them need a warehouse, credentials or a
network. The adapter contract is the same one the driver-backed adapters implement, so a suite proved
here is wired correctly — though only your own database can tell you your SQL is right.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .executor import SqlExecutor


def open_sqlite(*, path: str | Path, timeout: float = 5.0) -> SqlExecutor:
    """An executor over one SQLite file. Use `":memory:"` for a database that lives only in this run.

    One connection is held for the life of the executor rather than opened per statement, because
    `":memory:"` gives each new connection its own empty database — reconnecting would quietly lose
    the table you just created. Since the connection is shared, and sqlite3 is blocking while an
    evaluation scores cases concurrently, each statement runs in a worker thread under a lock. That
    serialises queries, which is the right trade for the small read-mostly tables this is meant for;
    reach for a server database when it is not.
    """

    connection = sqlite3.connect(str(path), timeout=timeout, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    guard = threading.Lock()

    def run(statement: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
        with guard, connection:
            cursor = connection.execute(statement, dict(parameters))
            return [dict(row) for row in cursor.fetchall()]

    async def execute(statement: str, parameters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(run, statement, parameters or {})

    return execute
