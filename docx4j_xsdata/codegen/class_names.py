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
  "elements": {"document": "Document", "ins": "RunIns", "t@CT_R": "RT"}
}
```

`types` maps the name of a complexType or simpleType in that namespace,
`elements` the name of a global or local element, to the name of the
class the generator emits for it. Names that are not in the table keep
the naming conventions. A name from the table is emitted verbatim: it is
applied before the case convention, not through it.

An `elements` key may carry a **scope**, `element@EnclosingType`, the
analogue of JAXB's `@XmlElementDecl(scope=...)`. The enclosing type is
read in the namespace of the file the entry is written in, so `t@CT_R`
in the wml file is wml's `CT_R` and not the `CT_R` of another namespace
that happens to hold a wml element. It addresses the one
element of the one compound field the generator invented an intermediate
class for (`DisambiguateChoices`, `w:t` of `CT_R` where `w:t`,
`w:instrText` and `w:delInstrText` all have the type `CT_Text`). Those
classes have no xml identity of their own -- the element name lives in the
`choices` metadata of the field -- and JAXB had no class for them either,
it had one `JAXBElement` per name over the shared type. An unscoped entry
therefore never renames them; only a scoped one does.
"""

import json
from dataclasses import dataclass, field
from keyword import iskeyword
from pathlib import Path

from docx4j_xsdata.codegen.exceptions import CodegenError
from docx4j_xsdata.logger import logger
from docx4j_xsdata.utils.namespaces import build_qname

TYPES = "types"
ELEMENTS = "elements"
SCOPE_SEPARATOR = "@"


@dataclass
class ClassNames:
    """An explicit schema name to class name table, by namespace.

    Attributes:
        types: The (namespace, type name) to class name map
        elements: The (namespace, element name) to class name map
        scoped: The (namespace, element name, enclosing type qualified
            name) to class name map, from the `element@EnclosingType`
            keys; the enclosing type is qualified with the namespace of
            the file the entry came from
        java_packages: The namespace to java package map, informative
    """

    types: dict[tuple[str, str], str] = field(default_factory=dict)
    elements: dict[tuple[str, str], str] = field(default_factory=dict)
    scoped: dict[tuple[str, str, str], str] = field(default_factory=dict)
    java_packages: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        """Return the total number of entries."""
        return len(self.types) + len(self.elements) + len(self.scoped)

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

    def find_scoped(self, namespace: str | None, name: str, scope: str) -> str | None:
        """Return the class name for an element in one enclosing type.

        Args:
            namespace: The target namespace of the schema that declares it
            name: The element name
            scope: The qualified name of the type whose compound field
                declares it

        Returns:
            The class name to emit, or None to keep the conventions.
        """
        return self.scoped.get((namespace or "", name, scope))

    def names(self) -> set[str]:
        """Return every class name the table can produce."""
        return (
            set(self.types.values())
            | set(self.elements.values())
            | set(self.scoped.values())
        )

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

        self.update(namespace, data.get(TYPES), TYPES, path)
        self.update(namespace, data.get(ELEMENTS), ELEMENTS, path)

    def update(
        self,
        namespace: str,
        entries: dict | None,
        kind: str,
        path: Path,
    ) -> None:
        """Merge one section of one file into the table.

        Args:
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
            if not isinstance(class_name, str) or not self.is_valid(class_name):
                logger.warning(
                    "ClassNames: `%s` is not a valid class name, ignoring %s %s",
                    class_name,
                    kind,
                    name,
                )
                continue

            table: dict[tuple, str]
            key: tuple
            if kind == ELEMENTS and SCOPE_SEPARATOR in name:
                local, _, scope = name.partition(SCOPE_SEPARATOR)
                table = self.scoped
                key = (namespace, local, build_qname(namespace, scope))
            elif kind == ELEMENTS:
                table, key = self.elements, (namespace, name)
            else:
                table, key = self.types, (namespace, name)

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
