"""docx4j fork: <Output><SchemaDefaults>metadata</SchemaDefaults></Output>."""

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig

SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns="urn:fork" targetNamespace="urn:fork"
           elementFormDefault="qualified">
  <xs:simpleType name="OnOff">
    <xs:restriction base="xs:string">
      <xs:enumeration value="on"/>
      <xs:enumeration value="off"/>
    </xs:restriction>
  </xs:simpleType>
  <xs:complexType name="LsdException">
    <xs:attribute name="name" type="xs:string"/>
    <xs:attribute name="locked" type="xs:boolean" default="true"/>
    <xs:attribute name="semiHidden" type="xs:boolean" default="false"/>
    <xs:attribute name="state" type="OnOff" default="on"/>
    <xs:attribute name="kind" type="xs:string" fixed="paragraph"/>
  </xs:complexType>
  <xs:element name="lsdException" type="LsdException"/>
</xs:schema>
"""

METADATA = "    <SchemaDefaults>metadata</SchemaDefaults>"


def _render(obj, **config) -> str:
    serializer = XmlSerializer(
        context=XmlContext(), config=SerializerConfig(xml_declaration=False, **config)
    )
    return serializer.render(obj)


def test_default_is_upstream_behaviour(gen) -> None:
    off = gen(SCHEMA)
    on = gen(SCHEMA, options="    <SchemaDefaults>field</SchemaDefaults>")
    assert off.source == on.source
    assert "schema_default" not in off.source


def test_schema_default_moves_to_the_metadata(gen) -> None:
    upstream = gen(SCHEMA).source
    forked = gen(SCHEMA, options=METADATA).source

    assert "locked: bool = field(\n        default=True," in upstream
    assert "state: OnOff = field(\n        default=OnOff.ON," in upstream

    assert "locked: None | bool = field(\n        default=None," in forked
    assert '"schema_default": "true",' in forked
    assert '"schema_default": "false",' in forked

    # The enum member, not its lexical value, so the reference is not lost.
    assert "state: None | OnOff = field(\n        default=None," in forked
    assert '"schema_default": OnOff.ON,' in forked

    # A fixed value attr is left alone, it has no constructor argument and
    # the field is the only place the value lives.
    assert 'default="paragraph"' in forked
    assert "init=False" in forked


def test_runtime_exposes_the_schema_default(gen) -> None:
    module = gen(SCHEMA, options=METADATA).load()
    meta = XmlContext().build(module.LsdException)
    schema_defaults = {var.name: var.schema_default for var in meta.get_all_vars()}

    assert schema_defaults["locked"] == "true"
    assert schema_defaults["semi_hidden"] == "false"
    assert schema_defaults["state"] is module.OnOff.ON
    assert schema_defaults["name"] is None


def test_absent_attribute_stays_absent(gen) -> None:
    module = gen(SCHEMA, options=METADATA).load()
    source = '<lsdException xmlns="urn:fork" name="heading 1"/>'

    obj = XmlParser(context=XmlContext()).from_string(source, module.LsdException)

    # The parser must not fill the field with the schema default.
    assert obj.locked is None
    assert obj.semi_hidden is None
    assert obj.state is None

    assert _render(obj, indent=None) == (
        '<ns0:lsdException xmlns:ns0="urn:fork" name="heading 1" kind="paragraph"/>'
    )


def test_present_attribute_equal_to_the_default_is_written(gen) -> None:
    module = gen(SCHEMA, options=METADATA).load()
    source = (
        '<lsdException xmlns="urn:fork" name="heading 1" locked="true" state="on"/>'
    )

    obj = XmlParser(context=XmlContext()).from_string(source, module.LsdException)
    assert obj.locked is True
    assert obj.state is module.OnOff.ON

    output = _render(obj, indent=None)
    assert 'locked="true"' in output
    assert 'state="on"' in output

    # ... and ignore_default_attributes no longer eats it, there is no
    # field default for it to match.
    output = _render(obj, indent=None, ignore_default_attributes=True)
    assert 'locked="true"' in output
    assert 'state="on"' in output


def test_ignore_default_attributes_is_unaffected_when_the_option_is_off(gen) -> None:
    module = gen(SCHEMA).load()
    source = '<lsdException xmlns="urn:fork" name="heading 1" locked="true"/>'

    obj = XmlParser(context=XmlContext()).from_string(source, module.LsdException)
    assert obj.locked is True
    assert obj.semi_hidden is False  # invented by the schema default

    # Upstream behaviour, both halves of REPORT.md 7.1: absent attributes are
    # materialised, and ignoring the defaults drops the one that was present.
    output = _render(obj, indent=None)
    assert 'semiHidden="false"' in output

    output = _render(obj, indent=None, ignore_default_attributes=True)
    assert "semiHidden" not in output
    assert "locked" not in output
