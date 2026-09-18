from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from typing import Any

from docx4j_xsdata.formats.dataclass.parsers.skipped import SkippedReport
from docx4j_xsdata.formats.types import T


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
        skipped_report: docx4j fork: collect the elements and attributes
            lenient parsing drops. True for a new report, or a
            `SkippedReport` instance to configure it or to share it.

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
    skipped_report: InitVar[bool | SkippedReport] = False
    skipped: SkippedReport | None = field(
        init=False, default=None, compare=False, repr=False
    )

    def __post_init__(self, skipped_report: bool | SkippedReport) -> None:
        """Set up the skipped content report, if it's requested."""
        if skipped_report is True:
            self.skipped = SkippedReport()
        elif isinstance(skipped_report, SkippedReport):
            self.skipped = skipped_report
