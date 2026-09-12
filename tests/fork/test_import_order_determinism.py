"""docx4j fork: the import order manifest is the same on every run.

`<DeferredImports>` appends an import order manifest to the output root
package. Any order in which no module is entered from another module's
top imports while it is still running its own is correct, so the walk
that produces one is free to pick -- and it used to pick by iterating a
`set` of module names, whose order depends on the process's string hash
seed. The manifest is a file that gets committed and diffed, so "any
correct order" has to become "the same correct order every time".
"""

import random

from docx4j_xsdata.formats.dataclass.generator import DataclassGenerator
from docx4j_xsdata.utils.graphs import strongly_connected_components
from tests.fork.test_deferred_imports import OTHER, SCHEMA

DEFERRED = "    <DeferredImports>true</DeferredImports>"

# The shape a per namespace layout of ECMA-376 has: the top imports are
# acyclic, the bottom imports close the cycles, so the whole graph has the
# two components {a, b, c} and {d, e, f} plus the singletons.
EAGER = {
    "pkg.a": set(),
    "pkg.b": {"pkg.a"},
    "pkg.c": {"pkg.b"},
    "pkg.d": set(),
    "pkg.e": {"pkg.d"},
    "pkg.f": {"pkg.d", "pkg.e"},
    "pkg.g": set(),
    "pkg.h": {"pkg.c", "pkg.g"},
}
DEFERRED_DEPS = {
    "pkg.a": {"pkg.c"},
    "pkg.d": {"pkg.f"},
    "pkg.g": {"pkg.h"},
}


def shuffled(mapping: dict, seed: int) -> dict:
    """Return the same mapping with its keys in another order."""
    keys = list(mapping)
    random.Random(seed).shuffle(keys)
    return {key: mapping[key] for key in keys}


def test_the_component_walk_visits_vertices_in_order() -> None:
    graph = {
        module: sorted(deps | DEFERRED_DEPS.get(module, set()))
        for module, deps in EAGER.items()
    }

    first = list(strongly_connected_components(graph))
    for seed in range(8):
        assert list(strongly_connected_components(shuffled(graph, seed))) == first

    # It is still a correct answer: every cycle is one component.
    assert {"pkg.a", "pkg.b", "pkg.c"} in first
    assert {"pkg.d", "pkg.e", "pkg.f"} in first


def test_the_manifest_is_the_same_whatever_the_dict_order() -> None:
    render = DataclassGenerator.render_import_order
    first = render(EAGER, DEFERRED_DEPS)

    assert "import pkg.a  # noqa: F401" in first
    for seed in range(8):
        assert render(shuffled(EAGER, seed), shuffled(DEFERRED_DEPS, seed)) == first


def test_the_manifest_is_still_a_dependency_order() -> None:
    lines = DataclassGenerator.render_import_order(EAGER, DEFERRED_DEPS).splitlines()
    order = [line.split()[1] for line in lines if line.startswith("import ")]

    assert sorted(order) == sorted(EAGER)
    # Every top import is already imported by the time its module is reached,
    # which is the one property the manifest has to have.
    for module, deps in EAGER.items():
        for dep in deps:
            assert order.index(dep) < order.index(module)


def test_two_generations_of_one_schema_are_byte_identical(gen) -> None:
    kwargs = {
        "options": DEFERRED,
        "structure": "namespaces",
        "files": {"other.xsd": OTHER},
    }
    one = gen(SCHEMA, **kwargs)
    two = gen(SCHEMA, **kwargs)

    files_one = sorted(p.relative_to(one.root) for p in one.root.rglob("*.py"))
    files_two = sorted(p.relative_to(two.root) for p in two.root.rglob("*.py"))
    assert [str(p).replace(one.package, "") for p in files_one] == [
        str(p).replace(two.package, "") for p in files_two
    ]
    assert one.source.replace(one.package, "") == two.source.replace(two.package, "")
