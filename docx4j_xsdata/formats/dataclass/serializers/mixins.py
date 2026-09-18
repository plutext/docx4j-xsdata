import abc
from abc import ABC
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from io import TextIOBase
from typing import (
    Any,
    Final,
    Literal,
    TypeAlias,
)
from xml.etree.ElementTree import QName
from xml.sax.handler import ContentHandler

from docx4j_xsdata.exceptions import SerializerError, XmlWriterError
from docx4j_xsdata.formats.converter import converter
from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.models.elements import XmlMeta, XmlVar
from docx4j_xsdata.formats.dataclass.serializers.config import (
    BOOL_NUMERIC,
    BOOL_WORDS,
    SerializerConfig,
)
from docx4j_xsdata.models.enums import DataType, Namespace, QNames
from docx4j_xsdata.utils import collections, namespaces
from docx4j_xsdata.utils.constants import EMPTY_MAP
from docx4j_xsdata.utils.namespaces import generate_prefix, split_qname

XSI_NIL = (Namespace.XSI.uri, "nil")


class XmlWriterEvent:
    """Event names."""

    START: Final = "start"
    ATTR: Final = "attr"
    DATA: Final = "data"
    END: Final = "end"


StartEvent: TypeAlias = tuple[Literal["start"], str]
AttrEvent: TypeAlias = tuple[Literal["attr"], str, Any]
DataEvent: TypeAlias = tuple[Literal["data"], str]
EndEvent: TypeAlias = tuple[Literal["end"], str]

EventIterator = Iterator[StartEvent | AttrEvent | DataEvent | EndEvent]


class EventHandler(abc.ABC):
    """A consistency wrapper for sax events.

    Args:
        config: The serializer config instance
        ns_map: A user defined namespace prefix-URI map

    Attributes:
        in_tail: Specifies whether the text content has been written
        tail: The current element tail content
        attrs: The current element attributes
        ns_context: The namespace context queue
        pending_tag: The pending element namespace, name tuple
        pending_prefixes: The pending element namespace prefixes
        ns_uris: docx4j fork: the URIs of the current prefix map, indexed
        uri_context: docx4j fork: the ns_uris queue, one entry per ns_context
        ns_dirty: docx4j fork: whether the pending element added a prefix of
            its own to the map it inherited from its parent
    """

    __slots__ = (
        "attrs",
        "config",
        # Instance attributes
        "in_tail",
        "ns_context",
        "ns_dirty",
        "ns_map",
        "ns_uris",
        "pending_prefixes",
        "pending_tag",
        "tail",
        "uri_context",
    )

    def __init__(self, config: SerializerConfig, ns_map: dict):
        """Initialize the event handler."""
        self.config = config
        self.ns_map = ns_map

        self.in_tail = False
        self.tail: str | None = None
        self.attrs: dict = {}
        self.ns_context: list[dict] = []
        self.pending_tag: tuple | None = None
        self.pending_prefixes: list[list] = []

        # docx4j fork: the prefix map, indexed and shared copy-on-write.
        self.ns_uris: set[str] = set(ns_map.values())
        self.uri_context: list[set] = []
        self.ns_dirty = False

    def own_ns_map(self) -> None:
        """Give the pending element its own copy of the prefix map.

        docx4j fork. An element's namespace context is the parent's until
        something actually puts a prefix in it, which for a document that
        declares its namespaces on the root never happens. Until then the
        frame holds the *same* dict object as its parent, which is what
        :meth:`start_namespaces` tests for.
        """
        context = self.ns_context
        if len(context) > 1 and context[-1] is context[-2]:
            self.ns_map = context[-1] = dict(self.ns_map)
            self.ns_uris = self.uri_context[-1] = set(self.ns_uris)

    def reindex_namespaces(self) -> None:
        """Rebuild the URI index of the current prefix map.

        docx4j fork. Call it after a change to the map that is not a plain
        addition, e.g. the default namespace being reset.
        """
        self.ns_uris = uris = set(self.ns_map.values())
        if self.uri_context:
            self.uri_context[-1] = uris

    def write(self, events: EventIterator) -> None:
        """Feed the sax content handler with events.

        The receiver will also add additional root attributes
        like xsi or no namespace location.

        Args:
            events: An iterator of sax events

        Raises:
            XmlWriterError: On unknown events.
        """
        # docx4j fork: the render owns its prefix map, so the element frames
        # below can share it copy-on-write, and indexes its URIs once.
        self.ns_map = dict(self.ns_map)
        self.ns_uris = set(self.ns_map.values())
        self.ns_dirty = False

        self.start_document()

        if self.config.schema_location:
            self.add_attribute(
                QNames.XSI_SCHEMA_LOCATION,
                self.config.schema_location,
                root=True,
            )

        if self.config.no_namespace_schema_location:
            self.add_attribute(
                QNames.XSI_NO_NAMESPACE_SCHEMA_LOCATION,
                self.config.no_namespace_schema_location,
                root=True,
            )

        # docx4j fork: `for name, *args in events` builds a list for every
        # event; there are about seven per element. The events are fixed-width
        # tuples, so index them.
        for event in events:
            name = event[0]
            if name == XmlWriterEvent.START:
                self.start_tag(event[1])
            elif name == XmlWriterEvent.END:
                self.end_tag(event[1])
            elif name == XmlWriterEvent.ATTR:
                self.add_attribute(event[1], event[2])
            elif name == XmlWriterEvent.DATA:
                self.set_data(event[1])
            else:
                raise XmlWriterError(f"Unhandled event: `{name}`")

        self.end_document()

    def start_tag(self, qname: str) -> None:
        """Start tag notification receiver.

        The receiver will flush the start of any pending element, create
        new namespaces context and queue the current tag for generation.

        Args:
            qname: The qualified name of the starting element
        """
        self.flush_start(False)

        # docx4j fork: the frame starts as the parent's map, copied only if
        # something adds to it (:meth:`own_ns_map`).
        self.ns_context.append(self.ns_map)
        self.uri_context.append(self.ns_uris)
        self.ns_dirty = False

        self.pending_tag = split_qname(qname)
        self.add_namespace(self.pending_tag[0])

    def add_attribute(self, qname: str, value: Any, root: bool = False) -> None:
        """Add attribute notification receiver.

        The receiver will convert the key to a namespace, name tuple and
        convert the value to string. Internally the converter will also
        generate any missing namespace prefixes.

        Args:
            qname: The qualified name of the attribute
            value: The value of the attribute
            root: Specifies if attribute is for the root element

        Raises:
            XmlWriterError: If it's not a root element attribute
                and not no element is pending to start.
        """
        if not self.pending_tag and not root:
            raise XmlWriterError("Empty pending tag.")

        if self.is_xsi_type(qname, value):
            value = QName(value)

        name_tuple = split_qname(qname)
        self.attrs[name_tuple] = self.encode_data(value)

    def add_namespace(self, uri: str | None) -> None:
        """Add the given uri to the current namespace context.

         If the uri empty or a prefix already exists, skip silently.

        Args:
            uri: The namespace URI
        """
        # docx4j fork: `prefix_exists` scans the map's values; the index makes
        # the check, which happens once per element and once per attribute, a
        # set lookup, and the map is only copied when the answer is no.
        if uri and uri not in self.ns_uris:
            self.own_ns_map()
            generate_prefix(uri, self.ns_map)
            self.ns_uris.add(uri)
            self.ns_dirty = True

    def set_data(self, data: Any) -> None:
        """Set data notification receiver.

        The receiver will convert the data to string, flush any previous
        pending start element and send it to the handler for generation.

        If the text content of the tag has already been generated then
        treat the current data as element tail content and queue it to
        be generated when the tag ends.

        Args:
            data: The element text or tail content
        """
        value = self.encode_data(data)
        self.flush_start(is_nil=value is None)

        if value:
            if not self.in_tail:
                self.set_characters(value)
            else:
                self.tail = value

        self.in_tail = True

    def end_tag(self, qname: str) -> None:
        """End tag notification receiver.

        The receiver will flush if pending the start of the element, end
        the element, its tail content and its namespaces prefix mapping
        and current context.

        Args:
            qname: The qualified name of the element
        """
        self.flush_start(True)
        self.end_element(split_qname(qname), qname)

        if self.tail:
            self.set_characters(self.tail)

        self.tail = None
        self.in_tail = False
        self.ns_context.pop()
        self.uri_context.pop()
        if self.ns_context:
            self.ns_map = self.ns_context[-1]
            self.ns_uris = self.uri_context[-1]

        for prefix in self.pending_prefixes.pop():
            self.end_prefix_mapping(prefix)

    def flush_start(self, is_nil: bool = True) -> None:
        """Flush start notification receiver.

        The receiver will pop the xsi:nil attribute if the element is
        not empty, prepare and send the namespace prefix-URI map and
        the element with its attributes to the content handler for
        generation.

        Args:
            is_nil: Specify if the element requires `xsi:nil="true"`
                when content is empty
        """
        if not self.pending_tag:
            return

        if not is_nil:
            self.attrs.pop(XSI_NIL, None)

        for name in self.attrs:
            self.add_namespace(name[0])

        self.reset_default_namespace()
        self.start_namespaces()

        self.start_element(self.pending_tag, "", self.attrs)
        self.attrs = {}
        self.in_tail = False
        self.pending_tag = None

    def start_namespaces(self) -> None:
        """Send the current namespace prefix-URI map to the content handler.

        Save the list of prefixes to be removed at the end of the
        current pending tag.
        """
        prefixes: list[str] = []
        self.pending_prefixes.append(prefixes)

        context = self.ns_context
        if len(context) > 1:
            # docx4j fork: nothing put a prefix in this element's map, so it is
            # still the parent's map and declares nothing of its own. Upstream
            # reached the same answer by comparing every entry, which is one
            # dict lookup per prefix per element.
            if not self.ns_dirty:
                return

            parent_ns_map = context[-2]
        else:
            parent_ns_map = EMPTY_MAP

        for prefix, uri in self.ns_map.items():
            if parent_ns_map.get(prefix) != uri:
                prefixes.append(prefix)
                self.start_prefix_mapping(prefix, uri)

    def reset_default_namespace(self) -> None:
        """Reset the default namespace if the pending element is not qualified."""
        if self.pending_tag and not self.pending_tag[0] and None in self.ns_map:
            self.own_ns_map()
            self.ns_map[None] = ""
            self.reindex_namespaces()
            self.ns_dirty = True

    @classmethod
    def is_xsi_type(cls, qname: str, value: Any) -> bool:
        """Return whether the value is a xsi:type.

        Args:
            qname: The attribute qualified name
            value: The attribute value

        Returns:
            The bool result.
        """
        if isinstance(value, str) and value.startswith("{"):
            return qname == QNames.XSI_TYPE or DataType.from_qname(value) is not None

        return False

    def encode_data(self, data: Any) -> str | None:
        """Encode data for xml rendering.

        Args:
            data: The content to encode/serialize

        Returns:
            The xml encoded data
        """
        if data is None or isinstance(data, str):
            return data

        if isinstance(data, list) and not data:
            return None

        if self.config.bool_format == BOOL_NUMERIC and (data is True or data is False):
            return "1" if data else "0"

        # docx4j fork: a QName value makes the converter generate a prefix in
        # the map, so the element takes its own copy first and a prefix that
        # appears is a real change, to be declared on this element.
        self.own_ns_map()
        ns_map = self.ns_map
        size = len(ns_map)
        value = converter.serialize(data, ns_map=ns_map)
        if len(ns_map) != size:
            self.reindex_namespaces()
            self.ns_dirty = True

        return value

    @abc.abstractmethod
    def start_document(self) -> None:
        """Start document notification receiver."""

    @abc.abstractmethod
    def end_document(self) -> None:
        """End document notification receiver."""

    @abc.abstractmethod
    def start_element(self, name: tuple[str, str], qname: str, attrs: dict) -> None:
        """Start element notification receiver.

        Args:
            name: The qname as tuple
            qname: The qualified name
            attrs: The attributes mapping
        """

    @abc.abstractmethod
    def end_element(self, name: tuple[str, str], qname: str) -> None:
        """End element notification receiver.

        Args:
            name: The qname as tuple
            qname: The qualified name
        """

    @abc.abstractmethod
    def set_characters(self, data: str) -> None:
        """Characters notification receiver.

        Args:
            data: The characters data to write
        """

    @abc.abstractmethod
    def start_prefix_mapping(self, prefix: str | None, uri: str) -> None:
        """Start namespace prefix notification receiver.

        Args:
            prefix: The namespace prefix
            uri: The namespace URI
        """

    @abc.abstractmethod
    def end_prefix_mapping(self, prefix: str) -> None:
        """End namespace prefix notification receiver.

        Args:
            prefix: The namespace prefix
        """


class EventContentHandler(EventHandler):
    """A consistency wrapper for sax content handlers.

    Args:
        config: The serializer config instance
        ns_map: A user defined namespace prefix-URI map

    Attributes:
        handler: The content handler instance
        in_tail: Specifies whether the text content has been written
        tail: The current element tail content
        attrs: The current element attributes
        ns_context: The namespace context queue
        pending_tag: The pending element namespace, name tuple
        pending_prefixes: The pending element namespace prefixes
    """

    def __init__(self, config: SerializerConfig, ns_map: dict):
        """Initialize the content handler."""
        super().__init__(config, ns_map)
        self.handler = self.build_handler()

    @abc.abstractmethod
    def build_handler(self) -> ContentHandler:
        """Build the content handler instance.

        Returns:
            A content handler instance.
        """

    def start_document(self) -> None:
        """Start document notification receiver.

        Write the xml version and encoding, if the
        configuration is enabled.
        """
        self.handler.startDocument()

    def end_document(self) -> None:
        """End document entrypoint."""
        self.handler.endDocument()

    def end_element(self, name: tuple[str, str], qname: str) -> None:
        """End element notification receiver.

        Args:
            name: The qname as tuple
            qname: The qualified name
        """
        self.handler.endElementNS(name, qname)

    def set_characters(self, data: str) -> None:
        """Characters notification receiver.

        Args:
            data: The characters data to write
        """
        self.handler.characters(data)

    def end_prefix_mapping(self, prefix: str) -> None:
        """End namespace prefix notification receiver.

        Args:
            prefix: The namespace prefix
        """
        self.handler.endPrefixMapping(prefix)

    def start_element(self, name: tuple[str, str], qname: str, attrs: dict) -> None:
        """Start element notification receiver.

        Args:
            name: The qname as tuple
            qname: The qualified name
            attrs: The attributes mapping
        """
        self.handler.startElementNS(name, qname, attrs)  # type: ignore

    def start_prefix_mapping(self, prefix: str | None, uri: str) -> None:
        """Start namespace prefix notification receiver.

        Args:
            prefix: The namespace prefix
            uri: The namespace URI
        """
        self.handler.startPrefixMapping(prefix, uri)


class XmlWriter(EventContentHandler, ABC):
    """A consistency wrapper for sax content writers.

    Args:
        config: The serializer config instance
        output: The writer output stream
        ns_map: A user defined namespace prefix-URI map

    Attributes:
        handler: The content handler instance
        in_tail: Specifies whether the text content has been written
        tail: The current element tail content
        attrs: The current element attributes
        ns_context: The namespace context queue
        pending_tag: The pending element namespace, name tuple
        pending_prefixes: The pending element namespace prefixes
    """

    def __init__(self, config: SerializerConfig, output: TextIOBase, ns_map: dict):
        """Initialize the writer."""
        self.output = output
        super().__init__(config, ns_map)

    def start_document(self) -> None:
        """Start document notification receiver.

        Write the xml version and encoding, if the
        configuration is enabled.
        """
        if self.config.xml_declaration:
            self.output.write(f'<?xml version="{self.config.xml_version}"')
            self.output.write(f' encoding="{self.config.encoding}"?>\n')


@dataclass
class EventGenerator:
    """Event generator class."""

    context: XmlContext = field(default_factory=XmlContext)
    config: SerializerConfig = field(default_factory=SerializerConfig)

    def generate(self, obj: Any) -> EventIterator:
        """Convert a user model, or derived element instance to sax events.

        Args:
            obj: A user model, or derived element instance

        Yields:
            An iterator of sax events.
        """
        qname = xsi_type = None
        if isinstance(obj, self.context.class_type.derived_element):
            meta = self.context.build(
                obj.value.__class__, globalns=self.config.globalns
            )
            qname = obj.qname
            obj = obj.value
            xsi_type = self.real_xsi_type(qname, meta.target_qname)

        yield from self.convert_dataclass(obj, qname=qname, xsi_type=xsi_type)

    def convert_dataclass(
        self,
        obj: Any,
        namespace: str | None = None,
        qname: str | None = None,
        nillable: bool = False,
        xsi_type: str | None = None,
    ) -> EventIterator:
        """Convert a model instance to sax events.

        Optionally override the qualified name and the
        xsi attributes type and nil.

        Args:
            obj: A model instance
            namespace: The field namespace URI
            qname: Override the field qualified name
            nillable: Specifies whether the field is nillable
            xsi_type: Override the field xsi type

        Yields:
            An iterator of sax events.
        """
        meta = self.context.build(
            obj.__class__,
            namespace,
            globalns=self.config.globalns,
        )
        nillable = nillable or meta.nillable
        if qname:
            namespace = namespaces.target_uri(qname)
        else:
            # docx4j fork: the meta carries the split of its own qname, so the
            # common case, the field's name not overridden, needs no lookup.
            qname = meta.qname
            namespace = meta.namespace

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
            wrapper_qname = var.wrapper_qname
            if wrapper_qname:
                yield XmlWriterEvent.START, wrapper_qname

            # docx4j fork: a plain element field is converted here rather than
            # through `convert_value` and, for a list, `convert_list` as well,
            # so a child's events cross one generator frame instead of three.
            fast = var.fast_element
            if fast is None:
                fast = var.fast_element = self.is_fast_element(var)

            if fast:
                yield from self.convert_fast_element(value, var, namespace)
            elif var.is_elements and not var.mixed and not var.tokens:
                # the same shortcut for a compound field: `convert_value` would
                # fall through its first three branches to this one.
                yield from self.convert_elements(value, var, namespace)
            else:
                yield from self.convert_value(value, var, namespace)

            if wrapper_qname:
                yield XmlWriterEvent.END, wrapper_qname

        yield XmlWriterEvent.END, qname

    def convert_xsi_type(
        self,
        value: Any,
        var: XmlVar,
        namespace: str | None,
    ) -> EventIterator:
        """Convert a xsi:type value to sax events.

        The value can be assigned to wildcard, element or compound fields

        Args:
            value: A model instance
            var: The field metadata instance
            namespace: The field namespace URI

        Yields:
            An iterator of sax events.
        """
        if var.is_wildcard:
            choice = var.find_value_choice(value, True)
            if choice:
                yield from self.convert_value(value, choice, namespace)
            else:
                yield from self.convert_dataclass(value, namespace)
        elif var.is_element:
            xsi_type = self.xsi_type(var, value, namespace)
            yield from self.convert_dataclass(
                value,
                namespace,
                var.qname,
                var.nillable,
                xsi_type,
            )
        else:
            # var elements/compound
            meta = self.context.fetch(value.__class__, namespace)
            yield from self.convert_dataclass(value, qname=meta.target_qname)

    def convert_value(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        """Convert any value to sax events according to the var instance.

        The order of the checks is important as more than one condition
        can be true.

        Args:
            value: The input value
            var: The field metadata instance
            namespace: The class namespace URI

        Yields:
            An iterator of sax events.
        """
        # docx4j fork: a plain single dataclass element holding exactly its
        # declared class goes straight to `convert_dataclass`. Upstream reaches
        # the same events through `convert_any_type`, three isinstance checks
        # and `convert_xsi_type`, for an xsi:type decision whose answer is
        # `None` by construction. Anything else -- a subclass value, an
        # object-typed var, a wildcard, a compound field -- keeps that path.
        if value.__class__ is var.clazz:
            fast = var.fast_element
            if fast is None:
                fast = var.fast_element = self.is_fast_element(var)

            if fast:
                yield from self.convert_dataclass(
                    value, namespace, var.qname, var.nillable
                )
                return

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

    def is_fast_element(self, var: XmlVar) -> bool:
        """Return whether `var` takes the fast path of `convert_value`.

        docx4j fork. A var qualifies when it is a single element field with a
        declared model class that is neither of the generic wrappers, so that
        a value of exactly that class can be converted without asking for an
        xsi:type: `XmlVar.xsi_type` would answer `None`, because the declared
        class is always one of the var's types.

        Args:
            var: The field metadata instance

        Returns:
            The bool result, cached on the var.
        """
        clazz = var.clazz
        if clazz is None or not var.is_element or var.mixed or var.tokens:
            return False

        class_type = self.context.class_type
        return not issubclass(
            clazz, (class_type.any_element, class_type.derived_element)
        )

    def convert_fast_element(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        """Convert the value of a plain element field to sax events.

        docx4j fork. `var` has already answered `is_fast_element`, so it is a
        single element field with a declared model class: `convert_value`'s
        mixed, text, tokens and compound branches are all false for it by
        construction, and what is left is this. Upstream reaches the same
        events through `convert_value` and, for a list, `convert_list` too.

        Args:
            value: The input value, a model instance or a list of them
            var: The field metadata instance
            namespace: The class namespace URI

        Yields:
            An iterator of sax events.
        """
        clazz = var.clazz
        if value.__class__ is clazz:
            yield from self.convert_dataclass(value, namespace, var.qname, var.nillable)
        elif var.list_element and collections.is_array(value):
            for item in value:
                if item.__class__ is clazz:
                    yield from self.convert_dataclass(
                        item, namespace, var.qname, var.nillable
                    )
                else:
                    yield from self.convert_any_type(item, var, namespace)
        else:
            yield from self.convert_any_type(value, var, namespace)

    def convert_list(
        self,
        values: Iterable,
        var: XmlVar,
        namespace: str | None,
    ) -> EventIterator:
        """Convert an array of values to sax events.

        Args:
            values: A list, set, tuple instance
            var: The field metadata instance
            namespace: The class namespace

        Yields:
            An iterator of sax events.
        """
        for value in values:
            yield from self.convert_value(value, var, namespace)

    def convert_tokens(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        """Convert an array of token values to sax events.

        Args:
            value: A list, set, tuple instance
            var: The field metadata instance
            namespace: The class namespace

        Yields:
            An iterator of sax events.
        """
        if value or var.nillable:
            if value and collections.is_array(value[0]):
                for val in value:
                    yield from self.convert_element(val, var, namespace)
            else:
                yield from self.convert_element(value, var, namespace)

    def convert_mixed_content(
        self,
        values: list,
        var: XmlVar,
        namespace: str | None,
    ) -> EventIterator:
        """Convert mixed content values to sax events.

        Args:
            values: A list instance of mixed type values
            var: The field metadata instance
            namespace: The class namespace

        Yields:
            An iterator of sax events.
        """
        for value in values:
            yield from self.convert_any_type(value, var, namespace)

    def convert_any_type(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        """Convert a value assigned to a xs:anyType field to sax events.

        Args:
            value: A list instance of mixed type values
            var: The field metadata instance
            namespace: The class namespace

        Yields:
            An iterator of sax events.
        """
        if isinstance(value, self.context.class_type.any_element):
            yield from self.convert_any_element(value, var, namespace)
        elif isinstance(value, self.context.class_type.derived_element):
            yield from self.convert_derived_element(value, namespace)
        elif self.context.class_type.is_model(value):
            yield from self.convert_xsi_type(value, var, namespace)
        elif var.is_element:
            yield from self.convert_element(value, var, namespace)
        else:
            yield from self.convert_data(value, var)

    def convert_derived_element(
        self, value: Any, namespace: str | None
    ) -> EventIterator:
        """Convert a derived element instance to sax events.

        Args:
            value: A list instance of mixed type values
            namespace: The class namespace

        Yields:
            An iterator of sax events.
        """
        if self.context.class_type.is_model(value.value):
            meta = self.context.fetch(value.value.__class__)
            qname = value.qname
            xsi_type = self.real_xsi_type(qname, meta.target_qname)

            yield from self.convert_dataclass(
                value.value, namespace, qname=qname, xsi_type=xsi_type
            )
        else:
            datatype = DataType.from_value(value.value)

            yield XmlWriterEvent.START, value.qname
            yield XmlWriterEvent.ATTR, QNames.XSI_TYPE, QName(str(datatype))
            yield XmlWriterEvent.DATA, value.value
            yield XmlWriterEvent.END, value.qname

    def convert_any_element(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        """Convert a generic any element instance to sax events.

        Args:
            value: A list instance of mixed type values
            var: The field metadata instance
            namespace: The class namespace

        Yields:
            An iterator of sax events.
        """
        if value.qname:
            namespace, _tag = namespaces.split_qname(value.qname)
            yield XmlWriterEvent.START, value.qname

        for key, val in value.attributes.items():
            yield XmlWriterEvent.ATTR, key, val

        yield XmlWriterEvent.DATA, value.text

        for child in value.children:
            yield from self.convert_any_type(child, var, namespace)

        if value.qname:
            yield XmlWriterEvent.END, value.qname

        if value.tail:
            yield XmlWriterEvent.DATA, value.tail

    def xsi_type(self, var: XmlVar, value: Any, namespace: str | None) -> str | None:
        """Return the xsi:type for the given value and field metadata instance.

        If the value type is either a child or parent for one of the var types,
        we need to declare it as n xsi:type.

        Args:
            value: A list instance of mixed type values
            var: The field metadata instance
            namespace: The class namespace

        Raises:
            SerializerError: If the value type is completely unrelated to
                the field types.
        """
        if not value or value.__class__ in var.types:
            return None

        clazz = var.clazz
        if clazz is None or self.context.is_derived(value, clazz):
            meta = self.context.fetch(value.__class__, namespace)
            return self.real_xsi_type(var.qname, meta.target_qname)

        raise SerializerError(
            f"{value.__class__.__name__} is not derived from {clazz.__name__}"
        )

    def convert_elements(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        """Convert the value assigned to a compound field to sax events.

        Args:
            value: A list instance of mixed type values
            var: The field metadata instance
            namespace: The class namespace

        Yields:
            An iterator of sax events.
        """
        if collections.is_array(value):
            for val in value:
                yield from self.convert_choice(val, var, namespace)
        else:
            yield from self.convert_choice(value, var, namespace)

    def convert_choice(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        """Convert a single value assigned to a compound field to sax events.

        Args:
            value: A list instance of mixed type values
            var: The field metadata instance
            namespace: The class namespace

        Yields:
            An iterator of sax events.

        Raises:
            SerializerError: If the value doesn't match any choice field.
        """
        fast = False
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
            elif choice is not None and value.__class__ is choice.clazz:
                # docx4j fork: `convert_value` would take its fast path for
                # this choice; take it here instead, one frame earlier.
                fast = choice.fast_element
                if fast is None:
                    fast = choice.fast_element = self.is_fast_element(choice)

        if not choice:
            raise SerializerError(
                f"XmlElements undefined choice: `{var.name}` for `{type(value)}`"
            )

        if fast:
            yield from self.convert_dataclass(
                value, namespace, choice.qname, choice.nillable
            )
        else:
            yield from func(value, choice, namespace)

    def convert_element(
        self,
        value: Any,
        var: XmlVar,
        namespace: str | None,
    ) -> EventIterator:
        """Convert a value assigned to an element field to sax events.

        Args:
            value: A list instance of mixed type values
            var: The field metadata instance
            namespace: The class namespace (unused)

        Yields:
            An iterator of sax events.
        """
        yield XmlWriterEvent.START, var.qname

        if var.nillable and not value:
            yield XmlWriterEvent.ATTR, QNames.XSI_NIL, "true"

        if value is not None and value != "" and var.any_type:
            datatype = DataType.from_value(value)
            if datatype != DataType.STRING:
                yield XmlWriterEvent.ATTR, QNames.XSI_TYPE, QName(str(datatype))

        yield (
            XmlWriterEvent.DATA,
            self.encode_primitive(value, var, self.config.bool_format),
        )
        yield XmlWriterEvent.END, var.qname

    def convert_data(self, value: Any, var: XmlVar) -> EventIterator:
        """Convert a value assigned to a text field to sax events.

        Args:
            value: A list instance of mixed type values
            var: The field metadata instance

        Yields:
            An iterator of sax events.
        """
        yield (
            XmlWriterEvent.DATA,
            self.encode_primitive(value, var, self.config.bool_format),
        )

    @classmethod
    def next_value(cls, obj: Any, meta: XmlMeta) -> Iterator[tuple[XmlVar, Any]]:
        """Produce the next non attribute value of a model instance to convert.

        The generator will produce the values in the order the fields
        are defined in the model or by their sequence number.

        Sequential fields need to be rendered together in parallel order
        eg: <a1/><a2/><a1/><a/2></a1>

        Args:
            obj: The input model instance
            meta: The model metadata instance

        Yields:
            An iterator of field metadata instance and value tuples.
        """
        index = 0
        attrs = meta.get_element_vars()
        stop = len(attrs)
        while index < stop:
            var = attrs[index]

            if var.sequence is None:
                value = getattr(obj, var.name)
                if value is not None or var.nillable:
                    yield var, value
                index += 1
                continue

            indices = range(index, stop)
            end = next(
                i for i in indices[::-1] if attrs[i].sequence == var.sequence
            )  # pragma: no cover
            sequence = attrs[index : end + 1]
            index = end + 1
            j = 0

            rolling = True
            while rolling:
                rolling = False
                for var in sequence:
                    values = getattr(obj, var.name)
                    if collections.is_array(values):
                        if j < len(values):
                            rolling = True
                            value = values[j]
                            if value is not None or var.nillable:
                                yield var, value
                    elif j == 0:
                        rolling = True
                        if values is not None or var.nillable:
                            yield var, values

                j += 1

    @classmethod
    def next_attribute(
        cls,
        obj: Any,
        meta: XmlMeta,
        nillable: bool,
        xsi_type: str | None,
        ignore_optionals: bool,
        bool_format: str = BOOL_WORDS,
    ) -> Iterator[tuple[str, Any]]:
        """Produce the next attribute value to convert.

        Args:
            obj: The input model instance
            meta: The model metadata instance
            nillable: Specifies if the current element supports nillable content
            xsi_type: The real xsi:type of the object
            ignore_optionals: Specifies if optional attributes with default
                values should be ignored.

        Yields:
            An iterator of attribute name-value pairs.
        """
        for var in meta.get_attribute_vars():
            if var.is_attribute:
                value = getattr(obj, var.name)
                if (
                    value is None
                    or (collections.is_array(value) and not value)
                    or (ignore_optionals and var.is_optional(value))
                ):
                    continue

                yield var.qname, cls.encode_primitive(value, var, bool_format)
            else:
                yield from getattr(obj, var.name, EMPTY_MAP).items()

        if xsi_type:
            yield QNames.XSI_TYPE, QName(xsi_type)

        if nillable:
            yield QNames.XSI_NIL, "true"

    @classmethod
    def encode_primitive(
        cls, value: Any, var: XmlVar, bool_format: str = BOOL_WORDS
    ) -> Any:
        """Encode a value for xml serialization.

        Converts values to strings. QName instances is an exception,
        those values need to wait until the XmlWriter assigns prefixes
        to namespaces per element node. Enums and Tokens may contain
        QName(s) so they also get a special treatment.

        We can't do all the conversions in the writer because we would
        need to carry the xml vars inside the writer. Instead of that we
        do the easy encoding here and leave the qualified names for
        later.

        Args:
            value: The simple type vale to encode
            var: The field metadata instance
            bool_format: docx4j fork: the xsd:boolean spelling,
                `words` for `true`/`false`, `numeric` for `1`/`0`

        Returns:
            The encoded value.
        """
        if isinstance(value, (str, QName)) or var is None:
            return value

        if collections.is_array(value):
            return [cls.encode_primitive(v, var, bool_format) for v in value]

        if isinstance(value, Enum):
            return cls.encode_primitive(value.value, var, bool_format)

        if bool_format == BOOL_NUMERIC and (value is True or value is False):
            return "1" if value else "0"

        return converter.serialize(value, format=var.format)

    @classmethod
    def real_xsi_type(cls, qname: str, target_qname: str | None) -> str | None:
        """Compare the qname with the target qname and return the real xsi:type.

        Args:
            qname: The field type qualified name
            target_qname: The value type qualified name

        Returns:
            None if the qname and target qname match, otherwise
            return the target qname.
        """
        return target_qname if target_qname != qname else None
