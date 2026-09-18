# CR-001: The serialiser, and the parser after it

**Status:** Proposed 2026-09-19. **Phase A implemented 2026-09-19** (in docx4j-python, not in the
fork; section 8 below, and docx4j-python's CR-002 section 12.13). Phases B, C and D proposed.
**Where:** this fork (`~/git/docx4j-xsdata`, branch `docx4j`), for phases B, C and D;
**docx4j-python** (`../docx4j-python`, its engine's `XmlPart._marshal`) for Phase A, which is not
the serialiser at all and is where the measurement says to start.
**Depends on:** nothing. docx4j-python's CR-005 (SpreadsheetML) asks for this first; its CR-004
and the large-document story benefit.
**Counterpart:** upstream xsdata's `XmlSerializer` / `EventGenerator` / `LxmlEventWriter` and
`XmlParser` / `LxmlEventHandler`, which the fork carries unchanged so far
(`docs/fork/CHANGES.md` records every difference from upstream `v26.2`); the deferred upstream
reports in docx4j-python's `docs/UPSTREAM.md`, which a runtime speed-up would join.

## 1. Why

docx4j-python's throughput is the one number that limits it. Measured on 2026-09-18 and
2026-09-19 (`docs/python_ecosystem.md` in the portfolio; the profile below) on
`samples/Symbols.docx`, whose main part is 771 KB, 24,758 elements and 3,902 runs:

| | ms | rate |
|---|---:|---:|
| parse `document.xml` into typed objects | 294 | 2.6 MiB/s |
| marshal it back | 820 | 0.9 MiB/s |
| python-docx (lxml, no typed objects), open plus save with an edit | 26 | |

A typical document costs three times python-docx; this one costs forty, because the first edit
re-marshals the whole main part. A 50 MB spreadsheet sheet would be twenty seconds to parse
and a minute to write, which is why CR-005 keeps sheet data out of the typed model altogether.
The decision of 2026-09-12 accepted about 1 s of import and 3 MiB/s for a long-running process;
it did not accept 0.9 MiB/s, and the serialiser was never profiled until now.

## 2. Where the time goes

A `cProfile` of `XmlPart._marshal` over that part (2.4 s under the profiler for 0.82 s real):

| where | share | what it is |
|---|---:|---|
| `XmlPart._marshal` in docx4j-python: `_redeclare` | **345 ms of the 820 real, 42%** | the engine copies the whole tree into a new root to change its namespace map, so that the prefixes `mc:Ignorable` names are declared; lxml walks 24,758 nodes to move them |
| the same method: the three passes | (in the rest) | xsdata renders to a **string**, lxml **parses** it back, `cleanup_namespaces`, `_redeclare`, `tostring`: the document is serialised twice and parsed once on every marshal |
| `mixins.py:start_namespaces` | 0.40 s profiled, the largest single function | per-element namespace bookkeeping: for every element the writer checks each attribute's and the element's namespace against the running prefix map |
| `convert_dataclass` → `convert_value` → `convert_any_type` → `convert_xsi_type` → `convert_elements` / `convert_choice` → `generate` | 0.9 s profiled, 5 to 7 nested calls per value | the generic dispatch for every field value, including the `xsi:type` decision, which is never needed when the value's class is the field's declared class (always, for a document this engine parsed) |
| `next_value` / `next_attribute` | 0.18 s | generators over a class's metadata, rebuilt per instance |
| `dict.get` | 3.2 M calls | the metadata lookups the above imply |
| `sorted` | 49,516 calls | attribute ordering per element |

And the parser (1.06 s profiled for 0.29 real): `LxmlEventHandler.process_context` drives it; per
element `bases.start` → `element.bind` → `bind_attrs` / `bind_content` → `build_node` /
`build_element_node` / `child`, and `converter.deserialize` per attribute; `link_parents` in
docx4j-python's `child.py` is 0.12 s of it, the one docx4j-python cost on that path.

## 3. Design

Four phases, each measured before the next starts, each gated by docx4j-python's round trip
staying **canonically identical** over its corpus (`scripts/roundtrip.py`, every category zero
but `boolean-spelling`) and its suite green. The benchmark is one script, committed in
docx4j-python as `scripts/bench_marshal.py`: parse and marshal of every WordprocessingML main
part in `samples/` plus `Symbols.docx` on its own, median of five, printed as a table; its
output before and after each phase goes in this CR's notes.

### 3.1 Phase A, the engine, not the fork: one pass instead of three

In docx4j-python's `XmlPart._marshal`: render straight to an **lxml tree** with the final
namespace map, and serialise once.

- xsdata's `XmlSerializer.render` takes `ns_map`; the engine already computes the prefixes it
  wants (the table plus the `mc:Ignorable` ones plus the source root's). Pass the **complete**
  map up front, so nothing needs re-declaring.
- Use `TreeSerializer` (xsdata's lxml-tree writer, `serializers/tree.py`) or `LxmlEventWriter`
  into a tree rather than a string, then `cleanup_namespaces` in place only when the map was
  over-declared, then `tostring`. No re-parse, no `_redeclare`.
- `_rename` (a different root element name) becomes `root.tag = ...` on the tree.

Expected: the 345 ms copy and the re-parse go; `Symbols.docx` from 820 ms to about 450 ms with
no change in the fork. This is the cheapest 40% in the whole portfolio and it is docx4j-python's
to take, recorded in its CR-002 as an amendment (section 12.13) when done. **One day.**

### 3.2 Phase B, the writer's per-element cost

In the fork's `formats/dataclass/serializers/mixins.py`, keeping upstream's structure so the
diff stays reviewable and upstreamable:

- **Namespace work per class, not per element.** Precompute, per `XmlMeta`, the element and
  attribute qnames with their prefixes under the serialiser's `ns_map` (the map is fixed for a
  `render` call), so `start_namespaces` becomes a check of one flag per element and the running
  prefix map is touched only when an unseen namespace appears (wildcard content, `xsi:type`).
- **A fast path in `convert_value`.** When the field is a single dataclass-typed element and the
  value's class **is** the declared class (or a `Substitutions`-known one), skip `convert_xsi_type`
  and `convert_any_type` and go to `convert_dataclass` directly; the `xsi:type` decision stays for
  every other case.
- **Cache the metadata iteration.** `next_value` / `next_attribute` rebuilt per instance become a
  per-class tuple of `(var, getter)` in field order, computed once on first use; `sorted` of
  attributes done once per class.
- **Fewer events.** `write` yields one tuple per element for the common case rather than start,
  attributes, text and end as separate events.

Expected: the writer's share halves; `Symbols.docx` to about 250 ms. Each change is a candidate
upstream contribution (docx4j-python `docs/UPSTREAM.md` gets an entry) because none depends on
the fork's other changes. **Two days.**

### 3.3 Phase C, generated writers (only if B measures short)

The generator emits, per class, a `__write__(self, writer, ns)` method that walks its fields in
order with the qnames as literals, the way the `code` serialiser already emits Python for
dataclasses in the other direction. No dispatch, no metadata lookups at run time; the generic
path stays for wildcard content and `AnyElement`. Expected: a further 2 to 3×, at the price of
a bigger generated package (the import-time budget of docx4j-python CR-001 section 8 is the
limit: the methods must not add more than 10% to import) and a generator change to maintain
through rebases. **Three days.** Started only if Phase B leaves the writer above 3 MiB/s.

### 3.4 Phase D, the parser

The same two ideas on the read side: per-class binding plans (the child-element lookup table,
the attribute converters in a tuple) built once, and a fast path in `bind_content` for a child
whose declared type is a single dataclass; `link_parents` in docx4j-python folded into the
parser's end-element callback (one walk instead of two, which docx4j-python's `child.py` can
offer as a hook). Expected: 2×, to about 5 MiB/s. **Two days.**

## 4. What does not change

- The generated model's shape, the `el` tables, `Child` and `ChildList`: nothing a caller sees.
- Fidelity: the round trip's canonical identity is the gate for every phase, and the
  skipped-content report and numeric booleans are untouched.
- Upstream's structure: every change is a diff over upstream's files, recorded in
  `docs/fork/CHANGES.md` as a new stage with the measurement, so that `REBASING.md`'s procedure
  still applies and each piece can be offered upstream.

## 5. Tests

- The fork's `tests/fork/`: a serialiser test per change (namespace precomputation over a
  multi-namespace document with wildcards and `xsi:type`; the fast path never taken for a
  subclass value; attribute order unchanged), and the benchmark's numbers asserted as a floor
  (not a ceiling) with a generous margin.
- docx4j-python: the whole suite and `scripts/roundtrip.py` before each phase's commit; the
  benchmark table in the phase notes.

## 6. Phasing and effort

| Phase | Where | Content | Effort |
|---|---|---|---|
| A | docx4j-python | one pass: render to a tree with the full `ns_map`, no re-parse, no `_redeclare` | 1 day |
| B | the fork | per-class namespace plans, the `convert_value` fast path, cached metadata iteration, fewer events | 2 days |
| C | the fork | generated per-class writers, only if B leaves the writer under 3 MiB/s | 3 days |
| D | the fork (and `child.py`) | per-class binding plans, the `bind_content` fast path, `link_parents` folded in | 2 days |

## 7. Open questions (recommendations for decision)

1. **Generated writers or runtime only.** Recommendation: runtime only (A, B, D) first, measure,
   and start C only against a measured shortfall; a generator change is the most expensive kind
   to carry through rebases.
2. **Bypass xsdata's event layer and emit lxml directly.** Recommendation: no; the
   `LxmlEventWriter` into a tree is the supported path and Phase A gets the big win without
   leaving it.
3. **Cython or mypyc for `mixins.py`.** Recommendation: no; it complicates the wheel and the
   rebase for a gain Phase B should get in pure Python.
4. **Target.** Recommendation: parse and marshal both at or above 5 MiB/s on `Symbols.docx`, which
   makes a 5 MB main part a two-second edit and a 50 MB one still a spreadsheet problem, as
   CR-005 assumes.

## 8. Phase A implementation notes (2026-09-19)

### 8.1 What changed

One method, `XmlPart._marshal`, in **docx4j-python** (`docx4j_py/openpackaging/parts/xml_part.py`);
nothing in the fork. It was five steps --- render to a string, `etree.fromstring` it back,
`cleanup_namespaces`, copy the whole tree into a new root with `_redeclare`, `tostring` --- and is
now three, with one serialisation and no parse:

1. `runtime.tree_serializer(bool_format=...).render(obj, ns_map).getroot()`. The new
   `tree_serializer()` is the twin of docx4j-python's `serializer()`: the same
   `serializer_config()` (numeric booleans, no declaration), the fork's
   `serializers.tree.TreeSerializer` instead of `XmlSerializer`.
2. `root.tag = wanted` where the part's `root_name` differs from the object's element name
   (`w:glossaryDocument` over a `Document`, the only such shape in the corpus). lxml keeps the
   root's namespace declarations through the assignment, and the wanted namespace is declared
   already because the render declares the whole prefix table, so the rename keeps its prefix.
   `_rename`'s tree copy is gone.
3. `etree.cleanup_namespaces(root)`, then --- only when `mc:Ignorable` names a prefix the cleanup
   just dropped --- a second `etree.cleanup_namespaces(root, top_nsmap=missing,
   keep_ns_prefixes=list(missing))`, which declares those prefixes on the root and stops the
   cleanup taking them straight back off. This replaces `_redeclare`'s copy of 24,758 nodes into a
   fresh root. Two cleanup passes rather than one because the order of the declarations must stay
   what it was: the ignorable prefixes the tree does not use are declared **after** the ones it
   does, which is what a single call with `top_nsmap` would not give (the prefixes are in the
   render's map already, so they would keep their table position instead of moving to the end).
   Both passes together are 4.8 ms of a 469 ms marshal.

`_redeclare`, `_rename` and the module's `_LXML_PARSER` are deleted; nothing else used them.

### 8.2 The benchmark

`scripts/bench_marshal.py` in docx4j-python, as section 3 asks: every WordprocessingML main
document part in `samples/`, parse and marshal, median of five, `--json` for machine use. Python
3.14, lxml 6.1, the same machine and the same run of the corpus.

**Before** (commit 959edcb):

| document | KB | parse ms | MiB/s | marshal ms | MiB/s |
|---|---:|---:|---:|---:|---:|
| 2010-glow-then-AlternateContent.docx | 9 | 1.1 | 7.50 | 2.0 | 4.11 |
| 2010-mcAlternateContent-in-header.docx | 1 | 0.2 | 5.16 | 0.6 | 1.82 |
| 2010-sample1.docx | 4 | 1.5 | 2.48 | 2.8 | 1.27 |
| 2016_image_with_text_effects.docx | 4 | 0.8 | 4.85 | 1.5 | 2.59 |
| DrawingML_GraphicData_wps.docx | 14 | 1.3 | 11.07 | 2.6 | 5.34 |
| Headers.docx | 6 | 1.8 | 3.11 | 3.2 | 1.77 |
| Images.docx | 3 | 0.9 | 3.29 | 1.8 | 1.62 |
| Normal.dotm | 2 | 0.2 | 11.05 | 0.5 | 3.53 |
| **Symbols.docx** | **772** | **302.4** | **2.49** | **887.1** | **0.85** |
| invoice2013.docx | 25 | 7.8 | 3.13 | 10.0 | 2.43 |
| sample-docx.docx | 17 | 8.6 | 1.91 | 13.1 | 1.25 |
| tables.docx | 51 | 26.3 | 1.90 | 36.6 | 1.37 |
| toc.docx | 51 | 13.4 | 3.73 | 20.3 | 2.46 |
| w14_texteffects.docx | 6 | 1.5 | 3.78 | 2.7 | 2.08 |

14 documents, 964 KB of main parts: parse 368 ms, **marshal 985 ms**.

**After** (commit 7b501f5):

| document | KB | parse ms | MiB/s | marshal ms | MiB/s |
|---|---:|---:|---:|---:|---:|
| 2010-glow-then-AlternateContent.docx | 9 | 1.0 | 8.30 | 1.7 | 4.75 |
| 2010-mcAlternateContent-in-header.docx | 1 | 0.2 | 5.30 | 0.5 | 2.23 |
| 2010-sample1.docx | 4 | 1.4 | 2.63 | 2.5 | 1.45 |
| 2016_image_with_text_effects.docx | 4 | 0.8 | 4.70 | 1.3 | 3.03 |
| DrawingML_GraphicData_wps.docx | 14 | 1.2 | 11.44 | 2.3 | 6.15 |
| Headers.docx | 6 | 1.8 | 3.11 | 2.9 | 1.98 |
| Images.docx | 3 | 0.9 | 3.23 | 1.7 | 1.73 |
| Normal.dotm | 2 | 0.2 | 11.06 | 0.4 | 4.34 |
| **Symbols.docx** | **772** | **302.6** | **2.49** | **484.5** | **1.56** |
| invoice2013.docx | 25 | 6.2 | 3.91 | 8.2 | 2.96 |
| sample-docx.docx | 17 | 6.9 | 2.36 | 10.4 | 1.56 |
| tables.docx | 51 | 28.8 | 1.74 | 34.4 | 1.46 |
| toc.docx | 51 | 13.2 | 3.79 | 18.9 | 2.64 |
| w14_texteffects.docx | 6 | 1.4 | 3.98 | 2.3 | 2.46 |

14 documents, 964 KB of main parts: parse 367 ms, **marshal 572 ms**.

`Symbols.docx`, the number section 1 states the target against: **marshal 887 ms to 484 ms, 0.85
to 1.56 MiB/s, 45% off**. Section 3.1 expected "about 450 ms"; the measured 484 ms is that, within
the noise of the machine. Parse is untouched, as it should be (302 ms, 2.49 MiB/s).

### 8.3 Where the 484 ms now is

Timed stage by stage on `Symbols.docx`'s main part, median of five:

| stage | ms | share |
|---|---:|---:|
| render to a tree (the fork's `TreeSerializer`) | 450.2 | 96% |
| `cleanup_namespaces` | 3.0 | 0.6% |
| the `mc:Ignorable` walk (`_ignorable_prefixes`) | 10.2 | 2.2% |
| the re-declare cleanup | 1.8 | 0.4% |
| `tostring` | 4.4 | 0.9% |
| total | 468.9 | |

The engine's own share of a marshal is now 19 ms, and the largest piece of it is a full-tree walk
looking for `mc:Ignorable` attributes, which only the root and a handful of elements ever carry.
Everything else belongs to the fork, which is Phase B's subject.

### 8.4 What Phase B starts from

`cProfile` of one `_marshal` of that part (1.99 s profiled for 0.48 s real), by `tottime`:

| # | function | ncalls | tottime | cumtime |
|---:|---|---:|---:|---:|
| 1 | `mixins.py:263 start_namespaces` | 24,758 | 0.391 | 0.679 |
| 2 | `dict.get` | 3,193,937 | 0.282 | 0.282 |
| 3 | `mixins.py:524 convert_dataclass` | 458,205/79,961 | 0.124 | 0.911 |
| 4 | `mixins.py:617 convert_value` | 555,493/79,958 | 0.111 | 0.896 |
| 5 | `mixins.py:704 convert_any_type` | 378,244/79,958 | 0.094 | 0.880 |
| 6 | `mixins.py:443 start_element` | 24,758 | 0.081 | 0.081 |
| 7 | `mixins.py:579 convert_xsi_type` | 378,244/79,958 | 0.076 | 0.865 |
| 8 | `mixins.py:924 next_value` | 48,946 | 0.054 | 0.128 |
| 9 | `isinstance` | 340,833 | 0.052 | 0.073 |
| 10 | `mixins.py:90 write` | 1 | 0.051 | 1.967 |
| 11 | `mixins.py:833 convert_choice` | 174,461/80,091 | 0.043 | 0.804 |
| 12 | `mixins.py:980 next_attribute` | 51,845 | 0.039 | 0.171 |
| 13 | `mixins.py:814 convert_elements` | 170,534/79,933 | 0.038 | 0.821 |
| 14 | `mixins.py:234 flush_start` | 52,873 | 0.036 | 0.821 |

This is section 2's profile with the engine's own costs taken out of it, and it says the same
things, so section 3.2's four items stand unchanged and in the same order: `start_namespaces` is
still the single largest function (one call per element, 0.39 s of 1.99 profiled); the 3.2 M
`dict.get` are the metadata lookups behind it and behind `convert_*`; `convert_any_type` and
`convert_xsi_type` are called 378,244 times for an `xsi:type` decision that a document parsed by
this engine never needs; `next_value` and `next_attribute` rebuild a generator per instance.

Two things Phase B should know that the earlier profile did not say:

* **`flush_start` is 52,873 calls for 24,758 elements**, so the "fewer events" item of section 3.2
  has more in it than the element count suggests; the attribute and text events dominate.
* **`TreeSerializer` and `XmlSerializer` are the same writer** up to the last step (below), so
  every Phase B change to `mixins.py` applies to both and the benchmark measures it through the
  tree path.

### 8.5 The tree writer against the string writer

Checked, because Phase A's acceptance is byte equality and the two writers are different classes:

* Both are built on `EventGenerator`, and `LxmlTreeBuilder` and `LxmlEventWriter` are both
  `EventContentHandler` over `lxml.sax.ElementTreeContentHandler`. The event stream, the namespace
  bookkeeping, the attribute order, `xml:space`, empty elements and text escaping are therefore
  the **same code**, and `bool_format` and the rest of `SerializerConfig` mean the same thing
  through both. No fork change was needed and none was made.
* Two differences, neither of which the round trip depends on. `XmlWriter.start_document` writes
  the XML declaration to the output stream and does **not** call `handler.startDocument()`, where
  `EventContentHandler.start_document` (so `LxmlTreeBuilder`) does; for lxml's content handler
  that call is a no-op. And `xml_declaration` has no meaning for a tree: the engine writes its own
  declaration (Word's, CRLF and all) either way.
* The string path ended `etree.tostring(handler.etree)` and the engine then parsed that back, so
  it had one XML parse of its own output on every marshal. Dropping it is safe for exactly the
  reason it was pointless: the tree the engine went on to work with was the tree the sax handler
  had just built.

### 8.6 Fidelity

* **Byte equality, part for part.** docx4j-python's new
  `tests/openpackaging/test_marshal_one_pass.py` keeps the old method as `reference_marshal` and
  marshals every typed XML part of every sample both ways: **150 parts over 16 documents,
  identical**.
* One deliberate departure, found by that test and worth recording because it was a latent bug.
  The old method iterated a **`set`** of the prefixes it was re-adding, so the *order* of the
  namespace declarations on a saved root was a function of `PYTHONHASHSEED`: over three seeds,
  **49 of the 150 parts** produced three different byte strings. Both the new method and the
  reference sort, so the output is now deterministic; the affected parts differ from an arbitrary
  earlier run only in the order of the declarations, which is canonically identical
  (`scripts/canon.py`) and is what Word, C14N and the round trip all already treated as the same
  document.
* docx4j-python's suite: 1,553 passed, 2 skipped, 1 xfailed.
* `scripts/roundtrip.py --models-module docx4j_py.wml --runtime docx4j_xsdata`: 50/50 parts
  canonically identical, 0 differences, 0 skipped, 34 `boolean-spelling` respellings and no other
  category --- the gate of section 3, unchanged.
* `scripts/acceptance.py` regenerated. Against the eleven artefacts built from the commit before
  the change, every differing entry is either a wall-clock date (`docProps/core.xml`, the comment
  and revision dates) or the namespace declaration order above, and all ten differing parts are
  canonically identical once the dates are scrubbed. All eleven **passed in Word** on
  2026-09-19; docx4j-python's `tests/README.md` records the run.
