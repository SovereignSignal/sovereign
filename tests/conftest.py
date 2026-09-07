"""Make the repo's own packages importable from a test run.

`lib/` holds `archive_evidence`, and this repo ships no packaging file (no
pyproject.toml, setup.cfg or pytest.ini), so nothing else puts it on sys.path:
without this, `pytest tests` aborts at collection with four ModuleNotFoundErrors
before a single test runs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
