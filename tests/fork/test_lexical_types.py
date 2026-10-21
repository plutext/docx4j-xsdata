"""docx4j fork: `ParserConfig(lexical_types=...)`, values that keep the spelling they were read with.

docx4j-python CR-012 Phase C puts VML in its model, and VML is the first
vocabulary it reads with an `xsd:float` attribute and a base64 one that Word
writes in a spelling the converter does not: ``o:spt="202"``, which the
converter writes ``202.0``, and ``o:gfxdata``, which Word wraps at 76
characters and the converter writes on one line. Both are valid lexical forms
of the same value, but a part read and saved unchanged must be canonically
identical to its source there. With the option, such a value is bound as a
subclass of its type carrying the source text, and the serializer writes the
text back. Everything else is as before.
"""

import copy
import pickle
from dataclasses import dataclass, field

import pytest

from docx4j_xsdata.formats.dataclass.parsers import XmlParser
from docx4j_xsdata.formats.dataclass.parsers.config import ParserConfig
from docx4j_xsdata.formats.dataclass.parsers.handlers import (
    LxmlEventHandler,
    XmlEventHandler,
)
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.config import SerializerConfig
from docx4j_xsdata.formats.dataclass.serializers.tree import TreeSerializer
from docx4j_xsdata.models.datatype import XmlLexicalBytes, XmlLexicalFloat

NS = "urn:fork:lexical"

LEXICAL = frozenset({float, bytes})


@dataclass
class Shape:
    """A VML shapetype's shape: a float, a base64 and a hex attribute, and simple elements."""

    class Meta:
        name = "shapetype"
        namespace = NS

    spt: float | None = field(default=None, metadata={"type": "Attribute"})
    gfxdata: bytes | None = field(
        default=None, metadata={"type": "Attribute", "format": "base64"}
    )
    hex: bytes | None = field(
        default=None, metadata={"type": "Attribute", "format": "base16"}
    )
    count: int | None = field(default=None, metadata={"type": "Attribute"})
    name: str | None = field(default=None, metadata={"type": "Attribute"})
    angle: float | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    angles: list[float] = field(
        default_factory=list,
        metadata={"type": "Element", "namespace": NS, "tokens": True},
    )


SOURCE = (
    f'<shapetype xmlns="{NS}" spt="202" gfxdata="YWJj&#10;ZGVm" hex="0a0B" '
    'count="05" name="n"><angle>45</angle><angles>1 2.5</angles></shapetype>'
)

WRAPPED = "YWJj\nZGVm"


def parse(xml: str = SOURCE, handler=None, **config) -> Shape:
    parser = XmlParser(config=ParserConfig(**config), handler=handler or XmlEventHandler)
    return parser.from_string(xml, Shape)


def render(obj) -> str:
    config = SerializerConfig(xml_declaration=False)
    return XmlSerializer(config=config).render(obj, ns_map={None: NS})


def test_off_by_default_the_converters_spelling():
    obj = parse()

    assert type(obj.spt) is float
    assert type(obj.gfxdata) is bytes
    out = render(obj)
    assert 'spt="202.0"' in out
    assert 'gfxdata="YWJjZGVm"' in out
    assert 'hex="0A0B"' in out
    assert "<angle>45.0</angle>" in out


@pytest.mark.parametrize("handler", [XmlEventHandler, LxmlEventHandler])
def test_with_the_option_each_value_keeps_its_spelling(handler):
    obj = parse(handler=handler, lexical_types=LEXICAL)

    assert type(obj.spt) is XmlLexicalFloat
    assert obj.spt.lexical == "202"
    assert type(obj.gfxdata) is XmlLexicalBytes
    assert obj.gfxdata.lexical == WRAPPED
    assert type(obj.hex) is XmlLexicalBytes
    assert obj.hex.lexical == "0a0B"
    assert type(obj.angle) is XmlLexicalFloat
    out = render(obj)
    assert 'spt="202"' in out
    assert 'gfxdata="YWJj&#10;ZGVm"' in out
    assert 'hex="0a0B"' in out
    assert "<angle>45</angle>" in out


def test_a_lexical_value_is_its_value():
    obj = parse(lexical_types=LEXICAL)

    assert obj.spt == 202.0
    assert hash(obj.spt) == hash(202.0)
    assert obj.gfxdata == b"abcdef"
    assert obj.hex == b"\x0a\x0b"
    assert obj == parse()  # equal to the plain parse, field for field
    assert repr(obj.spt) == "202.0"


def test_a_value_the_converter_spells_as_its_source_is_plain():
    obj = parse(
        f'<shapetype xmlns="{NS}" spt="0.5" gfxdata="YWJjZGVm" hex="0A0B"/>',
        lexical_types=LEXICAL,
    )

    assert type(obj.spt) is float
    assert type(obj.gfxdata) is bytes
    assert type(obj.hex) is bytes


def test_only_the_types_asked_for():
    obj = parse(lexical_types=frozenset({float}))

    assert type(obj.spt) is XmlLexicalFloat
    assert type(obj.gfxdata) is bytes
    assert 'gfxdata="YWJjZGVm"' in render(obj)


def test_other_types_and_tokens_are_untouched():
    obj = parse(lexical_types=LEXICAL)

    assert type(obj.count) is int
    assert obj.count == 5
    assert type(obj.name) is str
    assert [type(v) for v in obj.angles] == [float, float]
    out = render(obj)
    assert 'count="5"' in out
    assert "<angles>1.0 2.5</angles>" in out


def test_a_value_changed_or_set_in_code_takes_the_converters_spelling():
    obj = parse(lexical_types=LEXICAL)

    obj.spt = obj.spt + 1  # arithmetic gives a plain float
    obj.gfxdata = b"xyz"
    assert type(obj.spt) is float
    out = render(obj)
    assert 'spt="203.0"' in out
    assert 'gfxdata="eHl6"' in out


def test_copied_and_pickled_with_its_spelling():
    obj = parse(lexical_types=LEXICAL)

    assert copy.copy(obj.spt) is obj.spt
    assert copy.deepcopy(obj.gfxdata) is obj.gfxdata
    again = pickle.loads(pickle.dumps(obj))
    assert again.spt.lexical == "202"
    assert again.gfxdata.lexical == WRAPPED
    assert render(copy.deepcopy(obj)) == render(obj)


def test_the_tree_serializer_writes_the_spelling():
    obj = parse(lexical_types=LEXICAL)

    root = TreeSerializer().render(obj, ns_map={None: NS}).getroot()
    assert root.get("spt") == "202"
    assert root.get("gfxdata") == WRAPPED


def test_an_unsupported_type_is_refused():
    with pytest.raises(ValueError, match="no lexical class for int"):
        ParserConfig(lexical_types=frozenset({int}))


def test_a_value_that_does_not_convert_is_reported_as_before():
    with pytest.warns(Warning, match="Failed to convert value"):
        obj = parse(
            f'<shapetype xmlns="{NS}" spt="lots"/>', lexical_types=LEXICAL
        )

    assert obj.spt == "lots"
