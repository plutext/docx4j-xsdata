"""The docx4j fork's skipped content report.

Lenient parsing (``fail_on_unknown_properties=False`` and
``fail_on_unknown_attributes=False``) drops unknown elements and
attributes without a trace. This module collects them instead, when the
parser config asks for it.
"""

from dataclasses import dataclass, field
from typing import Any

from docx4j_xsdata.logger import logger

ELEMENT = "element"
ATTRIBUTE = "attribute"


@dataclass(frozen=True)
class SkippedNode:
    """A single element or attribute the parser dropped.

    Args:
        kind: Either `element` or `attribute`
        qname: The qualified name of the skipped element or attribute
        parent_qname: The qualified name of the element that contains it
        parent_class: The name of the class bound to the parent element
        path: The `/` joined qualified names of the ancestor elements,
            with the skipped item last, attributes prefixed with `@`
        line: The line number in the document, if the handler knows it
    """

    kind: str
    qname: str
    parent_qname: str | None = None
    parent_class: str | None = None
    path: str = ""
    line: int | None = None


@dataclass
class SkippedReport:
    """The elements and attributes a lenient parse dropped.

    The report is attached to a `ParserConfig` and is reachable
    through the parser, `parser.skipped`. It is cleared at the
    start of every parse.

    Args:
        log: Emit a warning through the `docx4j_xsdata` logger
            for every skipped element and attribute

    Attributes:
        items: The skipped elements and attributes. An element is
            recorded when it starts, an attribute when the element
            that carries it ends.
    """

    log: bool = True
    items: list[SkippedNode] = field(default_factory=list, compare=False)
    path: list[str] = field(default_factory=list, compare=False, repr=False, init=False)

    def __iter__(self) -> Any:
        """Yield the skipped nodes."""
        return iter(self.items)

    def __len__(self) -> int:
        """Return the number of skipped nodes."""
        return len(self.items)

    def __getitem__(self, index: int) -> SkippedNode:
        """Return the skipped node at the given index."""
        return self.items[index]

    def clear(self) -> None:
        """Forget everything, at the start of a parse."""
        self.items.clear()
        self.path.clear()

    def start_element(self, qname: str, skipped: bool, parent: Any) -> None:
        """Enter an element, record it if the parser is skipping it.

        Args:
            qname: The element qualified name
            skipped: Whether the parser built a skip node for it
            parent: The parent element node, or None if the parent
                is not a bound element, e.g. it's skipped as well
        """
        self.path.append(qname)

        if skipped and parent is not None:
            self.add(ELEMENT, qname, parent.meta, self.location())

    def end_element(self) -> None:
        """Leave an element."""
        if self.path:
            self.path.pop()

    def add_attribute(self, qname: str, meta: Any) -> None:
        """Record an attribute the parser dropped.

        Args:
            qname: The attribute qualified name
            meta: The class metadata of the element it appeared on
        """
        self.add(ATTRIBUTE, qname, meta, f"{self.location()}/@{qname}")

    def add(self, kind: str, qname: str, meta: Any, path: str) -> None:
        """Append a skipped node and warn about it.

        Args:
            kind: Either `element` or `attribute`
            qname: The skipped qualified name
            meta: The class metadata of the parent element
            path: The document path of the skipped item
        """
        self.items.append(
            SkippedNode(
                kind=kind,
                qname=qname,
                parent_qname=meta.qname,
                parent_class=meta.clazz.__name__,
                path=path,
            )
        )

        if self.log:
            logger.warning(
                "Skipped unknown %s %s in %s",
                kind,
                qname,
                meta.qname,
            )

    def location(self) -> str:
        """Return the current document path."""
        return "/".join(self.path)
