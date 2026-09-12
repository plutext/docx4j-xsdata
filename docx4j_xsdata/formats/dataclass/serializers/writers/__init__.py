from docx4j_xsdata.formats.dataclass.serializers.mixins import XmlWriter
from docx4j_xsdata.formats.dataclass.serializers.writers.native import (
    XmlEventWriter,
)

try:
    from docx4j_xsdata.formats.dataclass.serializers.writers.lxml import LxmlEventWriter

    DEFAULT_XML_WRITER: type[XmlWriter] = LxmlEventWriter
except ImportError:  # pragma: no cover
    DEFAULT_XML_WRITER = XmlEventWriter


__all__ = [
    "DEFAULT_XML_WRITER",
    "LxmlEventWriter",
    "XmlEventWriter",
]
