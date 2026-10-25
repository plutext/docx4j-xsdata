"""docx4j fork: `ParserConfig(exact_types=...)` naming `int`, integers read exactly as written.

docx4j-python CR-021 (Q2, its phase 0). The int converter is Python's `int`,
which accepts surrounding whitespace, underscores (``"1_000"``) and other
scripts' digits (``"٢٤٠"``), so each binds as 240 or 1000 with no warning and
no record, and a save writes the integer. Word refuses a document holding any
of them. With `int` among the exact types, a string converts only if it is
xs:integer's lexical form as written, ``[+-]?[0-9]+`` in ASCII digits. Any
other value is bound as its text and written back as read: silently when
XSD's whitespace rule alone would have converted it, with the usual warning
otherwise. Stage 13's rules for `bool` and `Enum` are unchanged.
"""

import warnings
from dataclasses import dataclass, field
from enum import Enum

import pytest

from docx4j_xsdata.exceptions import ConverterError, ConverterWarning, ParserError
from docx4j_xsdata.formats.converter import converter
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import (
    LxmlEventHandler,
    XmlEventHandler,
)
from docx4j_xsdata.formats.dataclass.parsers.skipped import KEPT_EXACT, KEPT_INVALID
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig

NS = "urn:fork:exact-int"

STAGE_13 = frozenset({bool, Enum})
EXACT = frozenset({bool, Enum, int})


class Level(Enum):
    """An enumeration of integers."""

    ONE = 1
    TWO = 2


@dataclass
class Count:
    """A simple-content element: its text is an xs:integer."""

    class Meta:
        name = "count"
        namespace = NS

    value: int | None = field(default=None)


@dataclass
class Spacing:
    """Integer attributes, elements and text, and their neighbours."""

    class Meta:
        name = "spacing"
        namespace = NS

    before: int | None = field(default=None, metadata={"type": "Attribute"})
    after: int | None = field(default=None, metadata={"type": "Attribute"})
    b: bool | None = field(default=None, metadata={"type": "Attribute"})
    level: Level | None = field(default=None, metadata={"type": "Attribute"})
    x: int | str | None = field(default=None, metadata={"type": "Attribute"})
    either: bool | int | None = field(default=None, metadata={"type": "Attribute"})
    widths: list[int] = field(
        default_factory=list, metadata={"type": "Attribute", "tokens": True}
    )
    line: int | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    count: Count | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    anything: object | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )


def spacing(attrs: str = "", body: str = "") -> str:
    return f'<spacing xmlns="{NS}" {attrs}>{body}</spacing>'


def parse(xml: str, handler=None, **config) -> tuple[Spacing, list[str], list]:
    config.setdefault("skipped_report", True)
    parser = XmlParser(
        config=ParserConfig(**config), handler=handler or XmlEventHandler
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        obj = parser.from_string(xml, Spacing)
    warned = [str(w.message) for w in caught if w.category is ConverterWarning]
    kept = [(k.reason, k.text, k.field_name) for k in parser.skipped.kept]
    return obj, warned, kept


def render(obj) -> str:
    config = SerializerConfig(xml_declaration=False)
    return XmlSerializer(config=config).render(obj, ns_map={None: NS})


@pytest.mark.parametrize("exact_types", [frozenset(), STAGE_13])
def test_without_int_pythons_int_as_before(exact_types):
    xml = spacing('before=" 240 " after="1_000" line="٢٤٠"')
    obj, warned, kept = parse(xml, exact_types=exact_types)

    assert obj.before == 240
    assert obj.after == 1000
    assert warned == []
    assert kept == []

    obj, _, _ = parse(spacing(body="<line>٢٤٠</line>"), exact_types=exact_types)
    assert obj.line == 240


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
@pytest.mark.parametrize(
    ("text", "expected"),
    [("240", 240), ("+240", 240), ("0240", 240), ("-0", 0), ("-15", -15)],
)
def test_the_lexical_form_converts_as_before(handler, text, expected):
    obj, warned, kept = parse(
        spacing(f'before="{text}"'), handler=handler, exact_types=EXACT
    )

    assert obj.before == expected
    assert type(obj.before) is int
    assert warned == []
    assert kept == []


def test_a_large_integer_converts():
    text = "123456789012345678901234567890"
    obj, _, kept = parse(spacing(f'before="{text}"'), exact_types=EXACT)

    assert obj.before == int(text)
    assert kept == []


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
# An attribute value has no tab or newline left: XML normalises them to spaces.
@pytest.mark.parametrize("text", [" 240", "240 ", "  -240  "])
def test_whitespace_alone_is_kept_on_purpose(handler, text):
    obj, warned, kept = parse(
        spacing(f'before="{text}"'), handler=handler, exact_types=EXACT
    )

    assert obj.before == text
    assert warned == []
    assert kept == [(KEPT_EXACT, text, "before")]


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
@pytest.mark.parametrize(
    "text",
    [
        "1_000",
        " 1_000 ",
        "٢٤٠",  # Arabic-Indic digits
        "２４０",  # fullwidth digits
        " 240",  # a no-break space isn't XSD whitespace
        "+-240",
    ],
)
def test_a_form_no_xsd_rule_converts_is_invalid(handler, text):
    obj, warned, kept = parse(
        spacing(f'before="{text}"'), handler=handler, exact_types=EXACT
    )

    assert obj.before == text
    assert len(warned) == 1
    assert "Spacing.before" in warned[0]
    assert kept == [(KEPT_INVALID, text, "before")]


@pytest.mark.parametrize("exact_types", [frozenset(), EXACT])
@pytest.mark.parametrize("text", ["240.5", ""])
def test_a_decimal_and_the_empty_string_warn_as_before(exact_types, text):
    obj, warned, kept = parse(spacing(f'before="{text}"'), exact_types=exact_types)

    assert obj.before == text
    assert len(warned) == 1
    assert kept == [(KEPT_INVALID, text, "before")]


def test_a_kept_value_is_written_back_as_read():
    obj, _, _ = parse(spacing('before=" 240" after="1_000"'), exact_types=EXACT)

    out = render(obj)
    assert 'before=" 240"' in out
    assert 'after="1_000"' in out


def test_strict_parsing_raises_for_both():
    xml = spacing('before=" 240"')
    with pytest.raises(ParserError, match="not exactly a lexical form"):
        parse(xml, exact_types=EXACT, fail_on_converter_warnings=True)

    with pytest.raises(ParserError, match="Failed to convert value"):
        parse(
            spacing('before="1_000"'),
            exact_types=EXACT,
            fail_on_converter_warnings=True,
        )

    obj, _, _ = parse(xml, fail_on_converter_warnings=True)
    assert obj.before == 240


def test_element_text_and_simple_content():
    body = "<line>\t240\n</line><count> 7</count>"
    obj, warned, kept = parse(spacing(body=body), exact_types=EXACT)

    assert obj.line == "\t240\n"
    assert obj.count.value == " 7"
    assert warned == []
    assert [reason for reason, _, _ in kept] == [KEPT_EXACT, KEPT_EXACT]
    out = render(obj)
    assert "<line>\t240\n</line>" in out
    assert "<count> 7</count>" in out


def test_a_value_typed_by_xsi_type():
    xsi = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    xs = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'
    body = f'<anything {xsi} {xs} xsi:type="xs:int"> 240</anything>'

    off, _, _ = parse(spacing(body=body))
    on, warned, _ = parse(spacing(body=body), exact_types=EXACT)

    assert off.anything == 240
    assert on.anything == " 240"
    assert warned == []


def test_a_list_is_split_as_xsd_says_and_each_token_is_exact():
    obj, warned, kept = parse(spacing('widths=" 1  -2 "'), exact_types=EXACT)

    assert obj.widths == [1, -2]
    assert warned == []
    assert kept == []

    obj, warned, kept = parse(spacing('widths="1 2_0"'), exact_types=EXACT)
    assert obj.widths == "1 2_0"
    assert len(warned) == 1
    assert kept == [(KEPT_INVALID, "1 2_0", "widths")]


def test_in_a_union_with_str_the_string_member_takes_what_int_refuses():
    obj, warned, kept = parse(spacing('x=" 240"'), exact_types=EXACT)

    assert obj.x == " 240"  # a str member: nothing is kept or recorded
    assert warned == []
    assert kept == []

    assert parse(spacing('x="1_000"'), exact_types=EXACT)[0].x == "1_000"
    assert parse(spacing('x="240"'), exact_types=EXACT)[0].x == 240
    assert parse(spacing('x=" 240"'))[0].x == 240


def test_in_a_union_without_str_a_value_no_member_takes_is_kept():
    obj, warned, kept = parse(spacing('either=" 1"'), exact_types=EXACT)

    assert obj.either == " 1"
    assert warned == []
    assert kept == [(KEPT_EXACT, " 1", "either")]

    obj, warned, kept = parse(spacing('either="1_000"'), exact_types=EXACT)
    assert obj.either == "1_000"
    assert len(warned) == 1
    assert kept == [(KEPT_INVALID, "1_000", "either")]

    assert parse(spacing('either="1"'), exact_types=EXACT)[0].either == 1
    assert parse(spacing('either="true"'), exact_types=EXACT)[0].either is True
    assert parse(spacing('either=" 1"'), exact_types=STAGE_13)[0].either == 1


@pytest.mark.parametrize("text", [" 2", "0_2"])
def test_an_enumeration_of_integers_matches_as_before(text):
    # Its members are the `Enum` rule's, which matches other values as before.
    obj, warned, kept = parse(spacing(f'level="{text}"'), exact_types=EXACT)

    assert obj.level is Level.TWO
    assert warned == []
    assert kept == []


def test_only_the_types_asked_for():
    xml = spacing('before=" 240" b=" false"')

    obj, _, _ = parse(xml, exact_types=frozenset({int}))
    assert obj.before == " 240"
    assert obj.b is False

    obj, _, _ = parse(xml, exact_types=STAGE_13)
    assert obj.before == 240
    assert obj.b == " false"


def test_one_var_under_both_modes_in_one_process():
    xml = spacing('before=" 240"')

    assert parse(xml)[0].before == 240
    assert parse(xml, exact_types=EXACT)[0].before == " 240"
    assert parse(xml)[0].before == 240
    assert parse(xml, exact_types=STAGE_13)[0].before == 240
    assert parse(xml, exact_types=EXACT)[0].before == " 240"


def test_the_converter():
    exact = frozenset({int})

    assert converter.deserialize("-07", [int], exact_types=exact) == -7
    assert converter.deserialize(5, [int], exact_types=exact) == 5
    assert converter.deserialize(" 5", [int]) == 5
    with pytest.raises(ConverterError):
        converter.deserialize(" 5", [int], exact_types=exact)
    with pytest.raises(ConverterError):
        converter.deserialize("1_000", [int], exact_types=exact)
