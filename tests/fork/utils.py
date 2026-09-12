"""Helpers for the docx4j fork's generator tests.

Every fork option is a project configuration setting that defaults to
upstream behaviour, so the tests here generate the same schema twice --
once with the option off, once with it on -- and compare the emitted
source.
"""

import gc
import importlib
import itertools
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from docx4j_xsdata.cli import cli
from docx4j_xsdata.utils.package import module_path, package_path

_counter = itertools.count(1)

CONFIG = """<?xml version="1.0" encoding="UTF-8"?>
<Config xmlns="http://pypi.org/project/xsdata" version="26.2">
  <Output maxLineLength="99">
    <Package>{package}</Package>
    <Format repr="true" eq="true" slots="false">dataclasses</Format>
    <Structure>{structure}</Structure>
    <DocstringStyle>Blank</DocstringStyle>
    <CompoundFields defaultName="content" useSubstitutionGroups="true">true</CompoundFields>
{options}
  </Output>
</Config>
"""


class Generated:
    """A generated package in a throwaway directory."""

    def __init__(self, root: Path, package: str):
        self.root = root
        self.package = package

    @property
    def path(self) -> Path:
        """The directory or module file the generator wrote."""
        parts = self.package.split(".")
        target = self.root.joinpath(*parts)
        return target if target.is_dir() else target.with_suffix(".py")

    @property
    def source(self) -> str:
        """The concatenated source of every generated module."""
        if self.path.is_file():
            return self.path.read_text()

        return "\n".join(
            p.read_text()
            for p in sorted(self.path.rglob("*.py"))
            if p.name != "__init__.py"
        )

    def module_source(self, name: str) -> str:
        """Return the source of one generated module, by relative path."""
        return self.path.joinpath(*f"{name}.py".split("/")).read_text()

    def load(self) -> Any:
        """Import the generated package and return the module."""
        sys.path.insert(0, str(self.root))
        try:
            return importlib.import_module(self.package)
        finally:
            sys.path.remove(str(self.root))

    def cleanup(self) -> None:
        """Drop the generated modules from sys.modules and delete them.

        The collect matters: a module and the classes defined in it form a
        reference cycle, and while they are alive ``XmlContext`` keeps
        finding them through ``object.__subclasses__()``.
        """
        for name in list(sys.modules):
            if name == self.package or name.startswith(f"{self.package}."):
                del sys.modules[name]
        gc.collect()
        shutil.rmtree(self.root, ignore_errors=True)


def generate(
    schema: str,
    options: str = "",
    package: str | None = None,
    structure: str = "single-package",
    extra: tuple[str, ...] = (),
    files: dict[str, str] | None = None,
    expect_error: bool = False,
) -> Generated:
    """Generate a schema into a throwaway package.

    Args:
        schema: The xml schema source
        options: Extra ``<Output>`` child elements, e.g. ``<AllOptional>true</AllOptional>``
        package: The output package name, unique per call by default so that
            one test's output is never mistaken for another's
        structure: The output structure style
        extra: Extra command line arguments
        files: Extra schema files, by name, e.g. the other half of a pair
            of schemas that import each other
        expect_error: Keep the output of a generation that failed, which is
            what upstream does when it cannot import what it just wrote

    Returns:
        The generated package accessor.
    """
    package = package or f"models{next(_counter)}"
    root = Path(tempfile.mkdtemp(prefix="docx4j-xsdata-fork-"))
    root.joinpath("sample.xsd").write_text(schema)
    for name, source in (files or {}).items():
        root.joinpath(name).write_text(source)
    root.joinpath(".xsdata.xml").write_text(
        CONFIG.format(package=package, structure=structure, options=options)
    )

    # These are lru_cached on the package name and join it with the cwd.
    package_path.cache_clear()
    module_path.cache_clear()

    cwd = os.getcwd()
    os.chdir(root)
    try:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["generate", "sample.xsd", "-c", ".xsdata.xml", *extra]
        )
        if result.exception and not expect_error:
            raise result.exception
    finally:
        os.chdir(cwd)

    return Generated(root, package)
