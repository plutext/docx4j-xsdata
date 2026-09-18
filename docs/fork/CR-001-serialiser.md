# CR-001: The serialiser, and the parser after it

**Status:** Proposed 2026-09-19. Nothing implemented.
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
