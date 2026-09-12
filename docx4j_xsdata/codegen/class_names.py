"""The docx4j fork's explicit class name table.

`Substitutions` are regular expressions, which cannot express a thousand
entry name table like docx4j's `org.docx4j.wml.ObjectFactory`. This is
the table: one JSON file per namespace in a directory, named by the
generator config's `<Output><ClassNames>` element.

```json
{
  "namespace": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
  "java_package": "org.docx4j.wml",
  "types": {"CT_PPr": "PPr", "CT_Settings": "CTSettings", "ST_Jc": "STJc"},
  "elements": {"document": "Document", "ins": "RunIns", "t": "Text"}
}
```

`types` maps the name of a complexType or simpleType in that namespace,
`elements` the name of a global or local element, to the name of the
class the generator emits for it. Names that are not in the table keep
the naming conventions. A name from the table is emitted verbatim: it is
applied before the case convention, not through it.
"""

import json
from dataclasses import dataclass, field
from keyword import iskeyword
from pathlib import Path

from docx4j_xsdata.codegen.exceptions import CodegenError
from docx4j_xsdata.logger import logger

TYPES = "types"
ELEMENTS = "elements"


@dataclass
class ClassNames:
    """An explicit schema name to class name table, by namespace.

    Attributes:
        types: The (namespace, type name) to class name map
        elements: The (namespace, element name) to class name map
        java_packages: The namespace to java package map, informative
    """

    types: dict[tuple[str, str], str] = field(default_factory=dict)
    elements: dict[tuple[str, str], str] = field(default_factory=dict)
    java_packages: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        """Return the total number of entries."""
        return len(self.types) + len(self.elements)

    def find(self, namespace: str | None, name: str, is_element: bool) -> str | None:
        """Return the class name for a schema name, or None.

        Args:
            namespace: The target namespace of the schema that declares it
            name: The complexType, simpleType or element name
            is_element: Whether the class was generated for an element

        Returns:
            The class name to emit, or None to keep the conventions.
        """
        table = self.elements if is_element else self.types
        return table.get((namespace or "", name))

    def names(self) -> set[str]:
        """Return every class name the table can produce."""
        return set(self.types.values()) | set(self.elements.values())

    @classmethod
    def load(cls, directory: Path) -> "ClassNames":
        """Load every json file of a directory into one table.

        Args:
            directory: The directory with one json file per namespace

        Returns:
            The class name table.

        Raises:
            CodegenError: If the directory or one of the files is unusable.
        """
        if not directory.is_dir():
            raise CodegenError(f"ClassNames directory not found: {directory}")

        obj = cls()
        for path in sorted(directory.glob("*.json")):
            obj.load_file(path)

        return obj

    def load_file(self, path: Path) -> None:
        """Load one namespace file into the table.

        Args:
            path: The json file path

        Raises:
            CodegenError: If the file is not a json object.
        """
        try:
            data = json.loads(path.read_text())
        except ValueError as e:
            raise CodegenError(f"ClassNames file is not valid json: {path}") from e

        if not isinstance(data, dict):
            raise CodegenError(f"ClassNames file is not a json object: {path}")

        namespace = data.get("namespace") or ""
        java_package = data.get("java_package")
        if java_package:
            self.java_packages[namespace] = java_package

        self.update(self.types, namespace, data.get(TYPES), TYPES, path)
        self.update(self.elements, namespace, data.get(ELEMENTS), ELEMENTS, path)

    @classmethod
    def update(
        cls,
        table: dict[tuple[str, str], str],
        namespace: str,
        entries: dict | None,
        kind: str,
        path: Path,
    ) -> None:
        """Merge one section of one file into the table.

        Args:
            table: The types or the elements table
            namespace: The namespace the file is for
            entries: The schema name to class name map, if any
            kind: The section name, for the messages
            path: The json file path, for the messages

        Raises:
            CodegenError: If the section is not a json object.
        """
        if entries is None:
            return

        if not isinstance(entries, dict):
            raise CodegenError(f"ClassNames {kind} is not a json object: {path}")

        for name, class_name in entries.items():
            if not isinstance(class_name, str) or not cls.is_valid(class_name):
                logger.warning(
                    "ClassNames: `%s` is not a valid class name, ignoring %s %s",
                    class_name,
                    kind,
                    name,
                )
                continue

            key = (namespace, name)
            current = table.get(key)
            if current is not None and current != class_name:
                logger.warning(
                    "ClassNames: %s %s is mapped twice, `%s` wins over `%s`",
                    kind,
                    name,
                    class_name,
                    current,
                )

            table[key] = class_name

    @classmethod
    def is_valid(cls, name: str) -> bool:
        """Return whether the name can be a python class name."""
        return name.isidentifier() and not iskeyword(name)
