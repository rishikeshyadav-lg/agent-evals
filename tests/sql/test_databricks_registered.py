"""The databricks adapter is reachable by name, and says what to install when it is not."""

from __future__ import annotations

import pytest

from agent_evals.sql import adapter_names, open_executor


def test_databricks_is_a_known_adapter() -> None:
    """`init` writes database = "databricks" when it finds a warehouse, so the name must resolve.

    It did not, and the config init produced could not be used at all.
    """

    assert "databricks" in adapter_names()


def test_an_unknown_adapter_lists_what_is_known() -> None:
    """The error path. "unknown adapter" alone leaves you guessing at the spelling."""

    with pytest.raises(KeyError, match="databricks, sqlite"):
        open_executor("snowflake", {})


def test_the_adapter_refuses_without_a_warehouse() -> None:
    """A warehouse id cannot be defaulted, and failing late costs a credential round trip."""

    databricks = pytest.importorskip("agent_evals.sql.databricks", reason="needs the databricks extra")

    with pytest.raises(ValueError, match="warehouse_id is required"):
        databricks.open_databricks(warehouse_id="  ")
