from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "enforcement"))

import grounding_classifier


class GroundingClassifierTests(unittest.TestCase):
    def test_broad_prompts_are_flagged_for_grounding(self) -> None:
        for prompt in (
            "Give me a current-state overview of this project.",
            "Orient me in this codebase from the ground up.",
            "Reconcile the planning docs across the repository.",
            "Has this feature already shipped?",
        ):
            required, _reason = grounding_classifier.classify(prompt)
            self.assertTrue(required, prompt)

    def test_narrow_prompts_stay_silent(self) -> None:
        for prompt in (
            "Fix the failing test in tests/test_scheduler.py.",
            "Rename this function and run the focused suite.",
            "Bump the client timeout to 180 seconds.",
            "",
        ):
            required, _reason = grounding_classifier.classify(prompt)
            self.assertFalse(required, prompt)

    def test_cross_cutting_keys_on_scope_noun_not_the_preposition(self) -> None:
        # Narrow work phrased "across <small scope>" must stay silent; the scope noun is the signal.
        quiet, _ = grounding_classifier.classify("Compare the output across the two test runs.")
        self.assertFalse(quiet)
        loud, _ = grounding_classifier.classify("Compare the test coverage across the codebase.")
        self.assertTrue(loud)

    def test_claude_hook_injects_context_for_a_broad_prompt(self) -> None:
        script = ROOT / "examples" / "enforcement" / "grounding_classifier.py"
        result = subprocess.run(
            [sys.executable, str(script), "--hook", "claude"],
            input=json.dumps({"prompt": "Give me a current-state overview of the project."}),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("grounding", payload["hookSpecificOutput"]["additionalContext"].lower())

    def test_claude_hook_fails_open_on_invalid_input(self) -> None:
        # An advisory control must never halt a prompt: malformed stdin exits 0 and injects nothing.
        script = ROOT / "examples" / "enforcement" / "grounding_classifier.py"
        result = subprocess.run(
            [sys.executable, str(script), "--hook", "claude"],
            input="this is not json",
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
