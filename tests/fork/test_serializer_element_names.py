"""docx4j fork: `SerializerConfig(element_names=...)`.

The other half of `ParserConfig(wildcard_class=...)` (docx4j-python CR-012
Phase A). An object written without a field's name to say what it is called
-- one held by a wildcard, or the root -- is written under its class's own
qualified name, and for a class generated from a named complex type that is
the type's name: an ``mc:Choice`` holding a ``CT_SdtRun`` would be written
``<w:CT_SdtRun>``, where the document said ``<w:sdt>``. JAXB writes such an
object under its ``@XmlRootElement`` name. The table gives a class that name.

A field's own name always wins: the table names only what nothing else does.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from lxml import etree

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig
from docx4j_xsdata.formats.dataclass.serializers.tree import TreeSerializer

NS = "urn:fork:element-names"
ITEM = f"{{{NS}}}item"


@dataclass
class RowItem:
    """A class generated from a complex type: no element name of its own."""

    class Meta:
        name = "CT_RowItem"

    cell: list[str] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )


@dataclass
class Branch:
    class Meta:
        name = "branch"
        namespace = NS

    any_element: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##any"}
    )


@dataclass
class Row:
    class Meta:
        name = "row"
        namespace = NS

    item: list[RowItem] = field(default_factory=list, metadata={"type": "Element"})
    branch: list[Branch] = field(default_factory=list, metadata={"type": "Element"})


def row() -> Row:
    return Row(
        item=[RowItem(cell=["a"])], branch=[Branch(any_element=[RowItem(cell=["b"])])]
    )


def render(obj: Any, **kwargs: Any) -> str:
    config = SerializerConfig(xml_declaration=False, **kwargs)
    return XmlSerializer(config=config).render(obj, ns_map={"x": NS})


def test_the_table_is_empty_by_default() -> None:
    assert SerializerConfig().element_names is None


def test_without_the_table_a_wildcard_writes_the_type_name() -> None:
    assert "<x:CT_RowItem>" in render(row())


def test_with_the_table_a_wildcard_writes_the_element_name() -> None:
    xml = render(row(), element_names={RowItem: ITEM})
    assert xml == (
        '<x:row xmlns:x="urn:fork:element-names">'
        "<x:item><x:cell>a</x:cell></x:item>"
        "<x:branch><x:item><x:cell>b</x:cell></x:item></x:branch>"
        "</x:row>"
    )
    assert "xsi:type" not in xml


def test_a_fields_name_wins_over_the_table() -> None:
    xml = render(row(), element_names={RowItem: f"{{{NS}}}other"})
    assert "<x:item><x:cell>a</x:cell></x:item>" in xml
    assert "<x:other><x:cell>b</x:cell></x:other>" in xml


def test_the_root_takes_the_tables_name() -> None:
    assert render(RowItem(cell=["r"]), element_names={RowItem: ITEM}) == (
        '<x:item xmlns:x="urn:fork:element-names"><x:cell>r</x:cell></x:item>'
    )


def test_the_tree_serializer_agrees() -> None:
    config = SerializerConfig(element_names={RowItem: ITEM})
    tree = TreeSerializer(config=config).render(row(), ns_map={"x": NS})
    xml = etree.tostring(tree.getroot(), encoding="unicode")
    assert xml == render(row(), element_names={RowItem: ITEM})


@pytest.mark.parametrize("table", [None, {}], ids=["none", "empty"])
def test_a_class_not_in_the_table_keeps_its_own_name(table: Any) -> None:
    assert "<x:CT_RowItem>" in render(row(), element_names=table)


def test_written_and_read_back_through_the_wildcard_class_hook() -> None:
    xml = render(row(), element_names={RowItem: ITEM})
    context = XmlContext()

    def wildcard_class(qname: str, ancestors: tuple[type, ...]) -> type | None:
        return RowItem if Branch in ancestors[:1] else None

    config = ParserConfig(
        wildcard_class=wildcard_class, wildcard_class_for=frozenset({ITEM})
    )
    assert XmlParser(context=context, config=config).from_string(xml, Row) == row()
