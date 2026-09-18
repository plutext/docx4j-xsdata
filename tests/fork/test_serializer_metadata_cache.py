"""docx4j fork: the class's var lists, sorted once instead of once per instance.

CR-001 section 3.2, the third item. `XmlMeta.get_element_vars` and
`get_attribute_vars` chain the class's wildcards, choices, elements, text and
attributes together and `sorted` them by field index -- and the serializer asks
for both for every instance it writes, 49,516 `sorted` calls for one 24,758
element part. The answer is a property of the class, so the fork builds each
list on first use and keeps it on the meta.

The order those lists impose *is* the order of the elements and attributes in
the output, so the tests here are about the order: against upstream v26.2's
accessors as an oracle, and in the bytes.
"""

import itertools
from dataclasses import dataclass, field
from typing import Any

import pytest

from docx4j_xsdata.formats.dataclass.context import XmlContext
from docx4j_xsdata.formats.dataclass.models.elements import XmlMeta, XmlVar, get_index
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.mixins import (
    EventIterator,
    XmlWriterEvent,
)

NS = "urn:fork:meta"


# ---------------------------------------------------------------------------
# a class with one of everything, deliberately out of index order
# ---------------------------------------------------------------------------


@dataclass
class Child:
    """A model child."""

    class Meta:
        name = "child"
        namespace = NS

    value: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Everything:
    """Attributes, an attribute wildcard, elements, a wildcard and text."""

    class Meta:
        name = "everything"
        namespace = NS

    zeta: str | None = field(default=None, metadata={"type": "Attribute"})
    other: dict[str, str] = field(default_factory=dict, metadata={"type": "Attributes"})
    alpha: str | None = field(default=None, metadata={"type": "Attribute"})
    child: list[Child] = field(
        default_factory=list, metadata={"type": "Element", "namespace": NS}
    )
    beta: str | None = field(
        default=None, metadata={"type": "Element", "name": "beta", "namespace": NS}
    )
    content: list[object] = field(
        default_factory=list, metadata={"type": "Wildcard", "namespace": "##any"}
    )


@dataclass
class Sequential:
    """Two sequential fields, rendered in parallel order."""

    class Meta:
        name = "sequential"
        namespace = NS

    a: list[str] = field(
        default_factory=list,
        metadata={"type": "Element", "name": "a", "namespace": NS, "sequence": 1},
    )
    b: list[str] = field(
        default_factory=list,
        metadata={"type": "Element", "name": "b", "namespace": NS, "sequence": 1},
    )


# ---------------------------------------------------------------------------
# upstream v26.2's accessors, as the oracle
# ---------------------------------------------------------------------------


def upstream_element_vars(meta: XmlMeta) -> list[XmlVar]:
    """`XmlMeta.get_element_vars` exactly as upstream v26.2 has it."""
    result = list(
        itertools.chain(meta.wildcards, meta.choices, *meta.elements.values())
    )
    if meta.text:
        result.append(meta.text)

    return sorted(result, key=get_index)


def upstream_attribute_vars(meta: XmlMeta) -> list[XmlVar]:
    """`XmlMeta.get_attribute_vars` exactly as upstream v26.2 has it."""
    result = itertools.chain(meta.any_attributes, meta.attributes.values())
    return sorted(result, key=get_index)


def meta_of(clazz: type) -> XmlMeta:
    """A fresh meta for `clazz`, from a fresh context."""
    return XmlContext().build(clazz)


CLASSES = [Everything, Sequential, Child]


# ---------------------------------------------------------------------------
# the lists are upstream's lists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("clazz", CLASSES, ids=lambda c: c.__name__)
def test_the_var_lists_are_upstreams(clazz) -> None:
    """Same vars, same order, which is what the document's order is."""
    meta = meta_of(clazz)

    assert [v.name for v in meta.get_element_vars()] == [
        v.name for v in upstream_element_vars(meta)
    ]
    assert [v.name for v in meta.get_attribute_vars()] == [
        v.name for v in upstream_attribute_vars(meta)
    ]


@pytest.mark.parametrize("clazz", CLASSES, ids=lambda c: c.__name__)
def test_the_lists_are_built_once(clazz) -> None:
    """The second caller gets the first caller's list."""
    meta = meta_of(clazz)
    assert meta.element_vars is None
    assert meta.attribute_vars is None

    elements = meta.get_element_vars()
    attributes = meta.get_attribute_vars()

    assert meta.get_element_vars() is elements
    assert meta.get_attribute_vars() is attributes


def test_the_lists_are_in_field_index_order() -> None:
    """Both, whatever order the elements and attributes mappings are in."""
    meta = meta_of(Everything)

    for vars_ in (meta.get_element_vars(), meta.get_attribute_vars()):
        indexes = [var.index for var in vars_]
        assert indexes == sorted(indexes)


# ---------------------------------------------------------------------------
# and the order in the bytes
# ---------------------------------------------------------------------------


def render(obj: Any) -> str:
    """The body of the serialized document."""
    return XmlSerializer().render(obj, {"m": NS}).splitlines()[1]


def test_attributes_are_written_in_field_order() -> None:
    """Field order, with an attribute wildcard's entries in its own place."""
    obj = Everything(zeta="z", alpha="a", other={"extra": "e"})

    assert render(obj) == (
        '<m:everything xmlns:m="urn:fork:meta" zeta="z" extra="e" alpha="a"/>'
    )


def test_elements_are_written_in_field_order() -> None:
    """The element vars' order is the children's order."""
    obj = Everything(child=[Child(value="1")], beta="b")

    assert render(obj) == (
        '<m:everything xmlns:m="urn:fork:meta">'
        '<m:child value="1"/><m:beta>b</m:beta>'
        "</m:everything>"
    )


def test_sequential_fields_are_still_rendered_in_parallel() -> None:
    """`next_value`'s sequence branch, which the caching must not disturb."""
    obj = Sequential(a=["a1", "a2"], b=["b1", "b2"])

    assert render(obj) == (
        '<m:sequential xmlns:m="urn:fork:meta">'
        "<m:a>a1</m:a><m:b>b1</m:b><m:a>a2</m:a><m:b>b2</m:b>"
        "</m:sequential>"
    )


# ---------------------------------------------------------------------------
# the class namespace `convert_dataclass` passes down
# ---------------------------------------------------------------------------


@dataclass
class Unqualified:
    """No namespace of its own: it takes the one handed down to it."""

    class Meta:
        name = "unqualified"

    kid: "Unqualified | None" = field(default=None, metadata={"type": "Element"})


class UpstreamSplit(XmlSerializer):
    """`convert_dataclass` splitting the qname the way upstream v26.2 does."""

    def convert_dataclass(
        self,
        obj: Any,
        namespace: str | None = None,
        qname: str | None = None,
        nillable: bool = False,
        xsi_type: str | None = None,
    ) -> EventIterator:
        from docx4j_xsdata.utils import namespaces

        meta = self.context.build(
            obj.__class__, namespace, globalns=self.config.globalns
        )
        qname = qname or meta.qname
        nillable = nillable or meta.nillable
        namespace, _tag = namespaces.split_qname(qname)

        yield from self._events(obj, meta, qname, namespace, nillable, xsi_type)

    def _events(self, obj, meta, qname, namespace, nillable, xsi_type) -> EventIterator:
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


@pytest.mark.parametrize(
    "obj",
    [
        Everything(zeta="z", child=[Child(value="1")], beta="b"),
        Sequential(a=["a1"], b=["b1"]),
        Unqualified(kid=Unqualified()),
    ],
    ids=["everything", "sequential", "unqualified"],
)
def test_the_class_namespace_is_upstreams(obj) -> None:
    """The meta's own split replaces a `split_qname` of the same string."""
    assert render(obj) == UpstreamSplit().render(obj, {"m": NS}).splitlines()[1]


def test_a_second_instance_of_a_class_renders_the_same() -> None:
    """The kept list is read-only to its callers; nothing consumes it."""
    obj = Everything(zeta="z", alpha="a", child=[Child(value="1")], beta="b")

    assert render(obj) == render(obj)
    assert render(obj) == render(
        Everything(zeta="z", alpha="a", child=[Child(value="1")], beta="b")
    )
