from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _parsers() -> Iterator[tuple[str, argparse.ArgumentParser]]:
    """Every tool that builds an argument parser, loaded without running it."""
    sys.path.insert(0, str(TOOLS))
    try:
        for path in sorted(TOOLS.glob("*.py")):
            if "def _build_parser(" not in path.read_text(encoding="utf-8"):
                continue
            spec = importlib.util.spec_from_file_location(f"_help_{path.stem}", path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            try:
                spec.loader.exec_module(module)
                yield path.stem, module._build_parser()
            finally:
                sys.modules.pop(spec.name, None)
    finally:
        sys.path.remove(str(TOOLS))


def _undocumented(parser: argparse.ArgumentParser, prefix: str) -> Iterator[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {choice.dest: choice.help for choice in action._choices_actions}
            for name, subparser in action.choices.items():
                if not helps.get(name):
                    yield f"{prefix} {name}"
                yield from _undocumented(subparser, f"{prefix} {name}")
        elif not action.help:
            yield f"{prefix} {'/'.join(action.option_strings) or action.dest}"


class ParserHelpTests(unittest.TestCase):
    """Manual pages are generated from these parsers, so a blank help is a blank manual entry."""

    def test_every_option_argument_and_subcommand_has_help(self) -> None:
        parsers = list(_parsers())
        self.assertGreaterEqual(len(parsers), 8)
        for name, parser in parsers:
            with self.subTest(tool=name):
                self.assertEqual(list(_undocumented(parser, name)), [])


if __name__ == "__main__":
    unittest.main()
