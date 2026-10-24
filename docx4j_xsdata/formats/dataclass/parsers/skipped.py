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

#: The reasons a value is kept as its text, `KeptValue.reason`.
KEPT_EXACT = "exact"
KEPT_INVALID = "invalid"


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


@dataclass(frozen=True)
class KeptValue:
    """A value the parser bound as the text it was read with.

    docx4j fork, stage 13. It is not skipped content: the text is in the tree, in the
    field `field_name` of an instance of `parent_class`, and the serializer
    writes it back as read.

    Args:
        reason: `exact` (`KEPT_EXACT`) for a value `ParserConfig.exact_types`
            kept on purpose, which XSD's whitespace rule would have
            converted; `invalid` (`KEPT_INVALID`) for a value no rule
            converts, which also raised the usual conversion warning
        qname: The qualified name of the attribute, or of the element
            whose text the value is
        text: The value as read, which is what the field holds
        field_name: The name of the field it is bound to
        parent_class: The name of the class whose field it fills
        path: The `/` joined qualified names of the ancestor elements,
            with the value's element last and an attribute after it,
            prefixed with `@`
    """

    reason: str
    qname: str
    text: Any
    field_name: str
    parent_class: str
    path: str = ""


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
            that carries it ends, or starts if that element is of
            simple type.
        kept: docx4j fork, stage 13: the values bound as the text they
            were read with (`KeptValue`), in document order. They are
            not skipped content, so they are apart from `items` and
            neither the report's length nor its iteration counts them.
    """

    log: bool = True
    items: list[SkippedNode] = field(default_factory=list, compare=False)
    kept: list[KeptValue] = field(default_factory=list, compare=False)
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
        self.kept.clear()
        self.path.clear()

    def add_kept(self, reason: str, meta: Any, var: Any, text: Any) -> None:
        """Record a value bound as the text it was read with.

        docx4j fork, stage 13. An attribute is bound when its element
        ends, and an element's text when it ends, so the path's last step
        is the value's element in both cases.

        Args:
            reason: `KEPT_EXACT` or `KEPT_INVALID`
            meta: The class metadata of the class whose field the value
                fills
            var: The field's metadata
            text: The value as read
        """
        location = self.location()
        if var.is_attribute:
            qname = var.qname
            path = f"{location}/@{qname}"
        else:
            qname = self.path[-1] if self.path else var.qname
            path = location

        self.kept.append(
            KeptValue(
                reason=reason,
                qname=qname,
                text=text,
                field_name=var.name,
                parent_class=meta.clazz.__name__,
                path=path,
            )
        )

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

    def add_attribute(
        self, qname: str, meta: Any, element: str | None = None
    ) -> None:
        """Record an attribute the parser dropped.

        Args:
            qname: The attribute qualified name
            meta: The class metadata of the element it appeared on or,
                for a simple-typed element, of the class whose field
                the element fills
            element: The qualified name of the simple-typed element that
                carries the attribute. Such an element has no class of
                its own and is reported when it starts, before the path
                enters it, so it's named here. It is the node's
                `parent_qname` and the path's last step before the
                attribute.
        """
        if element is None:
            self.add(ATTRIBUTE, qname, meta, f"{self.location()}/@{qname}")
        else:
            path = f"{self.location()}/{element}/@{qname}"
            self.add(ATTRIBUTE, qname, meta, path, parent_qname=element)

    def add(
        self,
        kind: str,
        qname: str,
        meta: Any,
        path: str,
        parent_qname: str | None = None,
    ) -> None:
        """Append a skipped node and warn about it.

        Args:
            kind: Either `element` or `attribute`
            qname: The skipped qualified name
            meta: The class metadata of the parent element
            path: The document path of the skipped item
            parent_qname: The parent's qualified name, when it is not
                the meta's: a simple-typed element's
        """
        parent = parent_qname or meta.qname
        self.items.append(
            SkippedNode(
                kind=kind,
                qname=qname,
                parent_qname=parent,
                parent_class=meta.clazz.__name__,
                path=path,
            )
        )

        if self.log:
            logger.warning(
                "Skipped unknown %s %s in %s",
                kind,
                qname,
                parent,
            )

    def location(self) -> str:
        """Return the current document path."""
        return "/".join(self.path)
