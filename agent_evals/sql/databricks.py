"""Databricks SQL warehouses. Optional: `pip install "agent-evals[databricks]"`.

Runs one statement on a SQL warehouse through the Statement Execution API and returns its rows as
dictionaries, which is the whole contract in `executor.py`.

Authentication is never passed in here. The Databricks SDK already resolves it from the environment
or `~/.databrickscfg`, in that order, and re-asking for a host and a token would mean copying
credentials that are already on the machine into a second place.

Parameters are named, as the contract requires, and are sent as parameter markers rather than
formatted into the SQL. That is not a style preference: string formatting into a statement is how
injection happens, and an evaluation runs queries built from text that came out of a trace.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    Disposition,
    Format,
    StatementParameterListItem,
    StatementState,
)

from .executor import SqlExecutor

TERMINAL = {StatementState.SUCCEEDED, StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED}


def open_databricks(
    *,
    warehouse_id: str,
    catalog: str | None = None,
    schema: str | None = None,
    profile: str = "",
    wait_timeout: str = "30s",
    poll_seconds: float = 1.0,
    max_wait_s: float = 300.0,
) -> SqlExecutor:
    """An executor over one SQL warehouse.

    `profile` names a section of `~/.databrickscfg`; leave it empty to let the SDK resolve
    authentication the way it normally would.
    """

    if not warehouse_id.strip():
        raise ValueError("warehouse_id is required to know which warehouse runs the statement")
    client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()

    def run(sql: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
        response = client.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=warehouse_id,
            catalog=catalog,
            schema=schema,
            disposition=Disposition.INLINE,
            format=Format.JSON_ARRAY,
            wait_timeout=wait_timeout,
            parameters=[
                StatementParameterListItem(name=name, value=None if value is None else str(value))
                for name, value in sorted(parameters.items())
            ],
        )
        return _rows(_settled(client, response, poll_seconds, max_wait_s))

    async def execute(sql: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
        return await asyncio.to_thread(run, sql, parameters)

    return execute


def _settled(client: WorkspaceClient, response: Any, poll_seconds: float, max_wait_s: float) -> Any:
    """Wait for the statement to finish.

    `wait_timeout` only covers the first few seconds; a warehouse that was asleep, or a scan of a
    large table, returns PENDING and has to be polled.
    """

    waited = 0.0
    while _state(response) not in TERMINAL:
        if waited >= max_wait_s:
            raise TimeoutError(f"statement did not finish within {max_wait_s:.0f}s")
        import time

        time.sleep(poll_seconds)
        waited += poll_seconds
        response = client.statement_execution.get_statement(response.statement_id)
    if _state(response) is not StatementState.SUCCEEDED:
        raise RuntimeError(f"the statement ended as {_state(response)}: {_error(response)}")
    return response


def _state(response: Any) -> Any:
    return getattr(getattr(response, "status", None), "state", None)


def _error(response: Any) -> str:
    error = getattr(getattr(response, "status", None), "error", None)
    return str(getattr(error, "message", "") or "no message")


def _rows(response: Any) -> list[dict[str, Any]]:
    """The inline result as dictionaries, with the column names the warehouse reported."""

    manifest = getattr(response, "manifest", None)
    columns = getattr(getattr(manifest, "schema", None), "columns", None) or []
    names = [str(getattr(column, "name", index)) for index, column in enumerate(columns)]
    data = getattr(getattr(response, "result", None), "data_array", None) or []
    return [dict(zip(names, row, strict=False)) for row in data]


__all__ = ["open_databricks"]
