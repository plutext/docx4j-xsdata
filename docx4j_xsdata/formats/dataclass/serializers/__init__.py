from contextlib import suppress

from docx4j_xsdata.formats.dataclass.serializers.code import PycodeSerializer
from docx4j_xsdata.formats.dataclass.serializers.dict import DictEncoder, DictFactory
from docx4j_xsdata.formats.dataclass.serializers.json import JsonSerializer
from docx4j_xsdata.formats.dataclass.serializers.xml import XmlSerializer

__all__ = [
    "DictEncoder",
    "DictFactory",
    "JsonSerializer",
    "PycodeSerializer",
    "XmlSerializer",
]

with suppress(ImportError):
    from docx4j_xsdata.formats.dataclass.serializers.tree import (
        TreeSerializer,  # noqa: F401
    )

    __all__.append("TreeSerializer")
