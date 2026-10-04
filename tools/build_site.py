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
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_SOURCE = REPO_ROOT / "site"
DEFAULT_OUTPUT = REPO_ROOT / "_site"
REPOSITORY_URL = "https://github.com/sparklbarff/sysops_pub"
OUTPUT_MARKER = "deploy.json"
STATIC_FILES = ("styles.css", "theme.js", "favicon.svg", "vercel.json", "robots.txt")
STATIC_DIRECTORIES = ("fonts",)
MAN_WIDTH = 76


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

    @property
    def href(self) -> str:
        return f"/{self.slug}/"


CHAPTERS = (
    Chapter("1", "SOP-100", "docs/ARCHITECTURE.md", "architecture"),
    Chapter("2", "SOP-110", "docs/QUICKSTART.md", "quickstart"),
    Chapter("3", "SOP-120", "docs/ADAPTATION_GUIDE.md", "adaptation"),
    Chapter("4", "SOP-130", "docs/CAPABILITY_MATRIX.md", "capability-matrix"),
    Chapter("5", "SOP-200", "docs/SECURITY_BOUNDARY.md", "security-boundary"),
    Chapter("6", "SOP-210", "docs/EXPORT_MANIFEST.md", "export-manifest"),
    Chapter("7", "SOP-220", "docs/PARITY.md", "parity"),
    Chapter("8", "SOP-300", "docs/MACOS_OPTIONAL.md", "macos"),
)
APPENDICES = (
    Chapter("A", "SOP-900", "CHANGELOG.md", "revisions"),
    Chapter("B", "SOP-910", "LICENSE", "license"),
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
        return ManPage(name, summary, PARSERLESS[name], paragraphs, [], [], [])
    parser.prog = f"python3 tools/{name}.py"
    previous = os.environ.get("COLUMNS")
    os.environ["COLUMNS"] = str(MAN_WIDTH)
    try:
        usage = parser.format_usage()
    finally:
        if previous is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = previous
    synopsis = re.sub(r"^usage: ", "", usage.rstrip())
    synopsis = re.sub(r"\n {7}", "\n", synopsis)
    options, arguments, commands = _describe(parser)
    return ManPage(name, summary, synopsis, paragraphs, options, arguments, commands)


def render_man(page: ManPage, examples: list[str], see_also: list[tuple[str, str]]) -> str:
    def entries(rows: list[tuple[str, str]]) -> str:
        return "".join(
            f"<dt>{html.escape(flag)}</dt><dd>{html.escape(text) or '&#8203;'}</dd>"
            for flag, text in rows
        )

    blocks = [
        ("NAME", f"<p><b>{page.name}</b> — {html.escape(page.summary)}</p>"),
        ("SYNOPSIS", f"<pre>{html.escape(page.synopsis)}</pre>"),
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
# Page assembly


@dataclass(frozen=True)
class Site:
    commit: Commit
    version: str
    paths: frozenset[str]
    gate: dict[str, bool] | None
    template: Template


def _plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def _description(text: str, limit: int = 158) -> str:
    plain = LINK.sub(r"\1", re.sub(r"[`*]", "", text))
    return plain if len(plain) <= limit else plain[:limit].rsplit(" ", 1)[0] + "…"


def _page(
    site: Site,
    *,
    title: str,
    lede: str,
    center: str,
    order: str,
    body: str,
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
        page_title=html.escape(f"{title} · sysops_pub reference manual"),
        description=html.escape(_description(lede)),
        body_class="front" if front else "inner",
        center=html.escape(center),
        order=html.escape(order),
        version=html.escape(site.version),
        date=site.commit.date,
        body=body,
        prev=nav(previous, "prev"),
        next=nav(following, "next"),
        commit=site.commit.short,
        draft="" if site.commit.clean else '<p class="draft">Draft · uncommitted changes</p>',
        repository_url=REPOSITORY_URL,
    )


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


def render_home(site: Site, contents: list[tuple[str, str, str, str]], pages: list[ManPage]) -> str:
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
        f'<div class="ds-contents"><h2 class="label">Contents</h2><ol class="toc">{toc}</ol></div>'
        f'<div class="ds-typical"><h2 class="label">Typical application</h2>{quick.body}</div>'
        f'<div class="ds-commands"><h2 class="label">Commands</h2><ul class="cmdlist">{commands}'
        "</ul></div></section>"
        f'<section class="overview">{remainder.body}</section>'
    )
    page = _page(
        site,
        title="Overview",
        lede=intro.lede,
        center=f"Rev {site.version} · {site.commit.date}",
        order="Order no. SOP-000",
        body=body,
        following=(contents[0][1], contents[0][2]),
        front=True,
    )
    return page, context.commands


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
        previous=previous,
        following=following,
    )
    return page, context.commands


def render_404(site: Site) -> str:
    body = (
        '<article class="chapter"><p class="kicker">Not found</p><h1>No such page</h1>'
        "<p>There is no page at this address in the sysops_pub reference manual.</p>"
        '<p><a href="/">Return to the contents</a></p></article>'
    )
    return _page(
        site,
        title="Not found",
        lede="There is no page at this address.",
        center="Not found",
        order="SOP-404",
        body=body,
    )


# --------------------------------------------------------------------------------------------
# Release gate


def run_gate(commit: Commit) -> dict[str, bool]:
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
    return parse_gate(output)


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
    gate = run_gate(commit) if release else None
    revisions = parse_revisions((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    site = Site(
        commit=commit,
        version=revisions[0].version,
        paths=tracked_paths(),
        gate=gate,
        template=Template((SITE_SOURCE / "page.html").read_text(encoding="utf-8")),
    )

    pages = [man_page(name) for name in COMMANDS]
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
        _write(staging, "commands/index.html", render_command_index(site, pages, sequence))
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
                    previous=previous,
                    following=following,
                ),
            )
        _write(staging, "404.html", render_404(site))
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


def render_command_index(site: Site, pages: list[ManPage], sequence) -> str:
    rows = "".join(
        f'<tr><td><a class="mono" href="/commands/{page.name}/">{page.name}(1)</a></td>'
        f"<td>{html.escape(page.summary)}</td></tr>"
        for page in pages
    )
    body = (
        '<article class="chapter"><p class="kicker">Commands</p><h1>Commands</h1>'
        "<p>Every tool in <code>tools/</code>, as a manual page generated from its own argument "
        "parser and docstring.</p>"
        '<div class="table"><table><thead><tr><th scope="col">Page</th>'
        f'<th scope="col">Name</th></tr></thead><tbody>{rows}</tbody></table></div></article>'
    )
    return _page(
        site,
        title="Commands",
        lede="Every tool in tools/, as a manual page.",
        center="Commands",
        order="Section 1",
        body=body,
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
