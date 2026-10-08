"""Choosing a trace source by name, without importing the ones you did not choose."""

from __future__ import annotations

import pytest

from agent_evals.mining import open_source, source_names


def test_the_known_sources_are_listed() -> None:
    assert "mlflow" in source_names()


def test_an_unknown_source_says_what_is_known() -> None:
    """The error path. "unknown source" alone leaves you guessing at the spelling."""

    with pytest.raises(KeyError, match="mlflow"):
        open_source("datadog", {})
