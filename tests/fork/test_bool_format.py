"""docx4j fork: SerializerConfig(bool_format="numeric").

Word writes xsd:boolean as `1`/`0`, xsdata writes `true`/`false`. Both
are valid XML and both parse; the option is about diffing a saved
document against Word's own.
"""

from dataclasses import dataclass, field

import pytest

from docx4j_xsdata.exceptions import SerializerError
from docx4j_xsdata.formats.dataclass.models.generics import AnyElement
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import (
    BOOL_NUMERIC,
    SerializerConfig,
)
from docx4j_xsdata.formats.dataclass.serializers.writers import (
    LxmlEventWriter,
    XmlEventWriter,
)

NS = "urn:fork"


@dataclass
class OnOff:
    """An element with a boolean attribute, in the docx4j:w:b shape."""

    class Meta:
        name = "b"
        namespace = NS

    val: bool | None = field(
        default=None, metadata={"type": "Attribute", "name": "val"}
    )


@dataclass
class Props:
    """A boolean in every position the serializer encodes."""

    class Meta:
        name = "rPr"
        namespace = NS

    bold: OnOff | None = field(
        default=None,
        metadata={"type": "Element", "name": "b", "namespace": NS},
    )
    flag: bool | None = field(
        default=None,
        metadata={"type": "Element", "name": "flag", "namespace": NS},
    )
    flags: list[bool] = field(
        default_factory=list,
        metadata={
            "type": "Element",
            "name": "flags",
            "namespace": NS,
            "tokens": True,
        },
    )
    other: dict = field(
        default_factory=dict, metadata={"type": "Attributes", "namespace": "##other"}
    )
    any_element: object | None = field(
        default=None, metadata={"type": "Wildcard", "namespace": "##any"}
    )


def render(obj, **kwargs) -> str:
    """Serialize without the xml declaration."""
    config = SerializerConfig(xml_declaration=False, **kwargs)
    return XmlSerializer(config=config).render(obj, ns_map={None: NS})


@pytest.mark.parametrize(
    ("source", "expected"),
    [("1", True), ("0", False), ("true", True), ("false", False)],
)
def test_parsing_accepts_all_four_spellings(source, expected) -> None:
    parser = XmlParser()
    obj = parser.from_string(f'<b xmlns="{NS}" val="{source}"/>', OnOff)

    assert obj.val is expected


def test_the_default_is_upstream_behaviour() -> None:
    assert SerializerConfig().bool_format == "words"

    obj = Props(bold=OnOff(val=True), flag=False, flags=[True, False])
    expected = (
        f'<rPr xmlns="{NS}"><b val="true"/>'
        "<flag>false</flag><flags>true false</flags></rPr>"
    )

    assert render(obj) == expected


def test_numeric_attributes_elements_and_tokens() -> None:
    obj = Props(bold=OnOff(val=True), flag=False, flags=[True, False])
    expected = f'<rPr xmlns="{NS}"><b val="1"/><flag>0</flag><flags>1 0</flags></rPr>'

    assert render(obj, bool_format=BOOL_NUMERIC) == expected


@pytest.mark.parametrize("writer", [XmlEventWriter, LxmlEventWriter])
def test_every_writer_agrees(writer) -> None:
    config = SerializerConfig(xml_declaration=False, bool_format=BOOL_NUMERIC)
    serializer = XmlSerializer(config=config, writer=writer)

    result = serializer.render(OnOff(val=False), ns_map={None: NS})

    assert result == f'<b xmlns="{NS}" val="0"/>'


def test_wildcard_attributes_are_encoded_too() -> None:
    obj = Props(other={"{urn:other}flag": True})

    assert 'flag="true"' in render(obj)
    assert 'flag="1"' in render(obj, bool_format=BOOL_NUMERIC)


def test_generic_element_text_is_encoded_too() -> None:
    # The wildcard values never see a field metadata instance, the
    # writer encodes them.
    obj = Props(any_element=AnyElement(qname=f"{{{NS}}}flag", text=True))

    assert render(obj) == f'<rPr xmlns="{NS}"><flag>true</flag></rPr>'
    assert (
        render(obj, bool_format=BOOL_NUMERIC)
        == f'<rPr xmlns="{NS}"><flag>1</flag></rPr>'
    )


def test_round_trip_of_a_word_style_document() -> None:
    source = f'<b xmlns="{NS}" val="1"/>'
    obj = XmlParser().from_string(source, OnOff)

    assert render(obj, bool_format=BOOL_NUMERIC) == source
    assert render(obj) == f'<b xmlns="{NS}" val="true"/>'


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(SerializerError, match="Unknown bool format `yes`"):
        SerializerConfig(bool_format="yes")
