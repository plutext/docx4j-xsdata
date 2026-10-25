"""docx4j fork: `ParserConfig(exact_types=...)`, booleans and enumerations read exactly as written.

docx4j-python CR-018. XSD collapses the whitespace of an xs:boolean or an
enumeration value before it is matched, so the converter reads ``" false"``
as False and ``" yellow"`` as the member ``yellow``, and a save writes ``0``
and ``yellow``. Word reads both literally: an ST_OnOff value is off only for
exactly ``false``, ``off`` or ``0``, so a run Word shows bold is saved as one
it shows not bold. With the option, a value that is not exactly one of its
type's lexical forms is bound as the text it was read with and written back
as read: silently when XSD's whitespace rule would have converted it, with
the usual warning otherwise. Everything else is as before.
"""

import warnings
from dataclasses import dataclass, field
from enum import Enum

import pytest

from docx4j_xsdata.exceptions import ConverterWarning, ParserError
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import (
    LxmlEventHandler,
    XmlEventHandler,
)
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig
from docx4j_xsdata.formats.dataclass.serializers.tree import TreeSerializer

NS = "urn:fork:exact"

EXACT = frozenset({bool, Enum})


class Color(Enum):
    """An enumeration of strings, as WordprocessingML's ST_HighlightColor."""

    YELLOW = "yellow"
    DARK_BLUE = "darkBlue"


class Level(Enum):
    """An enumeration of integers."""

    ONE = 1
    TWO = 2


@dataclass
class OnOff:
    """A simple-content element: its text is an xs:boolean."""

    class Meta:
        name = "onOff"
        namespace = NS

    value: bool | None = field(default=None)


@dataclass
class Run:
    """Attributes, elements and text of the two types, and their neighbours."""

    class Meta:
        name = "run"
        namespace = NS

    b: bool | None = field(default=None, metadata={"type": "Attribute"})
    color: Color | None = field(default=None, metadata={"type": "Attribute"})
    level: Level | None = field(default=None, metadata={"type": "Attribute"})
    count: int | None = field(default=None, metadata={"type": "Attribute"})
    either: bool | int | None = field(default=None, metadata={"type": "Attribute"})
    label: bool | str | None = field(default=None, metadata={"type": "Attribute"})
    flags: list[bool] = field(
        default_factory=list, metadata={"type": "Attribute", "tokens": True}
    )
    flag: bool | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    shade: Color | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    on_off: OnOff | None = field(
        default=None, metadata={"name": "onOff", "type": "Element", "namespace": NS}
    )
    anything: object | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )


def run(attrs: str = "", body: str = "") -> str:
    return f'<run xmlns="{NS}" {attrs}>{body}</run>'


def parse(xml: str, handler=None, **config) -> tuple[Run, list[str]]:
    parser = XmlParser(
        config=ParserConfig(**config), handler=handler or XmlEventHandler
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        obj = parser.from_string(xml, Run)
    return obj, [str(w.message) for w in caught if w.category is ConverterWarning]


def render(obj) -> str:
    config = SerializerConfig(xml_declaration=False)
    return XmlSerializer(config=config).render(obj, ns_map={None: NS})


def test_off_by_default_xsds_whitespace_rule():
    obj, warned = parse(run('b=" false" color="yellow "'))

    assert obj.b is False
    assert obj.color is Color.YELLOW
    assert warned == []
    out = render(obj)
    assert 'b="false"' in out
    assert 'color="yellow"' in out


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
# An attribute value has no tab or newline left: XML normalises them to spaces.
@pytest.mark.parametrize("text", [" false", "false ", "  true", "1 "])
def test_with_the_option_a_boolean_not_exactly_written_keeps_its_text(handler, text):
    obj, warned = parse(run(f'b="{text}"'), handler=handler, exact_types=EXACT)

    assert obj.b == text
    assert warned == []


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
@pytest.mark.parametrize("text", [" yellow", "yellow ", " darkBlue "])
def test_with_the_option_an_enumeration_not_exactly_written_keeps_its_text(
    handler, text
):
    obj, warned = parse(run(f'color="{text}"'), handler=handler, exact_types=EXACT)

    assert obj.color == text
    assert warned == []


def test_a_kept_value_is_written_back_as_read():
    obj, _ = parse(run('b=" false" color="yellow "'), exact_types=EXACT)

    out = render(obj)
    assert 'b=" false"' in out
    assert 'color="yellow "' in out


def test_the_exact_spellings_bind_as_before():
    for text, expected in (("true", True), ("false", False), ("1", True), ("0", False)):
        obj, warned = parse(run(f'b="{text}" color="darkBlue"'), exact_types=EXACT)
        assert obj.b is expected
        assert obj.color is Color.DARK_BLUE
        assert warned == []


@pytest.mark.parametrize("exact_types", [frozenset(), EXACT])
def test_a_value_that_is_no_lexical_form_warns_as_before(exact_types):
    obj, warned = parse(run('b="off" color="Yellow"'), exact_types=exact_types)

    assert obj.b == "off"
    assert obj.color == "Yellow"
    assert len(warned) == 2
    assert "Run.b" in warned[0]


def test_strict_parsing_raises_for_a_kept_value():
    with pytest.raises(ParserError, match="not exactly a lexical form"):
        parse(run('b=" false"'), exact_types=EXACT, fail_on_converter_warnings=True)

    obj, _ = parse(run('b=" false"'), fail_on_converter_warnings=True)
    assert obj.b is False


def test_elements_and_text_alike():
    body = "<flag> false</flag><shade>yellow </shade><onOff>true\n</onOff>"
    obj, warned = parse(run(body=body), exact_types=EXACT)

    assert obj.flag == " false"
    assert obj.shade == "yellow "
    assert obj.on_off.value == "true\n"
    assert warned == []
    out = render(obj)
    assert "<flag> false</flag>" in out
    assert "<shade>yellow </shade>" in out
    assert "<onOff>true\n</onOff>" in out


def test_a_value_typed_by_xsi_type():
    xsi = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    xs = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'
    body = f'<anything {xsi} {xs} xsi:type="xs:boolean"> false</anything>'

    off, _ = parse(run(body=body))
    on, warned = parse(run(body=body), exact_types=EXACT)

    assert off.anything is False
    assert on.anything == " false"
    assert warned == []


def test_a_list_is_split_as_xsd_says_and_each_token_is_exact():
    obj, warned = parse(run('flags=" true  0 "'), exact_types=EXACT)

    assert obj.flags == [True, False]
    assert warned == []


def test_in_a_union_only_the_boolean_member_is_exact():
    obj, warned = parse(run('either=" 1" label=" false"'), exact_types=EXACT)

    assert obj.either == 1  # the int member, by its own whitespace rule
    assert obj.label == " false"  # the str member takes it
    assert warned == []

    obj, warned = parse(run('either=" true"'), exact_types=EXACT)
    assert obj.either == " true"  # no member takes it exactly: kept
    assert warned == []

    obj, _ = parse(run('either="true" label="false"'), exact_types=EXACT)
    assert obj.either is True
    assert obj.label is False


def test_only_the_types_asked_for():
    xml = run('b=" false" color=" yellow"')

    obj, _ = parse(xml, exact_types=frozenset({bool}))
    assert obj.b == " false"
    assert obj.color is Color.YELLOW

    obj, _ = parse(xml, exact_types=frozenset({Enum}))
    assert obj.b is False
    assert obj.color == " yellow"


def test_an_enumeration_of_other_values_and_other_types_match_as_before():
    obj, warned = parse(run('level=" 2" count=" 7"'), exact_types=EXACT)

    assert obj.level is Level.TWO
    assert obj.count == 7
    assert warned == []


def test_one_var_under_both_modes_in_one_process():
    xml = run('b=" false" color=" yellow"')

    assert parse(xml)[0].b is False
    assert parse(xml, exact_types=EXACT)[0].b == " false"
    assert parse(xml)[0].b is False
    assert parse(xml, exact_types=EXACT)[0].color == " yellow"
    assert parse(xml)[0].color is Color.YELLOW


def test_the_tree_serializer_writes_the_text():
    obj, _ = parse(run('b=" false"'), exact_types=EXACT)

    tree = TreeSerializer(config=SerializerConfig()).render(obj)
    assert tree.getroot().get("b") == " false"


def test_an_unsupported_type_is_refused():
    # `int` is supported since stage 14 (test_exact_int.py).
    with pytest.raises(ValueError, match="exact_types: not supported for float"):
        ParserConfig(exact_types=frozenset({float}))
