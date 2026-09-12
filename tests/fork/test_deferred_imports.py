"""docx4j fork: <Output><DeferredImports>true</DeferredImports></Output>."""

import importlib
import sys

import pytest

from tests.fork.utils import Generated

# Two namespaces that reference each other, the shape ECMA-376 has all over:
# WML embeds DML and DML embeds WML through a:graphicData. With one module
# per namespace that is an import cycle by construction.
SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:b="urn:fork:b" xmlns="urn:fork:a"
           targetNamespace="urn:fork:a" elementFormDefault="qualified">
  <xs:import namespace="urn:fork:b" schemaLocation="other.xsd"/>
  <xs:complexType name="Empty"/>
  <xs:complexType name="Para">
    <xs:attribute name="text" type="xs:string"/>
  </xs:complexType>
  <xs:complexType name="Doc">
    <xs:choice maxOccurs="unbounded">
      <xs:element name="para" type="Para"/>
      <xs:element name="widget" type="b:Widget"/>
    </xs:choice>
  </xs:complexType>
  <xs:element name="doc" type="Doc"/>
</xs:schema>
"""

OTHER = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:a="urn:fork:a" xmlns="urn:fork:b"
           targetNamespace="urn:fork:b" elementFormDefault="qualified">
  <xs:import namespace="urn:fork:a" schemaLocation="sample.xsd"/>
  <xs:complexType name="Widget">
    <xs:complexContent>
      <xs:extension base="a:Empty">
        <xs:sequence>
          <xs:element ref="a:doc" minOccurs="0"/>
        </xs:sequence>
      </xs:extension>
    </xs:complexContent>
  </xs:complexType>
</xs:schema>
"""


def _namespaces(gen, options="", expect_error=False) -> Generated:
    return gen(
        SCHEMA,
        options=options,
        structure="namespaces",
        files={"other.xsd": OTHER},
        expect_error=expect_error,
    )


def _import_in_isolation(generated, suffix: str) -> None:
    """Import a module with nothing of the package loaded yet."""
    package = generated.package
    module = f"{package}.{suffix}" if suffix else package
    for name in list(sys.modules):
        if name == package or name.startswith(f"{package}."):
            del sys.modules[name]

    root = generated.root
    sys.path.insert(0, str(root))
    try:
        importlib.import_module(module)
    finally:
        sys.path.remove(str(root))


def test_upstream_cannot_import_the_output(gen) -> None:
    generated = _namespaces(gen, expect_error=True)

    # The base class is a real dependency, the compound field is not, and
    # upstream puts both at the top of the module.
    package = generated.package
    assert "class Widget(Empty)" in generated.module_source("fork/b")
    assert f"from {package}.fork.b import Widget" in generated.module_source("fork/a")

    with pytest.raises(ImportError):
        _import_in_isolation(generated, "fork.b")


def test_the_output_imports_from_either_end(gen) -> None:
    generated = _namespaces(gen, options="    <DeferredImports>true</DeferredImports>")

    package = generated.package
    source_a = generated.module_source("fork/a")
    source_b = generated.module_source("fork/b")

    # The base class stays a real import at the top.
    assert source_b.index(f"from {package}.fork.a import Empty") < source_b.index(
        "class Widget(Empty)"
    )

    # What is only needed for the annotations and the choices metadata is
    # imported below the classes, and the metadata holds a forward reference
    # rather than the class object.
    assert source_a.index(f"from {package}.fork.b import Widget") > source_a.index(
        "class Doc"
    )
    assert '"type": ForwardRef("Widget")' in source_a
    assert '"type": ForwardRef("Para")' in source_a

    for suffix in ("fork.a", "fork.b", "fork"):
        _import_in_isolation(generated, suffix)


def test_the_forward_references_resolve_at_runtime(gen) -> None:
    from docx4j_xsdata.formats.dataclass.context import XmlContext
    from docx4j_xsdata.formats.dataclass.parsers import XmlParser
    from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
    from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig

    generated = _namespaces(gen, options="    <DeferredImports>true</DeferredImports>")
    _import_in_isolation(generated, "fork.b")

    sys.path.insert(0, str(generated.root))
    try:
        module_a = importlib.import_module(f"{generated.package}.fork.a")
        module_b = importlib.import_module(f"{generated.package}.fork.b")
    finally:
        sys.path.remove(str(generated.root))

    source = (
        '<doc xmlns="urn:fork:a" xmlns:b="urn:fork:b">'
        '<para text="one"/>'
        "<widget/>"
        '<para text="two"/>'
        "</doc>"
    )
    context = XmlContext()
    obj = XmlParser(context=context).from_string(source, module_a.Doc)

    assert [type(item) for item in obj.para_or_widget] == [
        module_a.Para,
        module_b.Widget,
        module_a.Para,
    ]

    serializer = XmlSerializer(
        context=context, config=SerializerConfig(xml_declaration=False, indent=None)
    )
    assert serializer.render(obj, ns_map={None: "urn:fork:a", "b": "urn:fork:b"}) == (
        source
    )


def test_the_package_re_exports_are_lazy(gen) -> None:
    generated = _namespaces(gen, options="    <DeferredImports>true</DeferredImports>")
    init = generated.path.joinpath("fork", "__init__.py").read_text()

    assert "def __getattr__(name: str) -> object:" in init
    assert "__lazy_imports__" in init

    _import_in_isolation(generated, "fork")
    sys.path.insert(0, str(generated.root))
    try:
        package = importlib.import_module(f"{generated.package}.fork")
        assert package.Widget.__name__ == "Widget"
        with pytest.raises(AttributeError):
            _ = package.NoSuchClass
    finally:
        sys.path.remove(str(generated.root))
