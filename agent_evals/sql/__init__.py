"""Reaching a database, without the rest of the package knowing which one.

This is the only folder allowed to import a driver, and only inside the adapter module that needs
it. Importing `agent_evals.sql` loads the contract and the registry and nothing else, so adding
adapters never costs the package its dependency-free import.
"""

from .executor import AdapterNotInstalled, SqlExecutor
from .registry import adapter_names, open_executor

__all__ = ["AdapterNotInstalled", "SqlExecutor", "adapter_names", "open_executor"]
