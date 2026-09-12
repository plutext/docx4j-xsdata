import os

from click.testing import CliRunner

from docx4j_xsdata.cli import cli
from docx4j_xsdata.utils.testing import load_class
from tests import fixtures_dir, root

os.chdir(root)


def test_dtd_documents() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "generate",
            str(fixtures_dir.joinpath("dtd/complete_example.dtd")),
            "--package",
            "tests.fixtures.dtd.models",
        ],
    )

    if result.exception:
        raise result.exception

    clazz = load_class(result.output, "Post")

    assert clazz is not None
