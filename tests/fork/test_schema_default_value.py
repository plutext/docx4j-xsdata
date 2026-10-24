"""docx4j fork: `XmlVar.schema_default_value`, the schema default typed.

docx4j-python CR-018. `<SchemaDefaults>metadata</SchemaDefaults>` (stage 2,
item 2) keeps a schema default out of the field, in its metadata, as the
schema's lexical string (`XmlVar.schema_default`), and a reader that wants
the effective value has to convert it. The binding metadata now carries it
converted too, once, when the var is built, as a parse of that spelling would
convert it. `schema_default` stays lexical.
"""

import math
from dataclasses import dataclass, field

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.parsers import XmlParser

SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns="urn:fork:typed" targetNamespace="urn:fork:typed"
           elementFormDefault="qualified">
  <xs:simpleType name="State">
    <xs:restriction base="xs:string">
      <xs:enumeration value="on"/>
      <xs:enumeration value="off"/>
    </xs:restriction>
  </xs:simpleType>
  <xs:complexType name="Props">
    <xs:attribute name="name" type="xs:string"/>
    <xs:attribute name="locked" type="xs:boolean" default="true"/>
    <xs:attribute name="size" type="xs:int" default="12"/>
    <xs:attribute name="scale" type="xs:double" default="NaN"/>
    <xs:attribute name="label" type="xs:string" default=""/>
    <xs:attribute name="state" type="State" default="on"/>
  </xs:complexType>
  <xs:complexType name="Child">
    <xs:complexContent>
      <xs:extension base="Props">
        <xs:attribute name="extra" type="xs:boolean" default="false"/>
      </xs:extension>
    </xs:complexContent>
  </xs:complexType>
  <xs:element name="props" type="Props"/>
  <xs:element name="child" type="Child"/>
</xs:schema>
"""

OPTIONS = (
    "    <AllOptional>true</AllOptional>\n    <SchemaDefaults>metadata</SchemaDefaults>"
)


def var_values(clazz) -> dict:
    meta = XmlContext().build(clazz)
    return {
        var.name: (var.schema_default, var.schema_default_value)
        for var in meta.get_all_vars()
    }


def test_typed_once_beside_the_lexical_default(gen) -> None:
    module = gen(SCHEMA, options=OPTIONS).load()
    values = var_values(module.Props)

    assert values["locked"] == ("true", True)
    assert values["size"] == ("12", 12)
    assert values["label"] == ("", "")
    assert values["state"] == (module.State.ON, module.State.ON)
    assert values["name"] == (None, None)
    lexical, typed = values["scale"]
    assert lexical == "NaN"
    assert isinstance(typed, float)
    assert math.isnan(typed)


def test_a_subclass_carries_its_inherited_defaults(gen) -> None:
    module = gen(SCHEMA, options=OPTIONS).load()
    values = var_values(module.Child)

    assert values["locked"] == ("true", True)
    assert values["extra"] == ("false", False)


def test_without_the_metadata_mode_there_is_none(gen) -> None:
    module = gen(SCHEMA).load()

    assert {typed for _, typed in var_values(module.Props).values()} == {None}


def test_the_field_is_still_never_filled(gen) -> None:
    module = gen(SCHEMA, options=OPTIONS).load()

    obj = XmlParser().from_string('<props xmlns="urn:fork:typed"/>', module.Props)
    assert obj.locked is None
    assert obj.size is None


def test_the_same_value_a_parse_of_the_spelling_gives(gen) -> None:
    module = gen(SCHEMA, options=OPTIONS).load()
    source = (
        '<props xmlns="urn:fork:typed" locked="true" size="12" label="" state="on"/>'
    )

    obj = XmlParser().from_string(source, module.Props)
    values = var_values(module.Props)
    for name in ("locked", "size", "label", "state"):
        assert getattr(obj, name) == values[name][1]


@dataclass
class HandWritten:
    """Metadata written by hand, as no generator would."""

    flag: bool | None = field(
        default=None, metadata={"type": "Attribute", "schema_default": "maybe"}
    )
    sizes: list[int] = field(
        default_factory=list,
        metadata={"type": "Attribute", "tokens": True, "schema_default": "1 2 3"},
    )


def test_a_list_default_and_one_that_does_not_convert() -> None:
    values = var_values(HandWritten)

    assert values["sizes"] == ("1 2 3", [1, 2, 3])
    assert values["flag"] == ("maybe", "maybe")  # kept lexical, not raised
