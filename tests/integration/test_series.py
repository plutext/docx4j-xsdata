import json
import os

from click.testing import CliRunner

from docx4j_xsdata.cli import cli
from docx4j_xsdata.formats.dataclass.parsers import JsonParser
from docx4j_xsdata.formats.dataclass.serializers import JsonSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig
from docx4j_xsdata.utils.testing import filter_none, load_class
from tests import fixtures_dir, root

os.chdir(root)


def test_json_documents() -> None:
    filepath = fixtures_dir.joinpath("series")
    package = "tests.fixtures.series"
    runner = CliRunner()
    result = runner.invoke(
        cli, ["generate", str(filepath.joinpath("samples")), "--package", package]
    )

    if result.exception:
        raise result.exception

    clazz = load_class(result.output, "Series")

    parser = JsonParser()
    config = SerializerConfig(indent="  ")
    serializer = JsonSerializer(config=config)

    for i in range(1, 3):
        ori = filepath.joinpath(f"samples/show{i}.json").read_text()
        obj = parser.from_string(ori, clazz)
        actual = serializer.render(obj)

        assert filter_none(json.loads(ori)) == filter_none(json.loads(actual))
