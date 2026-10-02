from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "macos"))

import iterm_agent_status


class ItermAgentStatusTests(unittest.TestCase):
    def test_label_uses_only_the_final_sanitized_component(self) -> None:
        self.assertEqual(
            iterm_agent_status.sanitize_label("/private/location/Example Project"),
            "Example_Project",
        )
        self.assertEqual(
            iterm_agent_status.sanitize_label(r"C:\private\Example Project"),
            "Example_Project",
        )

    def test_status_has_only_label_and_declared_state(self) -> None:
        value = iterm_agent_status.status_text("/private/location/demo", "working")
        self.assertEqual(value, "demo | Working")
        self.assertNotIn("private", value)

    def test_escape_sequence_contains_decodable_iterm_user_variable(self) -> None:
        sequence = iterm_agent_status.escape_sequence("demo", "waiting")
        prefix = "\033]1337;SetUserVar=agent_status="
        self.assertTrue(sequence.startswith(prefix))
        self.assertTrue(sequence.endswith("\a"))
        encoded = sequence[len(prefix) : -1]
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), "demo | Waiting")

    def test_unknown_state_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            iterm_agent_status.status_text("demo", "lost")


if __name__ == "__main__":
    unittest.main()
