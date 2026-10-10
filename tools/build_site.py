#!/usr/bin/env python3
"""Build the static reference manual site from the tracked documentation.

The site is set as a reference manual: each document is a numbered chapter, the changelog and
license are appendices, and every tool gets a manual page generated from its own argument parser.
Nothing is hand-copied, so the site cannot drift from the repository. The build uses only the
standard library, is reproducible from a commit (dates come from the commit, not the clock), and
prints the absolute maximum ratings only when this build ran the release gate and saw it pass.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import html
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_SOURCE = REPO_ROOT / "site"
DEFAULT_OUTPUT = REPO_ROOT / "_site"
REPOSITORY_URL = "https://github.com/sparklbarff/sysops_pub"
OUTPUT_MARKER = "deploy.json"
STATIC_FILES = ("styles.css", "theme.js", "eggs.js", "favicon.svg", "vercel.json", "robots.txt")
STATIC_DIRECTORIES = ("fonts",)
MAN_WIDTH = 76
NARROW_WIDTH = 32


class BuildError(Exception):
    """A build input is missing, malformed, or inconsistent with the manual."""


# --------------------------------------------------------------------------------------------
# The manual's structure


@dataclass(frozen=True)
class Chapter:
    number: str
    order: str
    source: str
    slug: str
    pin: str

    @property
    def href(self) -> str:
        return f"/{self.slug}/"


CHAPTERS = (
    Chapter("1", "SOP-100", "docs/ARCHITECTURE.md", "architecture", "ARCH"),
    Chapter("2", "SOP-110", "docs/QUICKSTART.md", "quickstart", "QSTART"),
    Chapter("3", "SOP-120", "docs/ADAPTATION_GUIDE.md", "adaptation", "ADAPT"),
    Chapter("4", "SOP-130", "docs/CAPABILITY_MATRIX.md", "capability-matrix", "CAPMAT"),
    Chapter("5", "SOP-200", "docs/SECURITY_BOUNDARY.md", "security-boundary", "SECBND"),
    Chapter("6", "SOP-210", "docs/EXPORT_MANIFEST.md", "export-manifest", "EXPORT"),
    Chapter("7", "SOP-220", "docs/PARITY.md", "parity", "PARITY"),
    Chapter("8", "SOP-300", "docs/MACOS_OPTIONAL.md", "macos", "MACOS"),
    Chapter("9", "SOP-310", "docs/OPERATIONS.md", "operations", "OPS"),
)
APPENDICES = (
    Chapter("A", "SOP-900", "CHANGELOG.md", "revisions", "REVS"),
    Chapter("B", "SOP-910", "LICENSE", "license", "LIC"),
)
HOME_SOURCE = "README.md"
# Tracked documents deliberately left out of the manual, with the reason.
EXCLUDED_SOURCES = {
    "docs/case-studies/SPECTRE.md": "case studies stay in the repository, not on the site",
    "docs/case-studies/EIDOLON.md": "case studies stay in the repository, not on the site",
}
# Every tool gets a manual page. Most are generated from the tool's own argument parser; these
# three have no parser, so their synopsis is stated here and their description is the docstring.
COMMANDS = (
    "demo",
    "test",
    "control",
    "adopt",
    "bootstrap",
    "verify_release",
    "pre_push",
    "update_supervisor",
    "managed_job",
    "calibrate_check",
    "search_docs",
    "eval_retrieval",
    "plan_index_refresh",
    "case_exercises",
    "build_site",
)
PARSERLESS = {
    "demo": "python3 tools/demo.py",
    "test": "python3 tools/test.py",
    "pre_push": "invoked by .githooks/pre-push; takes no arguments",
}

ALL_PAGES = CHAPTERS + APPENDICES
PAGES_BY_SOURCE = {page.source: page for page in ALL_PAGES}


@dataclass(frozen=True)
class Drawing:
    """A redrawn block diagram, bound to the exact text of the ASCII diagram it replaces."""

    name: str
    source_sha256: str
    caption: str


DRAWINGS = (
    Drawing(
        name="control-loop",
        source_sha256="ae65895eadb2d026295464968ae77d30c3d8ccc482b581936ddfada87d3bd0a8",
        caption="The configuration control loop.",
    ),
    Drawing(
        name="control-planes",
        source_sha256="52b28fab6c25877391a6c9a16f92e04186d8fdfa1d7de7ec667bd002ab69ba0c",
        caption="Two control planes.",
    ),
)
# A fenced text block containing a bare downward arrow line is a diagram, not a command.
DIAGRAM_LINE = re.compile(r"^\s*v\s*$", re.MULTILINE)

# Absolute maximum ratings: each row is printed only when the gate reported this exact pass.
RATINGS = (
    ("Secrets in the tree or Git history", "0", "gitleaks Git history", "gitleaks"),
    ("Personal identifiers in tracked files", "0", "dependency-free suite", "disclosure scan"),
    ("Failing tests", "0", "dependency-free suite", "test suite"),
    ("Untracked files in the release", "0", "no untracked files", "release check"),
)
GATE_LABELS = (
    "mandatory local pre-push gate is wired",
    "dependency-free suite",
    "case exercises",
    "configuration syntax",
    "no untracked files",
    "black",
    "ruff",
    "gitleaks Git history",
    "shellcheck",
)

REVISION_HEADING = re.compile(
    r"^## (?P<internal>Internal snapshot )?(?P<version>\d+\.\d+\.\d+) - (?P<date>\d{4}-\d{2}-\d{2})$"
)


# --------------------------------------------------------------------------------------------
# Repository facts


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str
    clean: bool

    @property
    def short(self) -> str:
        return self.sha[:7]


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=REPO_ROOT, check=False, capture_output=True, text=True
    )
    if result.returncode:
        raise BuildError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout


def read_commit() -> Commit:
    return Commit(
        sha=_git("rev-parse", "HEAD").strip(),
        date=_git("log", "-1", "--format=%cs", "HEAD").strip(),
        clean=_git("status", "--porcelain").strip() == "",
    )


def tracked_paths() -> frozenset[str]:
    files = [line for line in _git("ls-files").splitlines() if line]
    directories: set[str] = set()
    for name in files:
        parent = Path(name).parent
        while str(parent) != ".":
            directories.add(f"{parent}/")
            parent = parent.parent
    return frozenset(files) | frozenset(directories)


@dataclass(frozen=True)
class Revision:
    version: str
    date: str
    internal: bool
    changes: tuple[str, ...]


def parse_revisions(text: str) -> list[Revision]:
    revisions: list[Revision] = []
    heading: re.Match[str] | None = None
    changes: list[str] = []

    def close() -> None:
        if heading is not None:
            if not changes:
                raise BuildError(f"revision {heading['version']} lists no changes")
            revisions.append(
                Revision(
                    heading["version"],
                    heading["date"],
                    heading["internal"] is not None,
                    tuple(changes),
                )
            )

    for line in text.splitlines():
        if line.startswith("## "):
            close()
            heading = REVISION_HEADING.match(line)
            if heading is None:
                raise BuildError(f"unrecognized changelog heading: {line!r}")
            changes = []
        elif heading is not None and line.startswith("- "):
            changes.append(line[2:].strip())
        elif heading is not None and line.startswith("  ") and changes:
            changes[-1] = f"{changes[-1]} {line.strip()}"
    close()
    if not revisions:
        raise BuildError("the changelog contains no revisions")
    return revisions


# --------------------------------------------------------------------------------------------
# Markdown subset renderer: exactly the constructs the tracked documents use


@dataclass
class Context:
    commit: Commit
    paths: frozenset[str]
    chapter: str = ""
    figures: int = 0
    sections: int = 0
    commands: set[str] = field(default_factory=set)


CODE_SPAN = re.compile(r"`([^`]+)`")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
STRONG = re.compile(r"\*\*(.+?)\*\*")
ORDERED_ITEM = re.compile(r"^(\d+)\. (.*)$")
TABLE_RULE = re.compile(r"^\|(\s*:?-{3,}:?\s*\|)+\s*$")
HEADING = re.compile(r"^(#{1,3}) (.+)$")
TOOL_PATH = re.compile(r"\btools/([a-z_]+)\.py\b")


def _slugify(text: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", "", text)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def _resolve_href(target: str) -> str:
    if target.startswith(("https://", "http://")):
        return target
    page = PAGES_BY_SOURCE.get(target)
    if target == HOME_SOURCE:
        return "/"
    if page is None:
        raise BuildError(f"link target is not a page in the manual: {target!r}")
    return page.href


def _code(text: str, context: Context) -> str:
    escaped = html.escape(text, quote=False)
    for name in TOOL_PATH.findall(text):
        if name in COMMANDS:
            context.commands.add(name)
    page = PAGES_BY_SOURCE.get(text)
    if page is not None or text == HOME_SOURCE:
        href = "/" if page is None else page.href
        return f'<a class="xref" href="{href}"><code>{escaped}</code></a>'
    tool = re.fullmatch(r"tools/([a-z_]+)\.py", text)
    if tool and tool.group(1) in COMMANDS:
        return f'<a class="xref" href="/commands/{tool.group(1)}/"><code>{escaped}</code></a>'
    if text in context.paths:
        kind = "tree" if text.endswith("/") else "blob"
        url = f"{REPOSITORY_URL}/{kind}/{context.commit.sha}/{text.rstrip('/')}"
        return f'<a class="src" href="{html.escape(url)}"><code>{escaped}</code></a>'
    return f"<code>{escaped}</code>"


def _render_prose(text: str) -> str:
    escaped = html.escape(text, quote=False)

    def link(match: re.Match[str]) -> str:
        href = _resolve_href(html.unescape(match.group(2)))
        return f'<a href="{html.escape(href)}">{match.group(1)}</a>'

    return STRONG.sub(r"<strong>\1</strong>", LINK.sub(link, escaped))


def render_inline(text: str, context: Context) -> str:
    pieces: list[str] = []
    position = 0
    for match in CODE_SPAN.finditer(text):
        pieces.append(_render_prose(text[position : match.start()]))
        pieces.append(_code(match.group(1), context))
        position = match.end()
    pieces.append(_render_prose(text[position:]))
    return "".join(pieces)


def _split_row(line: str) -> list[str]:
    cells: list[str] = []
    current = ""
    in_code = False
    for character in line.strip()[1:-1]:
        if character == "`":
            in_code = not in_code
        if character == "|" and not in_code:
            cells.append(current.strip())
            current = ""
        else:
            current += character
    cells.append(current.strip())
    return cells


def _render_table(lines: list[str], context: Context) -> str:
    header = _split_row(lines[0])
    rows = [_split_row(line) for line in lines[2:]]
    for row in rows:
        if len(row) != len(header):
            raise BuildError(f"table row has {len(row)} cells, header has {len(header)}: {row}")
    head = "".join(f'<th scope="col">{render_inline(cell, context)}</th>' for cell in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{render_inline(cell, context)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def drawing_for(text: str) -> Drawing | None:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for drawing in DRAWINGS:
        if drawing.source_sha256 == digest:
            return drawing
    if DIAGRAM_LINE.search(text):
        raise BuildError(
            "a text diagram has no matching drawing; redraw site/drawings and update its "
            f"source_sha256 ({digest}) in tools/build_site.py:\n{text}"
        )
    return None


def render_drawing(drawing: Drawing, context: Context, numbered: bool = True) -> str:
    svgs = "".join(
        (SITE_SOURCE / "drawings" / f"{drawing.name}-{shape}.svg").read_text(encoding="utf-8")
        for shape in ("wide", "tall")
    )
    caption = ""
    if numbered and context.chapter:
        context.figures += 1
        label = f"Figure {context.chapter}-{context.figures}."
        caption = f"<figcaption><b>{label}</b> {html.escape(drawing.caption)}</figcaption>"
    return f'<figure class="fig">{svgs}{caption}</figure>'


def listing(text: str) -> str:
    return f'<div class="panel"><pre><code>{html.escape(text, quote=False)}</code></pre></div>'


def _is_block_start(line: str) -> bool:
    return bool(
        line.startswith(("```", "#", "|", "- ")) or ORDERED_ITEM.match(line) or not line.strip()
    )


@dataclass
class Document:
    title: str
    body: str
    sections: list[tuple[str, str]]
    lede: str


def render_markdown(text: str, context: Context) -> Document:
    lines = text.splitlines()
    out: list[str] = []
    sections: list[tuple[str, str]] = []
    title = ""
    lede = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            end = index + 1
            while end < len(lines) and lines[end] != "```":
                end += 1
            if end == len(lines):
                raise BuildError("unterminated code fence")
            body = "\n".join(lines[index + 1 : end]) + "\n"
            for name in TOOL_PATH.findall(body):
                if name in COMMANDS:
                    context.commands.add(name)
            drawing = drawing_for(body) if line[3:].strip() == "text" else None
            out.append(render_drawing(drawing, context) if drawing else listing(body))
            index = end + 1
            continue
        heading = HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            content = render_inline(heading.group(2), context)
            if level == 1:
                if title:
                    raise BuildError("a document has more than one top-level heading")
                title = content
            elif level == 2:
                context.sections += 1
                anchor = _slugify(content)
                sections.append((anchor, content))
                number = f"{context.chapter}.{context.sections}" if context.chapter else ""
                label = f'<span class="secno">{number}</span> ' if number else ""
                out.append(f'<h2 class="sec" id="{anchor}">{label}{content}</h2>')
            else:
                out.append(f'<h3 id="{_slugify(content)}">{content}</h3>')
            index += 1
            continue
        if line.startswith("|") and index + 1 < len(lines) and TABLE_RULE.match(lines[index + 1]):
            end = index
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            out.append(_render_table(lines[index:end], context))
            index = end
            continue
        if line.startswith("- ") or ORDERED_ITEM.match(line):
            ordered = not line.startswith("- ")
            items: list[str] = []
            while index < len(lines):
                current = lines[index]
                item = ORDERED_ITEM.match(current) if ordered else None
                if ordered and item:
                    items.append(item.group(2))
                elif not ordered and current.startswith("- "):
                    items.append(current[2:])
                elif current.startswith("  ") and current.strip() and items:
                    items[-1] = f"{items[-1]} {current.strip()}"
                else:
                    break
                index += 1
            tag = "ol" if ordered else "ul"
            rendered = "".join(f"<li>{render_inline(item, context)}</li>" for item in items)
            out.append(f"<{tag}>{rendered}</{tag}>")
            continue
        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and not _is_block_start(lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        joined = " ".join(paragraph)
        lede = lede or joined
        out.append(f"<p>{render_inline(joined, context)}</p>")
    return Document(title=title, body="\n".join(out), sections=sections, lede=lede)


def split_sections(text: str) -> tuple[str, dict[str, str]]:
    """Split a Markdown document into its preamble and its level-two sections, by title."""
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] = preamble
    for line in text.splitlines():
        if line.startswith("## "):
            current = sections.setdefault(line[3:].strip(), [])
        else:
            current.append(line)
    return "\n".join(preamble), {name: "\n".join(body) for name, body in sections.items()}


# --------------------------------------------------------------------------------------------
# Manual pages, generated from each tool's own argument parser


@dataclass
class ManPage:
    name: str
    summary: str
    synopsis: str
    synopsis_narrow: str
    description: list[str]
    options: list[tuple[str, str]]
    arguments: list[tuple[str, str]]
    commands: list[tuple[str, str, list[tuple[str, str]]]]


def _load_tool(name: str) -> tuple[str, argparse.ArgumentParser | None]:
    path = REPO_ROOT / "tools" / f"{name}.py"
    docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    if name in PARSERLESS:
        return docstring, None
    spec = importlib.util.spec_from_file_location(f"_manual_{name}", path)
    if spec is None or spec.loader is None:
        raise BuildError(f"cannot load tools/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
        sys.modules.pop(spec.name, None)
    builder = getattr(module, "_build_parser", None)
    if builder is None:
        raise BuildError(f"tools/{name}.py has no _build_parser(); add it to PARSERLESS")
    return docstring, builder()


def _flags(action: argparse.Action) -> str:
    names = ", ".join(action.option_strings) or action.dest
    if action.nargs == 0:
        return names
    if action.choices is not None and not action.option_strings:
        return "{" + ",".join(str(choice) for choice in action.choices) + "}"
    if action.choices is not None:
        return f"{names} {{{','.join(str(choice) for choice in action.choices)}}}"
    metavar = action.metavar or action.dest.upper()
    return f"{names} {metavar}" if action.option_strings else str(metavar)


def _describe(parser: argparse.ArgumentParser) -> tuple[list, list, list]:
    options: list[tuple[str, str]] = []
    arguments: list[tuple[str, str]] = []
    commands: list[tuple[str, str, list[tuple[str, str]]]] = []
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
            for name, subparser in action.choices.items():
                sub_options, sub_arguments, _ = _describe(subparser)
                commands.append((name, helps.get(name, ""), sub_arguments + sub_options))
            continue
        entry = (_flags(action), action.help or "")
        (options if action.option_strings else arguments).append(entry)
    return options, arguments, commands


def _usage(parser: argparse.ArgumentParser, width: int) -> str:
    """argparse's own usage line, wrapped at a fixed width so the build is reproducible."""
    previous = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(width)
    try:
        usage = parser.format_usage()
    finally:
        if previous is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous
    return re.sub(r"\n {7}", "\n", re.sub(r"^usage: ", "", usage.rstrip()))


def man_page(name: str) -> ManPage:
    docstring, parser = _load_tool(name)
    paragraphs = [
        " ".join(block.split()) for block in re.split(r"\n\s*\n", docstring) if block.strip()
    ]
    if not paragraphs:
        raise BuildError(f"tools/{name}.py has no docstring to describe it")
    summary = re.split(r"(?<=\.)\s", paragraphs[0], maxsplit=1)[0].rstrip(".")
    if len(paragraphs) > 1 and paragraphs[0].rstrip(".") == summary:
        paragraphs = paragraphs[1:]
    if parser is None:
        narrow = textwrap.fill(PARSERLESS[name], NARROW_WIDTH, subsequent_indent="  ")
        return ManPage(name, summary, PARSERLESS[name], narrow, paragraphs, [], [], [])
    parser.prog = f"python3 tools/{name}.py"
    synopsis = _usage(parser, MAN_WIDTH)
    synopsis_narrow = _usage(parser, NARROW_WIDTH)
    options, arguments, commands = _describe(parser)
    return ManPage(
        name, summary, synopsis, synopsis_narrow, paragraphs, options, arguments, commands
    )


def render_man(page: ManPage, examples: list[str], see_also: list[tuple[str, str]]) -> str:
    def entries(rows: list[tuple[str, str]]) -> str:
        return "".join(
            f"<dt>{html.escape(flag)}</dt><dd>{html.escape(text) or '&#8203;'}</dd>"
            for flag, text in rows
        )

    blocks = [
        ("NAME", f"<p><b>{page.name}</b> — {html.escape(page.summary)}</p>"),
        (
            "SYNOPSIS",
            (
                f'<pre class="wide">{html.escape(page.synopsis)}</pre>'
                f'<pre class="narrow">{html.escape(page.synopsis_narrow)}</pre>'
            ),
        ),
        ("DESCRIPTION", "".join(f"<p>{html.escape(text)}</p>" for text in page.description)),
    ]
    if page.arguments:
        blocks.append(("ARGUMENTS", f"<dl>{entries(page.arguments)}</dl>"))
    if page.commands:
        rows = "".join(
            f"<dt><b>{html.escape(command)}</b></dt><dd>{html.escape(text) or '&#8203;'}"
            + (f"<dl>{entries(options)}</dl>" if options else "")
            + "</dd>"
            for command, text, options in page.commands
        )
        blocks.append(("COMMANDS", f'<dl class="cmds">{rows}</dl>'))
    if page.options:
        blocks.append(("OPTIONS", f"<dl>{entries(page.options)}</dl>"))
    if examples:
        blocks.append(("EXAMPLES", f"<pre>{html.escape(chr(10).join(examples))}</pre>"))
    if see_also:
        links = ", ".join(f'<a href="{href}">{html.escape(label)}</a>' for label, href in see_also)
        blocks.append(("SEE ALSO", f"<p>{links}</p>"))
    sections = "".join(
        f'<section class="mansec"><h2>{title}</h2><div>{body}</div></section>'
        for title, body in blocks
    )
    upper = page.name.upper()
    return (
        f'<div class="manpage"><p class="manrun"><span>{upper}(1)</span>'
        f"<span>sysops_pub Commands</span><span>{upper}(1)</span></p>{sections}</div>"
    )


# --------------------------------------------------------------------------------------------
# Recorded sessions: every tool, really run, in a fresh clone of the commit


@dataclass(frozen=True)
class Step:
    """One command typed at the prompt; ``shell`` steps are setup shown as typed."""

    command: str
    shell: bool = False
    expect: tuple[int, ...] = (0,)


SESSIONS: dict[str, tuple[Step, ...]] = {
    "demo": (Step("python3 tools/demo.py"),),
    "control": (
        Step("python3 tools/control.py init --target ../sandbox"),
        Step("python3 tools/control.py plan --target ../sandbox"),
        Step("python3 tools/control.py apply --target ../sandbox"),
        Step("python3 tools/control.py apply --target ../sandbox --execute"),
        Step("python3 tools/control.py verify --target ../sandbox"),
        Step("python3 tools/control.py report --target ../sandbox"),
    ),
    "adopt": (
        Step("mkdir ../my-project", shell=True),
        Step("python3 tools/adopt.py --into ../my-project --tool both"),
        Step("python3 tools/adopt.py --into ../my-project --tool both --execute"),
        Step("python3 tools/adopt.py --into ../my-project --tool both --execute"),
    ),
    "bootstrap": (
        Step("python3 tools/bootstrap.py --check", expect=(2,)),
        Step("python3 tools/bootstrap.py"),
        Step("python3 tools/bootstrap.py --execute"),
        Step("python3 tools/bootstrap.py --check"),
    ),
    "update_supervisor": (
        Step("python3 tools/update_supervisor.py init ../update-demo"),
        Step("python3 tools/update_supervisor.py init ../update-demo --execute"),
        Step("python3 tools/update_supervisor.py check ../update-demo"),
        Step("python3 tools/update_supervisor.py apply ../update-demo --channel cli-tools"),
        Step(
            "python3 tools/update_supervisor.py apply ../update-demo --channel cli-tools --execute"
        ),
    ),
    "managed_job": (
        Step(
            "python3 tools/managed_job.py --receipt ../managed-job.json --timeout 60 -- "
            "python3 tools/plan_index_refresh.py sample-project"
        ),
        Step("cat ../managed-job.json", shell=True),
    ),
    "calibrate_check": (
        Step(
            "python3 tools/calibrate_check.py "
            "--checker samples/calibration/check_update_receipt.py "
            "--known-failure samples/calibration/known-failure.json "
            "--valid samples/calibration/valid.json "
            "--allowed-variation samples/calibration/allowed-variation.json "
            '--diagnostic "persisted state differs from expected" -- '
            "python3 samples/calibration/check_update_receipt.py {case}"
        ),
    ),
    "search_docs": (
        Step(
            'python3 tools/search_docs.py "How is desired state verified?" '
            "--requirement-id demo-orientation-001"
        ),
    ),
    "eval_retrieval": (Step("python3 tools/eval_retrieval.py"),),
    "plan_index_refresh": (Step("python3 tools/plan_index_refresh.py sample-project"),),
    "case_exercises": (Step("python3 tools/case_exercises.py all"),),
}
SESSION_TIMEOUT = 180


@dataclass(frozen=True)
class Exchange:
    command: str
    output: str
    status: int


def _sanitize(text: str, roots: Sequence[str]) -> str:
    for root in sorted(set(roots), key=len, reverse=True):
        text = text.replace(root, "/tmp/session")
    return text


def _disclosure_patterns() -> dict[str, re.Pattern[str]]:
    path = REPO_ROOT / "scripts" / "disclosure_scan.py"
    spec = importlib.util.spec_from_file_location("_session_disclosure", path)
    if spec is None or spec.loader is None:
        raise BuildError("cannot load scripts/disclosure_scan.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module.TEXT_PATTERNS


def record_sessions(commit: Commit) -> dict[str, list[Exchange]]:
    """Clone the commit into a temporary directory and run every session there, for real.

    Nothing runs against this working tree. Output is published, so every absolute path is
    replaced with /tmp/session and the result must pass the repository's own disclosure
    patterns; a match fails the build rather than publishing it.
    """
    patterns = _disclosure_patterns()
    recorded: dict[str, list[Exchange]] = {}
    with tempfile.TemporaryDirectory(prefix="sysops-pub-sessions-") as directory:
        root = Path(directory)
        scratch = root / "tmp"
        scratch.mkdir()
        roots = [directory, os.path.realpath(directory)]
        clone = root / "sysops_pub"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-local", str(REPO_ROOT), str(clone)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "--quiet", "--detach", commit.sha],
            cwd=clone,
            check=True,
            capture_output=True,
        )
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(root),
            "TMPDIR": str(scratch),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "COLUMNS": str(MAN_WIDTH),
        }
        for name, steps in SESSIONS.items():
            exchanges = []
            for step in steps:
                argv = shlex.split(step.command)
                if argv[0] == "python3":
                    argv[0] = sys.executable
                result = subprocess.run(
                    argv,
                    cwd=clone,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=SESSION_TIMEOUT,
                )
                if result.returncode not in step.expect:
                    raise BuildError(
                        f"recorded session {name}: {step.command!r} returned "
                        f"{result.returncode}, expected {step.expect}:\n"
                        f"{result.stdout}{result.stderr}"
                    )
                output = _sanitize((result.stdout + result.stderr).rstrip(), roots)
                for label, pattern in patterns.items():
                    if pattern.search(output) or pattern.search(step.command):
                        raise BuildError(
                            f"recorded session {name} would publish a {label}; refusing"
                        )
                exchanges.append(Exchange(step.command, output, result.returncode))
            recorded[name] = exchanges
    return recorded


CLONE_NOTE = (
    "Run by the build in a fresh clone of commit {short}, in a temporary directory shown as "
    "<code>/tmp/session</code>. The output is the tools' own, unedited apart from that path."
)
GATE_NOTE = (
    "The release gate exactly as this build ran it on commit {short}, before writing any page, "
    "reduced to its own verdict lines. A failing check stops the build, so this page cannot "
    "exist with a FAIL in it."
)


def render_session(name: str, exchanges: list[Exchange], commit: Commit) -> str:
    lines = []
    for exchange in exchanges:
        lines.append(
            f'<span class="prompt">$ </span><span class="typed">{html.escape(exchange.command)}'
            "</span>"
        )
        if exchange.output:
            lines.append(html.escape(exchange.output))
        if exchange.status:
            lines.append(f'<span class="status">[exit {exchange.status}]</span>')
    return (
        f'<section class="session" id="session"><h2 class="label">Recorded session</h2>'
        f'<p class="note">{(GATE_NOTE if name == "verify_release" else CLONE_NOTE).format(short=commit.short)}</p>'
        f'<div class="panel terminal"><pre><code>{chr(10).join(lines)}</code></pre></div>'
        "</section>"
    )


def gate_session(output: str, sha: str) -> list[Exchange]:
    """The release gate's own output, as the build captured it, reduced to its verdict lines."""
    # verify_release's own verdicts; nested test output (which exercises the gate with
    # fixture SHAs) is left out so the excerpt describes this commit only.
    kept = [
        line
        for line in output.splitlines()
        if line.startswith(("PASS: ", "FAIL: ", "SKIP: ", "release verification"))
        and not (
            line.startswith("PASS: candidate identity")
            and line != f"PASS: candidate identity ({sha})"
        )
    ]
    return [
        Exchange(
            f"python3 tools/verify_release.py --require-tools --candidate-sha {sha}",
            "\n".join(kept),
            0,
        )
    ]


# --------------------------------------------------------------------------------------------
# Page assembly


@dataclass(frozen=True)
class Site:
    commit: Commit
    version: str
    paths: frozenset[str]
    gate: dict[str, bool] | None
    template: Template
    titles: dict[str, str] = field(default_factory=dict)


def _plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def _description(text: str, limit: int = 158) -> str:
    plain = LINK.sub(r"\1", re.sub(r"[`*]", "", text))
    return plain if len(plain) <= limit else plain[:limit].rsplit(" ", 1)[0] + "…"


TABS = (
    ("0", "Overview", "/"),
    *((chapter.number, "", chapter.href) for chapter in ALL_PAGES),
    ("Cmd", "Commands", "/commands/"),
)


def render_tabs(current: str, titles: dict[str, str]) -> str:
    """The thumb index: one tab per chapter, cut into the page edge like a printed manual."""
    tabs = []
    for key, name, href in TABS:
        label = name or titles.get(key, key)
        attributes = ' aria-current="page"' if key == current else ""
        tabs.append(
            f'<li><a class="tab" href="{href}"{attributes}><span class="tab-key">{key}</span>'
            f'<span class="tab-name">{html.escape(label)}</span></a></li>'
        )
    return f'<nav class="thumbs" aria-label="Chapters"><ol>{"".join(tabs)}</ol></nav>'


def bit_rows(sha: str) -> list[str]:
    """The commit as four rows of bits, one column per hex digit, most significant bit on top."""
    return [
        "".join("1" if int(digit, 16) & weight else "0" for digit in sha) for weight in (8, 4, 2, 1)
    ]


def colophon(site: Site) -> str:
    grid = "\n".join(
        "    " + row.replace("1", "\u2588").replace("0", "\u00b7")
        for row in bit_rows(site.commit.sha)
    )
    hexes = "    " + site.commit.sha
    return (
        "<!--\n"
        f"  sysops_pub reference manual · rev {site.version} · {part_number(site.version)}\n"
        f"  commit {site.commit.sha}\n\n{grid}\n{hexes}\n\n"
        "  Built by tools/build_site.py from the tracked documents; nothing here is hand-copied.\n"
        "  Each column above is one hex digit of the commit, most significant bit on top.\n"
        "  Press ? on any page. Errata, if any, are at /errata/.\n"
        "-->"
    )


def _page(
    site: Site,
    *,
    title: str,
    lede: str,
    center: str,
    order: str,
    body: str,
    tab: str = "",
    previous: tuple[str, str] | None = None,
    following: tuple[str, str] | None = None,
    front: bool = False,
) -> str:
    def nav(link: tuple[str, str] | None, rel: str) -> str:
        if link is None:
            return "<span></span>"
        label, href = link
        arrow = "← " if rel == "prev" else ""
        tail = " →" if rel == "next" else ""
        return f'<a rel="{rel}" href="{href}">{arrow}{html.escape(label)}{tail}</a>'

    return site.template.substitute(
        colophon=colophon(site),
        page_title=html.escape(f"{title} · sysops_pub reference manual"),
        description=html.escape(_description(lede)),
        build=html.escape(f"{site.commit.sha} {site.version} {site.commit.date}"),
        body_class="front" if front else "inner",
        center=html.escape(center),
        order=html.escape(order),
        tabs=render_tabs(tab, site.titles),
        version=html.escape(site.version),
        date=site.commit.date,
        body=label_cells(body),
        prev=nav(previous, "prev"),
        next=nav(following, "next"),
        commit=site.commit.short,
        draft="" if site.commit.clean else '<p class="draft">Draft · uncommitted changes</p>',
        repository_url=REPOSITORY_URL,
    )


TABLE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL)


def label_cells(fragment: str) -> str:
    """Give every data cell its column header as data-label, for the stacked phone layout."""

    def label(table: re.Match[str]) -> str:
        text = table.group(0)
        headers = [
            html.escape(_plain(cell), quote=True)
            for cell in re.findall(r"<th[^>]*>(.*?)</th>", text, re.DOTALL)
        ]

        def row(match: re.Match[str]) -> str:
            cells = iter(headers)
            return re.sub(
                r"<td(?=[\s>])",
                lambda _: f'<td data-label="{next(cells, "")}"',
                match.group(0),
            )

        return re.sub(
            r"<tbody>.*?</tbody>",
            lambda body: re.sub(r"<tr>.*?</tr>", row, body.group(0), flags=re.DOTALL),
            text,
            flags=re.DOTALL,
        )

    return TABLE.sub(label, fragment)


def _neighbours(index: int, items: Sequence[tuple[str, str]]):
    previous = items[index - 1] if index > 0 else ("Contents", "/")
    following = items[index + 1] if index + 1 < len(items) else None
    return previous, following


def render_ratings(site: Site) -> str:
    rows = []
    for parameter, maximum, label, check in RATINGS:
        if site.gate:
            if not site.gate.get(label):
                raise BuildError(f"rating {parameter!r} has no matching gate pass {label!r}")
            value = maximum
        else:
            value = "—"
        rows.append(f"<tr><td>{parameter}</td><td class='max'>{value}</td><td>{check}</td></tr>")
    note = (
        f"Checked by <code>verify_release.py</code> for commit {site.commit.short}."
        if site.gate
        else "Not checked for this build. Values print only when the release gate has passed."
    )
    return (
        '<div class="ds-ratings"><h2 class="label">Absolute maximum ratings</h2>'
        '<div class="table"><table class="ratings"><thead><tr><th scope="col">Parameter</th>'
        '<th scope="col">Max</th><th scope="col">Checked by</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div><p class="note">{note}</p></div>'
    )


def render_home(
    site: Site, contents: list[tuple[str, str, str, str]], pages: list[ManPage]
) -> tuple[str, set[str]]:
    text = (REPO_ROOT / HOME_SOURCE).read_text(encoding="utf-8")
    preamble, sections = split_sections(text)
    required = ("What it demonstrates", "Quick start")
    for name in required:
        if name not in sections:
            raise BuildError(f"README.md has no '## {name}' section for the front page")
    context = Context(commit=site.commit, paths=site.paths)
    intro = render_markdown(preamble, context)
    demonstrates = render_markdown(sections["What it demonstrates"], context)
    quick = render_markdown(sections["Quick start"], context)
    rest = "\n".join(
        f"## {name}\n{body}" for name, body in sections.items() if name not in required
    )
    remainder = render_markdown(rest, context)

    features = re.search(r"<ul>.*?</ul>", demonstrates.body, re.DOTALL)
    figure = re.search(r'<figure class="fig">.*?</figure>', demonstrates.body, re.DOTALL)
    if features is None or figure is None:
        raise BuildError("README 'What it demonstrates' needs its list and the loop diagram")
    toc = "".join(
        f'<li><span class="n">{number}</span><a href="{href}">{html.escape(title)}</a>'
        f'<span class="dots"></span><span class="p">{order}</span></li>'
        for number, title, href, order in contents
    )
    commands = "".join(
        f'<li><a href="/commands/{page.name}/"><span class="mono">{page.name}(1)</span></a>'
        f"<span>{html.escape(page.summary)}</span></li>"
        for page in pages
    )
    body = (
        '<section class="cover"><p class="kicker">Declare-then-verify control loop</p>'
        f'<h1>{intro.title}</h1><div class="lede">{intro.body}</div></section>'
        '<section class="ds">'
        f'<div class="ds-features box"><h2 class="label">Features</h2>{features.group(0)}</div>'
        + render_ratings(site)
        + '<div class="ds-diagram"><h2 class="label">Functional block diagram</h2>'
        + figure.group(0)
        + "</div>"
        + render_pinout(site)
        + render_marking(site)
        + f'<div class="ds-contents"><h2 class="label">Contents</h2><ol class="toc">{toc}</ol></div>'
        f'<div class="ds-typical"><h2 class="label">Typical application</h2>{quick.body}</div>'
        f'<div class="ds-commands"><h2 class="label">Commands</h2><ul class="cmdlist">{commands}'
        "</ul></div></section>"
        f'<section class="overview">{remainder.body}</section>' + render_colophon(site)
    )
    page = _page(
        site,
        title="Overview",
        lede=intro.lede,
        center=f"Rev {site.version} · {site.commit.date}",
        order=f"Order no. {part_number(site.version)}",
        body=body,
        tab="0",
        following=(contents[0][1], contents[0][2]),
        front=True,
    )
    return page, context.commands


def render_colophon(site: Site) -> str:
    """The end of the front page: what this build is, how it was made, and its license."""
    sha = site.commit.sha
    gate = (
        "Passed for this build; see the absolute maximum ratings."
        if site.gate
        else "Not run for this build. Release builds run it before anything is written."
    )
    rows = (
        ("Revision", f"{site.version} · part number {part_number(site.version)}"),
        (
            "Commit",
            f'<a class="mono" href="{REPOSITORY_URL}/tree/{sha}">{sha}</a>',
        ),
        ("Date", f"{site.commit.date} · date code {date_code(site.commit.date)}"),
        ("Release gate", gate),
        (
            "Built by",
            (
                '<a class="mono" href="/commands/build_site/">build_site(1)</a> from the '
                "tracked documents and each tool's own argument parser. Nothing here is "
                "hand-copied."
            ),
        ),
        (
            "Typeset in",
            (
                "Chivo and Inconsolata, under the SIL Open Font License "
                '(<a href="/fonts/Chivo-OFL.txt">Chivo</a>, '
                '<a href="/fonts/Inconsolata-OFL.txt">Inconsolata</a>).'
            ),
        ),
        ("License", 'MIT. The full text is <a href="/license/">Appendix B</a>.'),
    )
    entries = "".join(f"<dt>{key}</dt><dd>{value}</dd>" for key, value in rows)
    return (
        '<section class="colophon" aria-labelledby="colophon-h">'
        f'<h2 id="colophon-h" class="label">Colophon</h2><dl>{entries}</dl>'
        '<p class="endmark" aria-hidden="true">■</p></section>'
    )


def render_chapter(
    site: Site, chapter: Chapter, previous, following, see_also: list[tuple[str, str]]
) -> tuple[str, set[str]]:
    context = Context(commit=site.commit, paths=site.paths, chapter=chapter.number)
    source = (REPO_ROOT / chapter.source).read_text(encoding="utf-8")
    appendix = chapter.number.isalpha()
    if chapter.source == "LICENSE":
        title = source.splitlines()[0].strip()
        document = Document(title, f'<pre class="license">{html.escape(source)}</pre>', [], title)
    else:
        document = render_markdown(source, context)
        if not document.title:
            raise BuildError(f"{chapter.source} has no top-level heading")
    kind = "Appendix" if appendix else "Chapter"
    links = see_also + [
        (f"{name}(1)", f"/commands/{name}/") for name in COMMANDS if name in context.commands
    ]
    see = (
        '<p class="see"><b>See also</b> '
        + ", ".join(f'<a href="{href}">{html.escape(label)}</a>' for label, href in links)
        + "</p>"
        if links
        else ""
    )
    body = (
        f'<article class="chapter"><p class="kicker">{kind} {chapter.number}</p>'
        f"<h1>{document.title}</h1>{document.body}{see}</article>"
    )
    title = _plain(document.title)
    page = _page(
        site,
        title=title,
        lede=document.lede,
        center=f"{kind} {chapter.number} · {title}",
        order=f"{chapter.order} · Rev {site.version}",
        body=body,
        tab=chapter.number,
        previous=previous,
        following=following,
    )
    return page, context.commands


def render_404(site: Site) -> str:
    body = (
        '<article class="chapter missing"><p class="kicker">ENOENT · exit status 2</p>'
        "<h1>No manual entry</h1>"
        '<div class="panel"><pre><code>$ man <span class="missing-path">this-page</span>\n'
        'No manual entry for <span class="missing-path">this-page</span></code></pre></div>'
        "<p>There is no page at this address in the sysops_pub reference manual. The contents "
        'are on the <a href="/">front page</a>, and every tool has a page under '
        '<a href="/commands/">Commands</a>.</p></article>'
    )
    return _page(
        site,
        title="No manual entry",
        lede="There is no page at this address.",
        center="Not found",
        order="ENOENT",
        body=body,
    )


# --------------------------------------------------------------------------------------------
# Data-sheet identity: part number, package marking, and pin configuration


def part_number(version: str) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    return f"SOP-{major}{minor}{patch:02d}"


def date_code(date: str) -> str:
    """YYWW, the ISO year and week, as semiconductor date codes are printed."""
    year, week, _ = datetime.date.fromisoformat(date).isocalendar()
    return f"{year % 100:02d}{week:02d}"


def render_marking(site: Site) -> str:
    sha = site.commit.sha
    cells = []
    for row, bits in enumerate(bit_rows(sha)):
        for column, bit in enumerate(bits):
            x, y = 70 + column * 10, 150 + row * 10
            css = "bit on" if bit == "1" else "bit"
            cells.append(f'<rect x="{x}" y="{y}" width="8" height="8" class="{css}"/>')
    pins = "".join(
        f'<rect x="{62 + index * 31}" y="6" width="14" height="14" class="pin"/>'
        f'<rect x="{62 + index * 31}" y="230" width="14" height="14" class="pin"/>'
        for index in range(14)
    )
    code = date_code(site.commit.date)
    svg = (
        '<svg class="marking" viewBox="0 0 540 250" role="img" aria-labelledby="mark-t mark-d" '
        'xmlns="http://www.w3.org/2000/svg"><title id="mark-t">Package marking</title>'
        f'<desc id="mark-d">Top of the package: part number {part_number(site.version)}, date '
        f"code {code}, lot {site.commit.short}, and the full commit {sha} as a field of 160 bits."
        f"</desc>{pins}"
        '<rect x="40" y="20" width="460" height="210" rx="6" class="body"/>'
        '<circle cx="62" cy="42" r="6" class="dot"/>'
        '<text x="70" y="70" class="mk mk-name">SYSOPS_PUB</text>'
        f'<text x="70" y="100" class="mk mk-part">{part_number(site.version)}</text>'
        f'<text x="70" y="126" class="mk mk-code">{code}  {site.commit.short.upper()}</text>'
        f'{"".join(cells)}</svg>'
    )
    legend = (
        '<div class="table"><table class="legend"><thead><tr><th scope="col">Marking</th>'
        '<th scope="col">Meaning</th></tr></thead><tbody>'
        f"<tr><td class='mono'>{part_number(site.version)}</td><td>Part number: sysops_pub "
        f"{site.version}.</td></tr>"
        f"<tr><td class='mono'>{code}</td><td>Date code YYWW: ISO week of the commit date, "
        f"{site.commit.date}.</td></tr>"
        f"<tr><td class='mono'>{site.commit.short.upper()}</td><td>Lot: the commit this page "
        "was built from.</td></tr>"
        "<tr><td>Bit field</td><td>The full 160-bit commit, one column per hex digit, most "
        f"significant bit on top: <code>{sha}</code>.</td></tr></tbody></table></div>"
    )
    return (
        '<div class="ds-marking"><h2 class="label">Package marking</h2>'
        f'<div class="part">{svg}</div>{legend}</div>'
    )


def pin_map() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Pins 1–16 down the left, 17–32 up the right; the last pin on each side is power."""
    left = [("OVW", "/")]
    left += [(chapter.pin, chapter.href) for chapter in ALL_PAGES]
    left += [("CMDS", "/commands/"), ("ERRATA", "/errata/")]
    left += [("NC", "")] * (15 - len(left)) + [("GND", "")]
    right = [(name, f"/commands/{name}/") for name in COMMANDS]
    right += [("NC", "")] * (15 - len(right)) + [("VCC", "")]
    if len(left) != 16 or len(right) != 16:
        raise BuildError("the pinout needs 16 pins a side; add or remove a pin")
    return left, right


def render_pinout(site: Site) -> str:
    left, right = pin_map()
    pitch, top = 28, 40
    parts = []
    for index, (label, href) in enumerate(left):
        y = top + index * pitch
        parts.append(f'<path d="M178 {y} H200" class="lead"/>')
        parts.append(f'<text x="208" y="{y + 4}" class="pn">{index + 1}</text>')
        parts.append(_pin_label(label, href, 170, y + 5, "end"))
    for index, (label, href) in enumerate(right):
        y = top + (15 - index) * pitch
        parts.append(f'<path d="M320 {y} H342" class="lead"/>')
        parts.append(f'<text x="312" y="{y + 4}" text-anchor="end" class="pn">{index + 17}</text>')
        parts.append(_pin_label(label, href, 350, y + 5, "start"))
    height = top + 15 * pitch + 32
    return (
        '<div class="ds-pinout"><h2 class="label">Pin configuration</h2><div class="part pins">'
        f'<svg class="pinout" viewBox="0 0 520 {height}" role="img" aria-labelledby="pin-t pin-d" '
        'xmlns="http://www.w3.org/2000/svg"><title id="pin-t">Pin configuration</title>'
        '<desc id="pin-d">The manual drawn as a 32-pin dual in-line package. Pins 1 to 16 down '
        "the left are the overview, chapters, appendices, commands index and errata; pins 17 "
        "to 32 up the right are the commands. Each labelled pin links to its page.</desc>"
        f'<rect x="200" y="{top - 22}" width="120" height="{15 * pitch + 44}" rx="4" class="body"/>'
        f'<path d="M245 {top - 22} A15 15 0 0 0 275 {top - 22}" class="notch"/>'
        f'<text transform="translate(260 {top + 7.5 * pitch}) rotate(-90)" text-anchor="middle" '
        f'class="chipname">{part_number(site.version)} · SYSOPS_PUB</text>'
        f'{"".join(parts)}</svg></div><p class="note">Top view. NC: no connection.</p>'
        + render_pin_table(left, right)
        + "</div>"
    )


def render_pin_table(left: list[tuple[str, str]], right: list[tuple[str, str]]) -> str:
    """Pin descriptions, as a data sheet lists them; shown in place of the drawing on phones."""
    rows = []
    for number, (label, href) in enumerate(left + right, start=1):
        name = f'<a href="{href}">{html.escape(label)}</a>' if href else html.escape(label)
        rows.append(f"<tr><td>{number}</td><td>{name}</td></tr>")
    return (
        '<div class="table pintable"><table><thead><tr><th scope="col">Pin</th>'
        f'<th scope="col">Name</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _pin_label(label: str, href: str, x: int, y: int, anchor: str) -> str:
    css = "pl mono" if href.startswith("/commands/") and href != "/commands/" else "pl"
    text = f'<text x="{x}" y="{y}" text-anchor="{anchor}" class="{css}">{html.escape(label)}</text>'
    return f'<a href="{href}">{text}</a>' if href else text.replace('class="pl', 'class="pl dim')


def errata(pages: list[ManPage]) -> list[tuple[str, str]]:
    """Every option, argument, or command a tool ships without help text, found in its parser."""
    found: list[tuple[str, str]] = []
    for page in pages:
        for flag, text in page.arguments + page.options:
            if not text:
                found.append((page.name, flag))
        for command, text, options in page.commands:
            if not text:
                found.append((page.name, command))
            for flag, help_text in options:
                if not help_text:
                    found.append((page.name, f"{command} {flag}"))
    return found


def render_errata(site: Site, pages: list[ManPage]) -> str:
    items = errata(pages)
    if items:
        rows = "".join(
            f'<tr><td><a class="mono" href="/commands/{name}/">{name}(1)</a></td>'
            f"<td><code>{html.escape(entry)}</code></td><td>Ships without help text, so its "
            "manual entry is blank.</td></tr>"
            for name, entry in items
        )
        listing_html = (
            f"<p>{len(items)} known defects against revision {site.version}. Each is found by "
            "reading the tool's own argument parser, so this sheet empties itself when the help "
            "text is written.</p>"
            '<div class="table"><table><thead><tr><th scope="col">Page</th>'
            '<th scope="col">Entry</th><th scope="col">Defect</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
        )
    else:
        listing_html = f"<p>No known errata against revision {site.version}.</p>"
    body = (
        '<article class="chapter"><p class="kicker">Errata</p><h1>Errata</h1>'
        f"{listing_html}</article>"
    )
    return _page(
        site,
        title="Errata",
        lede="Known defects against this revision of the manual.",
        center="Errata",
        order=f"{part_number(site.version)} errata",
        body=body,
    )


# --------------------------------------------------------------------------------------------
# Release gate


def run_gate(commit: Commit) -> tuple[dict[str, bool], str]:
    result = subprocess.run(
        [
            sys.executable,
            "tools/verify_release.py",
            "--require-tools",
            "--candidate-sha",
            commit.sha,
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode:
        raise BuildError(f"the release gate failed; nothing was built:\n{output}")
    return parse_gate(output), output


def parse_gate(output: str) -> dict[str, bool]:
    passed = [line[len("PASS: ") :] for line in output.splitlines() if line.startswith("PASS: ")]
    gate: dict[str, bool] = {}
    for label in GATE_LABELS:
        if not any(line == label or line.startswith(f"{label} ") for line in passed):
            raise BuildError(f"the release gate did not report a pass for {label!r}")
        gate[label] = True
    return gate


# --------------------------------------------------------------------------------------------
# Output


def _check_output_target(output: Path) -> None:
    resolved = output.resolve()
    if resolved in (REPO_ROOT, REPO_ROOT.parent, SITE_SOURCE, Path(resolved.anchor)):
        raise BuildError(f"refusing to build into {resolved}")
    if resolved.exists() and any(resolved.iterdir()) and not (resolved / OUTPUT_MARKER).is_file():
        raise BuildError(f"refusing to replace {resolved}: it is not a previous site build")


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _examples(name: str) -> list[str]:
    """Every command line in the tracked documents that runs this tool, verbatim."""
    found: list[str] = []
    for source in [HOME_SOURCE] + [page.source for page in ALL_PAGES]:
        text = (REPO_ROOT / source).read_text(encoding="utf-8")
        for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL):
            for line in block.splitlines():
                if f"tools/{name}.py" in line and line.strip() not in found:
                    found.append(line.strip())
    return found


def build(output: Path, *, release: bool, draft: bool) -> Path:
    commit = read_commit()
    if not commit.clean and not draft:
        raise BuildError("the working tree has uncommitted changes; commit them or pass --draft")
    if release:
        if draft or not commit.clean:
            raise BuildError("a release build needs a clean tree and cannot be a draft")
        pushed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
            cwd=REPO_ROOT,
            check=False,
        )
        if pushed.returncode:
            raise BuildError("a release build needs HEAD pushed to origin/main first")
    _check_output_target(output)
    gate, gate_output = run_gate(commit) if release else (None, "")
    revisions = parse_revisions((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    site = Site(
        commit=commit,
        version=revisions[0].version,
        paths=tracked_paths(),
        gate=gate,
        template=Template((SITE_SOURCE / "page.html").read_text(encoding="utf-8")),
        titles={chapter.number: _plain(_title_of(chapter)) for chapter in ALL_PAGES},
    )

    pages = [man_page(name) for name in COMMANDS]
    sessions = record_sessions(commit)
    if gate_output:
        sessions["verify_release"] = gate_session(gate_output, commit.sha)
    contents = [
        (chapter.number, _plain(_title_of(chapter)), chapter.href, chapter.order)
        for chapter in ALL_PAGES
    ]
    sequence = [(f"{number} {title}", href) for number, title, href, _ in contents]

    resolved = output.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".site-", dir=resolved.parent))
    try:
        home, used_on_home = render_home(site, contents, pages)
        _write(staging, "index.html", home)
        mentions: dict[str, list[tuple[str, str]]] = {name: [] for name in COMMANDS}
        for name in sorted(used_on_home):
            mentions[name].append(("sysops_pub(7)", "/"))
        for index, chapter in enumerate(ALL_PAGES):
            previous, following = _neighbours(index, sequence)
            if following is None:
                following = ("Commands", "/commands/")
            page, used = render_chapter(site, chapter, previous, following, [])
            _write(staging, f"{chapter.slug}/index.html", page)
            for name in used:
                mentions[name].append((f"{chapter.slug}(7)", chapter.href))
        _write(
            staging, "commands/index.html", render_command_index(site, pages, sequence, sessions)
        )
        for index, page in enumerate(pages):
            previous = (
                (f"{pages[index - 1].name}(1)", f"/commands/{pages[index - 1].name}/")
                if index
                else ("Commands", "/commands/")
            )
            following = (
                (f"{pages[index + 1].name}(1)", f"/commands/{pages[index + 1].name}/")
                if index + 1 < len(pages)
                else None
            )
            body = render_man(page, _examples(page.name), mentions[page.name])
            if page.name in sessions:
                body += render_session(page.name, sessions[page.name], commit)
            _write(
                staging,
                f"commands/{page.name}/index.html",
                _page(
                    site,
                    title=f"{page.name}(1)",
                    lede=page.summary,
                    center="Commands",
                    order=f"{page.name.upper()}(1)",
                    body=body,
                    tab="Cmd",
                    previous=previous,
                    following=following,
                ),
            )
        _write(staging, "404.html", render_404(site))
        _write(staging, "errata/index.html", render_errata(site, pages))
        for name in STATIC_FILES:
            shutil.copy2(SITE_SOURCE / name, staging / name)
        for name in STATIC_DIRECTORIES:
            shutil.copytree(SITE_SOURCE / name, staging / name)
        stamp = {
            "commit": commit.sha,
            "date": commit.date,
            "version": site.version,
            "tree_clean": commit.clean,
            "release_gate": "passed" if gate else "not run",
        }
        _write(staging, OUTPUT_MARKER, json.dumps(stamp, indent=2) + "\n")
        if resolved.exists():
            shutil.rmtree(resolved)
        staging.rename(resolved)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return resolved


def _title_of(chapter: Chapter) -> str:
    text = (REPO_ROOT / chapter.source).read_text(encoding="utf-8")
    if chapter.source == "LICENSE":
        return "License"
    match = re.search(r"^# (.+)$", text, re.MULTILINE)
    if match is None:
        raise BuildError(f"{chapter.source} has no top-level heading")
    return render_inline(match.group(1), Context(commit=Commit("", "", True), paths=frozenset()))


def render_command_index(
    site: Site, pages: list[ManPage], sequence, sessions: dict[str, list[Exchange]]
) -> str:
    rows = "".join(
        f'<tr><td><a class="mono" href="/commands/{page.name}/">{page.name}(1)</a></td>'
        f"<td>{html.escape(page.summary)}</td><td>"
        + (
            f'<a href="/commands/{page.name}/#session">{len(sessions[page.name])} commands</a>'
            if page.name in sessions
            else "—"
        )
        + "</td></tr>"
        for page in pages
    )
    body = (
        '<article class="chapter"><p class="kicker">Commands</p><h1>Commands</h1>'
        "<p>Every tool in <code>tools/</code>, as a manual page generated from its own argument "
        "parser and docstring. Most pages end with a recorded session: the build runs the tool "
        "in a fresh clone of this commit and prints exactly what it said.</p>"
        '<div class="table"><table><thead><tr><th scope="col">Page</th>'
        f'<th scope="col">Name</th><th scope="col">Recorded session</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div></article>"
    )
    return _page(
        site,
        title="Commands",
        lede="Every tool in tools/, as a manual page.",
        center="Commands",
        order="Section 1",
        body=body,
        tab="Cmd",
        previous=sequence[-1],
        following=(f"{pages[0].name}(1)", f"/commands/{pages[0].name}/"),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="output directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--release",
        action="store_true",
        help="run the release gate first and print the ratings; needs a clean, pushed HEAD",
    )
    mode.add_argument(
        "--draft", action="store_true", help="allow uncommitted changes; pages are marked draft"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        output = build(args.output, release=args.release, draft=args.draft)
    except BuildError as error:
        print(f"build_site: {error}", file=sys.stderr)
        return 1
    print(f"build_site: wrote the manual to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
