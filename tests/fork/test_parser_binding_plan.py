"""docx4j fork: the parser's per-class binding plans, built once.

CR-001 section 3.4, the first item. Upstream rebuilds three answers for every
element of every document, and all three are properties of the class:

* `XmlMeta.find_children` scans the elements mapping, then every compound
  choice, then every wildcard, for the vars a qname may bind to --- 99,068
  calls for one 24,758 element part. `get_children` builds the tuple once per
  qname and keeps it in `children_index`.
* `ParserUtils.parse_var` reaches the converter for an attribute value through
  `parse_value`, `converter.deserialize`, `type_converter` and a `suppress`
  context manager, 30,474 times for that part. The converter belongs to the
  var, so it is resolved once and kept on it, with the converter factory's
  `generation` so that a later `register_converter` invalidates it.
* `NodeParser.start` imports the three node classes it needs on every element,
  to break an import cycle; the cycle is broken once instead.

Every test here carries the upstream v26.2 code it replaces and compares
against it, so that it says "unchanged" rather than "as I expected".
"""

import warnings
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

import pytest

from docx4j_xsdata.exceptions import ConverterError, ConverterWarning, ParserError
from docx4j_xsdata.formats.converter import Converter, converter
from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.models.elements import XmlMeta, XmlVar
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers.lxml import LxmlEventHandler
from docx4j_xsdata.formats.dataclass.parsers.utils import ParserUtils
from docx4j_xsdata.models.datatype import XmlDate
from docx4j_xsdata.models.enums import EventType
from docx4j_xsdata.utils.namespaces import build_qname

NS_A = "urn:fork:parser:a"
NS_B = "urn:fork:parser:b"


# ---------------------------------------------------------------------------
# a multi-namespace class with a wildcard and a substitution group
# ---------------------------------------------------------------------------


class Colour(Enum):
    """An enum attribute type."""

    RED = "red"
    BLUE = "blue"


@dataclass
class Leaf:
    """One of everything the converters have to do."""

    class Meta:
        name = "leaf"
        namespace = NS_A

    value: str | None = field(default=None, metadata={"type": "Attribute"})
    count: int | None = field(default=None, metadata={"type": "Attribute"})
    flag: bool | None = field(default=None, metadata={"type": "Attribute"})
    ratio: Decimal | None = field(default=None, metadata={"type": "Attribute"})
    when: XmlDate | None = field(default=None, metadata={"type": "Attribute"})
    colour: Colour | None = field(default=None, metadata={"type": "Attribute"})
    tokens: list[int] = field(
        default_factory=list, metadata={"type": "Attribute", "tokens": True}
    )
    either: int | str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Other:
    """A child in the other namespace."""

    class Meta:
        name = "other"
        namespace = NS_B

    label: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Root:
    """Elements in two namespaces, a substitution group and a wildcard."""

    class Meta:
        name = "root"
        namespace = NS_A

    leaf: list[Leaf] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS_A}
    )
    other: Other | None = field(
        default=None, metadata={"type": "Element", "namespace": NS_B}
    )
    content: list[object] = field(
        default_factory=list,
        metadata={
            "type": "Elements",
            "choices": (
                {"name": "alpha", "type": str, "namespace": NS_A},
                {"name": "beta", "type": Leaf, "namespace": NS_B},
                {"name": "gamma", "type": Other, "namespace": NS_A},
            ),
        },
    )
    extra: list[object] = field(
        default_factory=list,
        metadata={"type": "Wildcard", "namespace": "##any"},
    )


@dataclass
class Strict:
    """No wildcard: a qname either matches one var or nothing."""

    class Meta:
        name = "strict"
        namespace = NS_A

    leaf: Leaf | None = field(
        default=None, metadata={"type": "Element", "namespace": NS_A}
    )


def q(namespace: str, name: str) -> str:
    """A qualified name."""
    return build_qname(namespace, name)


QNAMES = [
    q(NS_A, "leaf"),
    q(NS_B, "other"),
    q(NS_A, "alpha"),
    q(NS_B, "beta"),
    q(NS_A, "gamma"),
    q(NS_A, "unknown"),
    q(NS_B, "unknown"),
    "local",
    q("urn:fork:parser:c", "third"),
]


# ---------------------------------------------------------------------------
# upstream v26.2's find_children, as the oracle
# ---------------------------------------------------------------------------


def upstream_find_children(meta: XmlMeta, qname: str) -> Iterator[XmlVar]:
    """`XmlMeta.find_children` exactly as upstream v26.2 has it."""
    elements = meta.elements.get(qname)
    if elements:
        yield from elements

    for choice in meta.choices:
        match = choice.find_choice(qname)
        if match:
            yield match

    chd = meta.find_wildcard(qname)
    if chd:
        yield chd


def meta_of(clazz: type) -> XmlMeta:
    """A fresh meta for `clazz`, from a fresh context."""
    return XmlContext().build(clazz)


@pytest.mark.parametrize("clazz", [Root, Strict, Leaf], ids=lambda c: c.__name__)
@pytest.mark.parametrize("qname", QNAMES, ids=lambda s: s)
def test_the_children_are_upstreams(clazz, qname) -> None:
    """Same vars, in the same order, for every qname including the misses."""
    expected = [var.name for var in upstream_find_children(meta_of(clazz), qname)]

    meta = meta_of(clazz)
    assert [var.name for var in meta.get_children(qname)] == expected
    assert [var.name for var in meta.find_children(qname)] == expected


def test_a_qname_that_matches_two_vars() -> None:
    """The element and the wildcard that would also take it, in that order."""
    meta = meta_of(Root)
    names = [var.name for var in meta.get_children(q(NS_A, "leaf"))]

    assert names == ["leaf", "extra"]


def test_the_children_are_built_once_per_qname() -> None:
    """The second caller gets the first caller's tuple."""
    meta = meta_of(Root)
    assert meta.children_index == {}

    first = meta.get_children(q(NS_A, "leaf"))
    assert meta.get_children(q(NS_A, "leaf")) is first
    assert meta.children_index[q(NS_A, "leaf")] is first

    miss = meta.get_children(q(NS_A, "nothing-here"))
    assert meta.get_children(q(NS_A, "nothing-here")) is miss


def test_find_children_is_still_an_iterator() -> None:
    """Upstream's callers do `next(meta.find_children(qname), None)`."""
    meta = meta_of(Root)

    assert next(meta.find_children(q(NS_A, "leaf"))).name == "leaf"
    assert next(meta.find_children(q(NS_A, "leaf"))).name == "leaf"
    assert next(meta.find_children(q(NS_A, "leaf")), None) is not None
    assert next(meta_of(Strict).find_children("nothing"), None) is None


# ---------------------------------------------------------------------------
# upstream v26.2's parse_var, as the oracle
# ---------------------------------------------------------------------------


def upstream_parse_var(
    meta: XmlMeta,
    var: XmlVar,
    config: ParserConfig,
    value: Any,
    ns_map: dict | None = None,
    default: Any = None,
    types: Sequence[type] | None = None,
    tokens_factory: Callable | None = None,
    format: str | None = None,
) -> Any:
    """`ParserUtils.parse_var` exactly as upstream v26.2 has it."""
    try:
        value = ParserUtils.parse_value(
            value=value,
            types=types or var.types,
            default=default or var.default,
            ns_map=ns_map,
            tokens_factory=tokens_factory or var.tokens_factory,
            format=format or var.format,
        )
    except ConverterError as ex:
        message = (
            f"Failed to convert value for `{meta.clazz.__qualname__}.{var.name}`\n"
            f"  {ex}"
        )
        if config.fail_on_converter_warnings:
            raise ParserError(message)

        warnings.warn(message, ConverterWarning)

    return value


VALUES = [
    ("value", "text"),
    ("count", "42"),
    ("flag", "true"),
    ("flag", "1"),
    ("ratio", "1.25"),
    ("when", "2026-09-19"),
    ("colour", "red"),
    ("tokens", "1 2 3"),
    ("either", "7"),
    ("either", "seven"),
    ("value", ""),
    ("count", None),
    ("tokens", None),
]


def var_of(meta: XmlMeta, name: str) -> XmlVar:
    """The attribute var called `name`."""
    return next(var for var in meta.get_attribute_vars() if var.name == name)


@pytest.mark.parametrize(("name", "raw"), VALUES, ids=lambda v: repr(v))
def test_the_attribute_value_is_upstreams(name, raw) -> None:
    """The converted value, from a var that has never been used before."""
    config = ParserConfig()

    oracle_meta = meta_of(Leaf)
    expected = upstream_parse_var(
        oracle_meta, var_of(oracle_meta, name), config, raw, ns_map={}
    )

    meta = meta_of(Leaf)
    var = var_of(meta, name)
    assert var.converter_plan is None

    actual = ParserUtils.parse_var(meta, var, config, raw, ns_map={})

    assert actual == expected
    assert type(actual) is type(expected)
    # and again, now that the plan is there
    assert ParserUtils.parse_var(meta, var, config, raw, ns_map={}) == expected


def test_a_bad_value_warns_exactly_as_upstream() -> None:
    """The fast path must not swallow the failure, nor report it twice."""
    config = ParserConfig()

    oracle_meta = meta_of(Leaf)
    with pytest.warns(ConverterWarning) as expected:
        upstream_parse_var(
            oracle_meta, var_of(oracle_meta, "count"), config, "not-a-number"
        )

    meta = meta_of(Leaf)
    with pytest.warns(ConverterWarning) as actual:
        result = ParserUtils.parse_var(
            meta, var_of(meta, "count"), config, "not-a-number"
        )

    assert [str(w.message) for w in actual] == [str(w.message) for w in expected]
    assert result == "not-a-number"


def test_a_bad_value_raises_when_the_config_says_so() -> None:
    """`fail_on_converter_warnings` still fails, from the fast path."""
    meta = meta_of(Leaf)
    config = ParserConfig(fail_on_converter_warnings=True)

    with pytest.raises(ParserError):
        ParserUtils.parse_var(meta, var_of(meta, "count"), config, "not-a-number")


def test_the_overrides_take_upstreams_path() -> None:
    """`types`, `tokens_factory` and `format` overrides bypass the plan."""
    meta = meta_of(Leaf)
    var = var_of(meta, "value")
    config = ParserConfig()

    assert ParserUtils.parse_var(meta, var, config, "42", types=[int]) == 42
    assert var.converter_plan is None

    assert ParserUtils.parse_var(
        meta, var, config, "1 2", tokens_factory=list, types=[int]
    ) == [1, 2]
    assert var.converter_plan is None


class ShoutConverter(Converter):
    """A converter registered after the plan was built."""

    def deserialize(self, value: Any, **kwargs: Any) -> Any:
        """Deserialize loudly."""
        return f"{value}!"

    def serialize(self, value: Any, **kwargs: Any) -> str:
        """Serialize loudly."""
        return str(value)


def test_registering_a_converter_invalidates_the_plan() -> None:
    """The generation the plan carries is what notices."""
    meta = meta_of(Leaf)
    var = var_of(meta, "value")
    config = ParserConfig()

    assert ParserUtils.parse_var(meta, var, config, "hello") == "hello"
    assert var.converter_plan is not None

    original = converter.registry[str]
    converter.register_converter(str, ShoutConverter())
    try:
        assert ParserUtils.parse_var(meta, var, config, "hello") == "hello!"
    finally:
        converter.register_converter(str, original)

    assert ParserUtils.parse_var(meta, var, config, "hello") == "hello"


def test_an_unregistered_type_takes_upstreams_path() -> None:
    """No converter, no plan; the error is upstream's."""

    class Unconvertible:
        """Nothing knows how to build one of these."""

    meta = meta_of(Leaf)
    var = var_of(meta, "value")
    config = ParserConfig()
    object.__setattr__(var, "types", (Unconvertible,))

    with pytest.warns(ConverterWarning):
        assert ParserUtils.parse_var(meta, var, config, "x") == "x"

    assert var.converter_plan is not None
    assert var.converter_plan[1] is None


# ---------------------------------------------------------------------------
# upstream v26.2's start and process_context, as the oracle
# ---------------------------------------------------------------------------


class UpstreamHandler(LxmlEventHandler):
    """`LxmlEventHandler.process_context` exactly as upstream v26.2 has it."""

    def process_context(self, context: Any, ns_map: dict) -> Any:
        """Iterate the context, looking everything up on every event."""
        for event, element in context:
            if event == EventType.START:
                self.parser.start(
                    self.clazz,
                    self.queue,
                    self.objects,
                    element.tag,
                    element.attrib,
                    element.nsmap,
                )
            elif event == EventType.END:
                self.parser.end(
                    self.queue,
                    self.objects,
                    element.tag,
                    element.text,
                    element.tail,
                )
                element.clear()
            elif event == EventType.START_NS:
                prefix, uri = element
                self.parser.register_namespace(ns_map, prefix or None, uri)
            else:
                raise AssertionError(f"Unhandled event: `{event}`.")

        return self.objects[-1][1] if self.objects else None


DOCUMENTS = [
    f'<a:root xmlns:a="{NS_A}"/>',
    f'<a:root xmlns:a="{NS_A}"><a:leaf value="one" count="1" flag="true"/></a:root>',
    (
        f'<a:root xmlns:a="{NS_A}" xmlns:b="{NS_B}">'
        '<a:leaf value="one" ratio="1.25" when="2026-09-19" colour="blue"'
        ' tokens="1 2 3"/>'
        '<a:leaf value="two"/>'
        '<b:other label="l"/>'
        "<a:alpha>text</a:alpha>"
        '<b:beta value="in a choice"/>'
        '<a:gamma label="also a choice"/>'
        "</a:root>"
    ),
    (
        f'<a:root xmlns:a="{NS_A}" xmlns:c="urn:fork:parser:c">'
        "<c:third><c:deeper>x</c:deeper></c:third>"
        "</a:root>"
    ),
    f'<a:strict xmlns:a="{NS_A}"><a:leaf value="only"/></a:strict>',
]


@pytest.mark.parametrize("source", DOCUMENTS, ids=range(len(DOCUMENTS)))
def test_a_parse_is_upstreams(source) -> None:
    """The same object, whichever way the handler and `start` are written."""
    clazz = Strict if ":strict" in source or "a:strict" in source else Root

    expected = XmlParser(context=XmlContext(), handler=UpstreamHandler).from_string(
        source, clazz
    )
    actual = XmlParser(context=XmlContext()).from_string(source, clazz)

    assert actual == expected


def test_the_node_types_are_resolved_once() -> None:
    """`load_nodes` fills the module globals, and is idempotent."""
    from docx4j_xsdata.formats.dataclass.parsers import bases, nodes

    bases.load_nodes()
    assert bases.ElementNode is nodes.ElementNode
    assert bases.SkipNode is nodes.SkipNode
    assert bases.WrapperNode is nodes.WrapperNode

    bases.load_nodes()
    assert bases.ElementNode is nodes.ElementNode
