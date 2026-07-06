"""Conftest for letsFS tests.

Adds the project root to ``sys.path`` so the tests run against the source
tree without requiring an install. Marks network tests via the ``live``
marker (see ``pyproject.toml``).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
