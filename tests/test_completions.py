"""Drift guard: the shell completions must list the same commands as the parser.

build_parser() is the single source of truth for the command set (main derives its
implicit-search list from it too). The three completion scripts hand-maintain a copy;
this fails the moment one drifts, so "added a command but forgot a completion" can't merge.
"""

import re
import unittest
from pathlib import Path

from grimoireshim import grimoire

BASE = Path(__file__).resolve().parent.parent / "base"


def _canonical() -> set[str]:
	_, commands = grimoire.build_parser()
	return set(commands)


def _match_words(text: str, pattern: str) -> set[str] | None:
	# A single capture group holding a space-separated command list (fish/bash).
	m = re.search(pattern, text)
	return set(m.group(1).split()) if m else None


class CompletionCommandDriftTests(unittest.TestCase):
	def test_fish_commands_match_parser(self) -> None:
		text = (BASE / "grimoire.fish").read_text()
		self.assertEqual(
			_match_words(text, r"(?m)^set -l commands (.+)$"), _canonical()
		)

	def test_bash_commands_match_parser(self) -> None:
		text = (BASE / "grimoire-completion.bash").read_text()
		self.assertEqual(_match_words(text, r'subcmds="([^"]+)"'), _canonical())

	def test_zsh_commands_match_parser(self) -> None:
		# zsh lists 'cmd:description' entries inside a commands=( ... ) array. Anchor the
		# closing paren at line start: a description may itself contain "(...)".
		text = (BASE / "_grimoire.zsh").read_text()
		block = re.search(r"commands=\((.*?)\n\s*\)", text, re.DOTALL)
		found = set(re.findall(r"'([a-z][a-z-]*):", block.group(1))) if block else None
		self.assertEqual(found, _canonical())


if __name__ == "__main__":
	unittest.main()
