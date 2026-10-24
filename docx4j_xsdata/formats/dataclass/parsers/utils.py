import math
import warnings
from collections import UserList
from collections.abc import Callable, Iterable, Sequence
from enum import Enum, EnumMeta
from typing import Any

from docx4j_xsdata.exceptions import ConverterError, ConverterWarning, ParserError
from docx4j_xsdata.formats.converter import QNameConverter, converter
from docx4j_xsdata.formats.dataclass.models.elements import XmlMeta, XmlVar
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.skipped import KEPT_EXACT, KEPT_INVALID
from docx4j_xsdata.models.datatype import LEXICAL_CLASSES
from docx4j_xsdata.models.enums import QNames
from docx4j_xsdata.utils import collections, constants, text
from docx4j_xsdata.utils.namespaces import build_qname


class _MissingType: ...


MISSING = _MissingType()

# docx4j fork: what a var's converter plan says about its single type, in its
# fourth entry: nothing, a type whose values may keep their spelling
# (`ParserConfig.lexical_types`, stage 12), or one whose values may be read
# exactly (`ParserConfig.exact_types`, stage 13).
PLAN_PLAIN = 0
PLAN_LEXICAL = 1
PLAN_BOOL = 2
PLAN_ENUM = 3

#: docx4j fork: xs:boolean's lexical forms, exactly as written.
EXACT_BOOLEANS = frozenset(("true", "false", "1", "0"))


class PendingCollection(UserList):
    """An iterable implementation of parsed values.

    The values are parsed individually in the end we
    need to convert it to a tuple or a list based on
    the mutability setting of the data class.

    Args:
        initlist: An initial list of values or None
        factory: A callable factory for the values
            when the node parse has finished.

    """

    def __init__(self, initlist: Iterable | None, factory: Callable | None):
        """Initialize the pending collection."""
        super().__init__(initlist)
        self.factory = factory or list

    def evaluate(self) -> Iterable[Any]:
        """Evaluate the values factory and return the result.

        Returns:
            A list or tuple or set of values
        """
        return self.factory(self.data)


class ParserUtils:
    """Random parser util functions."""

    @classmethod
    def xsi_type(cls, attrs: dict, ns_map: dict) -> str | None:
        """Parse the xsi:type attribute value if present.

        Args:
            attrs: The element attributes
            ns_map: The element namespace prefix-URI map

        Returns:
            The xsi:type attribute value or None
        """
        xsi_type = attrs.get(QNames.XSI_TYPE)
        if not xsi_type:
            return None

        namespace, name = QNameConverter.resolve(xsi_type, ns_map)
        return build_qname(namespace, name)

    @classmethod
    def xsi_nil(cls, attrs: dict) -> bool | None:
        """Return whether xsi:nil attribute value.

        Args:
            attrs: The element attributes

        Returns:
            The bool value or None if it doesn't exist.
        """
        xsi_nil = attrs.get(QNames.XSI_NIL)
        return xsi_nil == constants.XML_TRUE if xsi_nil else None

    @classmethod
    def parse_var(
        cls,
        meta: XmlMeta,
        var: XmlVar,
        config: ParserConfig,
        value: Any,
        ns_map: dict | None = None,
        default: Any = None,
        types: Sequence[type] | None = None,
        tokens_factory: Callable | None = None,
        format: str | None = None,
    ) -> Any:
        """Convert a value to a python primitive type.

        Args:
            meta: The xml meta instance
            var: The xml var instance
            config: The parser config instance
            value: A primitive value or a list of primitive values
            ns_map: The element namespace prefix-URI map
            default: Override the var default value
            types: Override the var types
            tokens_factory: Override the var tokens factory
            format: Override the var format

        Returns:
            The converted value or values.
        """
        # docx4j fork: the common case is a present value on a var with one
        # declared type and no tokens factory, and upstream reaches its
        # converter through `parse_value`, `converter.deserialize`,
        # `type_converter` and a `suppress` context manager, per value. The
        # converter is a property of the var, so it is resolved once and kept
        # on it; anything else, and any failure, takes upstream's path below,
        # which is what reports it.
        if (
            value is not None
            and types is None
            and tokens_factory is None
            and format is None
            and not var.tokens
        ):
            plan = var.converter_plan
            if plan is None or plan[0] != converter.generation:
                plan = var.converter_plan = cls.build_converter_plan(var)

            instance = plan[1]
            if instance is not None:
                try:
                    result = instance.deserialize(
                        value, data_type=plan[2], ns_map=ns_map, format=var.format
                    )
                except ConverterError:
                    pass  # upstream's path below builds the message and warns
                else:
                    # docx4j fork: plan[3] says the type may keep a spelling
                    # (`ParserConfig.lexical_types`, stage 12) or be read
                    # exactly (`ParserConfig.exact_types`, stage 13), so the
                    # usual value pays one tuple index for both options.
                    kind = plan[3]
                    if kind:
                        if kind == PLAN_LEXICAL:
                            if plan[2] in config.lexical_types:
                                return cls.keep_lexical(
                                    result, value, var.format, config.lexical_types
                                )
                        elif config.exact_types and cls.is_inexact(
                            kind, result, value, config.exact_types
                        ):
                            return cls.keep_inexact(meta, var, config, value)
                    return result

        source = value
        try:
            value = cls.parse_value(
                value=value,
                types=types or var.types,
                default=default or var.default,
                ns_map=ns_map,
                tokens_factory=tokens_factory or var.tokens_factory,
                format=format or var.format,
                exact_types=config.exact_types,
            )
        except ConverterError as ex:
            # docx4j fork: a value the exact mode refused, but XSD's
            # whitespace rule converts, is kept on purpose
            # (`ParserConfig.exact_types`); only a failure that remains is
            # warned about.
            if config.exact_types:
                try:
                    cls.parse_value(
                        value=source,
                        types=types or var.types,
                        default=default or var.default,
                        ns_map=ns_map,
                        tokens_factory=tokens_factory or var.tokens_factory,
                        format=format or var.format,
                    )
                except ConverterError:
                    pass
                else:
                    return cls.keep_inexact(meta, var, config, source)

            message = (
                "Failed to convert value for "
                f"`{meta.clazz.__qualname__}.{var.name}`\n  {ex}"
            )
            if config.fail_on_converter_warnings:
                raise ParserError(message)

            # docx4j fork: the value is bound as its text; the skipped report
            # records it with its kept values (stage 13, item 30).
            if config.skipped is not None:
                config.skipped.add_kept(KEPT_INVALID, meta, var, source)

            warnings.warn(message, ConverterWarning)
        else:
            if config.lexical_types:
                value = cls.keep_lexical(
                    value, source, format or var.format, config.lexical_types
                )

        return value

    @classmethod
    def keep_lexical(
        cls,
        value: Any,
        source: Any,
        format: str | None,
        lexical_types: frozenset[type],
    ) -> Any:
        """docx4j fork: a value that keeps its source's spelling, if it needs to.

        See `ParserConfig.lexical_types`. Only a scalar of a type asked for,
        read from text, is considered; a list of tokens, a value of another
        type, and a value the converter spells as its source does are
        returned as they are.

        Args:
            value: The converted value
            source: The text it was converted from
            format: The var's format (``base64``, ``base16``), for bytes
            lexical_types: The types asked for

        Returns:
            The value, or its lexical subclass carrying `source`.
        """
        tp = value.__class__
        if tp not in lexical_types or not isinstance(source, str):
            return value

        try:
            spelled = converter.serialize(value, format=format)
        except ConverterError:
            return value

        if spelled == source:
            return value

        return LEXICAL_CLASSES[tp](value, source)

    @classmethod
    def is_inexact(
        cls, kind: int, result: Any, source: Any, exact_types: frozenset[type]
    ) -> bool:
        """docx4j fork: whether a converted value was not read from exactly a lexical form.

        See `ParserConfig.exact_types`. The converter collapses whitespace
        before it matches, so a value it converted on the fast path may have
        been read from a spelling the exact mode refuses.

        Args:
            kind: The var's converter plan kind, `PLAN_BOOL` or `PLAN_ENUM`
            result: The converted value
            source: The text it was converted from
            exact_types: The types asked for

        Returns:
            Whether the value must be kept as its source text.
        """
        if not isinstance(source, str):
            return False

        if kind == PLAN_BOOL:
            return bool in exact_types and source not in EXACT_BOOLEANS

        return (
            Enum in exact_types
            and isinstance(result.value, str)
            and result.value != source
        )

    @classmethod
    def keep_inexact(
        cls, meta: XmlMeta, var: XmlVar, config: ParserConfig, source: str
    ) -> str:
        """docx4j fork: keep a value that is not exactly a lexical form, as its text.

        See `ParserConfig.exact_types`. XSD's whitespace rule would have
        converted the value, so it's kept on purpose, without a warning and
        recorded with the skipped report's kept values (`KEPT_EXACT`),
        unless the config fails on converter warnings: under that, every
        value must convert, and `UnionNode` relies on a candidate type
        failing.

        Args:
            meta: The xml meta instance
            var: The xml var instance
            config: The parser config instance
            source: The text the value was read with

        Returns:
            The source text.

        Raises:
            ParserError: If the config fails on converter warnings.
        """
        if config.fail_on_converter_warnings:
            raise ParserError(
                "Failed to convert value for "
                f"`{meta.clazz.__qualname__}.{var.name}`\n"
                f"  `{source}` is not exactly a lexical form of its type"
            )

        # docx4j fork: recorded with the skipped report's kept values (item 30)
        if config.skipped is not None:
            config.skipped.add_kept(KEPT_EXACT, meta, var, source)

        return source

    @classmethod
    def build_converter_plan(cls, var: XmlVar) -> tuple[int, Any, Any, int]:
        """Resolve the converter for a var with a single declared type.

        docx4j fork: the answer `converter.deserialize` works out for every
        value of this var, carried with the converter factory generation it
        was worked out under so that a later `register_converter` invalidates
        it. The converter is None when the var has more than one type or its
        type has no converter, which sends the caller down upstream's path.

        Args:
            var: The xml var instance

        Returns:
            The generation, the converter instance or None, the data type,
            and the type's kind: whether a value of it may keep its spelling
            (`PLAN_LEXICAL`, `ParserConfig.lexical_types`, stage 12), may be
            read exactly (`PLAN_BOOL`, `PLAN_ENUM`, `ParserConfig.exact_types`,
            stage 13), or neither (`PLAN_PLAIN`).
        """
        types = var.types
        if len(types) == 1:
            data_type = types[0]
            try:
                return (
                    converter.generation,
                    converter.type_converter(data_type),
                    data_type,
                    cls.plan_kind(data_type),
                )
            except ConverterError:
                pass

        return converter.generation, None, None, PLAN_PLAIN

    @classmethod
    def plan_kind(cls, data_type: type) -> int:
        """docx4j fork: the converter plan kind of a var's single declared type.

        Args:
            data_type: The var's type

        Returns:
            One of `PLAN_PLAIN`, `PLAN_LEXICAL`, `PLAN_BOOL` and `PLAN_ENUM`.
        """
        if data_type in LEXICAL_CLASSES:
            return PLAN_LEXICAL
        if data_type is bool:
            return PLAN_BOOL
        if isinstance(data_type, EnumMeta):
            return PLAN_ENUM
        return PLAN_PLAIN

    @classmethod
    def parse_value(
        cls,
        value: Any,
        types: Sequence[type],
        default: Any | None = None,
        ns_map: dict | None = None,
        tokens_factory: Callable | None = None,
        format: str | None = None,
        exact_types: frozenset[type] = frozenset(),
    ) -> Any:
        """Convert a value to a python primitive type.

        Args:
            value: A primitive value or a list of primitive values
            types: An iterable of types to try to convert the value
            default: The default value/factory if the given is None
            ns_map: The element namespace prefix-URI map
            tokens_factory: A callable factory for the converted values
                if the element is derived from xs:NMTOKENS
            format: The format argument for base64/hex values or dates.
            exact_types: docx4j fork: `ParserConfig.exact_types`, passed to
                the converters only when there are any, so that a converter
                registered with a narrower signature sees upstream's call

        Returns:
            The converted value or values.
        """
        if value is None:
            if callable(default):
                return default() if tokens_factory else None

            return default

        # docx4j fork: see `exact_types` above.
        extra = {"exact_types": exact_types} if exact_types else {}
        if tokens_factory:
            value = value if collections.is_array(value) else value.split()
            return tokens_factory(
                converter.deserialize(val, types, ns_map=ns_map, format=format, **extra)
                for val in value
            )

        return converter.deserialize(
            value, types, ns_map=ns_map, format=format, **extra
        )

    @classmethod
    def normalize_content(cls, value: str | None) -> str | None:
        """Normalize element text or tail content.

        If content is just whitespace return None, otherwise preserve
        the original content.

        Args:
            value: The element content

        Returns:
            The normalized content
        """
        if value and value.strip():
            return value

        return None

    @classmethod
    def parse_any_attributes(
        cls, attrs: dict[str, str], ns_map: dict[str | None, str]
    ) -> dict[str, str]:
        """Parse attributes with qname support.

        Example:
            {"foo": "bar", "xsi:type": "my:type"} ->
            {"foo": "bar", "xsi:type" "{http://someuri.com}type"}

        Args:
            attrs: The element attributes
            ns_map: The element namespace prefix-URI map

        Returns:
            The parsed attributes with expanded namespace prefixes
        """
        return {
            key: cls.parse_any_attribute(value, ns_map) for key, value in attrs.items()
        }

    @classmethod
    def parse_any_attribute(cls, value: str, ns_map: dict) -> str:
        """Expand the value with the full namespace if it has a prefix.

        Args:
            value: The attr value
            ns_map: The element namespace prefix-URI map

        Returns:
            The expanded value.
        """
        prefix, suffix = text.split(value)
        if prefix and prefix in ns_map and not suffix.startswith("//"):
            value = build_qname(ns_map[prefix], suffix)

        return value

    @classmethod
    def validate_fixed_value(cls, meta: XmlMeta, var: XmlVar, value: Any):
        """Validate if the parsed value matches the fixed value.

        Special cases
            - float nans are never equal in python
            - strings with whitespaces, need trimming
            - comparing raw str values
        """
        default_value = var.default() if callable(var.default) else var.default
        if (
            isinstance(default_value, float)
            and isinstance(value, float)
            and math.isnan(default_value)
            and math.isnan(value)
        ) or (
            isinstance(default_value, str)
            and isinstance(value, str)
            and default_value.strip() == value.strip()
        ):
            return

        if isinstance(value, str) and not isinstance(default_value, str):
            default_value = converter.serialize(default_value, format=var.format)

        if default_value != value:
            raise ParserError(
                f"Fixed value mismatch {meta.qname}:{var.qname}, "
                f"`{default_value} != {value}`"
            )
