from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PolicyExampleTests(unittest.TestCase):
    def test_both_claude_settings_deny_artifact(self) -> None:
        examples = ROOT / "examples" / "claude-code"
        for name in ("settings.posix.json.example", "settings.windows.json.example"):
            with self.subTest(name=name):
                settings = json.loads((examples / name).read_text(encoding="utf-8"))
                self.assertEqual(settings["permissions"]["deny"], ["Artifact"])

    def test_both_agent_policies_cover_publication_copying_and_working_hours(self) -> None:
        paths = (
            ROOT / "examples" / "claude-code" / "CLAUDE.md.example",
            ROOT / "examples" / "codex" / "AGENTS.md.example",
        )
        for path in paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("Never publish", text)
                self.assertIn("fenced code block", text)
                self.assertIn("working hours", text)

    def test_codex_policy_has_default_mode_input_fallback(self) -> None:
        text = (ROOT / "examples" / "codex" / "AGENTS.md.example").read_text(encoding="utf-8")
        self.assertIn("structured input tool is unavailable", text)
        self.assertIn("ask one concise conversational", text)
        self.assertIn("question only when", text)
        self.assertIn("Do not enable undocumented feature flags", text)

    def test_both_policies_preserve_cross_runtime_evidence_and_readable_commands(self) -> None:
        paths = (
            ROOT / "examples" / "claude-code" / "CLAUDE.md.example",
            ROOT / "examples" / "codex" / "AGENTS.md.example",
        )
        for path in paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("runtime", text)
                self.assertIn("approval", text)
                self.assertIn("unlabelled", text)

    def test_codex_preferences_reduce_reasoning_output_and_disable_analytics(self) -> None:
        path = ROOT / "examples" / "codex" / "config.toml.example"
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertIs(config["hide_agent_reasoning"], True)
        self.assertIs(config["analytics"]["enabled"], False)

    def test_playwright_guidance_pins_browser_and_uses_mcp_installer(self) -> None:
        text = (ROOT / "examples" / "claude-code" / "PLAYWRIGHT.md.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("install-browser firefox", text)
        self.assertIn("--browser firefox", text)
        self.assertIn("not an installed daily browser", text)
        self.assertNotIn("npx playwright install firefox", text)


if __name__ == "__main__":
    unittest.main()
