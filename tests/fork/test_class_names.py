"""docx4j fork: <Output><ClassNames>codegen/names</ClassNames></Output>.

An explicit schema name to class name table, one json file per
namespace, because docx4j's thousand names cannot be expressed as
regular expression substitutions.
"""

import json

import pytest

from docx4j_xsdata.codegen.class_names import ClassNames
from docx4j_xsdata.codegen.exceptions import CodegenError
from docx4j_xsdata.models.config import GeneratorConfig

SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns="urn:fork" targetNamespace="urn:fork"
           elementFormDefault="qualified">
  <xs:simpleType name="ST_Jc">
    <xs:restriction base="xs:string">
      <xs:enumeration value="left"/>
      <xs:enumeration value="center"/>
    </xs:restriction>
  </xs:simpleType>
  <xs:complexType name="CT_PPr">
    <xs:attribute name="jc" type="ST_Jc"/>
  </xs:complexType>
  <xs:complexType name="CT_R">
    <xs:sequence>
      <xs:element name="t" minOccurs="0">
        <xs:complexType>
          <xs:simpleContent>
            <xs:extension base="xs:string">
              <xs:attribute name="space" type="xs:string"/>
            </xs:extension>
          </xs:simpleContent>
        </xs:complexType>
      </xs:element>
    </xs:sequence>
  </xs:complexType>
  <xs:complexType name="CT_P">
    <xs:sequence>
      <xs:element name="pPr" type="CT_PPr" minOccurs="0"/>
      <xs:choice maxOccurs="unbounded">
        <xs:element name="ins" type="CT_R"/>
        <xs:element name="moveTo" type="CT_R"/>
      </xs:choice>
    </xs:sequence>
  </xs:complexType>
  <xs:complexType name="CT_Body">
    <xs:sequence>
      <xs:element name="p" type="CT_P" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>
  <xs:element name="document" type="CT_Body"/>
</xs:schema>
"""

TABLE = {
    "namespace": "urn:fork",
    "java_package": "org.docx4j.fork",
    "types": {
        "CT_PPr": "PPr",
        "CT_P": "P",
        "CT_R": "R",
        "CT_Body": "Body",
        "ST_Jc": "STJc",
    },
    "elements": {"document": "Document", "ins": "RunIns", "t": "Text"},
}

OPTIONS = "    <UnnestClasses>true</UnnestClasses>\n    <ClassNames>names</ClassNames>"
UNNEST = "    <UnnestClasses>true</UnnestClasses>"


def names(table: dict = TABLE, path: str = "names/fork.json") -> dict:
    """Return a `files` mapping with one name table file."""
    return {path: json.dumps(table)}


def test_default_is_upstream_behaviour(gen) -> None:
    source = gen(SCHEMA, options=UNNEST, files=names()).source

    # The table is on disk but no <ClassNames> points at it.
    assert "class CtPpr" in source
    assert "class StJc" in source
    assert "class PPr" not in source
    assert "class RunIns" not in source


def test_types_are_renamed_verbatim(gen) -> None:
    source = gen(SCHEMA, options=OPTIONS, files=names()).source

    assert "class PPr:" in source
    assert "class P:" in source
    assert "class Body:" in source
    assert "class STJc(Enum):" in source
    # The case convention never runs over a name from the table.
    assert "class Ppr" not in source
    assert "class StJc" not in source
    assert "class CtPpr" not in source


def test_global_elements_keep_their_xml_name(gen) -> None:
    source = gen(SCHEMA, options=OPTIONS, files=names()).source

    assert "class Document(Body):" in source
    assert 'name = "document"' in source


def test_element_specific_classes_are_renamed(gen) -> None:
    source = gen(SCHEMA, options=OPTIONS, files=names()).source

    # The choice has two elements of the same type, the generator
    # creates a class per element name; `moveTo` is not in the table.
    assert "class RunIns(R):" in source
    assert "class MoveTo(R):" in source
    assert "class Ins" not in source


def test_unnested_local_elements_are_renamed(gen) -> None:
    generated = gen(SCHEMA, options=OPTIONS, files=names())
    source = generated.source

    assert "class Text:" in source
    assert "class RT" not in source
    assert "class R_T" not in source


def test_the_result_parses_and_serializes(gen) -> None:
    from docx4j_xsdata.formats.dataclass.parsers import XmlParser
    from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
    from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig

    module = gen(SCHEMA, options=OPTIONS, files=names()).load()
    xml = (
        '<document xmlns="urn:fork"><p><pPr jc="left"/>'
        '<ins><t space="preserve">hello</t></ins></p></document>'
    )

    obj = XmlParser().from_string(xml, module.Document)
    assert isinstance(obj, module.Document)
    assert isinstance(obj.p[0].p_pr, module.PPr)
    assert obj.p[0].p_pr.jc is module.STJc.LEFT
    assert isinstance(obj.p[0].ins_or_move_to[0], module.RunIns)
    assert isinstance(obj.p[0].ins_or_move_to[0].t, module.Text)
    assert obj.p[0].ins_or_move_to[0].t.value == "hello"

    config = SerializerConfig(xml_declaration=False)
    result = XmlSerializer(config=config).render(obj, ns_map={None: "urn:fork"})
    assert result == xml


def test_a_collision_is_reported_and_disambiguated(gen) -> None:
    table = json.loads(json.dumps(TABLE))
    table["types"]["CT_Body"] = "Text"

    generated = gen(SCHEMA, options=OPTIONS, files=names(table))
    source = generated.source

    assert "is mapped to `Text`" in generated.output
    # Neither class is overwritten, the duplicate name handler suffixes
    # both, as it does for any two same named non element classes.
    assert "class Text1:" in source
    assert "class Text2:" in source
    assert "class Text:" not in source


def test_it_composes_with_the_namespaces_layout(gen) -> None:
    generated = gen(
        SCHEMA,
        options=OPTIONS + "\n    <DeferredImports>true</DeferredImports>",
        structure="namespaces",
        files=names(),
    )
    source = generated.source

    assert "class PPr:" in source
    assert "class Text:" in source
    module = generated.load()
    assert module.Document.__name__ == "Document"


def test_an_unknown_directory_is_refused(gen) -> None:
    generated = gen(
        SCHEMA,
        options="    <ClassNames>nowhere</ClassNames>",
        expect_error=True,
    )

    assert "ClassNames directory not found" in generated.output


def test_an_invalid_class_name_is_ignored(gen) -> None:
    table = json.loads(json.dumps(TABLE))
    table["types"]["CT_PPr"] = "class"
    table["types"]["CT_P"] = "not a name"

    generated = gen(SCHEMA, options=OPTIONS, files=names(table))

    assert "is not a valid class name" in generated.output
    assert "class CtPpr:" in generated.source
    assert "class CtP:" in generated.source


def test_the_table_is_loaded_per_namespace(tmp_path) -> None:
    directory = tmp_path.joinpath("names")
    directory.mkdir()
    directory.joinpath("fork.json").write_text(json.dumps(TABLE))
    directory.joinpath("other.json").write_text(
        json.dumps({"namespace": "urn:other", "types": {"CT_PPr": "Other"}})
    )

    table = ClassNames.load(directory)

    assert len(table) == 9
    assert table.find("urn:fork", "CT_PPr", False) == "PPr"
    assert table.find("urn:other", "CT_PPr", False) == "Other"
    assert table.find("urn:fork", "CT_PPr", True) is None
    assert table.find("urn:fork", "t", True) == "Text"
    assert table.find(None, "CT_PPr", False) is None
    assert table.java_packages == {"urn:fork": "org.docx4j.fork"}
    assert "PPr" in table.names()


def test_a_missing_directory_raises(tmp_path) -> None:
    with pytest.raises(CodegenError, match="ClassNames directory not found"):
        ClassNames.load(tmp_path.joinpath("nowhere"))


def test_the_config_resolves_the_path_against_itself(tmp_path) -> None:
    tmp_path.joinpath("names").mkdir()
    tmp_path.joinpath("names", "fork.json").write_text(json.dumps(TABLE))
    config_file = tmp_path.joinpath(".xsdata.xml")
    config_file.write_text(
        '<Config xmlns="http://pypi.org/project/xsdata" version="26.2">'
        "<Output><ClassNames>names</ClassNames></Output></Config>"
    )

    config = GeneratorConfig.read(config_file)

    assert config.output.class_names == "names"
    assert config.output.class_name_table is not None
    assert config.output.class_name_table.find("urn:fork", "CT_P", False) == "P"


def test_the_table_is_not_a_configuration_value(tmp_path) -> None:
    config = GeneratorConfig()
    config.output.class_names = "names"

    with pytest.raises(CodegenError):
        config.output.load_class_names(tmp_path)

    config.output.class_names = None
    config.output.load_class_names(tmp_path)
    assert config.output.class_name_table is None
