"""docx4j fork: a compositor's identity in the generator is never reused.

The generator tells one ``xs:sequence``, ``xs:choice``, ``xs:all`` or
``xs:group`` from another by an integer in each attr's restriction path, and
``CreateCompoundFields`` merges into one compound field every attr whose
``choice`` integer is the same. Upstream takes that integer from ``id()``. An
XSD model object is freed once its schema has been mapped, and CPython hands its
address to the next object of the same size, so a choice of a later schema file
could take the integer of a choice of an earlier one. Two unrelated choices of
one class then merged, whenever the allocator happened to line them up.

docx4j-python met it on 2026-10-21: ``CT_TextCharacterProperties``' underline
choice (``uLnTx`` | ``uLn``, ``dml-textCharacter.xsd``) merged with the fill
choice before it (``EG_FillProperties``, another file), and only when the fork's
bytecode was already cached, which changes the allocation pattern; so
``codegen/generate.sh --check`` failed on a schema change that had nothing to do
with either. The integers now come from a counter, once per object.
"""

import gc

import pytest

from docx4j_xsdata.codegen.handlers.add_attribute_substitutions import (
    AddAttributeSubstitutions,
)
from docx4j_xsdata.codegen.models import Restrictions
from docx4j_xsdata.models import xsd
from tests.fork.utils import Generated

COMPOSITORS = (xsd.All, xsd.Sequence, xsd.Choice, xsd.Group)


def _path_id(obj: object) -> int:
    path = obj.get_restrictions()["path"]
    assert len(path) == 1
    return path[0][1]


@pytest.mark.parametrize("cls", COMPOSITORS, ids=lambda c: c.__name__)
def test_a_compositor_freed_and_another_made_never_share_an_identity(cls) -> None:
    seen = []
    for _ in range(50):
        obj = cls()
        seen.append(_path_id(obj))
        del obj
        gc.collect()
    # with id(), CPython gives the freed address to the next object
    assert len(set(seen)) == len(seen)


@pytest.mark.parametrize("cls", COMPOSITORS, ids=lambda c: c.__name__)
def test_a_compositor_keeps_its_identity(cls) -> None:
    obj = cls()
    assert _path_id(obj) == _path_id(obj)


def test_two_live_compositors_differ() -> None:
    one, two = xsd.Choice(), xsd.Choice()
    assert _path_id(one) != _path_id(two)


def test_the_path_keeps_its_shape() -> None:
    choice = xsd.Choice(min_occurs=0, max_occurs=3)
    ((kind, index, min_occurs, max_occurs),) = choice.get_restrictions()["path"]
    assert (kind, min_occurs, max_occurs) == ("c", 0, 3)
    assert isinstance(index, int)


def test_a_substituted_attrs_choice_is_never_reused() -> None:
    from docx4j_xsdata.codegen.models import Attr

    seen = []
    for _ in range(50):
        attr = Attr(tag="Element", name="a", restrictions=Restrictions())
        AddAttributeSubstitutions.prepare_substituted(attr)
        seen.append(attr.restrictions.choice)
        assert attr.restrictions.path[-1] == ("c", attr.restrictions.choice, 1, 1)
        del attr
        gc.collect()
    assert len(set(seen)) == len(seen)


TWO_CHOICES = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns="urn:fork:c" targetNamespace="urn:fork:c"
           elementFormDefault="qualified">
  <xs:group name="Fill">
    <xs:choice>
      <xs:element name="noFill" type="xs:string"/>
      <xs:element name="solidFill" type="xs:string"/>
    </xs:choice>
  </xs:group>
  <xs:group name="Line">
    <xs:choice>
      <xs:element name="uLnTx" type="xs:string"/>
      <xs:element name="uLn" type="xs:string"/>
    </xs:choice>
  </xs:group>
  <xs:complexType name="RPr">
    <xs:sequence>
      <xs:group ref="Fill" minOccurs="0"/>
      <xs:group ref="Line" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>
  <xs:element name="rPr" type="RPr"/>
</xs:schema>
"""


def test_two_choices_of_one_class_stay_two_fields(gen) -> None:
    generated: Generated = gen(TWO_CHOICES, package="compositor_identity_fork")
    source = generated.source
    assert "no_fill_or_solid_fill" in source
    assert "u_ln_tx_or_u_ln" in source
