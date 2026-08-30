"""The dependency rule, enforced mechanically.

The four layers, innermost first:

    domain  <-  usecase  <-  infrastructure  <-  controller

A module may import its own layer and anything inward of it; importing outward
is a violation. `controller/` is the composition root, so it may reach
`infrastructure/` to wire concrete adapters -- but no adapter may reach the
CLI. `domain/` and `usecase/` may additionally import the standard library
only. The full matrix and its reasoning live in CONTRIBUTING.md.

Convention is not enough: this walks the AST of every module under
`src/jmacat/`.

Known limitation: only `import` and `from ... import` statements are seen, so
dynamic imports (`importlib.import_module(...)`, `__import__(...)`) are not
detected.
"""

from __future__ import annotations

import ast
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

PACKAGE = "jmacat"


def imported_modules(tree: ast.AST, *, package: str) -> list[str]:
    """Absolute dotted names imported by `tree`, whose module lives in `package`.

    An `ImportFrom` reports its module *and*, when that module is one of ours,
    each name imported from it: `from jmacat import infrastructure` reaches
    `jmacat.infrastructure`, and only the dotted form carries a layer. The
    bare module is kept because it is what the third-party check reads.

    Names are only appended for our own package, where a layer can be read off
    them. A `from pyarrow import Table` or `from datetime import timezone`
    stays a single bare module, so no import is reported twice and no imported
    symbol is mistaken for a module.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(node, package=package)
            found.append(module)
            if module.split(".")[0] == PACKAGE:
                found.extend(
                    f"{module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
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


# The layers, innermost first. A layer may import itself and anything to its
# left; importing anything to its right points outward and is a violation.
#
# `infrastructure` and `controller` are both adapter layers, but they are not
# peers: composition happens at the outermost layer, so the CLI wires concrete
# adapters into interactors and therefore sits outside `infrastructure`. The
# reverse -- an adapter reaching for the CLI -- has no legitimate form, and is
# what issue #21 found unenforced. See CONTRIBUTING.md for the full matrix.
LAYERS = ("domain", "usecase", "infrastructure", "controller")

# Layers that may not import a third-party package: they carry the
# scientifically sensitive logic and must be testable with no dependencies
# installed. `infrastructure/` and `controller/` exist precisely to hold them.
PURE_LAYERS = ("domain", "usecase")

# Kept for the message and for tests that name the adapter layers as a set.
OUTER_LAYERS = ("infrastructure", "controller")


def layer_of(module: str) -> str | None:
    """The layer package a module belongs to, e.g. jmacat.usecase.ports -> usecase."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == PACKAGE else None


def points_outward(*, importer: str, imported: str) -> bool:
    """True when a module in layer `importer` may not import layer `imported`.

    Both names must be layers of ours; a module outside the four layers (for
    instance `jmacat` itself, whose `layer_of` is None) is nobody's dependency
    problem and is handled by the caller.
    """
    return LAYERS.index(imported) > LAYERS.index(importer)


def violations(module: str, imports: list[str]) -> list[str]:
    """Every way `module` breaks the dependency rule by importing `imports`."""
    layer = layer_of(module)
    if layer not in LAYERS:
        return []
    found: list[str] = []
    for imported in imports:
        target = layer_of(imported)
        if is_third_party(imported):
            if layer in PURE_LAYERS:
                found.append(
                    f"{module} imports third-party {imported!r}; "
                    f"{layer}/ is standard library only"
                )
        elif target in LAYERS and points_outward(importer=layer, imported=target):
            found.append(
                f"{module} imports {imported!r}; "
                f"{layer}/ must not depend on {target}/"
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
    """`from .record import X` inside jmacat.domain is jmacat.domain.record.

    The imported name is reported under it too; `Hypocenter` is a class rather
    than a submodule, but it inherits its module's layer, so it cannot change
    how the import is classified.
    """
    tree = ast.parse("from .record import Hypocenter")
    assert imported_modules(tree, package="jmacat.domain") == [
        "jmacat.domain.record",
        "jmacat.domain.record.Hypocenter",
    ]


def test_parent_relative_import_climbs_one_package_per_dot() -> None:
    tree = ast.parse("from ..infrastructure import http")
    assert imported_modules(tree, package="jmacat.usecase") == [
        "jmacat.infrastructure",
        "jmacat.infrastructure.http",
    ]


def test_bare_parent_relative_import_names_the_parent_package() -> None:
    """`from .. import x` inside jmacat.usecase.ports refers to jmacat.usecase."""
    tree = ast.parse("from .. import interactor")
    assert imported_modules(tree, package="jmacat.usecase.ports") == [
        "jmacat.usecase",
        "jmacat.usecase.interactor",
    ]


def test_from_import_of_a_submodule_yields_the_submodule() -> None:
    """`from jmacat import infrastructure` names jmacat.infrastructure.

    Recording only the bare module `jmacat` would hide the sibling-layer
    import, because `layer_of("jmacat")` is None.
    """
    tree = ast.parse("from jmacat import infrastructure")
    assert "jmacat.infrastructure" in imported_modules(tree, package="jmacat.domain")


def test_from_import_of_a_submodule_keeps_its_alias_name_not_the_asname() -> None:
    """`as` renames the local binding, not the module that is reached."""
    tree = ast.parse("from jmacat import infrastructure as infra")
    assert "jmacat.infrastructure" in imported_modules(tree, package="jmacat.domain")


def test_relative_from_import_of_a_submodule_yields_the_submodule() -> None:
    """`from ... import infrastructure` inside usecase/ports is the same leak."""
    tree = ast.parse("from ... import infrastructure")
    assert "jmacat.infrastructure" in imported_modules(
        tree, package="jmacat.usecase.ports"
    )


def test_a_third_party_from_import_is_not_reported_twice() -> None:
    """`from pyarrow import Table` reaches one package, so it reports once.

    The dotted name exists only to resolve our own layers; emitting
    `pyarrow.Table` too would duplicate every third-party violation message.
    """
    tree = ast.parse("from pyarrow import Table")
    assert imported_modules(tree, package="jmacat.domain") == ["pyarrow"]


def test_a_star_import_does_not_invent_a_module_named_star() -> None:
    tree = ast.parse("from jmacat import *")
    assert imported_modules(tree, package="jmacat.domain") == ["jmacat"]


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


def test_domain_importing_infrastructure_via_the_parent_package_is_a_violation() -> (
    None
):
    """The whole point of finding 1: `from jmacat import infrastructure`."""
    (message,) = violations("jmacat.domain.leak", ["jmacat", "jmacat.infrastructure"])
    assert "jmacat.infrastructure" in message


def test_usecase_importing_controller_via_the_parent_package_is_a_violation() -> None:
    (message,) = violations("jmacat.usecase.export", ["jmacat", "jmacat.controller"])
    assert "jmacat.controller" in message


def test_usecase_importing_its_own_ports_subpackage_is_allowed() -> None:
    """`from jmacat.usecase import ports` must not become a false positive."""
    assert (
        violations("jmacat.usecase.export", ["jmacat.usecase", "jmacat.usecase.ports"])
        == []
    )


def test_usecase_importing_domain_via_the_parent_package_is_allowed() -> None:
    """Inward dependencies stay legal; do not over-correct into a false positive."""
    assert violations("jmacat.usecase.export", ["jmacat", "jmacat.domain"]) == []


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


# --- infrastructure/ must not depend on controller/ (issue #21) -------------
#
# Until issue #21 these all returned [] because `violations` bailed out for any
# layer outside PURE_LAYERS. The rule CONTRIBUTING states was never enforced for
# the two outer layers, and nobody noticed because the original evidence only
# ever covered domain/ and usecase/.


def test_infrastructure_importing_controller_is_a_violation() -> None:
    (message,) = violations("jmacat.infrastructure.parquet", ["jmacat.controller.cli"])
    assert "jmacat.controller.cli" in message


def test_infrastructure_importing_controller_via_the_parent_package_is_a_violation() -> (
    None
):
    """`from jmacat import controller` — the shape that was the original blind spot."""
    (message,) = violations(
        "jmacat.infrastructure.parquet", ["jmacat", "jmacat.controller"]
    )
    assert "jmacat.controller" in message


def test_infrastructure_importing_the_controller_package_itself_is_a_violation() -> None:
    (message,) = violations("jmacat.infrastructure.parquet", ["jmacat.controller"])
    assert "jmacat.controller" in message


def test_infrastructure_importing_its_own_sibling_module_is_allowed() -> None:
    """A layer always reaches itself; do not over-correct into a false positive."""
    assert (
        violations(
            "jmacat.infrastructure.parquet",
            ["jmacat.infrastructure", "jmacat.infrastructure.event_schema"],
        )
        == []
    )


def test_infrastructure_importing_domain_is_allowed() -> None:
    """An adapter serialises a domain value object, so it must be able to see it."""
    assert violations("jmacat.infrastructure.parquet", ["jmacat.domain.hypocenter"]) == []


def test_infrastructure_importing_usecase_is_allowed() -> None:
    assert (
        violations(
            "jmacat.infrastructure.parquet",
            ["jmacat.usecase.ports", "jmacat.usecase.errors"],
        )
        == []
    )


# --- controller/ is the composition root ------------------------------------


def test_controller_importing_infrastructure_is_allowed() -> None:
    """Composition happens at the outermost layer; the CLI wires the adapters."""
    assert (
        violations(
            "jmacat.controller.cli",
            ["jmacat.infrastructure.parquet_event_writer"],
        )
        == []
    )


def test_controller_importing_infrastructure_via_the_parent_package_is_allowed() -> None:
    assert violations("jmacat.controller.cli", ["jmacat", "jmacat.infrastructure"]) == []


def test_controller_importing_domain_is_allowed() -> None:
    assert violations("jmacat.controller.cli", ["jmacat.domain.filters"]) == []


def test_controller_importing_a_third_party_package_is_allowed() -> None:
    """The CLI parses arguments and formats output; a library there is expected."""
    assert violations("jmacat.controller.cli", ["typer", "rich.table"]) == []


def test_infrastructure_may_import_a_third_party_package() -> None:
    assert violations("jmacat.infrastructure.parquet", ["pyarrow.parquet"]) == []


def test_an_outer_module_reports_every_violating_import_not_only_the_first() -> None:
    """The loop must not stop at the first find, for outer layers too."""
    assert (
        len(
            violations(
                "jmacat.infrastructure.parquet",
                ["jmacat.controller", "jmacat.controller.cli"],
            )
        )
        == 2
    )


def test_the_guard_actually_finds_the_source_tree() -> None:
    """A guard that scans nothing would pass vacuously for ever."""
    assert len(list(source_modules())) >= 5


def test_the_guard_scans_every_layer_it_claims_to_cover() -> None:
    """Vacuity, per layer: `no module breaks the rule` is empty for a layer we
    never scanned, and that is exactly how issue #21 stayed invisible.

    `controller/` currently holds only `__init__.py`, which is a real module
    under the rule, so the assertion is on the layer being reached at all.
    """
    scanned = {layer_of(module) for _, module in source_modules()}
    assert set(PURE_LAYERS) | set(OUTER_LAYERS) <= scanned


def scan(source: str, *, module: str) -> list[str]:
    """Run the whole guard over one module's source, as the suite does on disk."""
    tree = ast.parse(source)
    package = module.rsplit(".", 1)[0]
    return violations(module, imported_modules(tree, package=package))


def test_the_guard_catches_a_leak_written_the_idiomatic_way() -> None:
    """End to end over source text, not a hand-written import list.

    This is the exact file that merged clean before the fix.
    """
    leak = textwrap.dedent("""
        from jmacat import infrastructure

        def load() -> None:
            infrastructure.fetch()
    """)
    (message,) = scan(leak, module="jmacat.domain.leak")
    assert "jmacat.infrastructure" in message


def test_the_guard_catches_a_relative_leak_from_a_nested_package() -> None:
    (message,) = scan(
        "from ... import controller\n", module="jmacat.usecase.ports.sink"
    )
    assert "jmacat.controller" in message


def test_the_guard_allows_an_inward_import_written_the_idiomatic_way() -> None:
    assert scan("from jmacat import domain\n", module="jmacat.usecase.export") == []


def test_the_guard_catches_an_outward_leak_written_the_idiomatic_way() -> None:
    """`from jmacat import controller` inside infrastructure/, end to end."""
    leak = textwrap.dedent("""
        from jmacat import controller

        def report() -> None:
            controller.echo("done")
    """)
    (message,) = scan(leak, module="jmacat.infrastructure.leak")
    assert "jmacat.controller" in message


def test_the_guard_catches_an_absolute_outward_leak_from_infrastructure() -> None:
    """`from jmacat.controller import cli` reaches the package and the submodule.

    Both are reported, as they are for an inward leak: `imported_modules`
    records the module *and* the name taken from it, because only the dotted
    form carries a layer.
    """
    messages = scan(
        "from jmacat.controller import cli\n", module="jmacat.infrastructure.leak"
    )
    assert [m.split("imports ")[1] for m in messages] == [
        "'jmacat.controller'; infrastructure/ must not depend on controller/",
        "'jmacat.controller.cli'; infrastructure/ must not depend on controller/",
    ]


def test_the_guard_catches_a_plain_outward_import_from_infrastructure() -> None:
    (message,) = scan(
        "import jmacat.controller.cli\n", module="jmacat.infrastructure.leak"
    )
    assert "jmacat.controller.cli" in message


def test_the_guard_catches_a_bare_parent_relative_outward_leak() -> None:
    """`from .. import controller` inside jmacat.infrastructure.leak."""
    (message,) = scan("from .. import controller\n", module="jmacat.infrastructure.leak")
    assert "jmacat.controller" in message


def test_the_guard_catches_a_grandparent_relative_outward_leak() -> None:
    """`from ...controller import cli` inside a nested infrastructure package."""
    messages = scan(
        "from ...controller import cli\n", module="jmacat.infrastructure.codec.leak"
    )
    assert messages and all("jmacat.controller" in m for m in messages)


def test_the_guard_allows_the_composition_root_wiring_an_adapter() -> None:
    """The legitimate shape Dev-H's CLI needs; it must stay green."""
    wiring = textwrap.dedent("""
        from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
        from jmacat.usecase.ports import EventWriter

        def build() -> EventWriter[object]:
            return ParquetEventWriter()
    """)
    assert scan(wiring, module="jmacat.controller.cli") == []


def test_no_module_breaks_the_dependency_rule() -> None:
    found: list[str] = []
    for path, module in source_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = module.rsplit(".", 1)[0] if path.name != "__init__.py" else module
        found.extend(violations(module, imported_modules(tree, package=package)))
    assert not found, "dependency rule violated:\n" + "\n".join(found)
