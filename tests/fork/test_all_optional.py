"""docx4j fork: <Output><AllOptional>true</AllOptional></Output>."""

from docx4j_xsdata.codegen.models import Restrictions
from docx4j_xsdata.formats.dataclass.filters import Filters
from docx4j_xsdata.models.config import GeneratorConfig
from docx4j_xsdata.models.enums import DataType, Tag
from docx4j_xsdata.utils.testing import AttrFactory, AttrTypeFactory, ClassFactory

SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns="urn:fork" targetNamespace="urn:fork"
           elementFormDefault="qualified">
  <xs:complexType name="Grid">
    <xs:attribute name="width" type="xs:int" use="required"/>
  </xs:complexType>
  <xs:complexType name="Row">
    <xs:attribute name="height" type="xs:int"/>
  </xs:complexType>
  <xs:complexType name="Table">
    <xs:sequence>
      <xs:element name="grid" type="Grid" minOccurs="1" maxOccurs="1"/>
      <xs:element name="row" type="Row" minOccurs="1" maxOccurs="unbounded"/>
      <xs:element name="caption" type="xs:string" minOccurs="0"/>
    </xs:sequence>
    <xs:attribute name="style" type="xs:string" use="required"/>
    <xs:attribute name="locked" type="xs:boolean" default="true"/>
  </xs:complexType>
  <xs:complexType name="Measure">
    <xs:simpleContent>
      <xs:extension base="xs:int">
        <xs:attribute name="unit" type="xs:string" use="required"/>
      </xs:extension>
    </xs:simpleContent>
  </xs:complexType>
  <xs:element name="table" type="Table"/>
</xs:schema>
"""


def _filters(**output) -> Filters:
    config = GeneratorConfig()
    for key, value in output.items():
        setattr(config.output, key, value)
    return Filters(config)


def test_default_is_upstream_behaviour(gen) -> None:
    off = gen(SCHEMA)
    on = gen(SCHEMA, options="    <AllOptional>false</AllOptional>")
    assert off.source == on.source


def test_required_elements_and_attributes_become_optional(gen) -> None:
    upstream = gen(SCHEMA).source
    forked = gen(SCHEMA, options="    <AllOptional>true</AllOptional>").source

    # A required element is a mandatory keyword argument upstream ...
    assert "grid: Grid = field(" in upstream
    assert "style: str = field(" in upstream
    assert "unit: str = field(" in upstream

    # ... and never with the option on.
    assert "grid: None | Grid = field(" in forked
    assert "style: None | str = field(" in forked
    assert "unit: None | str = field(" in forked

    # Lists stay lists with a factory.
    assert "row: list[Row] = field(" in forked
    assert "default_factory=list" in forked

    # The value field of a simpleContent extension too.
    assert "value: int = field(" in upstream
    assert "value: None | int = field(default=None)" in forked

    # An already optional element is untouched.
    assert "caption: None | str = field(" in upstream
    assert "caption: None | str = field(" in forked

    # A schema default is not thrown away, see the SchemaDefaults option.
    assert "locked: None | bool = field(" in forked
    assert "default=True" in forked


def test_schema_invalid_document_loads(gen) -> None:
    """A table with no grid is schema invalid, Word writes them anyway."""
    module = gen(SCHEMA, options="    <AllOptional>true</AllOptional>").load()
    table = module.Table()
    assert table.grid is None
    assert table.style is None
    assert table.row == []


def test_force_optional_rules() -> None:
    filters = _filters(all_optional=True)
    obj = ClassFactory.create()

    element = AttrFactory.element(restrictions=Restrictions(min_occurs=1, max_occurs=1))
    attribute = AttrFactory.attribute(
        restrictions=Restrictions(min_occurs=1, max_occurs=1)
    )
    assert filters.force_optional(element)
    assert filters.force_optional(attribute)
    assert filters.field_default_value(element) is None
    assert filters.field_type(obj, attribute) == "None | str"

    # Lists, maps and token lists keep their factory.
    listed = AttrFactory.element(restrictions=Restrictions(min_occurs=1, max_occurs=2))
    assert not filters.force_optional(listed)
    assert filters.field_default_value(listed) == "list"

    any_attribute = AttrFactory.any_attribute()
    assert not filters.force_optional(any_attribute)
    assert filters.field_default_value(any_attribute) == "dict"

    tokens = AttrFactory.create(
        tag=Tag.ELEMENT,
        types=[AttrTypeFactory.native(DataType.NMTOKENS)],
        restrictions=Restrictions(min_occurs=1, max_occurs=1, tokens=True),
    )
    assert not filters.force_optional(tokens)

    # Prohibited and fixed value attrs are left alone.
    prohibited = AttrFactory.element(restrictions=Restrictions(max_occurs=0))
    assert not filters.force_optional(prohibited)

    fixed = AttrFactory.attribute(fixed=True, default="a")
    assert not filters.force_optional(fixed)

    # A text/value field only becomes optional when it would be required.
    extension = AttrFactory.extension(
        restrictions=Restrictions(min_occurs=1, max_occurs=1)
    )
    assert filters.force_optional(extension)

    optional_extension = AttrFactory.extension(
        restrictions=Restrictions(min_occurs=0, max_occurs=1)
    )
    assert not filters.force_optional(optional_extension)


def test_force_optional_is_off_by_default() -> None:
    filters = _filters()
    element = AttrFactory.element(restrictions=Restrictions(min_occurs=1, max_occurs=1))
    assert not filters.force_optional(element)
    assert filters.field_default_value(element) is False
