"""docx4j fork: the writer's namespace bookkeeping, once per document.

CR-001 section 3.2, the first item. Upstream copies the prefix map for every
element and then compares it entry by entry against the parent's to decide what
to declare: on a 130-prefix map and a 24,758-element part that is 3.2 M dict
lookups and 24,758 dict copies, and the answer is always "nothing". The fork
shares the map between frames copy-on-write, indexes its URIs in a set, and
declares only when something actually put a prefix in it.

What must not change is *which* prefixes are declared where, and in what order.
:class:`UpstreamEventWriter` below is upstream v26.2's namespace bookkeeping,
copied method for method, and the documents in :data:`DOCUMENTS` are rendered
through both and compared byte for byte.
"""

from dataclasses import dataclass, field
from typing import Any
from xml.etree.ElementTree import QName

import pytest

from docx4j_xsdata.formats.converter import converter
from docx4j_xsdata.formats.dataclass.models.generics import AnyElement, DerivedElement
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import (
    BOOL_NUMERIC,
    SerializerConfig,
)
from docx4j_xsdata.formats.dataclass.serializers.mixins import XSI_NIL
from docx4j_xsdata.formats.dataclass.serializers.tree import TreeSerializer
from docx4j_xsdata.formats.dataclass.serializers.writers import (
    LxmlEventWriter,
    XmlEventWriter,
)
from docx4j_xsdata.utils.constants import EMPTY_MAP
from docx4j_xsdata.utils.namespaces import generate_prefix, prefix_exists, split_qname

NS_A = "urn:fork:a"
NS_B = "urn:fork:b"
#: Never in a prefix map the tests pass: the writer has to invent a prefix.
NS_C = "urn:fork:c"


# ---------------------------------------------------------------------------
# the models
# ---------------------------------------------------------------------------


@dataclass
class Leaf:
    """A child in a second namespace."""

    class Meta:
        name = "leaf"
        namespace = NS_B

    value: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Root:
    """Two namespaces, a wildcard and a QName attribute."""

    class Meta:
        name = "root"
        namespace = NS_A

    ref: QName | None = field(default=None, metadata={"type": "Attribute"})
    leaf: list[Leaf] = field(
        default_factory=list,
        metadata={"type": "Element", "namespace": NS_B},
    )
    content: list[object] = field(
        default_factory=list,
        metadata={"type": "Wildcard", "namespace": "##any"},
    )


@dataclass
class Unqualified:
    """A child with no namespace of its own."""

    class Meta:
        name = "root"
        namespace = NS_A

    bare: str | None = field(default=None, metadata={"type": "Element", "name": "bare"})


@dataclass
class Nillable:
    """A nillable child, for the `xsi:nil` path through `flush_start`."""

    class Meta:
        name = "root"
        namespace = NS_A

    maybe: str | None = field(
        default=None,
        metadata={"type": "Element", "namespace": NS_A, "nillable": True},
    )


#: One entry per shape the namespace bookkeeping has a branch for.
DOCUMENTS = {
    "empty": Root(),
    "children": Root(leaf=[Leaf(value="1"), Leaf(value="2")]),
    "qname-known": Root(ref=QName(f"{{{NS_B}}}target")),
    "qname-unseen": Root(ref=QName(f"{{{NS_C}}}target")),
    "wildcard": Root(content=[AnyElement(qname=f"{{{NS_C}}}x", text="hi")]),
    "wildcard-siblings": Root(
        content=[AnyElement(qname=f"{{{NS_C}}}x"), AnyElement(qname=f"{{{NS_C}}}y")]
    ),
    "wildcard-nested": Root(
        content=[
            AnyElement(
                qname=f"{{{NS_C}}}x",
                children=[AnyElement(qname=f"{{{NS_B}}}deep", text="d")],
                tail="t",
            )
        ]
    ),
    "wildcard-deep": Root(
        content=[
            AnyElement(
                qname=f"{{{NS_C}}}x",
                children=[
                    AnyElement(qname=f"{{{NS_B}}}a"),
                    # the namespace its parent brought: nothing new to declare
                    AnyElement(qname=f"{{{NS_C}}}b"),
                    AnyElement(qname=f"{{{NS_B}}}c"),
                ],
            )
        ]
    ),
    "wildcard-attribute": Root(
        content=[AnyElement(qname=f"{{{NS_C}}}x", attributes={f"{{{NS_B}}}k": "v"})]
    ),
    "wildcard-unqualified": Root(content=[AnyElement(qname="plain", text="p")]),
    "derived": Root(content=[DerivedElement(qname=f"{{{NS_C}}}d", value=Leaf("v"))]),
    "mixed": Root(
        leaf=[Leaf(value="1")],
        content=[AnyElement(qname=f"{{{NS_C}}}x")],
        ref=QName(f"{{{NS_C}}}target"),
    ),
    "unqualified": Unqualified(bare="x"),
    "nillable": Nillable(),
}

#: The prefix maps to render each of them under.
PREFIX_MAPS = {
    "covering": {"a": NS_A, "b": NS_B, "unused": "urn:fork:unused"},
    "partial": {"a": NS_A},
    "empty": {},
    "default": {None: NS_A},
}

CASES = [
    pytest.param(doc, ns_map, id=f"{doc_id}-{map_id}")
    for doc_id, doc in DOCUMENTS.items()
    for map_id, ns_map in PREFIX_MAPS.items()
]


# ---------------------------------------------------------------------------
# upstream v26.2's namespace bookkeeping, as the oracle
# ---------------------------------------------------------------------------


class UpstreamEventWriter(LxmlEventWriter):
    """`EventHandler`'s namespace methods exactly as upstream v26.2 has them."""

    def start_tag(self, qname: str) -> None:
        self.flush_start(False)

        self.ns_context.append(self.ns_map.copy())
        self.ns_map = self.ns_context[-1]

        self.pending_tag = split_qname(qname)
        self.add_namespace(self.pending_tag[0])

    def add_namespace(self, uri: str | None) -> None:
        if uri and not prefix_exists(uri, self.ns_map):
            generate_prefix(uri, self.ns_map)

    def end_tag(self, qname: str) -> None:
        self.flush_start(True)
        self.end_element(split_qname(qname), qname)

        if self.tail:
            self.set_characters(self.tail)

        self.tail = None
        self.in_tail = False
        self.ns_context.pop()
        if self.ns_context:
            self.ns_map = self.ns_context[-1]

        for prefix in self.pending_prefixes.pop():
            self.end_prefix_mapping(prefix)

    def flush_start(self, is_nil: bool = True) -> None:
        if not self.pending_tag:
            return

        if not is_nil:
            self.attrs.pop(XSI_NIL, None)

        for name in self.attrs:
            self.add_namespace(name[0])

        self.reset_default_namespace()
        self.start_namespaces()

        self.start_element(self.pending_tag, "", self.attrs)
        self.attrs = {}
        self.in_tail = False
        self.pending_tag = None

    def start_namespaces(self) -> None:
        prefixes: list[str] = []
        self.pending_prefixes.append(prefixes)

        try:
            parent_ns_map = self.ns_context[-2]
        except IndexError:
            parent_ns_map = EMPTY_MAP

        for prefix, uri in self.ns_map.items():
            if parent_ns_map.get(prefix) != uri:
                prefixes.append(prefix)
                self.start_prefix_mapping(prefix, uri)

    def reset_default_namespace(self) -> None:
        if self.pending_tag and not self.pending_tag[0] and None in self.ns_map:
            self.ns_map[None] = ""

    def encode_data(self, data: Any) -> str | None:
        if data is None or isinstance(data, str):
            return data

        if isinstance(data, list) and not data:
            return None

        if self.config.bool_format == BOOL_NUMERIC and (data is True or data is False):
            return "1" if data else "0"

        return converter.serialize(data, ns_map=self.ns_map)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def render(obj, ns_map=None, writer=LxmlEventWriter, config=None) -> str:
    """The body (second line) of a string writer's output for `obj`."""
    serializer = XmlSerializer(writer=writer)
    if config is not None:
        serializer.config = config
    return serializer.render(obj, ns_map).splitlines()[1]


def tree_render(obj, ns_map=None) -> str:
    """The lxml tree writer's output for `obj`, as a string."""
    from lxml import etree

    root = TreeSerializer().render(obj, ns_map).getroot()
    return etree.tostring(root, encoding="unicode")


# ---------------------------------------------------------------------------
# the contract: byte for byte what upstream writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("obj", "ns_map"), CASES)
def test_the_output_is_upstreams_output(obj, ns_map) -> None:
    """Which prefixes are declared where, and in what order, is unchanged."""
    assert render(obj, ns_map) == render(obj, ns_map, writer=UpstreamEventWriter)


@pytest.mark.parametrize(("obj", "ns_map"), CASES)
def test_the_writers_all_produce_the_same_document(obj, ns_map) -> None:
    """`mixins` is shared, so the native, lxml and tree writers must agree."""
    body = render(obj, ns_map)

    assert render(obj, ns_map, writer=XmlEventWriter) == body
    assert tree_render(obj, ns_map) == body


# ---------------------------------------------------------------------------
# and the optimisation is actually engaged
# ---------------------------------------------------------------------------


class CountingWriter(LxmlEventWriter):
    """Counts the prefix-map copies and the prefix mappings emitted."""

    __slots__ = ("copies", "mappings")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.copies = 0
        self.mappings = 0

    def own_ns_map(self) -> None:
        context = self.ns_context
        before = context[-1] if context else None
        super().own_ns_map()
        if context and context[-1] is not before:
            self.copies += 1

    def start_prefix_mapping(self, prefix, uri) -> None:
        self.mappings += 1
        super().start_prefix_mapping(prefix, uri)


def count(obj, ns_map) -> tuple[int, int]:
    """(prefix-map copies, prefix mappings) for one render of `obj`."""
    from io import StringIO

    out = StringIO()
    writer = CountingWriter(config=SerializerConfig(), output=out, ns_map=dict(ns_map))
    writer.write(XmlSerializer().generate(obj))
    return writer.copies, writer.mappings


def test_a_covered_document_never_copies_the_prefix_map() -> None:
    """The whole point: one declaration pass, on the root, and no copies."""
    obj = Root(leaf=[Leaf(value=str(i)) for i in range(50)])

    copies, mappings = count(obj, PREFIX_MAPS["covering"])

    assert copies == 0
    assert mappings == 3  # the three prefixes of the map, on the root


def test_only_the_element_that_brings_a_namespace_copies_the_map() -> None:
    """One copy and one extra mapping per wildcard child, not per element."""
    obj = Root(
        leaf=[Leaf(value=str(i)) for i in range(50)],
        content=[AnyElement(qname=f"{{{NS_C}}}x"), AnyElement(qname=f"{{{NS_C}}}y")],
    )

    copies, mappings = count(obj, PREFIX_MAPS["covering"])

    assert copies == 2
    assert mappings == 5  # three on the root, one on each wildcard child


# ---------------------------------------------------------------------------
# the bytes themselves, for the shapes the corpus does not cover
# ---------------------------------------------------------------------------


def test_a_covered_document_declares_everything_on_the_root() -> None:
    """No child declares anything when the caller's map covers the document."""
    xml = render(Root(leaf=[Leaf(value="1"), Leaf(value="2")]), PREFIX_MAPS["covering"])

    assert xml == (
        '<a:root xmlns:a="urn:fork:a" xmlns:b="urn:fork:b" '
        'xmlns:unused="urn:fork:unused">'
        '<b:leaf value="1"/><b:leaf value="2"/></a:root>'
    )


def test_an_unseen_namespace_is_declared_on_the_element_that_brings_it() -> None:
    """A wildcard child in a namespace the map does not know."""
    obj = Root(content=[AnyElement(qname=f"{{{NS_C}}}x", text="hi")])

    assert render(obj, {"a": NS_A}) == (
        '<a:root xmlns:a="urn:fork:a"><ns1:x xmlns:ns1="urn:fork:c">hi</ns1:x></a:root>'
    )


def test_each_sibling_in_an_unseen_namespace_declares_it_again() -> None:
    """The frame's map is the parent's again once the element has ended.

    This is what the copy-on-write sharing has to get right: the prefix the
    first sibling invented must not still be in the map the second one sees.
    """
    obj = Root(
        content=[AnyElement(qname=f"{{{NS_C}}}x"), AnyElement(qname=f"{{{NS_C}}}y")]
    )

    assert render(obj, {"a": NS_A}).count('xmlns:ns1="urn:fork:c"') == 2


def test_a_qname_value_generates_its_prefix_where_it_is_used() -> None:
    """The converter puts a prefix in the map; the writer has to declare it."""
    assert render(Root(ref=QName(f"{{{NS_C}}}target")), {"a": NS_A}) == (
        '<a:root xmlns:a="urn:fork:a" xmlns:ns1="urn:fork:c" ref="ns1:target"/>'
    )


def test_a_qname_value_in_a_known_namespace_declares_nothing_new() -> None:
    """The map already has a prefix for it, so the element stays clean."""
    obj = Root(ref=QName(f"{{{NS_B}}}target"))

    assert render(obj, {"a": NS_A, "b": NS_B}) == (
        '<a:root xmlns:a="urn:fork:a" xmlns:b="urn:fork:b" ref="b:target"/>'
    )


# ---------------------------------------------------------------------------
# and the caller's map is still the caller's
# ---------------------------------------------------------------------------


def test_the_prefix_map_the_caller_passed_is_left_alone() -> None:
    """The render owns its map; the caller's dict is never mutated."""
    ns_map = {"a": NS_A}
    before = dict(ns_map)

    render(Root(content=[AnyElement(qname=f"{{{NS_C}}}x")]), ns_map)

    assert ns_map == before


def test_a_serializer_renders_twice_the_same_way() -> None:
    """A prefix invented for one render does not leak into the next."""
    obj = Root(content=[AnyElement(qname=f"{{{NS_C}}}x")])
    serializer = XmlSerializer(writer=LxmlEventWriter)

    assert serializer.render(obj, {"a": NS_A}) == serializer.render(obj, {"a": NS_A})
