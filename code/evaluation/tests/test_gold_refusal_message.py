"""T96 (1): the holdout refusal no longer prints the phrase it wants. No file is opened here."""
from __future__ import annotations

import unittest
from pathlib import Path

from evaluation.gold import UNLOCK_PHRASE, HoldoutLockedError, check_unlock, load_gold

NEVER = Path("/nonexistent/never-opened.csv")


def _norm(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalpha())


class TestRefusalMessage(unittest.TestCase):
    def messages(self) -> list[str]:
        out = []
        for phrase in (None, "", "yes", UNLOCK_PHRASE.lower(), UNLOCK_PHRASE + " "):
            with self.assertRaises(HoldoutLockedError) as cm:
                load_gold(NEVER, holdout=True, unlock_phrase=phrase)
            out.append(str(cm.exception))
            with self.assertRaises(HoldoutLockedError) as cm:
                check_unlock(True, phrase, "engine run", "r")
            out.append(str(cm.exception))
        return out

    def test_refusal_text_does_not_contain_the_phrase(self) -> None:
        for msg in self.messages():
            self.assertNotIn(UNLOCK_PHRASE, msg)
            self.assertNotIn(_norm(UNLOCK_PHRASE), _norm(msg))  # not in any case or spacing either

    def test_refusal_still_says_what_is_needed(self) -> None:
        for msg in self.messages():
            self.assertIn("locked", msg)
            self.assertIn("developer", msg)


if __name__ == "__main__":
    unittest.main()
