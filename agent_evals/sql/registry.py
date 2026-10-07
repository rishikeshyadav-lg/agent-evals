"""Choosing a database adapter by name, without importing the ones you did not choose.

The point of the registry is the import. Each adapter imports its driver at the top of its own
module, which is the readable way to write it, so the registry must not import an adapter module
until someone asks for that adapter by name. That keeps `import agent_evals` free of every driver —
the property `python -m agent_evals.selfcheck` exists to prove, and the reason this package can be a
dependency of anything.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

from .executor import AdapterNotInstalled, SqlExecutor

# name -> "module:function", resolved only when that name is asked for.
_ADAPTERS: Mapping[str, str] = {
    "sqlite": "agent_evals.sql.sqlite:open_sqlite",
}

# name -> the extra that installs its driver, for the message when it is missing.
_EXTRAS: Mapping[str, str] = {}


def adapter_names() -> tuple[str, ...]:
    """Every adapter this package knows how to open, whether or not its driver is installed."""

    return tuple(sorted(_ADAPTERS))


def open_executor(adapter: str, settings: Mapping[str, Any]) -> SqlExecutor:
    """An executor for one named adapter, configured by `settings`.

    Raises `KeyError` naming the known adapters when the name is unknown, and `AdapterNotInstalled`
    naming the extra to install when the adapter exists but its driver does not.
    """

    try:
        target = _ADAPTERS[adapter]
    except KeyError:
        raise KeyError(f"unknown adapter {adapter!r}; this package knows {', '.join(adapter_names())}") from None
    module_name, _, function_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        extra = _EXTRAS.get(adapter)
        hint = f'install it with `pip install "agent-evals[{extra}]"`' if extra else "its driver is unavailable"
        raise AdapterNotInstalled(f"the {adapter!r} adapter could not be loaded: {hint}") from error
    executor: SqlExecutor = getattr(module, function_name)(**settings)
    return executor
