"""Regression guard: a same-named test module in another layer must collect.

This file exists as the domain half of a deliberate basename collision with
`tests/infrastructure/test_record.py`. Under pytest's default `prepend` import
mode the pair aborts collection for the entire suite with "import file
mismatch", because `tests/` holds no `__init__.py` and both files would claim
the top-level module name `test_record`. `--import-mode=importlib` in the
pytest `addopts` keeps `tests/` free of packages and lets both be imported.

`test_record.py` is exactly the name the domain and infrastructure developers
would each pick independently, so the collision is kept here on purpose: if
the import mode is ever reverted, this pair fails loudly and immediately.
"""

from __future__ import annotations


def test_this_module_is_imported_under_its_full_path() -> None:
    """importlib mode gives the module a path-qualified name, not `test_record`."""
    assert __name__ != "test_record"
    assert __name__.endswith("test_record")
    assert "domain" in __name__
