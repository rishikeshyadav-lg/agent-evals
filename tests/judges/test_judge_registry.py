"""Choosing a model client by name, without importing the ones you did not choose."""

from __future__ import annotations

import pytest

from agent_evals.judges import client_names, open_judge
from agent_evals.judges.registry import JudgeNotInstalled


def test_the_known_clients_are_listed_whether_installed_or_not() -> None:
    assert "databricks" in client_names()


def test_an_unknown_name_says_what_is_known() -> None:
    with pytest.raises(KeyError, match="databricks"):
        open_judge("gpt", {})


def test_a_known_client_with_no_sdk_names_the_extra_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """The message has to name the extra. "could not be loaded" alone sends a reader looking for a
    bug in their config when the fix is one install."""

    import agent_evals.judges.registry as registry

    def missing(name: str) -> None:
        raise ImportError("No module named 'databricks'")

    monkeypatch.setattr(registry.importlib, "import_module", missing)

    with pytest.raises(JudgeNotInstalled, match=r'agent-evals\[databricks\]'):
        open_judge("databricks", {"endpoint": "x"})


def test_opening_a_judge_requires_an_endpoint() -> None:
    """No default model. A judge's identity belongs in a config a reader can see, because changing
    the model changes every score it produced."""

    pytest.importorskip("databricks.sdk")

    with pytest.raises(ValueError, match="endpoint is required"):
        open_judge("databricks", {"endpoint": "  "})
