"""Choosing a trace source by name, without importing the ones you did not choose.

Same reason as the database registry: each source imports its client at the top of its own module,
which is the readable way to write it, so nothing here may import a source module until someone asks
for that source by name. That is what keeps `import agent_evals` free of mlflow, and the selfcheck
proves it on every run.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any

from .source import SourceNotInstalled, TraceSource

# name -> "module:function", resolved only when that name is asked for.
_SOURCES: Mapping[str, str] = {
    "mlflow": "agent_evals.mining.mlflow_source:open_mlflow",
}

# name -> the extra that installs its client, for the message when it is missing.
_EXTRAS: Mapping[str, str] = {"mlflow": "mlflow"}


def source_names() -> tuple[str, ...]:
    """Every source this package knows how to open, whether or not its client is installed."""

    return tuple(sorted(_SOURCES))


def open_source(name: str, settings: Mapping[str, Any]) -> TraceSource:
    """A trace source by name, configured by `settings`.

    Raises `KeyError` naming the known sources when the name is unknown, and `SourceNotInstalled`
    naming the extra to install when the source exists but its client does not.
    """

    try:
        target = _SOURCES[name]
    except KeyError:
        raise KeyError(f"unknown trace source {name!r}; this package knows {', '.join(source_names())}") from None
    module_name, _, function_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        extra = _EXTRAS.get(name)
        hint = f'install it with `pip install "agent-evals[{extra}]"`' if extra else "its client is unavailable"
        raise SourceNotInstalled(f"the {name!r} trace source could not be loaded: {hint}") from error
    source: TraceSource = getattr(module, function_name)(**settings)
    return source


__all__ = ["open_source", "source_names"]
