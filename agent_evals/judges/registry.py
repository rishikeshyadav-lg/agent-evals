"""Choosing a model client by name, without importing the ones you did not choose.

The point of the registry is the import. A judge needs a model client, and a model client pulls in a
provider SDK; resolving one by name keeps that SDK out of `import agent_evals`, which is what lets
this package be a dependency of the thing it evaluates.

Deliberately no default. A judge costs money per call and its verdict can differ between runs, so
which model judges your agent is a decision to make out loud, in a config a reader can see.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

from ..scoring.judging import JudgeClient

# name -> "module:function", resolved only when that name is asked for.
_CLIENTS: Mapping[str, str] = {
    "databricks": "agent_evals.judges.databricks:open_databricks_judge",
}

# name -> the extra that installs its SDK, for the message when it is missing.
_EXTRAS: Mapping[str, str] = {"databricks": "databricks"}


class JudgeNotInstalled(RuntimeError):
    """A known client whose SDK is not installed."""


def client_names() -> tuple[str, ...]:
    """Every model client this package knows how to open, installed or not."""

    return tuple(sorted(_CLIENTS))


def open_judge(client: str, settings: Mapping[str, Any]) -> JudgeClient:
    """A judge client for one named provider, configured by `settings`.

    Raises `KeyError` naming the known clients when the name is unknown, and `JudgeNotInstalled`
    naming the extra to install when the client exists but its SDK does not.
    """

    try:
        target = _CLIENTS[client]
    except KeyError:
        raise KeyError(f"unknown judge client {client!r}; this package knows {', '.join(client_names())}") from None
    module_name, _, function_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        extra = _EXTRAS.get(client)
        hint = f'install it with `pip install "agent-evals[{extra}]"`' if extra else "its SDK is unavailable"
        raise JudgeNotInstalled(f"the {client!r} judge client could not be loaded: {hint}") from error
    opened: JudgeClient = getattr(module, function_name)(**settings)
    return opened
