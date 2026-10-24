"""docx4j fork: `SkippedReport.kept`, the values bound as the text they were read with.

docx4j-python CR-018. Under `ParserConfig(exact_types=...)` a value XSD's
whitespace rule would have converted, but that isn't exactly a lexical form,
is kept on purpose and raises no warning; a value no rule converts is bound
as its text too, with the usual warning. Neither is skipped content, so the
report lists them apart from its items, with the reason, and its length and
iteration are unchanged.
"""

import warnings
from dataclasses import dataclass, field
from enum import Enum

import pytest

from docx4j_xsdata.exceptions import ParserError
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import (
    LxmlEventHandler,
    XmlEventHandler,
)
from docx4j_xsdata.formats.dataclass.parsers.skipped import (
    KEPT_EXACT,
    KEPT_INVALID,
    KeptValue,
)

NS = "urn:fork:kept"

EXACT = frozenset({bool, Enum})


class Color(Enum):
    YELLOW = "yellow"


@dataclass
class OnOff:
    class Meta:
        name = "onOff"
        namespace = NS

    value: bool | None = field(default=None)


@dataclass
class Run:
    class Meta:
        name = "run"
        namespace = NS

    b: bool | None = field(default=None, metadata={"type": "Attribute"})
    color: Color | None = field(default=None, metadata={"type": "Attribute"})
    flag: bool | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    on_off: OnOff | None = field(
        default=None, metadata={"name": "onOff", "type": "Element", "namespace": NS}
    )


@dataclass
class Para:
    class Meta:
        name = "p"
        namespace = NS

    run: list[Run] = field(
        default_factory=list, metadata={"name": "run", "type": "Element"}
    )


def parse(xml: str, handler=None, **config) -> tuple[Para, XmlParser]:
    config.setdefault("skipped_report", True)
    config.setdefault("fail_on_unknown_properties", False)
    parser = XmlParser(
        config=ParserConfig(**config), handler=handler or XmlEventHandler
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        obj = parser.from_string(xml, Para)
    return obj, parser


def para(body: str) -> str:
    return f'<p xmlns="{NS}">{body}</p>'


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
def test_a_value_kept_on_purpose_is_recorded_as_exact(handler):
    obj, parser = parse(
        para('<run b=" false" color="yellow "/>'), handler=handler, exact_types=EXACT
    )

    assert obj.run[0].b == " false"
    assert parser.skipped.kept == [
        KeptValue(
            reason=KEPT_EXACT,
            qname="b",
            text=" false",
            field_name="b",
            parent_class="Run",
            path=f"{{{NS}}}p/{{{NS}}}run/@b",
        ),
        KeptValue(
            reason=KEPT_EXACT,
            qname="color",
            text="yellow ",
            field_name="color",
            parent_class="Run",
            path=f"{{{NS}}}p/{{{NS}}}run/@color",
        ),
    ]
    assert len(parser.skipped) == 0  # nothing was skipped
    assert list(parser.skipped) == []


@pytest.mark.parametrize("exact_types", [frozenset(), EXACT])
def test_a_value_no_rule_converts_is_recorded_as_invalid(exact_types):
    _, parser = parse(para('<run b="off"/>'), exact_types=exact_types)

    assert [(k.reason, k.text, k.field_name) for k in parser.skipped.kept] == [
        (KEPT_INVALID, "off", "b")
    ]


def test_an_invalid_value_still_warns():
    parser = XmlParser(config=ParserConfig(skipped_report=True, exact_types=EXACT))

    with pytest.warns(Warning, match="Failed to convert value"):
        parser.from_string(para('<run b="off"/>'), Para)

    assert parser.skipped.kept[0].reason == KEPT_INVALID


def test_element_text_and_simple_content():
    _, parser = parse(
        para("<run><flag> false</flag><onOff>true\n</onOff></run>"), exact_types=EXACT
    )

    run_path = f"{{{NS}}}p/{{{NS}}}run"
    assert [(k.qname, k.path, k.parent_class) for k in parser.skipped.kept] == [
        (f"{{{NS}}}flag", f"{run_path}/{{{NS}}}flag", "Run"),
        (f"{{{NS}}}onOff", f"{run_path}/{{{NS}}}onOff", "OnOff"),
    ]


def test_kept_values_are_apart_from_skipped_content():
    _, parser = parse(para('<run b=" 1"/><unknown/>'), exact_types=EXACT)

    assert len(parser.skipped) == 1
    assert parser.skipped[0].qname == f"{{{NS}}}unknown"
    assert len(parser.skipped.kept) == 1


def test_cleared_at_the_start_of_every_parse():
    config = ParserConfig(skipped_report=True, exact_types=EXACT)
    parser = XmlParser(config=config)

    parser.from_string(para('<run b=" 0"/>'), Para)
    assert len(parser.skipped.kept) == 1
    parser.from_string(para('<run b="0"/>'), Para)
    assert parser.skipped.kept == []


def test_nothing_recorded_without_a_report_or_when_strict():
    obj, parser = parse(para('<run b=" 0"/>'), skipped_report=False, exact_types=EXACT)
    assert obj.run[0].b == " 0"
    assert parser.skipped is None

    with pytest.raises(ParserError):
        parse(para('<run b=" 0"/>'), exact_types=EXACT, fail_on_converter_warnings=True)


def test_exact_values_record_nothing():
    _, parser = parse(para('<run b="0" color="yellow"/>'), exact_types=EXACT)

    assert parser.skipped.kept == []
