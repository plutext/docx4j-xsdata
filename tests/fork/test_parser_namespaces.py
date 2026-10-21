"""docx4j fork: `ParserConfig(on_namespaces=..., namespaces_for=...)`.

docx4j-python CR-011 Q3. A binding keeps an attribute's value as a string and
not the namespace declarations a prefix in it resolved through. Markup
compatibility needs them: ``<mc:Choice Requires="wps">`` names a namespace by
the prefix in scope at the element, and a producer may bind any prefix it
likes (docx4j's probe binds the wps namespace to ``shape2010``). The hook hands
a binding layer each object built for an element it asked for, typed or a
wildcard, with the declarations in scope there.

These tests pin that the hook is off by default and changes nothing about the
tree, that it sees exactly the elements asked for, typed and wildcard, with
the declarations of the element itself and of its ancestors, and what it does
not see.
"""

from dataclasses import dataclass, field
from typing import Any

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.models.generics import AnyElement
from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import XmlEventHandler

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
CHOICE = f"{{{MC}}}Choice"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
NS = "urn:fork:namespaces"


@dataclass
class Choice:
    """A typed ``mc:Choice``: its ``Requires`` and whatever it holds."""

    class Meta:
        name = "Choice"
        namespace = MC

    requires: str | None = field(default=None, metadata={"name": "Requires", "type": "Attribute"})
    any_element: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##any"}
    )


@dataclass
class Holder:
    """A root holding typed choices, and a wildcard for anything else."""

    class Meta:
        name = "holder"
        namespace = NS

    choice: list[Choice] = field(
        default_factory=list, metadata={"name": "Choice", "type": "Element", "namespace": MC}
    )
    other: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##other"}
    )


DOCUMENT = (
    f'<holder xmlns="{NS}" xmlns:mc="{MC}" xmlns:wps="{WPS}">'
    f'<mc:Choice xmlns:shape2010="{WPS}" Requires="shape2010"><shape2010:wsp/></mc:Choice>'
    '<mc:Choice Requires="wps"><wps:wsp/></mc:Choice>'
    f'<x:wrapper xmlns:x="urn:fork:wrapper" xmlns:zz9="urn:zz9">'
    '<mc:Choice Requires="zz9"><zz9:thing/></mc:Choice>'
    "</x:wrapper>"
    "</holder>"
)


def parse(source: str = DOCUMENT, handler: Any = None, **kwargs: Any) -> Any:
    """Parse `source` with a context and a config of their own."""
    config = ParserConfig(fail_on_unknown_properties=False, **kwargs)
    parser = XmlParser(context=XmlContext(), config=config)
    if handler is not None:
        parser.handler = handler
    return parser.from_string(source, Holder)


def record(seen: list) -> Any:
    """A hook that keeps what it was given, the map copied."""

    def on_namespaces(qname: str, obj: Any, ns_map: dict) -> None:
        seen.append((qname, obj, dict(ns_map)))

    return on_namespaces


# ---------------------------------------------------------------------------
# off by default
# ---------------------------------------------------------------------------


def test_the_hook_is_off_by_default() -> None:
    """Nothing to call and no names asked for."""
    config = ParserConfig()
    assert config.on_namespaces is None
    assert config.namespaces_for == frozenset()
    assert len(parse().choice) == 2


def test_the_hook_changes_nothing_about_the_tree() -> None:
    """The same object, hook or no hook."""
    seen: list = []
    assert parse() == parse(on_namespaces=record(seen), namespaces_for=frozenset({CHOICE}))
    assert seen


def test_no_names_asked_for_means_no_calls() -> None:
    """A hook with nothing to look for is never called."""
    seen: list = []
    parse(on_namespaces=record(seen))
    assert seen == []


# ---------------------------------------------------------------------------
# what it sees
# ---------------------------------------------------------------------------


def test_typed_and_wildcard_elements_are_both_seen() -> None:
    """The two typed choices, then the one inside the wildcard, in document order."""
    seen: list = []
    obj = parse(on_namespaces=record(seen), namespaces_for=frozenset({CHOICE}))
    assert [qname for qname, _obj, _map in seen] == [CHOICE, CHOICE, CHOICE]
    assert seen[0][1] is obj.choice[0]
    assert seen[1][1] is obj.choice[1]
    wildcard = seen[2][1]
    assert isinstance(wildcard, AnyElement)
    assert wildcard is obj.other[0].children[0]
    assert wildcard.attributes["Requires"] == "zz9"


def test_the_map_is_the_declarations_in_scope() -> None:
    """The element's own declarations and its ancestors'; the default namespace under None."""
    seen: list = []
    parse(on_namespaces=record(seen), namespaces_for=frozenset({CHOICE}))
    own, inherited, nested = (ns_map for _qname, _obj, ns_map in seen)
    assert own["shape2010"] == WPS
    assert own["wps"] == WPS
    assert own[None] == NS
    assert "shape2010" not in inherited
    assert inherited["wps"] == WPS
    assert nested["zz9"] == "urn:zz9"
    assert nested["mc"] == MC


def test_only_the_names_asked_for() -> None:
    """Asking for the wrapper sees the wrapper alone."""
    seen: list = []
    parse(on_namespaces=record(seen), namespaces_for=frozenset({"{urn:fork:wrapper}wrapper"}))
    assert [type(obj).__name__ for _qname, obj, _map in seen] == ["AnyElement"]
    assert seen[0][2]["x"] == "urn:fork:wrapper"


def test_the_hook_runs_after_on_bind() -> None:
    """``on_bind`` has had the object when ``on_namespaces`` sees it."""
    order: list[str] = []

    def on_bind(obj: Any) -> None:
        if isinstance(obj, Choice):
            order.append("bind")

    def on_namespaces(qname: str, obj: Any, ns_map: dict) -> None:
        if isinstance(obj, Choice):
            order.append("namespaces")

    parse(on_bind=on_bind, on_namespaces=on_namespaces, namespaces_for=frozenset({CHOICE}))
    assert order == ["bind", "namespaces", "bind", "namespaces"]


def test_the_hook_may_replace_a_value_on_the_object() -> None:
    """What a binding layer does with it: here, the ``Requires`` value replaced in place."""

    def on_namespaces(qname: str, obj: Any, ns_map: dict) -> None:
        if isinstance(obj, Choice):
            obj.requires = " ".join(ns_map.get(p, "?") for p in obj.requires.split())

    obj = parse(on_namespaces=on_namespaces, namespaces_for=frozenset({CHOICE}))
    assert [c.requires for c in obj.choice] == [WPS, WPS]


def test_the_event_handler_gives_the_same_maps() -> None:
    """The pure-Python event handler, which keeps its own map, agrees with lxml's."""
    by_lxml: list = []
    by_events: list = []
    parse(on_namespaces=record(by_lxml), namespaces_for=frozenset({CHOICE}))
    config = ParserConfig(
        fail_on_unknown_properties=False,
        on_namespaces=record(by_events),
        namespaces_for=frozenset({CHOICE}),
    )
    XmlParser(context=XmlContext(), config=config, handler=XmlEventHandler).from_string(DOCUMENT, Holder)
    assert [m for _q, _o, m in by_lxml] == [m for _q, _o, m in by_events]
