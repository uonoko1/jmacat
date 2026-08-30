"""The dependency rule, enforced mechanically.

    controller  ->  usecase  ->  domain
    infrastructure  ->  usecase/ports   (dependency inversion)

`domain/` may import the standard library only. `domain/` and `usecase/` may
never import `jmacat.infrastructure` or `jmacat.controller`. Convention is not
enough: this walks the AST of every module under `src/jmacat/`.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

PACKAGE = "jmacat"


def imported_modules(tree: ast.AST, *, package: str) -> list[str]:
    """Absolute dotted names imported by `tree`, whose module lives in `package`."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(_absolute(node, package=package))
    return found


def _absolute(node: ast.ImportFrom, *, package: str) -> str:
    """Resolve an ImportFrom to an absolute dotted name.

    `node.level` is the number of leading dots: 0 is already absolute, 1 means
    the containing package, and each further dot climbs one package.
    """
    if node.level == 0:
        assert node.module is not None  # level 0 always names a module
        return node.module
    parts = package.split(".")
    base = parts if node.level == 1 else parts[: -(node.level - 1)]
    return ".".join([*base, node.module]) if node.module else ".".join(base)


def is_third_party(module: str) -> bool:
    """True when `module` is neither our own package nor the standard library.

    The stdlib set comes from the running interpreter rather than a hardcoded
    list, so the guard stays correct as the baseline moves past 3.11.
    """
    root = module.split(".")[0]
    return root != PACKAGE and root not in sys.stdlib_module_names


# The layers that must not leak inward, and the layers that must not reach them.
OUTER_LAYERS = ("infrastructure", "controller")
PURE_LAYERS = ("domain", "usecase")


def layer_of(module: str) -> str | None:
    """The layer package a module belongs to, e.g. jmacat.usecase.ports -> usecase."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == PACKAGE else None


def violations(module: str, imports: list[str]) -> list[str]:
    """Every way `module` breaks the dependency rule by importing `imports`."""
    layer = layer_of(module)
    if layer not in PURE_LAYERS:
        return []
    found: list[str] = []
    for imported in imports:
        if is_third_party(imported):
            found.append(
                f"{module} imports third-party {imported!r}; "
                f"{layer}/ is standard library only"
            )
        elif layer_of(imported) in OUTER_LAYERS:
            found.append(
                f"{module} imports {imported!r}; "
                f"{layer}/ must not depend on {layer_of(imported)}/"
            )
    return found


SRC = Path(__file__).resolve().parent.parent / "src"


def source_modules() -> Iterator[tuple[Path, str]]:
    """Every module under src/jmacat/, with its absolute dotted name."""
    for path in sorted((SRC / PACKAGE).rglob("*.py")):
        relative = path.relative_to(SRC).with_suffix("")
        parts = relative.parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        yield path, ".".join(parts)


def test_plain_import_is_reported() -> None:
    tree = ast.parse("import json")
    assert imported_modules(tree, package="jmacat.domain") == ["json"]


def test_from_import_is_reported() -> None:
    tree = ast.parse("from datetime import timezone")
    assert imported_modules(tree, package="jmacat.domain") == ["datetime"]


def test_relative_import_is_resolved_against_the_containing_package() -> None:
    """`from .record import X` inside jmacat.domain is jmacat.domain.record."""
    tree = ast.parse("from .record import Hypocenter")
    assert imported_modules(tree, package="jmacat.domain") == ["jmacat.domain.record"]


def test_parent_relative_import_climbs_one_package_per_dot() -> None:
    tree = ast.parse("from ..infrastructure import http")
    assert imported_modules(tree, package="jmacat.usecase") == ["jmacat.infrastructure"]


def test_bare_parent_relative_import_names_the_parent_package() -> None:
    """`from .. import x` inside jmacat.usecase.ports refers to jmacat.usecase."""
    tree = ast.parse("from .. import interactor")
    assert imported_modules(tree, package="jmacat.usecase.ports") == ["jmacat.usecase"]


def test_dotted_import_keeps_its_full_path() -> None:
    tree = ast.parse("import jmacat.infrastructure.http")
    assert imported_modules(tree, package="jmacat.domain") == [
        "jmacat.infrastructure.http"
    ]


def test_standard_library_module_is_not_third_party() -> None:
    assert not is_third_party("datetime")


def test_submodule_of_the_standard_library_is_not_third_party() -> None:
    """Only the top-level name decides; `os.path` is still the stdlib."""
    assert not is_third_party("os.path")


def test_our_own_package_is_not_third_party() -> None:
    assert not is_third_party("jmacat.domain.record")


def test_an_installed_package_outside_the_standard_library_is_third_party() -> None:
    assert is_third_party("pyarrow")


def test_domain_importing_the_standard_library_is_allowed() -> None:
    assert violations("jmacat.domain.record", ["datetime", "dataclasses"]) == []


def test_domain_importing_a_third_party_package_is_a_violation() -> None:
    (message,) = violations("jmacat.domain.record", ["pyarrow"])
    assert "pyarrow" in message


def test_usecase_importing_a_third_party_package_is_a_violation() -> None:
    """Ports are typing.Protocol, so the use case layer stays pure too."""
    (message,) = violations("jmacat.usecase.export", ["httpx"])
    assert "httpx" in message


def test_domain_importing_infrastructure_is_a_violation() -> None:
    (message,) = violations("jmacat.domain.record", ["jmacat.infrastructure.http"])
    assert "jmacat.infrastructure.http" in message


def test_usecase_importing_controller_is_a_violation() -> None:
    (message,) = violations("jmacat.usecase.export", ["jmacat.controller.cli"])
    assert "jmacat.controller.cli" in message


def test_usecase_importing_domain_is_allowed() -> None:
    assert violations("jmacat.usecase.export", ["jmacat.domain.record"]) == []


def test_infrastructure_may_import_a_third_party_package_and_the_ports() -> None:
    assert (
        violations(
            "jmacat.infrastructure.parquet",
            ["pyarrow", "jmacat.usecase.ports"],
        )
        == []
    )


def test_controller_may_import_a_third_party_package_and_the_use_cases() -> None:
    assert violations("jmacat.controller.cli", ["typer", "jmacat.usecase.export"]) == []


def test_a_module_reports_every_violating_import_not_only_the_first() -> None:
    assert len(violations("jmacat.domain.record", ["pyarrow", "httpx"])) == 2


def test_the_guard_actually_finds_the_source_tree() -> None:
    """A guard that scans nothing would pass vacuously for ever."""
    assert len(list(source_modules())) >= 5


def test_no_module_breaks_the_dependency_rule() -> None:
    found: list[str] = []
    for path, module in source_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = module.rsplit(".", 1)[0] if path.name != "__init__.py" else module
        found.extend(violations(module, imported_modules(tree, package=package)))
    assert not found, "dependency rule violated:\n" + "\n".join(found)
