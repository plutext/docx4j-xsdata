"""docx4j fork: the generator's import check covers what it wrote, nothing else.

Upstream validates its output by importing the output package and then every
subpackage and module under it (`pkgutil.walk_packages`). That assumes the
output package is exclusively generated. docx4j-python keeps hand-written
packages beside the generated ones (`docx4j_py/model/`, `docx4j_py/openpackaging/`),
and those import names that only exist after a later step of the build has run
(`docx4j_py.wml.el`), so upstream's walk raised `ImportError` -- reported as
"Circular Dependencies Found" -- on a package that was perfectly fine. The
fork's `render` records the packages and modules it writes and
`validate_imports` imports exactly those.
"""

import pytest

from docx4j_xsdata.formats.dataclass.generator import DataclassGenerator
from docx4j_xsdata.models.config import GeneratorConfig

SCHEMA = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns="urn:fork:v" targetNamespace="urn:fork:v"
           elementFormDefault="qualified">
  <xs:complexType name="Para">
    <xs:attribute name="text" type="xs:string"/>
  </xs:complexType>
  <xs:element name="para" type="Para"/>
</xs:schema>
"""

# A hand-written package beside the generated one, importing a name that
# nothing in the generated output provides.
HANDWRITTEN = "from {package}.fork.v import el  # noqa: F401\n"


def test_a_hand_written_module_beside_the_output_is_not_imported(gen) -> None:
    package = "validate_imports_fork"
    generated = gen(
        SCHEMA,
        package=package,
        structure="namespaces",
        files={f"{package}/extra/__init__.py": HANDWRITTEN.format(package=package)},
    )

    # The run succeeded (gen raises on an error), the output is importable,
    # and the hand-written package is still there, untouched and still broken.
    module = generated.load()
    assert hasattr(module, "fork")
    assert "Circular Dependencies" not in generated.output
    with pytest.raises(ImportError):
        __import__(f"{package}.extra")


def test_the_generated_modules_are_still_imported() -> None:
    generator = DataclassGenerator(GeneratorConfig())

    with pytest.raises(ImportError):
        generator.validate_imports(["docx4j_xsdata_no_such_module_fork"])
