"""docx4j fork: <Output><ListFactory>...</ListFactory></Output>."""

import pytest

from docx4j_xsdata.codegen.exceptions import CodegenError
from docx4j_xsdata.formats.dataclass.filters import Filters
from docx4j_xsdata.models.config import GeneratorConfig

SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns="urn:fork" targetNamespace="urn:fork"
           elementFormDefault="qualified">
  <xs:complexType name="Row">
    <xs:attribute name="height" type="xs:int"/>
  </xs:complexType>
  <xs:complexType name="Table">
    <xs:choice maxOccurs="unbounded">
      <xs:element name="row" type="Row"/>
      <xs:element name="caption" type="xs:string"/>
    </xs:choice>
    <xs:attribute name="classes" type="xs:NMTOKENS"/>
  </xs:complexType>
  <xs:element name="table" type="Table"/>
</xs:schema>
"""

# A list subclass that is importable from the generated package's point of
# view: tests.fork is on the path whenever the test suite runs.
FACTORY = "    <ListFactory>tests.fork.childlist.ChildList</ListFactory>"


def test_default_is_upstream_behaviour(gen) -> None:
    off = gen(SCHEMA)
    assert "default_factory=list" in off.source
    assert "ChildList" not in off.source


def test_list_fields_use_the_factory(gen) -> None:
    generated = gen(SCHEMA, options=FACTORY)
    source = generated.source

    assert "from tests.fork.childlist import ChildList" in source
    assert "default_factory=ChildList" in source
    # The token list stays a plain list, its items are strings.
    assert "default_factory=list" in source


def test_the_factory_is_instantiated(gen) -> None:
    from tests.fork.childlist import ChildList

    module = gen(SCHEMA, options=FACTORY).load()
    table = module.Table()

    assert isinstance(table.row_or_caption, ChildList)
    assert table.classes == []
    assert type(table.classes) is list

    row = module.Row()
    table.row_or_caption.append(row)
    assert row.parent is table.row_or_caption


def test_invalid_dotted_path() -> None:
    config = GeneratorConfig()
    config.output.list_factory = "ChildList"

    with pytest.raises(CodegenError):
        Filters(config)
