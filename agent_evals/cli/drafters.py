"""Finding the drafter a project configured.

Which drafter to use is a project decision, not a library one: a template you wrote, a model you
pay for, or several in order. So `agent-evals.toml` names one as `module:attribute` and this loads
it, the same way the eval app loads a second agent.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from . import config as configuration


def load_drafter(root: Path, settings: configuration.Config) -> Any:
    """The drafter named by `drafter = "module:attribute"`, or None when none is set."""

    target = settings.drafter.strip()
    if not target:
        return None
    module_name, separator, attribute = target.partition(":")
    if not separator:
        raise ValueError(f"drafter {target!r} must be written module:attribute")
    # The drafter lives in the project being evaluated, which is not on the path by default.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return getattr(importlib.import_module(module_name), attribute)


__all__ = ["load_drafter"]
