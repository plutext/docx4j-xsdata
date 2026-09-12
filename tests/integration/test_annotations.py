import os

import pytest
from click.testing import CliRunner

from docx4j_xsdata.cli import cli
from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.parsers.xml import XmlParser
from docx4j_xsdata.utils.testing import load_class
from tests import fixtures_dir, root

os.chdir(root)


def test_annotations() -> None:
    filepath = fixtures_dir.joinpath("annotations")
    schema = filepath.joinpath("model.xsd")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["generate", str(schema), f"--config={filepath.joinpath('xsdata.xml')!s}"]
    )

    if result.exception:
        raise result.exception

    try:
        Measurement = load_class(result.output, "Measurement")
        unit = load_class(result.output, "unit")
    except Exception:
        pytest.fail("Could not load class with member having the same name as type")

    filename = str(filepath.joinpath("sample.xml"))
    parser = XmlParser(context=XmlContext())
    measurement = parser.parse(filename, Measurement)
    assert measurement.value == 2.0
    assert measurement.unit == unit.KG
