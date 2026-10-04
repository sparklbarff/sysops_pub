from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_site

COMMIT = build_site.Commit(
    sha="0123456789abcdef0123456789abcdef01234567", date="2026-10-02", clean=True
)
BODY_TAGS = {
    "a",
    "b",
    "code",
    "defs",
    "desc",
    "div",
    "figcaption",
    "figure",
    "h2",
    "h3",
    "li",
    "marker",
    "ol",
    "p",
    "path",
    "pre",
    "rect",
    "strong",
    "svg",
    "table",
    "tbody",
    "td",
    "text",
    "th",
    "thead",
    "title",
    "tr",
    "ul",
    "span",
}


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def collect(fragment: str) -> Collector:
    collector = Collector()
    collector.feed(fragment)
    collector.close()
    return collector


def tracked(pattern: str) -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", pattern], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [line for line in output.splitlines() if line]


def context(chapter: str = "") -> build_site.Context:
    return build_site.Context(commit=COMMIT, paths=build_site.tracked_paths(), chapter=chapter)


class RendererTests(unittest.TestCase):
    def test_angle_brackets_are_escaped_in_prose_code_fences_and_tables(self) -> None:
        source = (
            "# Title <script>\n"
            "\n"
            "Install with `adopt.py --into <project>` & keep <name> literal.\n"
            "\n"
            "```sh\n"
            "run <built-output-dir> && echo <done>\n"
            "```\n"
            "\n"
            "| Left <a> | Right |\n"
            "|---|---|\n"
            "| `x <y>` | a & b |\n"
        )
        document = build_site.render_markdown(source, context())
        collector = collect(document.title + document.body)
        self.assertNotIn("script", collector.tags)
        self.assertLessEqual(set(collector.tags), BODY_TAGS)
        text = "".join(collector.text)
        for literal in ("<project>", "<name>", "<built-output-dir>", "<done>", "<a>", "<y>"):
            self.assertIn(literal, text)
        self.assertIn("&amp;&amp;", document.body)

    def test_fence_contents_are_verbatim(self) -> None:
        source = "# T\n\n```text\npython3 tools/demo.py      # tour **not bold** `x`\n```\n"
        document = build_site.render_markdown(source, context())
        self.assertIn("python3 tools/demo.py      # tour **not bold** `x`", document.body)
        self.assertNotIn("<strong>", document.body)

    def test_sections_are_numbered_within_their_chapter(self) -> None:
        document = build_site.render_markdown("# T\n\n## One\n\n## Two\n", context("3"))
        self.assertIn('<span class="secno">3.1</span> One', document.body)
        self.assertIn('<span class="secno">3.2</span> Two', document.body)

    def test_links_resolve_to_pages_and_unknown_targets_fail(self) -> None:
        document = build_site.render_markdown(
            "# T\n\nSee [LICENSE](LICENSE) and [arch](docs/ARCHITECTURE.md).\n", context()
        )
        self.assertIn('href="/license/"', document.body)
        self.assertIn('href="/architecture/"', document.body)
        with self.assertRaises(build_site.BuildError):
            build_site.render_markdown("# T\n\n[gone](docs/MISSING.md)\n", context())

    def test_code_paths_link_to_pages_manuals_or_source_at_the_commit(self) -> None:
        ctx = context()
        document = build_site.render_markdown(
            "# T\n\n`docs/QUICKSTART.md`, `tools/adopt.py`, `registry/components.json`, "
            "`tools/missing.py`.\n",
            ctx,
        )
        self.assertIn('<a class="xref" href="/quickstart/">', document.body)
        self.assertIn('<a class="xref" href="/commands/adopt/">', document.body)
        url = f"{build_site.REPOSITORY_URL}/blob/{COMMIT.sha}/registry/components.json"
        self.assertIn(url, document.body)
        self.assertIn("<code>tools/missing.py</code>", document.body)
        self.assertIn("adopt", ctx.commands)

    def test_changed_or_unknown_diagram_text_fails_the_build(self) -> None:
        with self.assertRaises(build_site.BuildError):
            build_site.render_markdown("# T\n\n```text\nstart\n  |\n  v\nend\n```\n", context())

    def test_table_rows_must_match_the_header(self) -> None:
        with self.assertRaises(build_site.BuildError):
            build_site.render_markdown("# T\n\n| a | b |\n|---|---|\n| only |\n", context())


class CorpusTests(unittest.TestCase):
    """Render the real tracked documents and tools, not synthetic samples."""

    def test_every_tracked_document_is_a_chapter_or_deliberately_excluded(self) -> None:
        sources = {page.source for page in build_site.ALL_PAGES}
        for path in tracked("docs/*.md") + tracked("docs/case-studies/*.md"):
            self.assertIn(path, sources | set(build_site.EXCLUDED_SOURCES))
        self.assertFalse(sources & set(build_site.EXCLUDED_SOURCES))
        for path in sources:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_every_tool_has_a_manual_page(self) -> None:
        tools = {path.stem for path in (ROOT / "tools").glob("*.py")}
        self.assertEqual(tools, set(build_site.COMMANDS))

    def test_real_chapters_render_only_known_tags_and_no_leaked_markdown(self) -> None:
        for chapter in build_site.CHAPTERS + build_site.APPENDICES[:1]:
            with self.subTest(source=chapter.source):
                text = (ROOT / chapter.source).read_text(encoding="utf-8")
                document = build_site.render_markdown(text, context(chapter.number))
                collector = collect(document.body)
                self.assertLessEqual(set(collector.tags), BODY_TAGS)
                rendered = "".join(collector.text)
                self.assertNotIn("**", rendered)
                self.assertNotRegex(rendered, r"\]\([^)]+\)")
                self.assertNotIn("style", [name for name, _ in collector.attributes])

    def test_real_fences_and_tables_survive(self) -> None:
        quickstart = (ROOT / "docs/QUICKSTART.md").read_text(encoding="utf-8")
        body = build_site.render_markdown(quickstart, context("2")).body
        fences = len(re.findall(r"^```\S", quickstart, re.MULTILINE))
        self.assertEqual(body.count('class="panel"'), fences)
        matrix = (ROOT / "docs/CAPABILITY_MATRIX.md").read_text(encoding="utf-8")
        rows = [line for line in matrix.splitlines() if line.startswith("|")]
        body = build_site.render_markdown(matrix, context("4")).body
        self.assertEqual(body.count("<tr>"), len(rows) - 1)

    def test_both_diagrams_are_redrawn(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn('class="fig"', build_site.render_markdown(readme, context()).body)
        body = build_site.render_markdown(architecture, context("1")).body
        self.assertIn("Figure 1-1.", body)

    def test_manual_pages_come_from_the_real_parsers(self) -> None:
        for name in build_site.COMMANDS:
            with self.subTest(tool=name):
                page = build_site.man_page(name)
                self.assertTrue(page.summary)
                if name in build_site.PARSERLESS:
                    self.assertEqual(page.synopsis, build_site.PARSERLESS[name])
                else:
                    self.assertTrue(page.synopsis.startswith(f"python3 tools/{name}.py"))
        adopt = build_site.man_page("adopt")
        flags = [flag for flag, _ in adopt.options]
        self.assertIn("--into INTO", flags)
        self.assertIn("--execute", flags)
        control = build_site.man_page("control")
        self.assertEqual(
            [command for command, _, _ in control.commands],
            ["init", "plan", "apply", "verify", "report"],
        )


class RevisionAndGateTests(unittest.TestCase):
    PASSING = (
        "PASS: candidate identity (abc)\n"
        "PASS: mandatory local pre-push gate is wired\n"
        "PASS: dependency-free suite\n"
        "PASS: case exercises\n"
        "PASS: configuration syntax (12 JSON, 3 TOML)\n"
        "PASS: no untracked files\n"
        "PASS: black\n"
        "PASS: ruff\n"
        "PASS: gitleaks current tree\n"
        "PASS: gitleaks Git history\n"
        "PASS: shellcheck\n"
    )

    def test_changelog_parses_newest_first(self) -> None:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        revisions = build_site.parse_revisions(text)
        newest = re.search(r"^## (\S+)", text, re.MULTILINE)
        assert newest is not None
        self.assertEqual(revisions[0].version, newest.group(1))
        with self.assertRaises(build_site.BuildError):
            build_site.parse_revisions("# Changelog\n\n## next\n\n- x\n")

    def test_every_gate_label_needs_its_own_pass_line(self) -> None:
        gate = build_site.parse_gate(self.PASSING)
        self.assertEqual(set(gate), set(build_site.GATE_LABELS))
        with self.assertRaises(build_site.BuildError):
            build_site.parse_gate(self.PASSING.replace("PASS: ruff\n", ""))

    def test_ratings_print_values_only_when_the_gate_passed(self) -> None:
        template = build_site.Template("")
        unchecked = build_site.Site(COMMIT, "0.7.0", frozenset(), None, template)
        self.assertNotIn("<td class='max'>0</td>", build_site.render_ratings(unchecked))
        self.assertIn("Not checked for this build", build_site.render_ratings(unchecked))
        gate = build_site.parse_gate(self.PASSING)
        checked = build_site.Site(COMMIT, "0.7.0", frozenset(), gate, template)
        rendered = build_site.render_ratings(checked)
        self.assertEqual(rendered.count("<td class='max'>0</td>"), len(build_site.RATINGS))


class IdentityTests(unittest.TestCase):
    def test_part_number_and_date_code(self) -> None:
        self.assertEqual(build_site.part_number("0.8.0"), "SOP-0800")
        self.assertEqual(build_site.part_number("0.6.3"), "SOP-0603")
        self.assertEqual(build_site.date_code("2026-10-03"), "2640")
        self.assertEqual(build_site.date_code("2027-01-01"), "2653")

    def test_bit_field_decodes_back_to_the_commit(self) -> None:
        rows = build_site.bit_rows(COMMIT.sha)
        self.assertEqual(len(rows), 4)
        decoded = "".join(
            format(int("".join(row[column] for row in rows), 2), "x")
            for column in range(len(COMMIT.sha))
        )
        self.assertEqual(decoded, COMMIT.sha)

    def test_pinout_has_every_page_and_command_once(self) -> None:
        left, right = build_site.pin_map()
        self.assertEqual((len(left), len(right)), (16, 16))
        hrefs = [href for _, href in left + right if href]
        self.assertEqual(len(hrefs), len(set(hrefs)))
        for chapter in build_site.ALL_PAGES:
            self.assertIn(chapter.href, hrefs)
        for name in build_site.COMMANDS:
            self.assertIn(f"/commands/{name}/", hrefs)
        self.assertEqual((left[-1][0], right[-1][0]), ("GND", "VCC"))

    def test_errata_are_read_from_the_parsers(self) -> None:
        pages = [build_site.man_page(name) for name in build_site.COMMANDS]
        found = build_site.errata(pages)
        for page in pages:
            for flag, text in page.options:
                self.assertEqual((page.name, flag) in found, not text)


class SessionTests(unittest.TestCase):
    """The recorded sessions are real runs in a fresh clone, and publish no host paths."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sessions = build_site.record_sessions(build_site.read_commit())

    def test_every_session_ran_every_step(self) -> None:
        self.assertEqual(set(self.sessions), set(build_site.SESSIONS))
        for name, steps in build_site.SESSIONS.items():
            exchanges = self.sessions[name]
            self.assertEqual([e.command for e in exchanges], [s.command for s in steps])
            for exchange, step in zip(exchanges, steps, strict=True):
                self.assertIn(exchange.status, step.expect)

    def test_sessions_show_the_contracts_they_demonstrate(self) -> None:
        control = "\n".join(e.output for e in self.sessions["control"])
        self.assertIn("dry-run only: pass --execute to write", control)
        self.assertIn("summary: match=2", control)
        adopt = self.sessions["adopt"][-1].output
        self.assertIn("UNCHANGED .claude/settings.json", adopt)
        self.assertEqual(self.sessions["bootstrap"][0].status, 2)

    def test_no_host_path_is_published(self) -> None:
        text = "\n".join(e.output for exchanges in self.sessions.values() for e in exchanges)
        for fragment in (str(ROOT), str(Path.home()), "/var/folders", "/private/"):
            self.assertNotIn(fragment, text)
        self.assertIn("/tmp/session", text)

    def test_gate_excerpt_keeps_only_this_commits_verdicts(self) -> None:
        output = (
            "PASS: candidate identity (abc)\ncheck: black\nPASS: candidate identity (abc123)\n"
            "PASS: black\nrelease verification: pass\n"
        )
        excerpt = build_site.gate_session(output, "abc")[0].output.splitlines()
        self.assertEqual(
            excerpt,
            ["PASS: candidate identity (abc)", "PASS: black", "release verification: pass"],
        )

    def test_sanitize_replaces_the_longest_root_first(self) -> None:
        text = build_site._sanitize("/private/x/y and /x/y", ["/x/y", "/private/x/y"])
        self.assertEqual(text, "/tmp/session and /tmp/session")


class BuildTests(unittest.TestCase):
    def test_output_target_refuses_the_repository_and_unrelated_directories(self) -> None:
        with self.assertRaises(build_site.BuildError):
            build_site._check_output_target(ROOT)
        with tempfile.TemporaryDirectory(prefix="site-target-") as directory:
            (Path(directory) / "keep.txt").write_text("not a site\n", encoding="utf-8")
            with self.assertRaises(build_site.BuildError):
                build_site._check_output_target(Path(directory))

    def test_draft_build_is_complete_self_consistent_and_free_of_inline_styles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="site-build-") as directory:
            output = Path(directory) / "out"
            build_site.build(output, release=False, draft=True)
            stamp = json.loads((output / "deploy.json").read_text(encoding="utf-8"))
            self.assertEqual(stamp["release_gate"], "not run")
            self.assertEqual(len(stamp["commit"]), 40)
            pages = sorted(output.rglob("*.html"))
            expected = 1 + len(build_site.ALL_PAGES) + 1 + len(build_site.COMMANDS) + 2
            self.assertEqual(len(pages), expected)
            for page in pages:
                html = page.read_text(encoding="utf-8")
                collector = collect(html)
                names = [name for name, _ in collector.attributes]
                self.assertNotIn("style", names, page)
                self.assertNotIn("style", collector.tags, page)
                self.assertEqual(
                    [src for name, src in collector.attributes if name == "src"],
                    ["/theme.js", "/eggs.js"],
                )
                ids = [value for name, value in collector.attributes if name == "id"]
                self.assertEqual(len(ids), len(set(ids)), page)
                self.assertIsNone(re.search(r"\$[a-z_]+", re.sub(r"<pre.*?</pre>", "", html)))
                for name, href in collector.attributes:
                    if name == "href" and href and href.startswith("/"):
                        href = href.split("#", 1)[0]
                        target = output / href.lstrip("/")
                        if href.endswith("/"):
                            target = target / "index.html"
                        self.assertTrue(target.is_file(), f"{page}: broken link {href}")
            for name in ("404.html", "errata/index.html", "styles.css", "theme.js", "eggs.js"):
                self.assertTrue((output / name).is_file(), name)
            build_site.build(output, release=False, draft=True)
            self.assertTrue((output / "deploy.json").is_file())


if __name__ == "__main__":
    unittest.main()
