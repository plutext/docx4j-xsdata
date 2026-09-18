"""docx4j fork: `ParserConfig(on_bind=...)`, the post-bind hook.

CR-001 section 3.4, the third item. A binding layer that has to wire something
per object -- docx4j-python's parent pointers, and docx4j's own `Child`
interface before it -- otherwise walks the finished tree a second time.
xsdata binds bottom up, so at the moment `ElementNode.bind` has built an
object its children exist and are bound and its parent does not exist yet,
which is exactly the moment such a callback wants.

The hook is off by default and changes nothing when it is: these tests pin
that, the order, the count, and which objects it does and does not see.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig

NS = "urn:fork:onbind"
XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'


@dataclass
class Leaf:
    """The bottom of the tree."""

    class Meta:
        name = "leaf"
        namespace = NS

    value: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Branch:
    """A node with children of its own."""

    class Meta:
        name = "branch"
        namespace = NS

    name: str | None = field(default=None, metadata={"type": "Attribute"})
    leaf: list[Leaf] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )


@dataclass
class Tree:
    """The root."""

    class Meta:
        name = "tree"
        namespace = NS

    branch: list[Branch] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )
    nilly: Leaf | None = field(
        default=None,
        metadata={"type": "Element", "namespace": NS, "nillable": True},
    )
    content: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##any"}
    )


DOCUMENT = (
    f'<tree xmlns="{NS}">'
    '<branch name="one"><leaf value="a"/><leaf value="b"/></branch>'
    '<branch name="two"><leaf value="c"/></branch>'
    "</tree>"
)


def parse(source: str, on_bind: Any = None, clazz: type = Tree) -> Any:
    """Parse `source` with a context and a config of their own."""
    config = ParserConfig(on_bind=on_bind, fail_on_unknown_properties=False)
    return XmlParser(context=XmlContext(), config=config).from_string(source, clazz)


# ---------------------------------------------------------------------------
# off by default
# ---------------------------------------------------------------------------


def test_the_hook_is_off_by_default() -> None:
    """Nothing to call, and nothing tries to."""
    assert ParserConfig().on_bind is None

    obj = parse(DOCUMENT)

    assert len(obj.branch) == 2


def test_the_hook_changes_nothing_about_the_tree() -> None:
    """The same object, hook or no hook."""
    seen: list[Any] = []

    assert parse(DOCUMENT) == parse(DOCUMENT, on_bind=seen.append)
    assert seen


# ---------------------------------------------------------------------------
# once per object, bottom up
# ---------------------------------------------------------------------------


def test_the_hook_sees_every_object_once() -> None:
    """Three leaves, two branches, one tree, and no repeats."""
    seen: list[Any] = []
    obj = parse(DOCUMENT, on_bind=seen.append)

    assert len(seen) == 6
    assert len({id(x) for x in seen}) == 6
    assert [type(x).__name__ for x in seen] == [
        "Leaf",
        "Leaf",
        "Branch",
        "Leaf",
        "Branch",
        "Tree",
    ]
    assert seen[-1] is obj


def test_the_hook_sees_an_object_after_its_children() -> None:
    """Bottom up: the children are built, bound and already seen."""
    seen: list[Any] = []

    def record(item: Any) -> None:
        if isinstance(item, Branch):
            # its own children exist, and the hook has already had them
            assert item.leaf
            for leaf in item.leaf:
                assert any(x is leaf for x in seen)
        if isinstance(item, Tree):
            assert len(item.branch) == 2
        seen.append(item)

    obj = parse(DOCUMENT, on_bind=record)

    assert len(obj.branch) == 2


def test_nothing_holds_an_object_yet_when_the_hook_sees_it() -> None:
    """Bottom up means the parent is not built, so nothing can point at it."""
    seen: list[Any] = []

    def record(item: Any) -> None:
        for earlier in seen:
            held = [*getattr(earlier, "leaf", ()), *getattr(earlier, "branch", ())]
            assert all(child is not item for child in held)
        seen.append(item)

    parse(DOCUMENT, on_bind=record)

    assert len(seen) == 6


# ---------------------------------------------------------------------------
# what it does and does not see
# ---------------------------------------------------------------------------


def test_a_nil_element_builds_no_object_and_fires_nothing() -> None:
    """`xsi:nil` binds None, and the hook is for objects."""
    seen: list[Any] = []
    obj = parse(
        f'<tree xmlns="{NS}" {XSI}><nilly xsi:nil="true"/></tree>', on_bind=seen.append
    )

    assert obj.nilly is None
    assert [type(x).__name__ for x in seen] == ["Tree"]


def test_a_typed_object_under_a_wildcard_is_seen() -> None:
    """The wildcard absorbed it, but `ElementNode.bind` still built it."""
    seen: list[Any] = []
    parse(f'<tree xmlns="{NS}"><leaf value="wild"/></tree>', on_bind=seen.append)

    assert [type(x).__name__ for x in seen] == ["Leaf", "Tree"]


def test_unknown_wildcard_content_is_not_an_object() -> None:
    """A generic element is not built by `ElementNode.bind`."""
    seen: list[Any] = []
    parse(
        f'<tree xmlns="{NS}"><stranger><deeper/></stranger></tree>',
        on_bind=seen.append,
    )

    assert [type(x).__name__ for x in seen] == ["Tree"]


def test_the_hook_is_per_config() -> None:
    """Two parsers, two configs, two independent hooks."""
    first: list[Any] = []
    second: list[Any] = []

    parse(DOCUMENT, on_bind=first.append)
    parse(DOCUMENT, on_bind=second.append)

    assert len(first) == len(second) == 6
    assert all(a is not b for a, b in zip(first, second, strict=True))


def test_the_hook_runs_before_the_object_is_handed_up() -> None:
    """A mutation made by the hook is in the tree the caller gets."""

    def rename(item: Any) -> None:
        if isinstance(item, Leaf) and item.value:
            item.value = item.value.upper()

    obj = parse(DOCUMENT, on_bind=rename)

    assert [leaf.value for branch in obj.branch for leaf in branch.leaf] == [
        "A",
        "B",
        "C",
    ]


@pytest.mark.parametrize("source", [DOCUMENT, f'<tree xmlns="{NS}"/>'])
def test_the_hook_sees_the_root_last(source) -> None:
    """Including the degenerate document, where it is all there is."""
    seen: list[Any] = []
    obj = parse(source, on_bind=seen.append)

    assert seen[-1] is obj
