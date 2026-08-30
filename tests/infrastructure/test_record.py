"""Regression guard: the infrastructure half of a deliberate basename collision.

See the module docstring of `tests/domain/test_record.py`. The two files share
a basename on purpose so that losing `--import-mode=importlib` from the pytest
`addopts` breaks the suite immediately rather than the first time two layer
developers happen to choose the same test filename.
"""

from __future__ import annotations


def test_this_module_is_imported_under_its_full_path() -> None:
    """Collected alongside the domain module of the same basename."""
    assert __name__ != "test_record"
    assert __name__.endswith("test_record")
    assert "infrastructure" in __name__
