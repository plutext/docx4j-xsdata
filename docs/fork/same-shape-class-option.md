# A same-shape class written under the element its field matched

A note on a fork option that has been asked about and not asked for. Written 2026-10-28,
after docx4j-python's CR-020 Phase A (its sections 10.3, 10.11 item 1 and 10.12 item 4) and
docx4j-python's `docs/UPSTREAM.md` report 28. No code here changes; this records what the
option would be, what it would cost, and what else would do the same job, so the decision can
be made when something needs it.

## 1. The behaviour today

When an item in a compound (choice) field is an instance of none of the field's choice
classes, the serialiser has only the item's class to go on:

1. `convert_choice` (`docx4j_xsdata/formats/dataclass/serializers/mixins.py`) asks
   `var.find_value_choice(value, True)`, which is `XmlVar.find_clazz_choice(type(value))`
   (`formats/dataclass/models/elements.py`): an exact class match first, else the **first**
   choice whose class the item's class subclasses.
2. With no choice at all, it hands the compound var itself to `convert_xsi_type`, whose
   compound branch calls `convert_dataclass(value, qname=meta.target_qname)`.
3. `meta.target_qname` is None for a class with no element name of its own, which is every
   intermediate class the generator makes for a complex type several elements share. So
   `convert_dataclass` falls back to the fork's `SerializerConfig.element_names` table
   (stage 11, item 26), else `meta.qname`, which for such a class is the class's name.

Hence `<MoveFrom1>` in a paragraph and `<Sat1>` in a colour, elements no schema declares; and
`MoveFromRangeStart1`, a `CTMoveBookmark` and so a `CTBookmark`, written in `P.content` as
`<w:bookmarkStart>` with its `w:author` and `w:date`, with an `xsi:type` where the class has a
type name of its own. The serialiser never asks whether the item's class *is the same element*
as one of the field's choices, because nothing in xsdata's metadata records that `MoveFrom1` is
a `w:moveFrom`.

docx4j-python measured it (CR-020 10.3) over every checked compound field, for the classes of a
many-class element name the field does not declare:

| strangers of | count | CR-020's add-time verdict |
|---|---|---|
| one shape, written under the field's element name with no `xsi:type` | 300 | accepted |
| one shape, written otherwise (class name, or the wrong choice's name) | 692 | refused |
| another shape | 448 | refused |

The 692 are refused by rule 2's third condition (`placement.written_as`, a step-for-step
re-implementation of the serialiser's choice), because accepting them would save the
"unreadable content" that CR exists to prevent.

## 2. Two cases in the 692, two different fixes

**Class-name strangers** can be fixed in docx4j-python alone, today. `element_names` is read
by `convert_dataclass` exactly when no field names the object, and the compound fallback is such
a case. docx4j-python's table (`runtime._branch_element_names`) names 113 root-container classes
and none of the 72 intermediate WML classes. Adding them, `MoveFrom1` to `{w}moveFrom`, makes the
serialiser write `<w:moveFrom>`; `written_as` reads the same table, so rule 2 would accept those
placements with no fork change and no fork release.

**Subclass strangers** cannot be fixed by a table. `find_clazz_choice` returns the first choice
the class subclasses before any table is consulted, so `MoveFromRangeStart1` is `<w:bookmarkStart>`
whatever the table says. Only a change to the serialiser's order of questions fixes this half.

How the 692 split between the two cases has not been measured. `written_as` can count it: those
for which `find_clazz_choice` answers None are the first case.

## 3. The option

A `SerializerConfig` field, off by default, provisionally `choices_by_name: bool = False`.

In `convert_choice`, after the exact-class fast path misses and before the subclass fallback:

1. resolve the item's own element name: `meta.target_qname`, else `config.element_names.get(cls)`;
2. if that name is one of this field's choices (`var.find_choice(name)`), write the item under
   that choice's qname through `convert_dataclass`, with no `xsi:type`;
3. otherwise fall through to today's behaviour unchanged.

With the flag off the method is byte-for-byte today's. The check sits in the branch the exact-class
fast path (`value.__class__ is choice.clazz`, item 11's `fast_element`) already skips, so the hot
path pays nothing and off is free. On, it costs one lookup per item that is not exactly a choice
class, which is rare in a parsed document and common only for hand-built content.

**"Same shape" means nothing in the fork.** The serialiser cannot judge two classes' shapes cheaply
and should not try; it would trust the name table as the statement that the class *is* that
element. The shape check stays where it is, in docx4j-python's `placement.shape_of` at add time,
which refuses the 448 of another shape before anything reaches the serialiser. That division is
the right one: the fork writes what it is told a class is, the binding layer decides what may be
added.

**The parser is untouched.** `<w:moveFrom>` in a paragraph reads back as the paragraph's own
`MoveFrom` class, not `MoveFrom1`; the round trip changes the item's class. That is already true
of the 300 accepted today.

## 4. What docx4j-python would have to change

More than CR-020 section 10.12 item 4 suggests ("no change here beyond the test's expected
counts"). `written_as` is not a call into the serialiser but a re-implementation of its steps, so
it would gain the same step in the same place, guarded by the same configuration, or the rule and
the save would disagree. Then:

- the table of 72 intermediate classes to element names, fed to `element_names` through
  `runtime.serializer_config` (the class-name half needs this whether or not the option exists);
- `test_an_accepted_stranger_is_saved_as_the_element_the_field_takes`'s expected counts, from 300
  accepted to about 992, each still rendered and held to the element name with no `xsi:type`;
- the lower bound raised to the fork release carrying the option, in the usual order
  (`CLAUDE.md`, "Releasing").

## 5. The alternative with no fork change

docx4j-python's add-time check could convert a same-shape stranger into the field's own class on
the way in: the fields are identical by construction (that is what one shape means), so
`choice.clazz(**fields)` is a faithful copy. The serialiser then never sees a stranger. The cost
is that the item's identity changes on append, so a caller holding the original holds something
no longer in the tree, which `ChildList`'s parent bookkeeping would have to make visible.

## 6. Assessment

The 692 are a convenience: any same-shape class works in any holder, as a JAXB user expects
because JAXB has one class per type. Today they fail fast with a `MisplacedContentError` that
names the holder, the field and the item, and the right class is one `el` factory call away.

Recommendation: do not add the option until a real engine path or user hits the refusal. If the
class-name half is wanted first, it is a table edit in docx4j-python with no fork release. The
upstream report (docx4j-python `docs/UPSTREAM.md` report 28) stands either way: the bug is that
upstream's `convert_xsi_type` invents an undeclared element silently, and a `SerializerError`
there would be the plain upstream fix; writing by a name table is the fork's shape of the fix, as
reports 21 and 22 were for wildcards.

If it is done, it is one item (the next free number in `CHANGES.md`), one commit, one test file
`tests/fork/test_choices_by_name.py` pinning the default as well as the option, and this file
becomes that item's design note.
