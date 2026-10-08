"""Reaching a model, without the rest of the package knowing which one.

The mirror of `agent_evals/sql`, for the same reason. This is the only folder allowed to import a
model client, and only inside the adapter module that needs it. Importing `agent_evals.judges`
loads the registry and nothing else, so the package keeps the dependency-free import that
`python -m agent_evals.selfcheck` exists to prove.
"""

from .registry import client_names, open_judge

__all__ = ["client_names", "open_judge"]
