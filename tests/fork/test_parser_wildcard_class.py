"""docx4j fork: `ParserConfig(wildcard_class=..., wildcard_class_for=...)`.

docx4j-python CR-012 Phase A, docx4j's ``McBranchSdt`` (its CR-051 section
11.3). A lax wildcard types a child it meets by the child's name alone
(``XmlContext.find_type``), and one name may be declared by several types,
each in its own context: WordprocessingML's ``w:sdt`` is ``CT_SdtBlock`` in a
body, ``CT_SdtRun`` in a paragraph, ``CT_SdtRow`` in a table and
``CT_SdtCell`` in a row, and only the first is a global element. Markup
compatibility puts any of them straight into an ``mc:Choice``'s wildcard, so
the name alone gives the wrong class at three levels of four, and the
content the right class would bind is skipped.

The hook lets a binding layer choose the class from the element's context:
it is called with the qualified name and the classes of the enclosing
elements, innermost first, for the names it asks for, before the ordinary
lookup.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.models.generics import AnyElement
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import XmlEventHandler

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS = "urn:fork:wildcard-class"
ITEM = f"{{{NS}}}item"


@dataclass
class BlockItem:
    """The global ``item``: what a lookup by name finds."""

    class Meta:
        name = "item"
        namespace = NS

    para: list[str] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )


@dataclass
class RowItem:
    """An ``item`` as a row declares it: a type of its own, no global element."""

    class Meta:
        name = "CT_RowItem"

    cell: list[str] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )


@dataclass
class Choice:
    class Meta:
        name = "Choice"
        namespace = MC

    any_element: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##any"}
    )


@dataclass
class Skipping:
    """A wildcard that keeps its content untyped."""

    class Meta:
        name = "skipping"
        namespace = NS

    any_element: list[object] = field(
        default_factory=list,
        metadata={"type": "Wildcard", "namespace": "##any", "process_contents": "skip"},
    )


@dataclass
class Alternate:
    class Meta:
        name = "AlternateContent"
        namespace = MC

    choice: list[Choice] = field(
        default_factory=list, metadata={"name": "Choice", "type": "Element"}
    )


@dataclass
class Body:
    class Meta:
        name = "body"
        namespace = NS

    item: list[BlockItem] = field(default_factory=list, metadata={"type": "Element"})
    alternate: list[Alternate] = field(
        default_factory=list,
        metadata={"name": "AlternateContent", "type": "Element", "namespace": MC},
    )
    skipping: list[Skipping] = field(default_factory=list, metadata={"type": "Element"})


@dataclass
class Row:
    class Meta:
        name = "row"
        namespace = NS

    item: list[RowItem] = field(default_factory=list, metadata={"type": "Element"})
    alternate: list[Alternate] = field(
        default_factory=list,
        metadata={"name": "AlternateContent", "type": "Element", "namespace": MC},
    )


@dataclass
class Doc:
    class Meta:
        name = "doc"
        namespace = NS

    body: Body | None = field(default=None, metadata={"type": "Element"})
    row: Row | None = field(default=None, metadata={"type": "Element"})


DOCUMENT = (
    f'<doc xmlns="{NS}" xmlns:mc="{MC}">'
    "<body><mc:AlternateContent><mc:Choice><item><para>p</para></item></mc:Choice>"
    "</mc:AlternateContent>"
    "<skipping><item><para>s</para></item></skipping></body>"
    "<row><mc:AlternateContent><mc:Choice><item><cell>c</cell></item></mc:Choice>"
    "</mc:AlternateContent></row>"
    "</doc>"
)

TRANSPARENT = (Choice, Alternate)


def by_container(context: XmlContext, seen: list | None = None) -> Any:
    """The class the nearest enclosing element that is not a wrapper binds the name to."""

    def wildcard_class(qname: str, ancestors: tuple[type, ...]) -> type | None:
        if seen is not None:
            seen.append((qname, ancestors))
        for clazz in ancestors:
            if clazz in TRANSPARENT:
                continue
            for var in context.build(clazz).get_children(qname):
                if var.clazz is not None:
                    return var.clazz
            return None
        return None

    return wildcard_class


def parse(
    source: str = DOCUMENT, handler: Any = None, hook: bool = False, **kwargs: Any
) -> Any:
    context = XmlContext()
    if hook:
        kwargs.setdefault("wildcard_class", by_container(context))
        kwargs.setdefault("wildcard_class_for", frozenset({ITEM}))
    config = ParserConfig(
        fail_on_unknown_properties=False, skipped_report=True, **kwargs
    )
    parser = XmlParser(context=context, config=config)
    if handler is not None:
        parser.handler = handler
    return parser.from_string(source, Doc), parser


def branch_item(container: Any) -> Any:
    (alternate,) = container.alternate
    (choice,) = alternate.choice
    (item,) = choice.any_element
    return item


# ---------------------------------------------------------------------------
# off by default: the name alone
# ---------------------------------------------------------------------------


def test_the_hook_is_off_by_default() -> None:
    config = ParserConfig()
    assert config.wildcard_class is None
    assert config.wildcard_class_for == frozenset()


def test_without_the_hook_the_name_alone_chooses_and_the_rows_content_is_lost() -> None:
    doc, parser = parse()
    assert isinstance(branch_item(doc.body), BlockItem)
    item = branch_item(doc.row)
    assert isinstance(item, BlockItem)
    assert item.para == []
    assert any("cell" in str(entry) for entry in parser.skipped.items)


# ---------------------------------------------------------------------------
# with the hook: the container chooses
# ---------------------------------------------------------------------------


def test_with_the_hook_each_branch_takes_its_containers_class() -> None:
    doc, parser = parse(hook=True)
    assert branch_item(doc.body) == BlockItem(para=["p"])
    assert branch_item(doc.row) == RowItem(cell=["c"])
    assert not parser.skipped.items


def test_the_hook_sees_the_enclosing_classes_innermost_first() -> None:
    seen: list = []
    context = XmlContext()
    config = ParserConfig(
        fail_on_unknown_properties=False,
        wildcard_class=by_container(context, seen),
        wildcard_class_for=frozenset({ITEM}),
    )
    XmlParser(context=context, config=config).from_string(DOCUMENT, Doc)
    assert seen == [
        (ITEM, (Choice, Alternate, Body, Doc)),
        (ITEM, (Choice, Alternate, Row, Doc)),
    ]


def test_only_the_names_asked_for_reach_the_hook() -> None:
    seen: list = []
    context = XmlContext()
    doc, _ = parse(
        hook=True,
        wildcard_class=by_container(context, seen),
        wildcard_class_for=frozenset({f"{{{NS}}}other"}),
    )
    assert seen == []
    assert isinstance(branch_item(doc.row), BlockItem)


def test_a_hook_answering_none_leaves_the_ordinary_lookup() -> None:
    doc, _ = parse(hook=True, wildcard_class=lambda qname, ancestors: None)
    assert isinstance(branch_item(doc.row), BlockItem)


def test_a_skip_wildcard_never_asks() -> None:
    seen: list = []
    context = XmlContext()
    doc, _ = parse(hook=True, wildcard_class=by_container(context, seen))
    (skipping,) = doc.body.skipping
    (kept,) = skipping.any_element
    assert isinstance(kept, AnyElement)
    assert all(ancestors[0] is not Skipping for _, ancestors in seen)


def test_typed_content_outside_a_wildcard_never_asks() -> None:
    seen: list = []
    context = XmlContext()
    source = f'<doc xmlns="{NS}"><row><item><cell>x</cell></item></row></doc>'
    doc, _ = parse(source, hook=True, wildcard_class=by_container(context, seen))
    assert doc.row.item == [RowItem(cell=["x"])]
    assert seen == []


@pytest.mark.parametrize("handler", [None, XmlEventHandler], ids=["lxml", "native"])
def test_both_event_handlers_agree(handler: Any) -> None:
    doc, _ = parse(handler=handler, hook=True)
    assert branch_item(doc.row) == RowItem(cell=["c"])
    assert branch_item(doc.body) == BlockItem(para=["p"])
