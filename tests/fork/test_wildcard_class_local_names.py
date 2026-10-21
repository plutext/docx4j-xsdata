"""docx4j fork: item 25's hook for a name no global element declares (stage 11, item 27).

docx4j-python CR-012 Phase A2, docx4j's CR-051 phase 2. Item 25's hook was
first asked for ``w:sdt``, a name with a global element of the wrong class.
WordprocessingML's ``w:tc`` has none at all: ``CT_Tc`` is declared only inside
``CT_Row`` and the row's controls, so in a lax wildcard (an ``mc:Choice`` among
a row's cells) the lookup by name finds nothing and the cell stays an
``AnyElement`` tree, lossless but invisible to a reader of typed cells.
docx4j-python now asks the hook for ``w:tr`` and ``w:tc`` too, and no code
here changed: these tests pin the behaviour that relies on.

* without the hook, such a name stays a wildcard tree and nothing is skipped;
* with it, the name is typed as its container binds it;
* a child the hook typed is itself an enclosing class of what it holds, so a
  branch nested in it is bound by it;
* a name with a global element is asked about too, before the lookup by name;
* item 26's table writes the typed child back under its element's name.
"""

from dataclasses import dataclass, field
from typing import Any

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.models.generics import AnyElement
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS = "urn:fork:local-names"
ROW = f"{{{NS}}}row"
CELL = f"{{{NS}}}cell"
INNER = f"{{{NS}}}inner"


@dataclass
class Choice:
    class Meta:
        name = "Choice"
        namespace = MC

    any_element: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##any"}
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
class Inner:
    """Declared only inside a cell: no global element."""

    class Meta:
        name = "CT_Inner"

    text: list[str] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )


@dataclass
class Cell:
    """Declared only inside a row (``CT_Tc``): no global element."""

    class Meta:
        name = "CT_Cell"

    para: list[str] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )
    inner: list[Inner] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )
    alternate: list[Alternate] = field(
        default_factory=list,
        metadata={"name": "AlternateContent", "type": "Element", "namespace": MC},
    )


@dataclass
class Row:
    """A global element (``w:tr``), which a table binds to the same class."""

    class Meta:
        name = "row"
        namespace = NS

    cell: list[Cell] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )
    alternate: list[Alternate] = field(
        default_factory=list,
        metadata={"name": "AlternateContent", "type": "Element", "namespace": MC},
    )


@dataclass
class Table:
    class Meta:
        name = "tbl"
        namespace = NS

    row: list[Row] = field(default_factory=list, metadata={"type": "Element"})
    alternate: list[Alternate] = field(
        default_factory=list,
        metadata={"name": "AlternateContent", "type": "Element", "namespace": MC},
    )


#: A cell-level element (each branch a cell, the cell holding a branch of its
#: own) and a row-level one (each branch a row).
DOCUMENT = (
    f'<tbl xmlns="{NS}" xmlns:mc="{MC}">'
    "<row><cell><para>a</para></cell>"
    "<mc:AlternateContent><mc:Choice><cell><para>b</para>"
    "<mc:AlternateContent><mc:Choice><inner><text>i</text></inner></mc:Choice>"
    "</mc:AlternateContent></cell></mc:Choice></mc:AlternateContent></row>"
    "<mc:AlternateContent><mc:Choice><row><cell><para>r</para></cell></row>"
    "</mc:Choice></mc:AlternateContent>"
    "</tbl>"
)

TRANSPARENT = (Choice, Alternate)
NAMES = frozenset({ROW, CELL, INNER})


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


def parse(source: str = DOCUMENT, hook: bool = False, seen: list | None = None) -> Any:
    context = XmlContext()
    kwargs: dict[str, Any] = {}
    if hook:
        kwargs["wildcard_class"] = by_container(context, seen)
        kwargs["wildcard_class_for"] = NAMES
    config = ParserConfig(
        fail_on_unknown_properties=False, skipped_report=True, **kwargs
    )
    parser = XmlParser(context=context, config=config)
    return parser.from_string(source, Table), parser


def only(container: Any) -> Any:
    (alternate,) = container.alternate
    (choice,) = alternate.choice
    (item,) = choice.any_element
    return item


def render(obj: Any) -> str:
    config = SerializerConfig(
        xml_declaration=False, element_names={Cell: CELL, Inner: INNER}
    )
    return XmlSerializer(config=config).render(obj, ns_map={None: NS, "mc": MC})


def test_without_the_hook_a_name_no_global_declares_stays_a_wildcard_tree() -> None:
    table, parser = parse()
    (row,) = table.row
    cell = only(row)
    assert isinstance(cell, AnyElement)
    assert cell.qname == CELL
    assert not parser.skipped.items, "lossless: the wildcard keeps the tree"


def test_with_the_hook_it_is_typed_as_its_container_binds_it() -> None:
    table, parser = parse(hook=True)
    (row,) = table.row
    cell = only(row)
    assert type(cell) is Cell
    assert cell.para == ["b"]
    assert not parser.skipped.items


def test_a_child_the_hook_typed_binds_a_branch_nested_in_it() -> None:
    seen: list = []
    table, _ = parse(hook=True, seen=seen)
    (row,) = table.row
    inner = only(only(row))
    assert inner == Inner(text=["i"])
    assert (INNER, (Choice, Alternate, Cell, Choice, Alternate, Row, Table)) in seen


def test_a_name_with_a_global_element_is_asked_about_first() -> None:
    seen: list = []
    table, _ = parse(hook=True, seen=seen)
    assert only(table) == Row(cell=[Cell(para=["r"])])
    assert (ROW, (Choice, Alternate, Table)) in seen


def test_written_back_under_the_element_names_and_read_again_equal() -> None:
    table, _ = parse(hook=True)
    xml = render(table)
    assert "CT_Cell" not in xml and "CT_Inner" not in xml and "xsi:type" not in xml
    assert xml == DOCUMENT
    again, parser = parse(xml, hook=True)
    assert again == table
    assert not parser.skipped.items
