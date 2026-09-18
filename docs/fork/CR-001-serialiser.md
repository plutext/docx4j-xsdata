# CR-001: The serialiser, and the parser after it

**Status:** Proposed 2026-09-19. **Done 2026-09-19**, less Phase C. **Phase A implemented**
(in docx4j-python, not in the fork; section 8 below, and docx4j-python's CR-002 section 12.13).
**Phase B implemented** (in the fork; section 9 below). Phase C **not started**: section 3.3's
rule is "only if B leaves the writer under 3 MiB/s" and it leaves it at 3.24 (section 9.6).
**Phase D implemented** (in the fork and in docx4j-python's `child.py`, `runtime.py` and
`XmlPart._unmarshal`; section 10 below, and docx4j-python's CR-002 section 12.14). The parse is
329 ms to 193 ms on the CR's 772 KB reference part, 2.29 to 3.90 MiB/s, and the marshal 820 ms to
250 ms, 0.9 to 3.02 MiB/s; neither half reaches section 7's 5 MiB/s, and section 10.6 recommends
closing the CR rather than starting a fifth phase.
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

## 9. Phase B implementation notes (2026-09-19)

Section 3.2's four items, in its order, each measured before the next started and each
gated on docx4j-python's 150 typed parts marshalling to the **same bytes**. Four files
changed, all in the fork: `formats/dataclass/serializers/mixins.py`,
`formats/dataclass/models/elements.py` (two lazy slots and one more), and three new test
modules under `tests/fork/`. No upstream test was edited, and no generated model, `el`
table, `Child` or `ChildList` was touched.

### 9.1 The measurement, item by item

`Symbols.docx`'s main part, 772 KB and 24,758 elements, median of five, the same machine
and the same `scripts/bench_marshal.py` as section 8.2. Run-to-run spread on this machine
is about 3%.

| after | commit | Symbols ms | MiB/s | the corpus, marshal ms |
|---|---|---:|---:|---:|
| Phase A (where B starts) | `7b501f5` (docx4j-python) | 481 | 1.57 | 565 |
| item 1, the namespace work | `bdcc8a9` | 336 | 2.24 | 399 |
| item 2, the `convert_value` fast path | `fd28e1e` | 306 | 2.47 | 365 |
| item 3, the cached metadata iteration | `1d8b1f4` | 262 | 2.88 | 314 |
| item 4, fewer frames | `8f2fe66` | 249 | 3.03 | 301 |

**`Symbols.docx`: 481 ms to 249 ms, 1.57 to 3.03 MiB/s, 48% off.** Section 3.2 expected
"the writer's share halves; `Symbols.docx` to about 250 ms"; the measured 249 is that.
Against section 1's starting point the marshal of that part is **820 ms to 249 ms, 3.3x**.
Parse is untouched, as it should be (295 ms, 2.56 MiB/s).

The whole corpus, before Phase B and after:

| document | KB | parse ms | MiB/s | marshal ms | MiB/s | after: marshal ms | MiB/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2010-glow-then-AlternateContent.docx | 9 | 1.0 | 8.70 | 1.8 | 4.72 | **1.1** | **7.41** |
| 2010-mcAlternateContent-in-header.docx | 1 | 0.2 | 5.05 | 0.5 | 2.27 | **0.4** | **2.78** |
| 2010-sample1.docx | 4 | 1.4 | 2.61 | 2.4 | 1.49 | **1.8** | **1.96** |
| 2016_image_with_text_effects.docx | 4 | 0.8 | 5.13 | 1.3 | 3.09 | **0.9** | **4.35** |
| DrawingML_GraphicData_wps.docx | 14 | 1.2 | 11.81 | 2.3 | 6.15 | **1.5** | **9.40** |
| Headers.docx | 6 | 1.8 | 3.24 | 2.9 | 1.98 | **1.9** | **3.04** |
| Images.docx | 3 | 0.9 | 3.28 | 1.6 | 1.82 | **1.2** | **2.41** |
| Normal.dotm | 2 | 0.2 | 11.54 | 0.4 | 4.58 | **0.4** | **5.13** |
| **Symbols.docx** | **772** | **311.9** | **2.42** | **480.6** | **1.57** | **250.8** | **3.01** |
| invoice2013.docx | 25 | 6.2 | 3.94 | 8.5 | 2.86 | **4.7** | **5.14** |
| sample-docx.docx | 17 | 7.2 | 2.27 | 10.3 | 1.59 | **6.0** | **2.72** |
| tables.docx | 51 | 24.4 | 2.05 | 32.4 | 1.54 | **18.0** | **2.78** |
| toc.docx | 51 | 12.5 | 3.98 | 18.3 | 2.72 | **10.8** | **4.63** |
| w14_texteffects.docx | 6 | 1.4 | 4.07 | 2.1 | 2.64 | **1.6** | **3.46** |

14 documents, 964 KB of main parts: **marshal 565 ms to 301 ms**; parse 371 ms to 356 ms,
which is noise on a path nothing here touches.

### 9.2 Item 1: the namespace work, once per document instead of once per element

The largest single item, and the one with the largest single cause. `EventHandler.start_tag`
copied the whole prefix-URI map for every element, and `start_namespaces` then compared the
copy against the parent's entry by entry to decide what to declare. docx4j's prefix table is
**130 entries**, so on a 24,758-element part that is 24,758 dict copies and 3.2 M dict
lookups per marshal, for an answer that is "nothing new" every time. `add_namespace` on top
of that called `prefix_exists`, a linear scan of the map's *values*, once for the element
and once per attribute.

* An element's frame now holds the **same dict object** as its parent until something
  actually puts a prefix in it. `own_ns_map` makes the copy at that point and nowhere else;
  `ns_context` and the new parallel `uri_context` hold the shared objects.
* The map's URIs are indexed in a set (`ns_uris`), so `add_namespace` is a set lookup.
* `start_namespaces` returns on one flag (`ns_dirty`) unless this element added something.
  At the root, where the parent map is empty by definition, it declares the whole map
  exactly as before.
* The three things that can put a prefix in the map all mark the flag: `add_namespace`,
  `reset_default_namespace` (which also re-indexes, because it *replaces* a URI rather than
  adding one), and a **QName value**, which makes the converter generate a prefix inside
  `encode_data`. That last one is detected by the map's size before and after the call, so
  it is exact without the writer having to know which values carry qualified names.
* `write` copies the caller's map once, so a render owns the map it mutates. Upstream got
  that for free from the per-element copy.

**A departure from the letter of section 3.2**, which asked for the plan "per `XmlMeta` (or
per `XmlVar`) ... cached on the meta/context keyed by the map's identity". The writer only
ever sees qnames --- the meta is on the other side of the event stream --- and the
copy-on-write frame reaches the same end state ("`start_namespaces` becomes a check of one
flag per element and the running prefix map is touched only when an unseen namespace
appears") in the writer alone, with no cache to key and no invalidation to get wrong, and it
covers wildcard `AnyElement` content and `xsi:type` on the same terms as typed content.

### 9.3 Item 2: the fast path in `convert_value`

Every element value went `convert_value` to `convert_any_type` to `convert_xsi_type` to
`convert_dataclass`: three `isinstance` checks and an `xsi:type` decision, asked 378,244
times on that part for an answer that is `None` every time, because the value's class is the
field's declared class.

`XmlVar` gains `fast_element`, filled lazily beside the `namespace_matches` upstream already
caches there, by `EventGenerator.is_fast_element`: a single element var, not mixed, not
tokens, with a declared model class that is not a subclass of either generic wrapper
(`AnyElement`, `DerivedElement`). When it is set and the value's class **is** that class,
`convert_value` goes straight to `convert_dataclass`. The identity of the two is what makes
the decision safe: `EventGenerator.xsi_type` returns `None` exactly when
`value.__class__ in var.types`, and the builder takes `clazz` from `types`.

Subclass values, `object`-typed vars, wildcards, compound fields, tokens and mixed content
all keep upstream's path, and still get their `xsi:type`.

### 9.4 Item 3: the metadata iteration

`XmlMeta.get_element_vars` and `get_attribute_vars` chain a class's wildcards, choices,
elements, text and attributes together and `sorted` them by field index --- and the
serializer asks for both for every instance, 49,516 `sorted` calls and as many list builds
for that one part. Both are built on first use and kept on the meta (`element_vars`,
`attribute_vars`, two more lazy slots). Their only callers are the serializer's `next_value`
and `next_attribute`, which read them and never modify them; the docstrings say so.

`convert_dataclass` also stopped splitting a qname whose split it already has: `meta.namespace`
*is* `target_uri(meta.qname)`, so the common case --- a field whose name is not overridden ---
is two attribute reads rather than a cached `split_qname`.

### 9.5 Item 4: fewer frames, and the event that was not worth collapsing

Every event a nested element produces is yielded up through every generator frame between it
and `write`, and the frames between a parent and a child were four: a plain child went
`convert_dataclass`, `convert_value`, `convert_list`, `convert_value`, `convert_dataclass`;
a compound field's child had `convert_elements` and `convert_choice` in the middle as well.

`convert_dataclass` now takes the branch `convert_value` would have taken. For a plain
element field that is the new `convert_fast_element`, which is `convert_value` and
`convert_list` folded into the one case those two have for such a field; for a compound
field that is neither mixed nor tokens it is `convert_elements` directly. `convert_choice`
converts a value of the chosen field's own class itself. A child's events now cross one or
two frames. `write` indexes its event tuples instead of unpacking each one into a list
(`for name, *args in events` builds a list per event, and there are 79,960 of them).

**Tried and reverted, and it is the more interesting half of this item.** Section 3.2's
"`write` yields one tuple per element for the common case rather than start, attributes,
text and end as separate events" was implemented as a fifth event kind carrying the start
tag and an iterator over its attributes. It removes 27,087 of that part's 79,960 events ---
34% --- and measured **nothing**: 250 ms against 247, inside the noise. The attribute
iterator it has to carry costs what the events it saves cost. It also broke 30 of upstream's
serialiser tests, which assert the event tuples, so keeping it would have meant editing
upstream's tests for no gain. **The cost is the frames, not the events**, which is worth
knowing before Phase C is ever considered.

### 9.6 Where the 249 ms is, and what it says about Phase C

Stage by stage on `Symbols.docx`'s main part, median of five, as section 8.3:

| stage | ms | share |
|---|---:|---:|
| render to a tree (this fork's writer) | 232.3 | 92% |
| the `mc:Ignorable` walk (docx4j-python's `_ignorable_prefixes`) | 9.7 | 3.9% |
| `tostring` | 3.6 | 1.4% |
| `cleanup_namespaces` | 0.4 | 0.2% |

**The writer is 232 ms, 3.24 MiB/s.** Section 3.3 says Phase C, the generated per-class
writers, is "started only if Phase B leaves the writer above 3 MiB/s" --- it does, by 8% ---
so by the CR's own rule **Phase C is not started**. Section 7's recommendation 1 ("runtime
only first, measure, and start C only against a measured shortfall") holds, and 9.5's
finding argues the same way: what is left is the generator-frame machinery, and a generated
`__write__` per class would have to abandon the event stream altogether to beat it, at the
price of a generator change to carry through every rebase and an import-time budget to
defend.

The profile of one marshal of that part (0.93 s profiled for 0.25 s real, against 2.04 for
0.48 where Phase B started), by `tottime`:

| # | function | ncalls | tottime | cumtime |
|---:|---|---:|---:|---:|
| 1 | `mixins.py:603 convert_dataclass` | 458,205/79,961 | 0.131 | 0.568 |
| 2 | `mixins.py:522 start_element` (lxml's `startElementNS`) | 24,758 | 0.077 | 0.077 |
| 3 | `mixins.py:1109 next_value` | 48,946 | 0.052 | 0.081 |
| 4 | `mixins.py:1006 convert_choice` | 174,461/80,091 | 0.048 | 0.504 |
| 5 | `mixins.py:786 convert_fast_element` | 203,784/79,958 | 0.043 | 0.552 |
| 6 | `isinstance` | 250,580 | 0.040 | 0.057 |
| 7 | `mixins.py:987 convert_elements` | 170,534/79,933 | 0.037 | 0.520 |
| 8 | `mixins.py:1165 next_attribute` | 51,845 | 0.037 | 0.141 |
| 9 | `mixins.py:126 write` | 1 | 0.035 | 0.898 |
| 10 | `mixins.py:291 flush_start` | 52,873 | 0.034 | 0.138 |

`start_namespaces`, the largest function in section 8.4 at 0.391 tottime, is now 0.011 and
out of the table; the 3.2 M `dict.get` are gone entirely; `convert_any_type` and
`convert_xsi_type` no longer appear at all. What is left is **generator resumption**: items
1, 4, 5 and 7 are 1.0 M resumptions of five generators for 79,960 events, and `next_value`,
`next_attribute` and `flush_start` are the per-element bookkeeping under them. Nothing in it
is a mistake any more; it is the shape of the design.

### 9.7 What to do next

**Phase D, the parser.** Parse is now the slower half --- 295 ms against 249, 2.56 MiB/s
against 3.01 --- and it has had none of this attention: section 3.4's per-class binding
plans and `bind_content` fast path are the same two ideas that paid here, and 0.12 s of the
parse is docx4j-python's own `link_parents`, which the same walk could absorb. Section 7's
recommendation 4 wants both halves at 5 MiB/s; the marshal is within striking distance of it
and the parse is not.

### 9.8 Fidelity

* **Byte equality, part for part, after every item.** The 150 typed XML parts of the 16
  sample documents were frozen before the first change and compared after each: **identical,
  all four times**. docx4j-python's `tests/openpackaging/test_marshal_one_pass.py` passes
  too, but it compares the tree writer against the string writer and both go through this
  code, so the frozen bytes are the real gate here.
* **Oracles rather than expectations.** Each of the three new test modules carries the
  upstream v26.2 code it replaces and compares against it, so the tests say "unchanged"
  rather than "as I expected": `test_serializer_namespaces.py` has upstream's six namespace
  methods and compares the bytes over 14 documents x 4 prefix maps x 3 writers (and counts
  the map copies, to show the optimisation engaged); `test_serializer_fast_path.py` has
  upstream's `convert_value` and compares the event stream and the bytes over 17 documents;
  `test_serializer_events.py` records every content-handler call and compares it against
  upstream's `convert_dataclass`, `convert_value` and `convert_choice` over all 70 cases of
  the other two. Each oracle was checked by sabotage: reverting a part of the change fails
  the tests that cover it.
* The fork's suite: **1122 passed before, 1457 after** (`pytest tests -o addopts=""`, less the
  four modules that need `requests`, which is not installed). +335, all in `tests/fork/`. No
  upstream test edited or skipped.
* docx4j-python's suite: 1,553 passed, 2 skipped, 1 xfailed, after every item.
* `scripts/roundtrip.py --models-module docx4j_py.wml --runtime docx4j_xsdata`: 50/50 parts
  canonically identical, 0 differences, 0 skipped, 34 `boolean-spelling` respellings and no
  other category --- the gate of section 3, unchanged, after every item.
* `scripts/acceptance.py` regenerated. Against the eleven artefacts built from the commit
  before the change, **seven parts differ and every difference is a wall-clock date**
  (`docProps/core.xml`, the comment, revision and `pPrChange` dates); with dates scrubbed,
  zero parts differ. They **await a Word re-check**; docx4j-python's `tests/README.md` says
  so.

## 10. Phase D implementation notes (2026-09-19)

Section 3.4's three items, in its order, each measured before the next started and each
gated on docx4j-python's round trip staying canonically identical and its parent-pointer
check finding nothing. Six files changed, five in the fork ---
`formats/converter.py`, `formats/dataclass/models/elements.py`,
`formats/dataclass/parsers/utils.py`, `.../parsers/bases.py`,
`.../parsers/handlers/lxml.py`, `.../parsers/nodes/element.py` and
`.../parsers/config.py` --- and three in docx4j-python (`child.py`, `runtime.py`,
`openpackaging/parts/xml_part.py`), with three new test modules under `tests/fork/`.
No upstream test was edited, and no generated model, `el` table, `Child` or
`ChildList` public behaviour was touched.

### 10.1 The measurement, item by item

`Symbols.docx`'s main part, 772 KB and 24,758 elements, median of five,
`scripts/bench_marshal.py` as section 8.2. Run-to-run spread on this machine is about
3%, and the machine was slower on the day than it was for section 9: the **same code**
that measured 295 ms in section 9.7 measures 329 ms here, so every row below is from
this session and the comparison is like for like.

| after | commit | Symbols parse ms | MiB/s | the corpus, parse ms |
|---|---|---:|---:|---:|
| Phase B (where D starts) | `7b7d7f9` / `7afbd34` | 329 | 2.29 | 393 |
| item 1, the binding plans | `cc448de` | 222 | 3.39 | 268 |
| item 2, the `child` fast path | `b9be85f` | 189 | 3.98 | 229 |
| item 3, the post-bind hook | `c394b93` / `25f1f29` | 193 | 3.90 | 238 |

**`Symbols.docx`: 329 ms to 193 ms, 2.29 to 3.90 MiB/s, 41% off, 1.70x.** Section 3.4
expected "2x, to about 5 MiB/s"; the measured 1.70x and 3.90 MiB/s is short of it, and
section 10.6 says what the rest would cost. Marshal is untouched, as it should be (250
ms, 3.02 MiB/s over three runs of the benchmark after the change).

The whole corpus, before Phase D and after. The parse timed here is what
`XmlPart._unmarshal` does, so after item 3 it is the parser **with** the parent wiring
inside it rather than the parser plus a `link_parents` walk:

| document | KB | parse ms | MiB/s | after: parse ms | MiB/s | marshal ms |
|---|---:|---:|---:|---:|---:|---:|
| 2010-glow-then-AlternateContent.docx | 9 | 1.1 | 7.89 | **0.8** | **10.24** | 1.2 |
| 2010-mcAlternateContent-in-header.docx | 1 | 0.2 | 5.13 | **0.1** | **7.29** | 0.4 |
| 2010-sample1.docx | 4 | 1.4 | 2.62 | **0.9** | **3.96** | 1.5 |
| 2016_image_with_text_effects.docx | 4 | 1.0 | 3.68 | **0.6** | **6.95** | 0.9 |
| DrawingML_GraphicData_wps.docx | 14 | 1.3 | 11.12 | **1.0** | **13.42** | 1.5 |
| Headers.docx | 6 | 1.9 | 3.00 | **1.3** | **4.53** | 1.8 |
| Images.docx | 3 | 0.9 | 3.12 | **0.6** | **4.86** | 1.0 |
| Normal.dotm | 2 | 0.2 | 11.14 | **0.1** | **14.76** | 0.4 |
| **Symbols.docx** | **772** | **329.1** | **2.29** | **193.4** | **3.90** | **258.3** |
| invoice2013.docx | 25 | 6.3 | 3.84 | **4.8** | **5.02** | 5.3 |
| sample-docx.docx | 17 | 7.4 | 2.21 | **5.5** | **2.96** | 6.4 |
| tables.docx | 51 | 26.0 | 1.92 | **18.3** | **2.73** | 18.1 |
| toc.docx | 51 | 14.1 | 3.53 | **9.2** | **5.39** | 10.7 |
| w14_texteffects.docx | 6 | 1.7 | 3.24 | **1.0** | **5.92** | 1.5 |

14 documents, 964 KB of main parts: **parse 393 ms to 238 ms**; marshal 304 ms to 309 ms,
which is the 3% noise on a path nothing here touches.

### 10.2 Item 1: the binding plans, and three smaller things beside them

Three answers upstream rebuilds for every element of every document, and all three are
properties of the class.

* **The child-element lookup.** `XmlMeta.find_children` is a generator that scans the
  elements mapping, then calls `find_choice` on every compound choice, then
  `find_wildcard`; `ElementNode.child` and `ElementNode.bind_object` each ask for it per
  child, which is **99,068 calls** for one 24,758-element part. `get_children(qname)`
  builds the tuple once and keeps it in the new `children_index`; `find_children` is
  `iter()` over it, so upstream's `next(meta.find_children(q), None)` callers are
  unchanged. Caching per qname is exact because the wildcard half already caches its
  namespace decision per qname (`XmlVar.match_namespace`).
* **The attribute converters.** `ParserUtils.parse_var` reached its converter through
  `parse_value`, `converter.deserialize`, `type_converter` and a `suppress` context
  manager, **30,444 times** for that part, and `contextlib` alone was 61,088 calls of
  `__init__`/`__enter__`/`__exit__`. For the common case --- a present value, a var with
  one declared type, no tokens factory and no override --- the converter is resolved
  once and kept on the var as `converter_plan`, and `parse_var` becomes one call.
  `ConverterFactory` gained a **`generation` counter**, bumped by `register_converter`
  and `unregister_converter`, which the plan carries so a converter registered later
  invalidates it. Multiple types, tokens, the `types`/`tokens_factory`/`format`
  overrides and **every failure** take upstream's path, which is what builds the message
  and warns; the fast path catches `ConverterError` and falls through, so a bad value is
  reported exactly once and exactly as before.
* **The node classes.** `NodeParser.start` did `from ...parsers.nodes import ElementNode,
  SkipNode, WrapperNode` on every element, to break the import cycle between `bases` and
  the nodes package: 24,758 `_handle_fromlist` calls. `load_nodes()` breaks it once, on
  the first element, and the three names live in module globals. A module-level import
  is not available --- it is a real cycle (`parsers/__init__` imports `tree`, which
  imports `bases`; `nodes/union` imports `bases`).
* **The event loop.** `LxmlEventHandler.process_context` looked `self.parser.start`,
  `self.parser.end`, `self.parser.register_namespace`, `self.clazz`, `self.queue`,
  `self.objects` and the three `EventType` names up on every event; none of them can
  change during a parse, so they are local variables now.

**329 ms to 222 ms** (`cc448de`).

### 10.3 Item 2: the fast path for a plain dataclass child

`ElementNode.child` walked the vars a qname might match; `build_node` then asked whether
the var is a union, what `xsi:type` says, what `xsi:nil` says, and whether a datatype or
a wildcard class should take it; `build_element_node` fetched the meta, recomputed
`nillable`, and decided whether the object has to be wrapped as a derived element. For a
child whose qname matches **exactly one** var, whose var declares a single dataclass that
is neither a union nor a wildcard, and whose element carries neither `xsi:type` nor
`xsi:nil`, none of that has anything left to decide: the answer is a constant of the
class and the qname.

`build_child_plan` works it out once and keeps it in the meta's `child_plans`, beside
`children_index`; `child` then constructs the `ElementNode` itself, with upstream's
`assigned` bookkeeping (including its quirk that a var at field index 0 is never marked)
reproduced exactly. **That is every element of a WordprocessingML part: 24,757 of
24,757 on `Symbols.docx`.** `xsi:type`, substitution to another class, wildcards,
unions, primitives, mixed content and `xsi:nil` all keep upstream's path.

Two smaller things in `bind_content` came with it, because they are the same shape:

* the mixed-content and wild-text branches are skipped entirely when the class has no
  wildcard at all, and `bind_text` when it has no text var --- for most classes that is
  two frames per element that were only ever going to return immediately;
* the `PendingCollection` scan over the class parameters was an `isinstance` against a
  `UserList`, which is an **abc**, per parameter per element: 72,271 `__instancecheck__`
  calls for that part. `XmlMeta.has_list_vars` is computed once at build time --- no
  element var of the class is a list, so the parser cannot have left a pending
  collection --- and skips the scan. It is exact rather than a heuristic: all three
  places that build a `PendingCollection` do so only for a `list_element` var of this
  meta.

**222 ms to 189 ms** (`b9be85f`).

### 10.4 Item 3: the post-bind hook, and what it really cost

`ParserConfig(on_bind: Callable[[Any], None] | None = None)`, called by
`ElementNode.bind` immediately after `class_factory` builds the object. xsdata binds
bottom up, so at that moment the object's own children exist and are bound and its
parent does not exist yet --- exactly the moment a binding layer that wires something per
object wants. It is off by default, it is not called when `xsi:nil` means no object was
built, and it is per config, so a parse owns its hook the way it owns its skipped report.
This is the one piece of Phase D that is a **feature** rather than a speed-up, and it is
upstreamable on its own.

docx4j-python fills it in with the new `child.link_children(obj)`: one level of what
`link_parents` does, from the same `_child_plan` enumeration and by the same rules ---
every `Child` in a single-valued field or a list field gets `obj` as its parent, every
`ChildList` is bound to `obj` as its owner, and a typed object nested inside an
`AnyElement` wildcard keeps the parent it has, exactly as `link_parents` leaves it.
`runtime.parser_config` passes it as `functools.partial(link_children, context=...)`,
and `XmlPart._unmarshal` skips the second walk when the config carries a hook.
`link_parents` is unchanged and stays: hand-built trees, `deep_copy`, `set_contents` and
the markdown importer all need it.

**And it measures, on `Symbols.docx`, a wash: 189 ms to 193 ms, inside the noise.** Over
the 50 typed parts of the corpus, where `scripts/parents.py` now parses each part both
ways in one process, it is 293 ms against 268 ms, about 8%. The reason is worth
recording, because section 2 of this CR got it wrong:

* **Section 2's "0.12 s of the parse is `link_parents`" was a profiled cumulative time,
  not a real one.** Measured directly, `link_parents` over that part is **20.5 ms of a
  295 ms parse, 7%**, and `scripts/parents.py` has been reporting 9 to 11% of parse over
  the corpus all along. There was never 0.12 s to win.
* Of that 20 ms, almost all is the work itself --- a `getattr` for every element var of
  every object, 235,598 of them --- and that work has to happen whichever walk does it.
  What the hook removes is only the walk's own bookkeeping (the stack, the `id()`, the
  `seen` set of 24,758 ints), and it adds 24,758 callback invocations, which costs about
  the same.

It is kept regardless, on three grounds that are not the clock: it is an upstreamable
feature in its own right; it removes a second full traversal of the tree, which is
memory traffic and a `seen` set proportional to the document; and it puts the parent
pointer where docx4j puts it, at construction, so no window exists in which a parsed
tree has no parents.

**189 ms to 193 ms** (`c394b93` in the fork, `25f1f29` in docx4j-python).

### 10.5 Where the 193 ms is

`cProfile` of one parse of that part (0.54 s profiled for 0.19 s real, against 0.91 for
0.30 where Phase D started), by `tottime`:

| # | function | ncalls | tottime | cumtime |
|---:|---|---:|---:|---:|
| 1 | `handlers/lxml.py:44 process_context` | 1 | 0.089 | 0.547 |
| 2 | `nodes/element.py:82 bind` | 24,758 | 0.041 | 0.316 |
| 3 | `docx4j_py/child.py:678 link_children` | 24,758 | 0.039 | 0.069 |
| 4 | `parsers/bases.py:90 start` | 24,758 | 0.035 | 0.114 |
| 5 | `nodes/element.py:457 child` | 24,757 | 0.033 | 0.042 |
| 6 | `isinstance` | 169,087 | 0.025 | 0.038 |
| 7 | `nodes/element.py:169 bind_attrs` | 24,758 | 0.024 | 0.073 |
| 8 | `getattr` | 232,241 | 0.023 | 0.023 |
| 9 | `parsers/config.py:9 default_class_factory` | 24,758 | 0.019 | 0.053 |
| 10 | `parsers/bases.py:163 end` | 24,758 | 0.017 | 0.345 |
| 11 | `parsers/utils.py:84 parse_var` | 30,444 | 0.016 | 0.029 |
| 12 | `docx4j_py/child.py:229 __post_init__` | 24,758 | 0.014 | 0.025 |
| 13 | `nodes/element.py:130 bind_content` | 24,758 | 0.014 | 0.074 |
| 14 | `nodes/element.py:257 bind_object` | 24,757 | 0.012 | 0.036 |

`find_children`, `build_node`, `build_element_node`, `converter.deserialize`,
`type_converter`, `contextlib`'s three methods, `abc.__instancecheck__` and
`_handle_fromlist` --- eight of the fourteen entries of the profile Phase D started from
--- are **gone from the table entirely**; `getattr` and `isinstance` are down from
235,598 and 320,117 to 232,241 and 169,087. What is left is one Python frame per element
per layer: the event loop, `start`, `child`, `end`, `bind` and its three helpers, the
class factory, and docx4j-python's two (`link_children` and `__post_init__`, together 12%
of the parse and the price of the parent pointers). Nothing in it is a mistake; like the
writer after Phase B, it is the shape of the design.

### 10.6 Where the CR stands, and what is left

Section 7's recommendation 4 wants **both halves at or above 5 MiB/s on `Symbols.docx`**.
After four phases, measured in one session on one machine:

| | section 1 | now | |
|---|---:|---:|---|
| parse | 294 ms, 2.6 MiB/s | **193 ms, 3.90 MiB/s** | 1.5x |
| marshal | 820 ms, 0.9 MiB/s | **250 ms, 3.02 MiB/s** | 3.3x |

Neither half reaches 5 MiB/s; both are within 40% of it, and the one number section 1
said limits docx4j-python --- the 820 ms marshal, which made the first edit of a typical
document cost forty times python-docx --- is a third of what it was. A 5 MB main part is
now about a second to parse and 1.3 s to write, where CR-001 opened at 1.9 s and 5.6 s.

What it would take to close the remaining 25 to 40%, and why none of it is recommended
now:

1. **Fewer frames per element on the read side**, the twin of item 4 of Phase B: merge
   `NodeParser.start` with `ElementNode.child`, and `ElementNode.bind` with `bind_attrs`
   and `bind_content`. Worth perhaps 15%, at the price of a diff that no longer reads as
   upstream's file with changes in it, which every phase so far has been careful to
   remain. Offer the pieces upstream first; if they land, this stops being a fork
   question.
2. **Generated per-class binders**, the read-side Phase C. Section 3.3's rule ("only if
   the runtime work leaves it under 3 MiB/s") is not met on either side now, and section
   7's recommendation 1 --- runtime only, and a generator change is the most expensive
   kind to carry through rebases --- holds on the read side for the same reasons it held
   on the write side.
3. **Not Python.** The profile is now one Python frame per element per layer with almost
   no waste in any of them, and 24,758 elements is 24,758 x 8 frames. The honest next
   step for 5 MiB/s is not a better arrangement of those frames; it is lxml doing more of
   the work (a C-level binder), or not building typed objects at all for the parts that
   do not need them --- which is exactly what docx4j-python's CR-005 already decided for
   SpreadsheetML sheet data.

**Recommendation: close CR-001.** Phases A, B and D are done, Phase C is not started by
the CR's own rule, and the remaining gap to recommendation 4's 5 MiB/s is better spent on
docx4j-python's CR-005 assumption than on a fifth phase here. The four upstream offers
(reports 9 to 12 in docx4j-python's `docs/UPSTREAM.md`, plus the two Phase D adds) are
the durable output.

### 10.7 Fidelity

* **The gate after every item**, in docx4j-python: the whole suite (**1,560 passed**, 2
  skipped, 1 xfailed --- 1,553 before, plus seven new `link_children` and hook tests);
  `scripts/roundtrip.py --models-module docx4j_py.wml --runtime docx4j_xsdata`, **50/50
  parts canonically identical, 0 differences, 0 skipped, 34 `boolean-spelling`
  respellings and no other category**; `scripts/parents.py`, **0 parent problems over 50
  parts and 34,147 nodes**, now checking the hooked tree as well as the walked one;
  `scripts/threads.py`; and `tests/openpackaging/test_marshal_one_pass.py`, which a
  mis-bound parse would show.
* **Oracles rather than expectations**, as Phase B's tests did. The three new modules
  carry the upstream v26.2 code they replace: `test_parser_binding_plan.py` has
  upstream's `find_children`, `parse_var` and `process_context` and compares over nine
  qnames x three classes, thirteen attribute values and five documents;
  `test_parser_fast_path.py` has upstream's `ElementNode.child` and compares the parsed
  object over twelve documents, then pins which qnames get a plan and which children
  still reach `build_node`; `test_parser_on_bind.py` pins the hook's contract. Each
  oracle was checked by sabotage: removing the `xsi:type` guard fails four tests,
  allowing a wildcard qname to plan fails two, dropping the converter generation fails
  one, and dropping the wildcard from `get_children` fails ten.
* The fork's suite: **1457 passed before, 1554 after**
  (`pytest tests -o addopts=""`, less the four modules that need `requests`). +97, all in
  `tests/fork/`. No upstream test edited or skipped.
* `scripts/acceptance.py` regenerated. Against the eleven artefacts built from the two
  commits before the change (`7afbd34` in docx4j-python, `7b7d7f9` in the fork), **143
  parts compared, seven differ, and every difference is a wall-clock date**
  (`docProps/core.xml` in three, `word/comments.xml` in two, `word/document.xml` in two);
  with the dates scrubbed, zero parts differ. Parsing is not marshalling, and the user's
  decision of 2026-09-19 stands: a dates-only difference needs **no Word re-check**.
  docx4j-python's `tests/README.md` records it.
