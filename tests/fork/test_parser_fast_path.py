"""docx4j fork: the parser's fast path for a plain dataclass child.

CR-001 section 3.4, the second item. `ElementNode.child` walked every var a
qname might match, and for the one it found `build_node` asked whether the var
is a union, what `xsi:type` says, what `xsi:nil` says and whether a datatype or
a wildcard class should take it, before `build_element_node` fetched the meta
and decided whether the object has to be wrapped as a derived element. For a
child whose qname matches exactly one var, whose var declares a single
dataclass, and whose element carries neither `xsi:type` nor `xsi:nil` --- every
element of a WordprocessingML part --- all of that is a constant of the class
and the qname, so it is worked out once and kept on the meta.

The tests carry upstream v26.2's `ElementNode.child` as the oracle, and check
that the path a document needs is the path it gets: a wildcard, a union, a
primitive, mixed content, `xsi:type` and `xsi:nil` all keep the full path.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from docx4j_xsdata.exceptions import ParserError
from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.parsers import XmlParser, nodes
from docx4j_xsdata.formats.dataclass.parsers.mixins import XmlNode
from docx4j_xsdata.formats.dataclass.parsers.nodes.element import ElementNode

NS = "urn:fork:fastpath"


# ---------------------------------------------------------------------------
# a class per path
# ---------------------------------------------------------------------------


@dataclass
class Base:
    """A plain dataclass child."""

    class Meta:
        name = "base"
        namespace = NS

    value: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Derived(Base):
    """What an `xsi:type` on a `base` element substitutes."""

    class Meta:
        name = "derived"
        namespace = NS

    extra: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Left:
    """One half of a union."""

    class Meta:
        name = "left"
        namespace = NS

    a: int | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Right:
    """The other half."""

    class Meta:
        name = "right"
        namespace = NS

    b: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Plain:
    """No wildcard: the fast path for `base`, the full path for the rest."""

    class Meta:
        name = "plain"
        namespace = NS

    base: list[Base] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )
    single: Base | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    number: int | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    nilly: Base | None = field(
        default=None,
        metadata={"type": "Element", "namespace": NS, "nillable": True},
    )
    union: Left | Right | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )


@dataclass
class Wild:
    """A wildcard beside a typed element: every qname matches two vars."""

    class Meta:
        name = "wild"
        namespace = NS

    base: list[Base] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )
    content: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##any"}
    )


@dataclass
class Mixed:
    """Mixed content, which binds the children as generic elements."""

    class Meta:
        name = "mixed"
        namespace = NS

    content: list[object] = field(
        default_factory=list,
        metadata={"type": "Wildcard", "namespace": "##any", "mixed": True},
    )


XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'

DOCUMENTS = [
    (Plain, f'<plain xmlns="{NS}"/>'),
    (Plain, f'<plain xmlns="{NS}"><base value="one"/><base value="two"/></plain>'),
    (Plain, f'<plain xmlns="{NS}"><single value="s"/></plain>'),
    (Plain, f'<plain xmlns="{NS}"><number>42</number></plain>'),
    (Plain, f'<plain xmlns="{NS}" {XSI}><nilly xsi:nil="true"/></plain>'),
    (Plain, f'<plain xmlns="{NS}"><nilly value="n"/></plain>'),
    (Plain, f'<plain xmlns="{NS}"><union a="1"/></plain>'),
    (Plain, f'<plain xmlns="{NS}"><union b="x"/></plain>'),
    (
        Plain,
        f'<plain xmlns="{NS}" {XSI}><base xsi:type="derived" value="v" extra="e"/>'
        "</plain>",
    ),
    (Wild, f'<wild xmlns="{NS}"><base value="one"/></wild>'),
    (Wild, f'<wild xmlns="{NS}"><other><deeper>x</deeper></other></wild>'),
    (Mixed, f'<mixed xmlns="{NS}">text<base value="one"/>tail</mixed>'),
]


# ---------------------------------------------------------------------------
# upstream v26.2's child, as the oracle
# ---------------------------------------------------------------------------


def upstream_child(
    self: ElementNode, qname: str, attrs: dict, ns_map: dict, position: int
) -> XmlNode:
    """`ElementNode.child` exactly as upstream v26.2 has it."""
    for var in self.meta.find_children(qname):
        unique = 0 if not var.is_element or var.list_element else var.index
        if not unique or unique not in self.assigned:
            node = self.build_node(qname, var, attrs, ns_map, position)

            if node:
                if unique:
                    self.assigned.add(unique)

                return node

    if self.config.fail_on_unknown_properties:
        raise ParserError(f"Unknown property {self.meta.qname}:{qname}")

    return nodes.SkipNode()


@pytest.fixture
def slow_path(monkeypatch) -> list[str]:
    """Record the qnames that reached `build_node`, the path being replaced."""
    calls: list[str] = []
    original = ElementNode.build_node

    def spy(self, qname, var, attrs, ns_map, position) -> Any:
        calls.append(qname)
        return original(self, qname, var, attrs, ns_map, position)

    monkeypatch.setattr(ElementNode, "build_node", spy)
    return calls


def parse(clazz: type, source: str) -> Any:
    """Parse `source` with a context of its own."""
    return XmlParser(context=XmlContext()).from_string(source, clazz)


# ---------------------------------------------------------------------------
# the parsed object is upstream's, every time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("clazz", "source"), DOCUMENTS, ids=range(len(DOCUMENTS)))
def test_the_parsed_object_is_upstreams(clazz, source, monkeypatch) -> None:
    """The fast path and the full path build the same tree."""
    actual = parse(clazz, source)

    monkeypatch.setattr(ElementNode, "child", upstream_child)
    expected = parse(clazz, source)

    assert actual == expected


# ---------------------------------------------------------------------------
# which children take which path
# ---------------------------------------------------------------------------


def test_a_plain_child_takes_the_fast_path(slow_path) -> None:
    """`build_node` is not reached at all."""
    obj = parse(Plain, f'<plain xmlns="{NS}"><base value="one"/><single/></plain>')

    assert obj == Plain(base=[Base(value="one")], single=Base())
    assert slow_path == []


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (f'<plain xmlns="{NS}"><number>42</number></plain>', "a primitive var"),
        (f'<plain xmlns="{NS}"><union a="1"/></plain>', "a union var"),
        (
            f'<plain xmlns="{NS}" {XSI}><base xsi:type="derived"/></plain>',
            "an xsi:type",
        ),
        (
            f'<plain xmlns="{NS}" {XSI}><nilly xsi:nil="true"/></plain>',
            "an xsi:nil",
        ),
    ],
)
def test_these_children_keep_the_full_path(source, reason, slow_path) -> None:
    """Everything the fast path is not allowed to decide."""
    parse(Plain, source)

    assert slow_path, reason


def test_a_wildcard_keeps_the_full_path(slow_path) -> None:
    """Two vars match the qname, so there is no plan for it."""
    parse(Wild, f'<wild xmlns="{NS}"><base value="one"/><other/></wild>')

    assert slow_path == [f"{{{NS}}}base", f"{{{NS}}}other"]


def test_mixed_content_keeps_the_full_path(slow_path) -> None:
    """The only var is the mixed wildcard."""
    parse(Mixed, f'<mixed xmlns="{NS}">text<base value="one"/>tail</mixed>')

    assert slow_path == [f"{{{NS}}}base"]


# ---------------------------------------------------------------------------
# the plan itself
# ---------------------------------------------------------------------------


def node_of(clazz: type) -> ElementNode:
    """A root node for `clazz`, to ask for plans."""
    context = XmlContext()
    parser = XmlParser(context=context)
    return ElementNode(
        meta=context.build(clazz),
        attrs={},
        ns_map={},
        config=parser.config,
        context=context,
        position=0,
    )


@pytest.mark.parametrize(
    ("clazz", "local", "planned"),
    [
        (Plain, "base", True),
        (Plain, "single", True),
        (Plain, "nilly", True),
        (Plain, "number", False),
        (Plain, "union", False),
        (Plain, "unknown", False),
        (Wild, "base", False),
        (Wild, "anything", False),
        (Mixed, "anything", False),
    ],
)
def test_which_qnames_get_a_plan(clazz, local, planned) -> None:
    """A single var, a single dataclass, no union and no wildcard."""
    node = node_of(clazz)
    plan = node.build_child_plan(f"{{{NS}}}{local}")

    assert (plan is not None) is planned
    if plan is not None:
        var, meta = plan
        assert var.clazz is meta.clazz


def test_the_plan_is_built_once_per_qname() -> None:
    """Including the negative answer, which must not be recomputed either."""
    node = node_of(Plain)
    assert node.meta.child_plans == {}

    node.child(f"{{{NS}}}base", {}, {}, 0)
    node.child(f"{{{NS}}}number", {}, {}, 0)

    assert set(node.meta.child_plans) == {f"{{{NS}}}base", f"{{{NS}}}number"}
    assert node.meta.child_plans[f"{{{NS}}}number"] is None


def test_a_second_single_valued_child_is_still_refused() -> None:
    """`assigned` keeps its meaning on the fast path."""
    node = node_of(Plain)
    qname = f"{{{NS}}}single"

    first = node.child(qname, {}, {}, 0)
    assert isinstance(first, ElementNode)

    with pytest.raises(ParserError):
        node.child(qname, {}, {}, 0)


def test_a_repeated_list_child_is_not_refused() -> None:
    """A list var is never marked assigned, on either path."""
    node = node_of(Plain)
    qname = f"{{{NS}}}base"

    assert isinstance(node.child(qname, {}, {}, 0), ElementNode)
    assert isinstance(node.child(qname, {}, {}, 1), ElementNode)
