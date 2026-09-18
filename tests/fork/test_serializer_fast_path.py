"""docx4j fork: `convert_value`'s fast path for a plain dataclass element.

CR-001 section 3.2, the second item. Every element value upstream converts goes
`convert_value` -> `convert_any_type` -> `convert_xsi_type` -> `convert_dataclass`,
three isinstance checks and an xsi:type decision deep. On `Symbols.docx`'s main
part that decision is asked 378,244 times and the answer is `None` every time,
because the value's class *is* the field's declared class.

The fork answers it once per field, from the metadata (`is_fast_element`,
cached on the `XmlVar`), and goes straight to `convert_dataclass` when the
value's class is exactly the declared one. Everything else -- a subclass value,
an `object`-typed var, a wildcard, a compound field, tokens, mixed content, the
generic wrappers -- keeps upstream's path, and this module is mostly about
showing that it does.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from docx4j_xsdata.formats.dataclass.models.elements import XmlVar
from docx4j_xsdata.formats.dataclass.models.generics import AnyElement, DerivedElement
from docx4j_xsdata.formats.dataclass.serializers import XmlSerializer
from docx4j_xsdata.formats.dataclass.serializers.mixins import (
    EventGenerator,
    EventIterator,
)
from docx4j_xsdata.utils import collections

NS = "urn:fork:fast"


# ---------------------------------------------------------------------------
# the models
# ---------------------------------------------------------------------------


@dataclass
class Base:
    """The declared class of the element fields below."""

    class Meta:
        name = "base"
        namespace = NS

    value: str | None = field(default=None, metadata={"type": "Attribute"})


@dataclass
class Derived(Base):
    """A subclass: its values need an xsi:type."""

    class Meta:
        name = "derived"
        namespace = NS


@dataclass
class Holder:
    """One field per shape the fast path has to decide about."""

    class Meta:
        name = "holder"
        namespace = NS

    single: Base | None = field(
        default=None, metadata={"type": "Element", "namespace": NS}
    )
    many: list[Base] = field(
        default_factory=list,
        metadata={"type": "Element", "name": "item", "namespace": NS},
    )
    anything: object | None = field(
        default=None,
        metadata={"type": "Element", "name": "anything", "namespace": NS},
    )
    generic: AnyElement | None = field(
        default=None,
        metadata={"type": "Element", "name": "generic", "namespace": NS},
    )
    tokens: list[str] = field(
        default_factory=list,
        metadata={"type": "Element", "name": "tokens", "namespace": NS, "tokens": True},
    )
    content: list[object] = field(
        default_factory=list,
        metadata={"type": "Wildcard", "namespace": "##any"},
    )


@dataclass
class Compound:
    """A choice field: the value picks its var at run time."""

    class Meta:
        name = "compound"
        namespace = NS

    content: list[object] = field(
        default_factory=list,
        metadata={
            "type": "Elements",
            "choices": (
                {"name": "a", "type": Base, "namespace": NS},
                {"name": "b", "type": str, "namespace": NS},
            ),
        },
    )


@dataclass
class Mixed:
    """Mixed content: every value goes through `convert_any_type`."""

    class Meta:
        name = "mixed"
        namespace = NS

    content: list[object] = field(
        default_factory=list,
        metadata={"type": "Wildcard", "namespace": "##any", "mixed": True},
    )


#: One document per branch, plus the ones that must not take the fast path.
DOCUMENTS = {
    "single": Holder(single=Base(value="v")),
    "many": Holder(many=[Base(value="1"), Base(value="2")]),
    "empty-element": Holder(single=Base()),
    "subclass": Holder(single=Derived(value="v")),
    "subclass-in-list": Holder(many=[Base(value="1"), Derived(value="2")]),
    "object-var": Holder(anything=Base(value="v")),
    "object-var-primitive": Holder(anything="text"),
    "generic-var": Holder(generic=AnyElement(qname=f"{{{NS}}}g", text="t")),
    "tokens": Holder(tokens=["a", "b"]),
    "wildcard-model": Holder(content=[Base(value="w")]),
    "wildcard-any-element": Holder(content=[AnyElement(qname=f"{{{NS}}}x", text="t")]),
    "wildcard-derived": Holder(
        content=[DerivedElement(qname=f"{{{NS}}}d", value=Base(value="d"))]
    ),
    "choice-model": Compound(content=[Base(value="c")]),
    "choice-subclass": Compound(content=[Derived(value="c")]),
    "choice-primitive": Compound(content=["text"]),
    "mixed": Mixed(content=["text", AnyElement(qname=f"{{{NS}}}m")]),
    "everything": Holder(
        single=Derived(value="v"),
        many=[Base(value="1")],
        anything=Base(value="a"),
        tokens=["t"],
        content=[AnyElement(qname=f"{{{NS}}}x")],
    ),
}

CASES = [pytest.param(doc, id=name) for name, doc in DOCUMENTS.items()]

NS_MAP = {"f": NS}


# ---------------------------------------------------------------------------
# upstream v26.2's `convert_value`, as the oracle
# ---------------------------------------------------------------------------


class UpstreamEventGenerator(EventGenerator):
    """`EventGenerator` with upstream v26.2's `convert_value`."""

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


@dataclass
class UpstreamXmlSerializer(UpstreamEventGenerator, XmlSerializer):
    """The string serializer over upstream's `convert_value`."""


class CountingEventGenerator(EventGenerator):
    """Counts the xsi:type decisions the generator still asks for."""

    xsi_type_calls = 0

    def convert_xsi_type(
        self, value: Any, var: XmlVar, namespace: str | None
    ) -> EventIterator:
        self.xsi_type_calls += 1
        yield from super().convert_xsi_type(value, var, namespace)


def events(obj: Any, generator: type[EventGenerator] = EventGenerator) -> list:
    """The sax event stream `generator` produces for `obj`."""
    return list(generator().generate(obj))


def render(obj: Any) -> str:
    """The body of the serialized document."""
    return XmlSerializer().render(obj, NS_MAP).splitlines()[1]


# ---------------------------------------------------------------------------
# the contract: upstream's events, event for event
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("obj", CASES)
def test_the_event_stream_is_upstreams(obj) -> None:
    """The fast path is a shortcut through the dispatch, not a change to it."""
    assert events(obj) == events(obj, UpstreamEventGenerator)


@pytest.mark.parametrize("obj", CASES)
def test_the_document_is_upstreams(obj) -> None:
    """And the bytes with it."""
    upstream = UpstreamXmlSerializer().render(obj, NS_MAP).splitlines()[1]

    assert render(obj) == upstream


# ---------------------------------------------------------------------------
# which vars qualify
# ---------------------------------------------------------------------------


def var_of(clazz: type, name: str) -> XmlVar:
    """The field metadata of `clazz`'s field `name`."""
    from docx4j_xsdata.formats.dataclass.context import XmlContext

    meta = XmlContext().build(clazz)
    return next(var for var in meta.get_all_vars() if var.name == name)


@pytest.mark.parametrize(
    ("clazz", "name", "expected"),
    [
        (Holder, "single", True),
        (Holder, "many", True),
        (Holder, "anything", False),  # object-typed: no declared class
        (Holder, "generic", False),  # AnyElement: the generic wrapper
        (Holder, "tokens", False),
        (Holder, "content", False),  # a wildcard
        (Compound, "content", False),  # a compound field
        (Mixed, "content", False),
    ],
)
def test_which_vars_take_the_fast_path(clazz, name, expected) -> None:
    """`is_fast_element` is the whole decision, and it is made from metadata."""
    var = var_of(clazz, name)

    assert EventGenerator().is_fast_element(var) is expected


def test_the_decision_is_cached_on_the_var() -> None:
    """Once per field per process, like `namespace_matches` above it."""
    var = var_of(Holder, "single")
    assert var.fast_element is None

    list(EventGenerator().generate(Holder(single=Base(value="v"))))

    assert var_of(Holder, "single").fast_element is None  # a fresh context
    generator = EventGenerator()
    meta = generator.context.build(Holder)
    element = next(v for v in meta.get_all_vars() if v.name == "single")
    list(generator.generate(Holder(single=Base(value="v"))))
    assert element.fast_element is True


# ---------------------------------------------------------------------------
# and the xsi:type decision is gone where it should be
# ---------------------------------------------------------------------------


def test_a_document_of_declared_classes_asks_for_no_xsi_type() -> None:
    """The 378,244 decisions of the CR, none of which was ever needed."""
    generator = CountingEventGenerator()

    list(generator.generate(Holder(many=[Base(value=str(i)) for i in range(20)])))

    assert generator.xsi_type_calls == 0


def test_a_subclass_value_still_asks() -> None:
    """And still gets its xsi:type on the wire."""
    generator = CountingEventGenerator()

    list(generator.generate(Holder(single=Derived(value="v"))))

    assert generator.xsi_type_calls == 1
    assert 'type="f:derived"' in render(Holder(single=Derived(value="v")))


def test_an_object_typed_var_still_asks() -> None:
    """`object` has no declared class, so the decision is real."""
    generator = CountingEventGenerator()

    list(generator.generate(Holder(anything=Base(value="v"))))

    assert generator.xsi_type_calls == 1


def test_a_plain_element_is_written_without_an_xsi_type() -> None:
    """The fast path's own output, for the record."""
    assert render(Holder(single=Base(value="v"))) == (
        '<f:holder xmlns:f="urn:fork:fast"><f:single value="v"/></f:holder>'
    )
