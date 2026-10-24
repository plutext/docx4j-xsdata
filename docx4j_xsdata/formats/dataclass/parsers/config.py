from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from enum import Enum
from typing import Any

from docx4j_xsdata.formats.dataclass.parsers.skipped import SkippedReport
from docx4j_xsdata.formats.types import T
from docx4j_xsdata.models.datatype import LEXICAL_CLASSES

#: docx4j fork: the types `ParserConfig.exact_types` may name.
EXACT_TYPES: frozenset[type] = frozenset((bool, Enum))


def default_class_factory(cls: type[T], params: dict[str, Any]) -> T:
    """The default class factory.

    To be used as a hook for plugins.

    Args:
        cls: The target class type to instantiate
        params: The class keyword arguments

    Returns:
        A new class instance with the given params.
    """
    return cls(**params)  # type: ignore


@dataclass
class ParserConfig:
    """Parsing configuration options.

    Not all options are applicable for both xml and json documents.

    Args:
        base_url: Specify a base URL when parsing from memory, and
            you need support for relative links e.g. xinclude
        load_dtd: Enable loading external dtd (lxml only)
        process_xinclude: Enable xinclude statements processing
        class_factory: Override default object instantiation
        fail_on_unknown_properties: Skip unknown properties or fail with exception
        fail_on_unknown_attributes: Skip unknown XML attributes or fail with exception
        fail_on_converter_warnings: Turn converter warnings to exceptions
        on_bind: docx4j fork: called with every object the parser builds, once
            each, as soon as it is built. The parser binds bottom up, so the
            object's own children exist and are bound when the callback sees
            it, and its parent does not exist yet. It is the hook a binding
            layer needs to wire something per object -- a parent pointer, a
            registry entry -- without walking the finished tree a second time.
            It must not raise, and what it returns is ignored.
        on_namespaces: docx4j fork: called as ``on_namespaces(qname, obj,
            ns_map)`` with each object the parser builds for an element whose
            qualified name is in `namespaces_for`, typed or a wildcard
            (``AnyElement``), and the namespace declarations in scope at that
            element (prefix to URI, the default namespace under None). A
            binding keeps an attribute's value, not the declarations a prefix
            in it resolved through; this is where a binding layer can record
            them. Called after `on_bind`. It must not raise, and what it
            returns is ignored.
        namespaces_for: docx4j fork: the qualified names (``{uri}local``)
            `on_namespaces` is called for.
        wildcard_class: docx4j fork: called as ``wildcard_class(qname,
            ancestors)`` for an element a lax wildcard (``process_contents``
            other than ``skip``) receives, when its qualified name is in
            `wildcard_class_for`, before the ordinary lookup by name
            (``XmlContext.find_type``). `ancestors` is the classes of the
            enclosing typed elements, innermost first: the class whose
            wildcard field receives the element, then its parent's, up to the
            root. It returns the class to bind the element to, or None for the
            ordinary lookup. One name may be declared by several types, each
            in its own context, and only one of them can be global; this is
            where a binding layer chooses by the context. It must not raise.
        wildcard_class_for: docx4j fork: the qualified names
            `wildcard_class` is called for.
        skipped_report: docx4j fork: collect the elements and attributes
            lenient parsing drops. True for a new report, or a
            `SkippedReport` instance to configure it or to share it.
        lexical_types: docx4j fork: the value types, of `float` and `bytes`,
            whose values keep the spelling they were read with. Where the
            converter would write a value of one of them in another spelling
            than its source's (``202`` as ``202.0``, a base64 value Word wraps
            at 76 characters on one line), the value bound is a subclass of
            its type that carries the source text (`XmlLexicalFloat`,
            `XmlLexicalBytes`), and the serializer writes that text. A value
            the converter spells as its source does is bound plain, as is
            every value of the other types. Off (empty) by default.
        exact_types: docx4j fork: the value types, of `bool` and `Enum`
            (every enumeration of string values), whose values convert only
            from a lexical form exactly as written. XSD collapses the
            whitespace of an xs:boolean or an enumeration value before it is
            matched, so ``" false"`` reads False and ``" yellow"`` the member
            ``yellow``, and a save writes ``0`` and ``yellow``; Word reads
            both literally, and ``" false"`` as on. For a type here, a value
            that is not exactly one of its lexical forms is bound as the text
            it was read with, and written back as read: silently when XSD's
            whitespace rule would have converted it, which is a value kept on
            purpose, and with the usual conversion warning otherwise. Under
            `fail_on_converter_warnings` both raise. Off (empty) by default.

    Attributes:
        skipped: docx4j fork: the skipped content report, or None when
            the feature is off. Also reachable as `parser.skipped`.
    """

    base_url: str | None = None
    load_dtd: bool = False
    process_xinclude: bool = False
    class_factory: Callable[[type[T], dict[str, Any]], T] = field(
        default=default_class_factory
    )
    fail_on_unknown_properties: bool = True
    fail_on_unknown_attributes: bool = False
    fail_on_converter_warnings: bool = False
    on_bind: Callable[[Any], None] | None = None
    on_namespaces: Callable[[str, Any, dict], None] | None = None
    namespaces_for: frozenset[str] = frozenset()
    wildcard_class: Callable[[str, tuple[type, ...]], type | None] | None = None
    wildcard_class_for: frozenset[str] = frozenset()
    skipped_report: InitVar[bool | SkippedReport] = False
    lexical_types: frozenset[type] = frozenset()
    exact_types: frozenset[type] = frozenset()
    skipped: SkippedReport | None = field(
        init=False, default=None, compare=False, repr=False
    )

    def __post_init__(self, skipped_report: bool | SkippedReport) -> None:
        """Set up the skipped content report, if it's requested."""
        if skipped_report is True:
            self.skipped = SkippedReport()
        elif isinstance(skipped_report, SkippedReport):
            self.skipped = skipped_report
        unsupported = set(self.lexical_types) - set(LEXICAL_CLASSES)
        if unsupported:
            names = ", ".join(sorted(tp.__name__ for tp in unsupported))
            raise ValueError(
                f"lexical_types: no lexical class for {names}; "
                f"supported: {', '.join(tp.__name__ for tp in LEXICAL_CLASSES)}"
            )
        unsupported = set(self.exact_types) - EXACT_TYPES
        if unsupported:
            names = ", ".join(sorted(tp.__name__ for tp in unsupported))
            raise ValueError(
                f"exact_types: not supported for {names}; supported: bool, Enum"
            )
