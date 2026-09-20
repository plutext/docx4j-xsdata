#!/usr/bin/env python3
"""Rename an upstream xsdata checkout into the docx4j-xsdata fork.

This script is the *only* source of the rename commit on the ``docx4j`` branch.
Nothing in the rename is hand-edited, so that rebasing onto a new upstream tag is
a matter of re-running this script on a fresh checkout of that tag
(see ``tools/rebase-upstream.sh`` and ``docs/fork/REBASING.md``).

What it does
------------
* moves the import package ``xsdata/`` to ``docx4j_xsdata/``
* rewrites module references (``import xsdata``, ``from xsdata...``, dotted
  ``xsdata.a.b`` paths in code, strings, ``mock.patch`` targets, mkdocstrings
  references and the code the generator emits into generated bindings)
* renames the distribution to ``docx4j-xsdata``, the console script to
  ``docx4j-xsdata`` and the plugin entry-point groups to
  ``docx4j_xsdata.plugins.cli`` / ``docx4j_xsdata.plugins.class_types``
* replaces upstream CI with a minimal test-only workflow and drops the PyPI
  publish workflow
* prepends a fork notice to README.md

What it deliberately does NOT do is listed in ``KEEP`` below and repeated in
``docs/fork/CHANGES.md``.

Usage::

    python3 tools/rename.py [REPO_ROOT]

Stdlib only.  Idempotent-safe: run against an already renamed tree it prints
"already renamed" and exits 0 without touching anything.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

OLD_PKG = "xsdata"
NEW_PKG = "docx4j_xsdata"
NEW_DIST = "docx4j-xsdata"
FORK_ORG = "plutext"
FORK_REPO = f"https://github.com/{FORK_ORG}/{NEW_DIST}"
UPSTREAM_REPO = "https://github.com/tefra/xsdata"

# ---------------------------------------------------------------------------
# What is deliberately left alone, and why.  Keep in sync with docs/fork/CHANGES.md.
# ---------------------------------------------------------------------------
KEEP = [
    (
        "http://pypi.org/project/xsdata",
        "the generator config XML namespace: existing .xsdata.xml files must keep "
        "validating against the fork",
    ),
    (
        ".xsdata.xml",
        "the default config file name, for the same reason",
    ),
    (
        '"xsdata" as a bare string',
        "hundreds of tests and fixtures use it as an arbitrary XML namespace URI / "
        "target namespace; it has nothing to do with the package name",
    ),
    (
        "URLs containing xsdata",
        "links to upstream's repository, docs, PyPI page and W3C test suite still "
        "point at upstream, which is where that material lives",
    ),
    (
        "CHANGES.md",
        "upstream's changelog is a historical record; the fork's log is "
        "docs/fork/CHANGES.md",
    ),
    (
        "prose in docs/",
        "sentences like 'xsdata is using python's dataclasses' describe the same "
        "software; renaming prose is churn that buys nothing",
    ),
    (
        "docs/logo.svg, docs/logo-small.svg, docs/robots.txt",
        "upstream branding and the readthedocs sitemap",
    ),
]

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    "site",
    "build",
    "dist",
    ".eggs",
}
# Fork-owned paths: already written in the new naming, never rewritten.
SKIP_RELPATHS = {
    "tools",
    "docs/fork",
    "CHANGES.md",
    "docs/logo.svg",
    "docs/logo-small.svg",
    "docs/robots.txt",
    ".github/pull_request_template.md",
}

# ---------------------------------------------------------------------------
# Explicit, per-file replacements.  Applied *before* the generic rules, written
# against the upstream text and producing the final text (the generic rules are
# no-ops on their output).  required=True means the script fails if upstream has
# changed the text out from under us -- that is the point: loud, not silent.
# ---------------------------------------------------------------------------
Rule = tuple[str, str, str, bool]  # path, old, new, required

EXPLICIT: list[Rule] = [
    # -- packaging -----------------------------------------------------------
    ("pyproject.toml", 'include = ["xsdata*"]', f'include = ["{NEW_PKG}*"]', True),
    ("pyproject.toml", 'name = "xsdata"', f'name = "{NEW_DIST}"', True),
    (
        "pyproject.toml",
        'description = "Python XML Binding"',
        'description = "Python XML Binding - the docx4j-python fork of xsdata"',
        True,
    ),
    (
        "pyproject.toml",
        '[project.urls]\n'
        'Homepage = "https://github.com/tefra/xsdata"\n'
        'Source = "https://github.com/tefra/xsdata"\n'
        'Documentation = "https://xsdata.readthedocs.io/"\n'
        'Changelog = "https://xsdata.readthedocs.io/en/latest/changelog/"',
        "[project.urls]\n"
        f'Homepage = "{FORK_REPO}"\n'
        f'Source = "{FORK_REPO}"\n'
        f'Upstream = "{UPSTREAM_REPO}"\n'
        'Documentation = "https://xsdata.readthedocs.io/"\n'
        f'Changelog = "{FORK_REPO}/blob/docx4j/docs/fork/CHANGES.md"',
        True,
    ),
    (
        "pyproject.toml",
        '[project.scripts]\nxsdata = "xsdata.__main__:main"',
        f'[project.scripts]\n{NEW_DIST} = "{NEW_PKG}.__main__:main"',
        True,
    ),
    (
        "pyproject.toml",
        '    "xsdata/__main__.py",\n    "xsdata/utils/debug.py",',
        f'    "{NEW_PKG}/__main__.py",\n    "{NEW_PKG}/utils/debug.py",',
        True,
    ),
    (
        "pyproject.toml",
        'exclude = ["tests/fixtures"]',
        'exclude = ["tests/fixtures", "tools"]',
        True,
    ),
    ("MANIFEST.in", "recursive-include xsdata *", f"recursive-include {NEW_PKG} *", True),
    (".pre-commit-config.yaml", "files: ^(xsdata/)", f"files: ^({NEW_PKG}/)", True),
    # -- docs build ----------------------------------------------------------
    ("mkdocs.yml", 'site_name: "xsdata"', f'site_name: "{NEW_DIST}"', True),
    ("mkdocs.yml", "repo_name: tefra/xsdata", f"repo_name: {FORK_ORG}/{NEW_DIST}", True),
    ("mkdocs.yml", "repo_url: https://github.com/tefra/xsdata", f"repo_url: {FORK_REPO}", True),
    ("mkdocs.yml", "watch:\n  - xsdata", f"watch:\n  - {NEW_PKG}", True),
    (
        "docs/scripts/generate_api.py",
        'Path(__file__).parent.parent.parent / "xsdata"',
        f'Path(__file__).parent.parent.parent / "{NEW_PKG}"',
        True,
    ),
    (
        "docs/scripts/generate_api.py",
        'print("::: xsdata." + identifier, file=fd)',
        f'print("::: {NEW_PKG}." + identifier, file=fd)',
        True,
    ),
    # -- user-visible strings that name the tool -----------------------------
    (
        "xsdata/cli.py",
        '"========= xsdata v%s / Python %s / Platform %s =========\\n"',
        f'"========= {NEW_DIST} v%s / Python %s / Platform %s =========\\n"',
        True,
    ),
    (
        "tests/test_cli.py",
        '"========= xsdata v%s / Python %s / Platform %s =========\\n"',
        f'"========= {NEW_DIST} v%s / Python %s / Platform %s =========\\n"',
        True,
    ),
    (
        "docs/codegen/download_schemas.md",
        "========= xsdata v24.6.1 / Python 3.11.8 / Platform linux =========",
        f"========= {NEW_DIST} v24.6.1 / Python 3.11.8 / Platform linux =========",
        True,
    ),
    # -- the header the generator writes into every generated module ---------
    (
        "xsdata/formats/mixins.py",
        'f\'"""This file was generated by xsdata, v{__version__}, on {now}\'',
        f'f\'"""This file was generated by {NEW_DIST}, v{{__version__}}, on {{now}}\'',
        True,
    ),
    (
        "tests/formats/test_mixins.py",
        "f'\"\"\"This file was generated by xsdata, v{__version__}, on {now_iso_format}\\n'",
        f"f'\"\"\"This file was generated by {NEW_DIST}, v{{__version__}}, on "
        f"{{now_iso_format}}\\n'",
        True,
    ),
    (
        "docs/codegen/config.md",
        '"""This file was generated by xsdata, v24.1, on 2024-01-22 10:20:25',
        f'"""This file was generated by {NEW_DIST}, v24.1, on 2024-01-22 10:20:25',
        True,
    ),
    (
        "xsdata/__main__.py",
        'print(\'Install cli requirements "pip install xsdata[cli]"\')',
        f'print(\'Install cli requirements "pip install {NEW_DIST}[cli]"\')',
        True,
    ),
    # -- names that would collide with an upstream xsdata in the same env ----
    (
        "xsdata/codegen/__init__.py",
        'opener.addheaders = [("User-agent", f"xsdata/{__version__}")]',
        f'opener.addheaders = [("User-agent", f"{NEW_DIST}/{{__version__}}")]',
        True,
    ),
    (
        "xsdata/codegen/transformer.py",
        'f"xsdata.{__version__}.{key}.cache"',
        f'f"{NEW_DIST}.{{__version__}}.{{key}}.cache"',
        True,
    ),
    (
        "tests/codegen/test_transformer.py",
        'f"xsdata.{__version__}.ae1bed744d3d3611e698a2d2ef5335d2.cache"',
        f'f"{NEW_DIST}.{{__version__}}.ae1bed744d3d3611e698a2d2ef5335d2.cache"',
        True,
    ),
    (
        "tests/__init__.py",
        'Path(tempfile.gettempdir()).joinpath("xsdata")',
        f'Path(tempfile.gettempdir()).joinpath("{NEW_DIST}")',
        True,
    ),
    (
        "xsdata/utils/debug.py",
        'Path.cwd().joinpath("xsdata_dump.json")',
        f'Path.cwd().joinpath("{NEW_PKG}_dump.json")',
        True,
    ),
    # -- import ordering of generated / PycodeSerializer output --------------
    # The serializer sorts its imports; "docx4j_xsdata" sorts before "tests"
    # where "xsdata" sorted after it, so the expected output moves.
    (
        "tests/formats/dataclass/serializers/test_code.py",
        '            "from tests.fixtures.books.books import BookForm\\n"\n'
        '            "from tests.fixtures.books.books import Books\\n"\n'
        '            "from xsdata.models.datatype import XmlDate\\n"',
        f'            "from {NEW_PKG}.models.datatype import XmlDate\\n"\n'
        '            "from tests.fixtures.books.books import BookForm\\n"\n'
        '            "from tests.fixtures.books.books import Books\\n"',
        True,
    ),
    (
        "docs/data_binding/pycode_serializing.md",
        "from tests.fixtures.books.books import BookForm\n"
        "from tests.fixtures.books.books import Books\n"
        "from xsdata.models.datatype import XmlDate\n",
        f"from {NEW_PKG}.models.datatype import XmlDate\n"
        "from tests.fixtures.books.books import BookForm\n"
        "from tests.fixtures.books.books import Books\n",
        True,
    ),
    # The same reordering in the two committed fixtures that the test suite
    # regenerates with the PycodeSerializer; without this the tree is dirty
    # after every test run.
    (
        "tests/fixtures/books/fixtures.py",
        "from tests.fixtures.books import BookForm, Books\n"
        "from xsdata.models.datatype import XmlDate\n",
        f"from {NEW_PKG}.models.datatype import XmlDate\n"
        "from tests.fixtures.books import BookForm, Books\n",
        True,
    ),
    (
        "tests/fixtures/primer/sample.py",
        "from decimal import Decimal\n"
        "from tests.fixtures.primer.order import Comment\n"
        "from tests.fixtures.primer.order import Items\n"
        "from tests.fixtures.primer.order import PurchaseOrder\n"
        "from tests.fixtures.primer.order import Usaddress\n"
        "from xsdata.models.datatype import XmlDate\n",
        "from decimal import Decimal\n"
        f"from {NEW_PKG}.models.datatype import XmlDate\n"
        "from tests.fixtures.primer.order import Comment\n"
        "from tests.fixtures.primer.order import Items\n"
        "from tests.fixtures.primer.order import PurchaseOrder\n"
        "from tests.fixtures.primer.order import Usaddress\n",
        True,
    ),
    # -- install instructions ------------------------------------------------
    (
        "docs/installation.md",
        "pip install xsdata[cli,lxml] @ git+https://github.com/tefra/xsdata",
        f"pip install {NEW_DIST}[cli,lxml] @ git+{FORK_REPO}",
        False,
    ),
    (
        "docs/installation.md",
        "## Using conda\n\n```console\nconda install -c conda-forge xsdata\n```\n\n",
        "",
        False,
    ),
]

# ---------------------------------------------------------------------------
# Generic rules
# ---------------------------------------------------------------------------
# Anything that looks like a URL and mentions xsdata is protected from the
# generic rules: those links point at upstream on purpose.
RE_URL = re.compile(r"https?://[^\s\"'`)\]>|]+")

# xsdata.<identifier> -- a dotted module path.  The lookbehind keeps
# ".xsdata.xml", "sample.xsdata.xml" and "xsdata-w3c-tests" out of it; the
# negative lookahead keeps file names ("xsdata.xml") and hosts
# ("xsdata.readthedocs.io") out of it.  None of the real submodules of the
# package are named after a file extension or a TLD.
NOT_A_MODULE = (
    "xml|xsd|json|md|txt|cfg|toml|yml|yaml|html|svg|png|cache|"
    "readthedocs|com|org|net|io|dev"
)
RE_DOTTED = re.compile(rf"(?<![\w./-])xsdata(?!\.(?:{NOT_A_MODULE})\b)(?=\.[A-Za-z_])")
RE_FROM = re.compile(r"(?<=\bfrom )xsdata(?![\w.])")
RE_IMPORT = re.compile(r"(?<=\bimport )xsdata(?![\w.])")
# pip extras: xsdata[cli,lxml,soap] -> the *distribution* name
RE_EXTRAS = re.compile(r"(?<![\w./-])xsdata(?=\[)")
# shell examples: "$ xsdata generate ..." / "❯ xsdata download ..."
RE_SHELL = re.compile(r"(?m)^(\s*)([$❯] )xsdata(?= )")

# ---------------------------------------------------------------------------
# Import sorting.  "docx4j_xsdata" sorts before "tests", "typing", "toposort"
# and friends where "xsdata" sorted after them, so every import block that
# mixes our package with a later-sorting one comes out unsorted.  Upstream's
# blocks were isort-clean, so re-sorting exactly those blocks by module name
# restores that, with no dependency on ruff being installed.
# ---------------------------------------------------------------------------
RE_IMPORT_START = re.compile(r"^(\s*)(?:from\s+[\w.]+\s+import\b|import\s+[\w.]+)")
RE_IMPORT_MODULE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\b|import\s+([\w.]+))")


def sort_import_blocks(text: str) -> str:
    """Re-sort contiguous import blocks that mention the renamed package."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        match = RE_IMPORT_START.match(lines[i])
        if not match:
            out.append(lines[i])
            i += 1
            continue

        indent = match.group(1)
        block: list[tuple[tuple[int, str], list[str]]] = []
        while i < n:
            head = RE_IMPORT_START.match(lines[i])
            if not head or head.group(1) != indent:
                break
            stmt = [lines[i]]
            depth = lines[i].count("(") - lines[i].count(")")
            i += 1
            while depth > 0 and i < n:
                stmt.append(lines[i])
                depth += lines[i].count("(") - lines[i].count(")")
                i += 1
            mod = RE_IMPORT_MODULE.match(stmt[0])
            # plain "import x" sorts before "from x import y", as isort does
            kind = 0 if mod.group(2) else 1  # type: ignore[union-attr]
            module = (mod.group(1) or mod.group(2)).lower()  # type: ignore[union-attr]
            block.append(((kind, module), stmt))

        if len(block) > 1 and any(key[1].startswith(NEW_PKG) for key, _ in block):
            block.sort(key=lambda entry: entry[0])
        for _key, stmt in block:
            out.extend(stmt)
    return "\n".join(out)


LINE_LENGTH = 88  # [tool.ruff] line-length
RE_FROM_IMPORT = re.compile(
    rf"^(\s*)from ({NEW_PKG}[\w.]*) import ([^(#]+?)(\s+#.*)?$"
)


def wrap_long_imports(text: str) -> str:
    """Wrap our imports that the longer package name pushed over the line limit.

    Same shape ruff's isort produces: parenthesised, one name per line,
    trailing comma.  Only imports of the renamed package are touched.
    """
    out = []
    for line in text.split("\n"):
        match = RE_FROM_IMPORT.match(line)
        if not match or len(line) <= LINE_LENGTH:
            out.append(line)
            continue
        indent, module, names, comment = match.groups()
        parts = [name.strip() for name in names.split(",") if name.strip()]
        # a trailing comment rides on the last name, as ruff's isort puts it
        tail = [f"{indent}    {name}," for name in parts]
        if comment:
            tail[-1] += comment
        out.append(f"{indent}from {module} import (")
        out.extend(tail)
        out.append(f"{indent})")
    return "\n".join(out)


MINIMAL_WORKFLOW = """\
name: tests

on:
  push:
    branches: [ docx4j ]
  pull_request:
    branches: [ docx4j ]

jobs:
  tests:
    name: ${{ matrix.name }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - {name: Python 3.10, python: '3.10'}
          - {name: Python 3.11, python: '3.11'}
          - {name: Python 3.12, python: '3.12'}
          - {name: Python 3.13, python: '3.13'}
          - {name: Python 3.14, python: '3.14'}
    steps:
      - uses: actions/checkout@v6
      - name: Set up Python ${{ matrix.python }}
        uses: actions/setup-python@v6
        with:
          python-version: ${{ matrix.python }}
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip setuptools
          python -m pip install .[lxml,cli,test,soap]
      - name: Test
        run: |
          pytest --doctest-glob="docs/*.md"
  minimum:
    name: Minimum Installation
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.11'
      - name: Install without extras
        run: |
          pip install -e .[test]
      - name: Verify
        run: |
          docx4j-xsdata | xargs -0 python -c "import sys; assert 'Install cli' in sys.argv[1]"
"""

README_HEADER = f"""\
# {NEW_DIST}

**This is the docx4j-python fork of [xsdata]({UPSTREAM_REPO}) (MIT).** It is the
same library, published as the distribution `{NEW_DIST}` with the import package
`{NEW_PKG}` and the console script `{NEW_DIST}`, so that it can be installed
alongside upstream `xsdata` in one environment. Code generated by this fork imports
its runtime types from `{NEW_PKG}`.

* What differs from upstream, release by release: [docs/fork/CHANGES.md](docs/fork/CHANGES.md)
* How the fork tracks upstream tags: [docs/fork/REBASING.md](docs/fork/REBASING.md)
* Upstream project, documentation and issue tracker: <{UPSTREAM_REPO}>
* The rename is entirely script-generated by [tools/rename.py](tools/rename.py);
  no part of it is hand-edited.

Upstream's MIT licence and copyright (Christodoulos Tsoulloftas) are unchanged and
are kept in [LICENSE](LICENSE); the MIT text requires no additional notice for the
fork's changes. Modifications in this fork are copyright (c) 2026 Plutext Pty Ltd
and are released under the same MIT licence.

The rest of this README is upstream's.

---

"""


def log(msg: str) -> None:
    print(msg)


def is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def move_package(root: Path) -> None:
    src = root / OLD_PKG
    dst = root / NEW_PKG
    if is_git_repo(root):
        subprocess.run(["git", "mv", OLD_PKG, NEW_PKG], cwd=root, check=True)
    else:
        shutil.move(str(src), str(dst))
    log(f"  moved {OLD_PKG}/ -> {NEW_PKG}/")


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if any(p in SKIP_DIR_NAMES or p.endswith(".egg-info") for p in parts):
            continue
        if rel in SKIP_RELPATHS or any(
            rel.startswith(f"{p}/") for p in SKIP_RELPATHS
        ):
            continue
        yield path, rel


def apply_generic(text: str) -> str:
    urls: list[str] = []

    def stash(m: re.Match) -> str:
        urls.append(m.group(0))
        return f"\x00URL{len(urls) - 1}\x00"

    text = RE_URL.sub(stash, text)
    text = RE_DOTTED.sub(NEW_PKG, text)
    text = RE_FROM.sub(NEW_PKG, text)
    text = RE_IMPORT.sub(NEW_PKG, text)
    text = RE_EXTRAS.sub(NEW_DIST, text)
    text = RE_SHELL.sub(rf"\1\2{NEW_DIST}", text)
    for i, url in enumerate(urls):
        text = text.replace(f"\x00URL{i}\x00", url)
    return text


def rewrite_ci(root: Path) -> list[str]:
    done = []
    publish = root / ".github/workflows/publish.yml"
    if publish.exists():
        if is_git_repo(root):
            subprocess.run(["git", "rm", "-q", "--", str(publish.relative_to(root))],
                           cwd=root, check=True)
        else:
            publish.unlink()
        done.append(
            "removed upstream .github/workflows/publish.yml "
            "(the fork's own is a feature commit on docx4j)"
        )
    tests_wf = root / ".github/workflows/tests.yml"
    tests_wf.parent.mkdir(parents=True, exist_ok=True)
    tests_wf.write_text(MINIMAL_WORKFLOW, encoding="utf-8")
    done.append("wrote minimal .github/workflows/tests.yml (py3.10-3.14)")
    return done


def rewrite_readme(root: Path) -> None:
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    if text.startswith(README_HEADER[:40]):
        return
    readme.write_text(README_HEADER + text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Leftover report
# ---------------------------------------------------------------------------
def classify(line: str) -> str:
    """Return "expected" or "review" for a line that still mentions xsdata."""
    stripped = line
    # upstream links
    stripped = RE_URL.sub("", stripped)
    stripped = stripped.replace("http://pypi.org/project/xsdata", "")
    stripped = stripped.replace(".xsdata.xml", "")
    stripped = stripped.replace("xsdata.xml", "")
    if OLD_PKG not in stripped:
        return "expected"
    # anything left that still looks like a module path / package path / extras
    if re.search(r"(?<![\w./-])xsdata(?=\.[A-Za-z_]|\[|/[A-Za-z_])", stripped):
        return "review"
    return "expected"


def report_leftovers(root: Path) -> int:
    expected = 0
    review: list[str] = []
    for path, rel in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        if OLD_PKG not in text:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if OLD_PKG not in line:
                continue
            if classify(line) == "review":
                review.append(f"    {rel}:{n}: {line.strip()[:110]}")
            else:
                expected += 1
    log("")
    log(f"  leftover 'xsdata' mentions, expected (see KEEP): {expected}")
    if review:
        log(f"  leftover 'xsdata' mentions NEEDING REVIEW: {len(review)}")
        for item in review:
            log(item)
    else:
        log("  leftover 'xsdata' mentions needing review: 0")
    return len(review)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    # Presence is decided by __init__.py, not by the directory: a stale
    # __pycache__ tree left behind by an editable install must not be mistaken
    # for a renamed package.
    old_dir = root / OLD_PKG
    new_dir = root / NEW_PKG
    for stale in (old_dir, new_dir):
        if stale.is_dir() and not (stale / "__init__.py").exists():
            shutil.rmtree(stale)
            log(f"  removed stale build leftovers in {stale.name}/")
    if new_dir.is_dir() and old_dir.is_dir():
        print(
            f"error: both {OLD_PKG}/ and {NEW_PKG}/ exist in {root}; "
            "the tree is in an unknown state",
            file=sys.stderr,
        )
        return 2
    if new_dir.is_dir():
        log(f"{root} is already renamed ({NEW_PKG}/ exists); nothing to do.")
        return 0
    if not old_dir.is_dir():
        print(f"error: {root} does not look like an xsdata checkout", file=sys.stderr)
        return 2

    log(f"Renaming {root}")
    log(f"  distribution : xsdata -> {NEW_DIST}")
    log(f"  import package: xsdata -> {NEW_PKG}")
    log(f"  console script: xsdata -> {NEW_DIST}")
    log("")

    # 1. explicit, per-file rules (before the package move, paths are upstream's)
    applied = 0
    for rel, old, new, required in EXPLICIT:
        path = root / rel
        if not path.exists():
            if required:
                print(f"error: {rel} does not exist", file=sys.stderr)
                return 3
            continue
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            if required:
                print(
                    f"error: {rel}: expected text not found, upstream has changed:\n"
                    f"       {old[:120]!r}",
                    file=sys.stderr,
                )
                return 3
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        applied += count
    log(f"  explicit replacements applied: {applied} "
        f"(of {len(EXPLICIT)} rules)")

    # 2. move the package
    move_package(root)

    # 3. generic rules over every text file
    changed = 0
    for path, _rel in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        if OLD_PKG not in text:
            continue
        new_text = apply_generic(text)
        if path.suffix == ".py":
            new_text = sort_import_blocks(wrap_long_imports(new_text))
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1
    log(f"  files rewritten by the generic rules: {changed}")

    # 4. CI and README
    for line in rewrite_ci(root):
        log(f"  {line}")
    rewrite_readme(root)
    log("  prepended the fork notice to README.md")

    # 5. report
    needs_review = report_leftovers(root)
    log("")
    log("  deliberately kept:")
    for what, why in KEEP:
        log(f"    - {what}: {why}")
    log("")
    log("Done." if not needs_review else "Done, with items to review above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
