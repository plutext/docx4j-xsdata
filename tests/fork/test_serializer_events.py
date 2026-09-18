"""docx4j fork: the same handler calls, over fewer frames and cheaper events.

CR-001 section 3.2, the fourth item. A child element's events used to travel
`convert_dataclass` -> `convert_value` -> `convert_list` -> `convert_value` ->
`convert_dataclass`, and a compound field's `convert_dataclass` ->
`convert_value` -> `convert_elements` -> `convert_choice` -> `convert_value` ->
`convert_dataclass`: four generator frames for every event of every element,
resumed once per event that passes through them. `convert_dataclass` and
`convert_choice` now take the decision `convert_value` would have taken, so the
events cross one or two frames instead of four, and `write` indexes its event
tuples instead of unpacking them into a list.

None of that may change what reaches the content handler, which is what this
module records and compares -- against an oracle carrying upstream v26.2's
`convert_dataclass`, `convert_value` and `convert_choice`.
"""

from typing import Any
from xml.sax.handler import ContentHandler

import pytest

from docx4j_xsdata.exceptions import XmlWriterError
from docx4j_xsdata.formats.dataclass.models.elements import XmlVar
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig
from docx4j_xsdata.formats.dataclass.serializers.mixins import (
    EventContentHandler,
    EventGenerator,
    EventIterator,
    XmlWriterEvent,
)
from docx4j_xsdata.utils import collections, namespaces
from tests.fork.test_serializer_fast_path import DOCUMENTS as FAST_DOCUMENTS
from tests.fork.test_serializer_fast_path import NS_MAP as FAST_NS_MAP
from tests.fork.test_serializer_namespaces import DOCUMENTS as NS_DOCUMENTS
from tests.fork.test_serializer_namespaces import PREFIX_MAPS

# ---------------------------------------------------------------------------
# a content handler that records what it is told
# ---------------------------------------------------------------------------


class RecordingHandler(ContentHandler):
    """Every call the writer makes, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []

    def startDocument(self) -> None:
        self.calls.append(("startDocument",))

    def endDocument(self) -> None:
        self.calls.append(("endDocument",))

    def startElementNS(self, name, qname, attrs) -> None:
        self.calls.append(("startElementNS", name, qname, dict(attrs)))

    def endElementNS(self, name, qname) -> None:
        self.calls.append(("endElementNS", name, qname))

    def characters(self, content) -> None:
        self.calls.append(("characters", content))

    def startPrefixMapping(self, prefix, uri) -> None:
        self.calls.append(("startPrefixMapping", prefix, uri))

    def endPrefixMapping(self, prefix) -> None:
        self.calls.append(("endPrefixMapping", prefix))


class RecordingWriter(EventContentHandler):
    """An `EventContentHandler` over a `RecordingHandler`."""

    def build_handler(self) -> ContentHandler:
        return RecordingHandler()


# ---------------------------------------------------------------------------
# upstream v26.2's dispatch, as the oracle
# ---------------------------------------------------------------------------


class UpstreamEventGenerator(EventGenerator):
    """`convert_dataclass`, `convert_value` and `convert_choice`, upstream's."""

    def convert_dataclass(
        self,
        obj: Any,
        namespace: str | None = None,
        qname: str | None = None,
        nillable: bool = False,
        xsi_type: str | None = None,
    ) -> EventIterator:
        meta = self.context.build(
            obj.__class__, namespace, globalns=self.config.globalns
        )
        qname = qname or meta.qname
        nillable = nillable or meta.nillable
        namespace, _tag = namespaces.split_qname(qname)

        yield XmlWriterEvent.START, qname

        for key, value in self.next_attribute(
            obj,
            meta,
            nillable,
            xsi_type,
            self.config.ignore_default_attributes,
            self.config.bool_format,
        ):
            yield XmlWriterEvent.ATTR, key, value

        for var, value in self.next_value(obj, meta):
            if var.wrapper_qname:
                yield XmlWriterEvent.START, var.wrapper_qname

            yield from self.convert_value(value, var, namespace)

            if var.wrapper_qname:
                yield XmlWriterEvent.END, var.wrapper_qname

        yield XmlWriterEvent.END, qname

    def convert_value(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        if var.mixed:
            yield from self.convert_mixed_content(value, var, namespace)
        elif var.is_text:
            yield from self.convert_data(value, var)
        elif var.tokens:
            yield from self.convert_tokens(value, var, namespace)
        elif var.is_elements:
            yield from self.convert_elements(value, var, namespace)
        elif var.list_element and collections.is_array(value):
            yield from self.convert_list(value, var, namespace)
        else:
            yield from self.convert_any_type(value, var, namespace)

    def convert_choice(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        from docx4j_xsdata.exceptions import SerializerError

        if isinstance(value, self.context.class_type.derived_element):
            choice = var.find_choice(value.qname)
            value = value.value

            if self.context.class_type.is_model(value):
                func = self.convert_xsi_type
            else:
                func = self.convert_element
        elif isinstance(value, self.context.class_type.any_element) and value.qname:
            choice = var.find_choice(value.qname)
            func = self.convert_any_type
        else:
            check_subclass = self.context.class_type.is_model(value)
            choice = var.find_value_choice(value, check_subclass)
            func = self.convert_value

            if not choice and check_subclass:
                func = self.convert_xsi_type
                choice = var

        if not choice:
            raise SerializerError(
                f"XmlElements undefined choice: `{var.name}` for `{type(value)}`"
            )

        yield from func(value, choice, namespace)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def calls(
    obj: Any,
    ns_map: dict,
    generator: type[EventGenerator] = EventGenerator,
) -> list[tuple]:
    """The handler calls one render of `obj` makes."""
    writer = RecordingWriter(config=SerializerConfig(), ns_map=dict(ns_map))
    writer.write(generator().generate(obj))
    return writer.handler.calls  # type: ignore[attr-defined]


CASES = [
    pytest.param(doc, ns_map, id=f"{doc_id}-{map_id}")
    for doc_id, doc in NS_DOCUMENTS.items()
    for map_id, ns_map in PREFIX_MAPS.items()
] + [
    pytest.param(doc, FAST_NS_MAP, id=f"fast-{doc_id}")
    for doc_id, doc in FAST_DOCUMENTS.items()
]


# ---------------------------------------------------------------------------
# the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("obj", "ns_map"), CASES)
def test_the_handler_calls_are_upstreams(obj, ns_map) -> None:
    """Same calls, same arguments, same order: the frames are all that moved."""
    assert calls(obj, ns_map) == calls(obj, ns_map, UpstreamEventGenerator)


@pytest.mark.parametrize(("obj", "ns_map"), CASES)
def test_the_handler_is_told_something(obj, ns_map) -> None:
    """A guard on the comparison above: an empty stream would pass it."""
    recorded = calls(obj, ns_map)

    assert recorded[0] == ("startDocument",)
    assert recorded[-1] == ("endDocument",)
    assert any(call[0] == "startElementNS" for call in recorded)


# ---------------------------------------------------------------------------
# and `write` still takes the four events, one at a time
# ---------------------------------------------------------------------------


def test_a_hand_fed_event_stream_still_works() -> None:
    """The dispatch is indexed rather than unpacked, and nothing else."""
    writer = RecordingWriter(config=SerializerConfig(), ns_map={"a": "urn:a"})
    writer.write(
        iter(
            [
                (XmlWriterEvent.START, "{urn:a}root"),
                (XmlWriterEvent.ATTR, "k", "v"),
                (XmlWriterEvent.DATA, "text"),
                (XmlWriterEvent.END, "{urn:a}root"),
            ]
        )
    )

    assert writer.handler.calls == [  # type: ignore[attr-defined]
        ("startDocument",),
        ("startPrefixMapping", "a", "urn:a"),
        ("startElementNS", ("urn:a", "root"), "", {(None, "k"): "v"}),
        ("characters", "text"),
        ("endElementNS", ("urn:a", "root"), "{urn:a}root"),
        ("endPrefixMapping", "a"),
        ("endDocument",),
    ]


def test_an_unknown_event_is_still_an_error() -> None:
    """The `else` of the dispatch."""
    writer = RecordingWriter(config=SerializerConfig(), ns_map={})

    with pytest.raises(XmlWriterError, match="Unhandled event: `nope`"):
        writer.write(iter([("nope", "x")]))
