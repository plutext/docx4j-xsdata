# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

docx4j-xsdata is docx4j-python's fork of [tefra/xsdata](https://github.com/tefra/xsdata) (MIT):
the same library, published as the distribution `docx4j-xsdata` with the import package
`docx4j_xsdata` and the console script `docx4j-xsdata`, so that it installs beside upstream
`xsdata`. It exists for one consumer, **docx4j-python** (sibling checkout `../docx4j-python`):
its generator options produce `docx4j_py/`, the OOXML object model, and that generated code
imports its runtime from `docx4j_xsdata`. The aim is a small, rebasable delta on an upstream
tag, with each generic fix offered upstream later.

- `docs/fork/CHANGES.md` is the authoritative list of every difference from upstream, by stage and
  numbered item. Read the stage that covers the code before changing it.
- `docs/fork/REBASING.md` covers moving to a new upstream tag, the branches and remotes,
  publishing and releasing.
- `docs/fork/CR-001-serialiser.md` is the fork's own change request, the parser and serialiser
  throughput work (phases B and D here, A in docx4j-python).
- The root `CHANGES.md` is upstream's changelog and is never edited. Everything in `README.md`
  below its first rule is upstream's.

**Status, 2026-10-24:**
- The base is upstream `v26.2`.
- **26.2.3** (tag `docx4j-v26.2.3`, stages 1 to 13, items 1 to 31) is on PyPI, published
  2026-10-24. Before it, **26.2.2** (stages 1 to 12) and **26.2.1** (stages 1 to 8).
- `docx4j` is pushed up to the 26.2.3 commit. docx4j-python's CR-018 Phase A uses stage 13, so its
  next step is raising its lower bound to `docx4j-xsdata[lxml]>=26.2.3,<26.3`.
- The next fork release is **26.2.4**, or **26.3.1** after a rebase.

## Branches, remotes and the rename

- **`docx4j`** is the fork: the working branch and GitHub's default.
- **`main`** is an exact mirror of `upstream/main`. Never commit to it or merge `docx4j` into it.
- **Remotes:** `upstream` is tefra/xsdata, and `tools/rebase-upstream.sh` fetches by that name.
  `origin` is plutext/docx4j-xsdata.
- **The branch's shape:** upstream tag, then a tooling commit (`tools/`, `docs/fork/`), then the
  rename commit, then the feature commits.
- **The rename commit is 100% the output of `tools/rename.py`** and is never hand-edited. It is
  regenerated on each new upstream tag, not rebased. To change what the rename does, change the
  script, and check the self-test in `REBASING.md` gives an empty diff.
- **Feature commits** are ordinary edits to the renamed tree (`docx4j_xsdata/...`), replayed
  onto each new base. This file is one of them: a root file upstream does not have, so it never
  conflicts.
- **Commit hashes are not stable.** Every rebase rewrites `docx4j`, so anything that depends on the
  fork pins a tag, never a commit or the branch.

## Environment and commands

- `.venv` (CPython 3.14) has this checkout installed editable (`uv pip install -e
  '.[cli,lxml,soap,test]'`).
- **docx4j-python's `.venv-fork` has it installed editable too.** An edit here is live in
  docx4j-python at once. Don't leave the working tree half-changed while work runs there.

```bash
PATH=$PWD/.venv/bin:$PATH .venv/bin/python -m pytest tests -o addopts=""        # the suite, as CHANGES.md records it
PATH=$PWD/.venv/bin:$PATH .venv/bin/python -m pytest tests/fork -o addopts=""   # the fork's own tests only
PATH=$PWD/.venv/bin:$PATH .venv/bin/python -m pytest tests/fork/test_lexical_types.py -o addopts=""
pytest --doctest-glob="docs/*.md"                                               # CI's command (tests.yml), in an activated venv
python -m build && twine check --strict dist/*                                  # a release's build check
tools/rebase-upstream.sh v26.3 [--no-rebase] [--branch NAME]                    # onto a new upstream tag (REBASING.md)
```

- **`PATH` must hold `.venv/bin`.** The generator's tests shell out to `docx4j-xsdata` and `ruff`
  by bare name. Without it, 47 of them fail with `FileNotFoundError` and look like real failures.
- **`-o addopts=""`** drops upstream's `--color=yes --benchmark-skip`.
- **The last count:** after stage 13, the suite is 1,713 passed and 1 skipped. Each stage's
  "Test status" table in `CHANGES.md` has the current count; a change that moves it records the
  new one.
- **CI** (`.github/workflows/tests.yml`) runs on `docx4j` pushes and pull requests: CPython 3.10
  to 3.14, plus a minimum-install check. `publish.yml` is the PyPI release (below).

## How a change is made here

**Only when docx4j-python needs it.** Make a generator or runtime change only when one of
docx4j-python's change requests needs it and a fix there would be a workaround. Name that CR in
the commit and in `CHANGES.md`. The fork's job is to stay small.

1. **Defaults stay upstream's.**
   - A new behaviour is an option, off by default: a generator config element
     (`docx4j_xsdata/models/config.py`) or a `ParserConfig` / `SerializerConfig` field.
   - With every option at its default, the fork behaves as upstream does. A test pins the
     default as well as the option.
2. **Mark fork code.** Put `docx4j fork:` in a comment or docstring at each changed place, so a
   rebase conflict says whose line it is. There are about a hundred such markers.
3. **One item per commit.**
   - Items are numbered across the fork; the last is 31, so the next is **32**.
   - Items are grouped into stages; the last is 13, so the next is **14**. A stage is usually
     what one docx4j-python CR or phase asked for.
   - Subject style: `Area: what it does (stage N, item M)`, for example `Parser and serialiser:
     float and bytes values that keep the spelling they were read with (stage 12, item 28)`.
4. **Tests** go in `tests/fork/`, one file per item, named for it. Say how many of them fail
   without the item.
5. **`CHANGES.md`.** Each new stage gets a section, `## Stage N — what (done)`, holding:
   - one `### M.` per item: the files, the option, why, and the tests;
   - a "Verified against the real project" section: what docx4j-python ran with it;
   - a "Test status" table: the suite before and after, and the exact command.
6. **Verify in docx4j-python** before calling a change done. Its `CLAUDE.md` has the commands:
   - its whole suite;
   - `codegen/generate.sh --check` (byte identical), and a regeneration for a generator change;
   - `scripts/roundtrip.py`;
   - for a parser or serialiser hot path, the cost (`scripts/bench_marshal.py`, `Symbols.docx`
     parse and marshal). Off must be free, and the fast path must pay at most a check.
7. **Upstream reports.** The live list is docx4j-python's `docs/UPSTREAM.md`; `CHANGES.md`'s
   "Deferred upstream reports" is an early copy. Each item upstream could take gets a numbered
   row there: the bug or feature, how to reproduce it, and this item as the patch to offer.
   Upstream reporting is deferred: fix here first, offer later.

Style is upstream's: ruff as configured in `pyproject.toml`, Google-style docstrings, type hints.
`LICENSE` stays upstream's MIT; the fork's modifications are copyright Plutext Pty Ltd, under the
same licence (the README says so).

## Releasing: the user's

**Never push, tag, publish, create a GitHub release, or run `publish.yml`'s TestPyPI dispatch.**
Those are the user's. Commits are fine, on `docx4j` only.

- **The procedure** is `REBASING.md` "Releasing". Prepare its step 1 only when asked: bump
  `__version__` in `docx4j_xsdata/__init__.py`, which the publish workflow checks against the tag,
  add a `CHANGES.md` section, make sure the suite is green, check the built wheel with
  docx4j-python, and commit.
- **Version scheme:** tag `docx4j-v<upstream tag>.<fork release>` and `__version__` the same
  without the prefix (`26.2.1`, then `26.2.2`). The fork release counts from 1 on each upstream
  tag. **A version once published is never reused,** on PyPI or TestPyPI, even after a deletion.
- **Order with docx4j-python:**
  1. the fork release is published;
  2. docx4j-python raises its lower bound (`docx4j-xsdata[lxml]>=26.2.x,<26.3`);
  3. docx4j-python is released.
  
  docx4j-python is never released against an unreleased fork. Its CI installs the fork from
  PyPI, so a docx4j-python `main` that needs unreleased stages fails CI until the release is
  out.

## The portfolio registry

The fork's change requests are indexed in `../docx4j-portfolio/tasks.yaml` under the key
`xsdata` (ids such as `xsdata/CR-001.A`). A fork stage made for a docx4j-python CR is recorded in
that CR's entry (`python/...`), with the fork release it needs.

**Don't edit `tasks.yaml`, `scripts/status-snapshots.yaml` or `docs/dependencies.md` directly.**
Send the change to the docx4j-portfolio session: the one working in `~/git/docx4j-portfolio`,
found by that directory in `ListAgents`, not by its name. docx4j-python's `CLAUDE.md` has the
full rule.
