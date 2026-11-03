"""docx4j fork: `ParserConfig(recover=...)`, XML that is not well formed refused or mended.

docx4j-python CR-031 (phase 0). The lxml event handler reads with
``etree.iterparse(recover=True)``, upstream's setting, so a part that is not
well formed is mended with no report: a cut document is read up to the cut,
stray characters and a second root are dropped, the first of a repeated
attribute is kept. The native handler refuses every one of them. With
``recover=False`` the lxml handler refuses them too: the first fatal error
raises `ParserError`, lxml's ``XMLSyntaxError`` as its cause. True, the
default, is upstream's behaviour.
"""

from dataclasses import dataclass, field
from enum import Enum

import pytest
from lxml import etree

from docx4j_xsdata.exceptions import ParserError
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import (
    LxmlEventHandler,
    XmlEventHandler,
)


@dataclass
class A:
    """A root holding a list of `b` and an attribute `x`."""

    class Meta:
        name = "a"

    b: list[str] = field(default_factory=list, metadata={"type": "Element"})
    x: str | None = field(default=None, metadata={"type": "Attribute"})
    n: int | None = field(default=None, metadata={"type": "Attribute"})


# (name, the source, what recovery binds, the start of lxml's message)
MALFORMATIONS = [
    (
        "a cut",
        b"<a><b>one</b><b>two</b><b>thr",
        A(b=["one", "two", "thr"]),
        "Premature end of data in tag b",
    ),
    (
        "a cut inside a start tag",
        b"<a><b>one</b><b",
        A(b=["one", ""]),
        "Couldn't find end of Start Tag b",
    ),
    (
        "an undefined entity",
        b"<a><b>one&nbsp;two</b></a>",
        A(b=["onetwo"]),
        "Entity 'nbsp' not defined",
    ),
    (
        "a tag mismatch",
        b"<a><b>one</a>",
        A(b=["one"]),
        "Opening and ending tag mismatch: b line 1 and a",
    ),
    (
        "the root left open",
        b"<a><b>one</b>",
        A(b=["one"]),
        "Premature end of data in tag a",
    ),
    ("a cut end tag", b"<a><b>one</b></a", A(b=["one"]), "expected '>'"),
    (
        "a stray ampersand",
        b"<a><b>one & two</b></a>",
        A(b=["one  two"]),
        "xmlParseEntityRef: no name",
    ),
    (
        "a stray less-than",
        b"<a><b>one < two</b></a>",
        A(b=["one "]),
        "StartTag: invalid element name",
    ),
    (
        "a repeated attribute",
        b'<a x="1" x="2"><b>one</b></a>',
        A(b=["one"], x="1"),
        "Attribute x redefined",
    ),
    (
        "a control character",
        b"<a><b>one\x01two</b></a>",
        A(b=["onetwo"]),
        "PCDATA invalid Char value 1",
    ),
    (
        "a byte that is not UTF-8",
        b"<a><b>one \xe9 two</b></a>",
        A(b=["one � two"]),
        "Invalid bytes in character encoding",
    ),
    (
        "a second root",
        b"<a><b>one</b></a><c/>",
        A(b=["one"]),
        "Extra content at the end of the document",
    ),
]
IDS = [m[0] for m in MALFORMATIONS]


def parser(**kwargs) -> XmlParser:
    handler = kwargs.pop("handler", LxmlEventHandler)
    config = ParserConfig(
        fail_on_unknown_properties=False, skipped_report=True, **kwargs
    )
    return XmlParser(config=config, handler=handler)


def test_the_default_is_upstreams() -> None:
    assert ParserConfig().recover is True


@pytest.mark.parametrize(
    ("source", "mended"), [(m[1], m[2]) for m in MALFORMATIONS], ids=IDS
)
def test_by_default_the_lxml_handler_mends(source: bytes, mended: A) -> None:
    """The pin: upstream's recovery, and nothing reported."""
    assert parser().from_bytes(source, A) == mended


@pytest.mark.parametrize(
    ("source", "message"), [(m[1], m[3]) for m in MALFORMATIONS], ids=IDS
)
def test_with_recover_false_the_lxml_handler_refuses(
    source: bytes, message: str
) -> None:
    p = parser(recover=False)
    with pytest.raises(ParserError) as info:
        p.from_bytes(source, A)

    assert str(info.value).startswith(message), str(info.value)
    assert ", line 1, column " in str(info.value)
    cause = info.value.__cause__
    assert isinstance(cause, etree.XMLSyntaxError)
    assert info.value.__suppress_context__ is True
    assert cause.lineno == 1
    assert isinstance(cause.position, tuple) and cause.position[0] == 1


def test_a_double_less_than_before_the_root_is_lxmls_error_not_an_empty_result() -> (
    None
):
    """``<<a>``: recovery binds nothing and the parser says "Failed to create"."""
    with pytest.raises(ParserError, match="Failed to create target class `A`") as info:
        parser().from_bytes(b"<<a><b>one</b></a>", A)
    assert info.value.__cause__ is None

    with pytest.raises(ParserError, match="StartTag: invalid element name") as info:
        parser(recover=False).from_bytes(b"<<a><b>one</b></a>", A)
    assert isinstance(info.value.__cause__, etree.XMLSyntaxError)


WELL_FORMED = b'<a x="1" n=" 2"><b>one</b><unknown/><b>two</b><!-- c --></a>'


@pytest.mark.parametrize("handler", [LxmlEventHandler, XmlEventHandler])
def test_a_well_formed_document_parses_identically_under_both(handler: type) -> None:
    """The same object, the same skipped and kept records, either way."""
    on = parser(handler=handler, recover=True, exact_types=frozenset({int}))
    off = parser(handler=handler, recover=False, exact_types=frozenset({int}))

    assert on.from_bytes(WELL_FORMED, A) == off.from_bytes(WELL_FORMED, A)
    assert on.from_bytes(WELL_FORMED, A) == A(b=["one", "two"], x="1", n=" 2")
    assert on.skipped is not None and off.skipped is not None
    assert len(on.skipped) == len(off.skipped) == 1
    assert on.skipped.items == off.skipped.items
    assert len(on.skipped.kept) == len(off.skipped.kept) == 1
    assert on.skipped.kept == off.skipped.kept


def test_a_tree_source_is_unaffected() -> None:
    """A tree is already parsed: the `iterwalk` path takes no `recover`."""
    # a fresh tree each time: the handler clears the elements it has read
    for recover in (False, True):
        tree = etree.fromstring(b"<a><b>one</b><b>thr", etree.XMLParser(recover=True))
        assert parser(recover=recover).parse(tree, A) == A(b=["one", "thr"])


@pytest.mark.parametrize("recover", [True, False])
def test_the_xinclude_path_is_strict_under_both(recover: bool) -> None:
    with pytest.raises(ParserError, match="Premature end of data") as info:
        parser(recover=recover, process_xinclude=True).from_bytes(
            MALFORMATIONS[0][1], A
        )
    assert isinstance(info.value.__cause__, etree.XMLSyntaxError)


@pytest.mark.parametrize("recover", [True, False])
@pytest.mark.parametrize(
    ("source", "message"), [(m[1], m[3]) for m in MALFORMATIONS], ids=IDS
)
def test_the_native_handler_never_recovers(
    source: bytes, message: str, recover: bool
) -> None:
    """The option is lxml's; the native handler refuses either way, its error the cause."""
    with pytest.raises(ParserError) as info:
        parser(handler=XmlEventHandler, recover=recover).from_bytes(source, A)
    assert "line 1, column" in str(info.value)
    assert isinstance(info.value.__cause__, SyntaxError)
    assert not isinstance(info.value.__cause__, etree.XMLSyntaxError)
    assert info.value.__suppress_context__ is True


def test_nothing_is_bound_when_refused() -> None:
    """The objects built before the error are discarded with it."""
    p = parser(recover=False)
    with pytest.raises(ParserError):
        p.from_bytes(b"<a><b>one</b><b>two</b><b>thr", A)
    assert p.skipped is not None and len(p.skipped) == 0
    # and the parser is reusable
    assert p.from_bytes(b"<a><b>one</b></a>", A) == A(b=["one"])


def test_the_default_mends_the_same_as_26_2_4_with_the_other_options() -> None:
    """Recovery with every other fork option set, as docx4j-python reads today."""
    p = parser(
        exact_types=frozenset({bool, Enum, int}),
        lexical_types=frozenset({float, bytes}),
    )
    assert p.from_bytes(MALFORMATIONS[0][1], A) == MALFORMATIONS[0][2]
