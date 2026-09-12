"""docx4j fork: ParserConfig(skipped_report=True).

Lenient parsing drops unknown elements and attributes silently. With the
report on, the parser collects them and logs a warning for each.
"""

import logging
from dataclasses import dataclass, field

import pytest

from docx4j_xsdata.exceptions import ParserError
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import (
    LxmlEventHandler,
    XmlEventHandler,
)
from docx4j_xsdata.formats.dataclass.parsers.skipped import (
    SkippedNode,
    SkippedReport,
)

NS = "urn:fork"


@dataclass
class Child:
    """A known child element."""

    class Meta:
        name = "child"
        namespace = NS

    value: str | None = field(
        default=None, metadata={"type": "Attribute", "name": "value"}
    )


@dataclass
class Root:
    """The document root."""

    class Meta:
        name = "root"
        namespace = NS

    child: Child | None = field(
        default=None,
        metadata={"type": "Element", "name": "child", "namespace": NS},
    )


XML = f"""<?xml version="1.0"?>
<root xmlns="{NS}" ghost="yes">
  <child value="a" phantom="no"/>
  <unknown><deeper/></unknown>
</root>
"""

LENIENT = {"fail_on_unknown_properties": False, "fail_on_unknown_attributes": False}


def parse(handler=XmlEventHandler, source=XML, **kwargs) -> XmlParser:
    """Parse the sample document and return the parser."""
    parser = XmlParser(config=ParserConfig(**kwargs), handler=handler)
    parser.from_string(source, Root)
    return parser


def test_disabled_by_default() -> None:
    parser = parse(**LENIENT)

    assert parser.skipped is None
    assert parser.config.skipped is None
    assert not hasattr(parser.config, "items")


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
def test_elements_and_attributes_are_collected(handler) -> None:
    parser = parse(handler=handler, skipped_report=True, **LENIENT)

    # An element is recorded when it starts, an attribute when the
    # element that carries it ends, so <child> comes first.
    assert list(parser.skipped) == [
        SkippedNode(
            kind="attribute",
            qname="phantom",
            parent_qname=f"{{{NS}}}child",
            parent_class="Child",
            path=f"{{{NS}}}root/{{{NS}}}child/@phantom",
        ),
        SkippedNode(
            kind="element",
            qname=f"{{{NS}}}unknown",
            parent_qname=f"{{{NS}}}root",
            parent_class="Root",
            path=f"{{{NS}}}root/{{{NS}}}unknown",
        ),
        SkippedNode(
            kind="attribute",
            qname="ghost",
            parent_qname=f"{{{NS}}}root",
            parent_class="Root",
            path=f"{{{NS}}}root/@ghost",
        ),
    ]
    assert len(parser.skipped) == 3
    assert parser.skipped[0].line is None


def test_nested_unknown_elements_are_reported_once() -> None:
    parser = parse(skipped_report=True, **LENIENT)
    elements = [x for x in parser.skipped if x.kind == "element"]

    assert [x.qname for x in elements] == [f"{{{NS}}}unknown"]


def test_a_warning_is_logged_per_item(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="docx4j_xsdata.logger"):
        parser = parse(skipped_report=True, **LENIENT)

    assert len(caplog.records) == len(parser.skipped)
    assert caplog.messages == [
        f"Skipped unknown attribute phantom in {{{NS}}}child",
        f"Skipped unknown element {{{NS}}}unknown in {{{NS}}}root",
        f"Skipped unknown attribute ghost in {{{NS}}}root",
    ]


def test_logging_can_be_turned_off(caplog) -> None:
    report = SkippedReport(log=False)

    with caplog.at_level(logging.WARNING, logger="docx4j_xsdata.logger"):
        parser = parse(skipped_report=report, **LENIENT)

    assert parser.skipped is report
    assert len(report) == 3
    assert caplog.records == []


def test_nothing_is_collected_when_strict_raises() -> None:
    source = f'<root xmlns="{NS}"><unknown/></root>'
    config = ParserConfig(skipped_report=True, fail_on_unknown_properties=True)
    parser = XmlParser(config=config, handler=XmlEventHandler)

    with pytest.raises(ParserError, match="Unknown property"):
        parser.from_string(source, Root)

    assert list(parser.skipped) == []


def test_nothing_is_collected_when_strict_attributes_raise() -> None:
    source = f'<root xmlns="{NS}" ghost="yes"><child/></root>'
    config = ParserConfig(
        skipped_report=True,
        fail_on_unknown_properties=False,
        fail_on_unknown_attributes=True,
    )
    parser = XmlParser(config=config, handler=XmlEventHandler)

    with pytest.raises(ParserError, match="Unknown attribute"):
        parser.from_string(source, Root)

    assert list(parser.skipped) == []


def test_the_report_is_cleared_per_parse() -> None:
    parser = parse(skipped_report=True, **LENIENT)
    assert len(parser.skipped) == 3

    parser.from_string(XML, Root)
    assert len(parser.skipped) == 3

    parser.from_string(f'<root xmlns="{NS}"><child/></root>', Root)
    assert list(parser.skipped) == []
    assert parser.skipped.path == []


def test_xsi_attributes_are_not_reported() -> None:
    source = (
        f'<root xmlns="{NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:schemaLocation="urn:fork fork.xsd"><child/></root>'
    )
    parser = parse(source=source, skipped_report=True, **LENIENT)

    assert list(parser.skipped) == []


def test_the_document_still_parses() -> None:
    config = ParserConfig(skipped_report=True, **LENIENT)
    parser = XmlParser(config=config, handler=XmlEventHandler)

    assert parser.from_string(XML, Root) == Root(child=Child(value="a"))
