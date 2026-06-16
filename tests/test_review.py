"""The PKGBUILD review gate before an AUR build.

_review_pkgbuild shows the whole PKGBUILD on a fresh install and only the git
diff since the installed version on an update (diff_base set), then lets the user
proceed or abort. These tests drive it through mocked prompts and observe which
view path runs, without touching git or a pager.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire


class ReviewPkgbuildTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.dir = Path(tmp.name)
		(self.dir / "PKGBUILD").write_text("pkgname=foo\npkgver=1\n")

	def _patch(self, *, answers: list[bool], head: str | None = "newsha") -> None:
		# Patch the gate's collaborators: prompt answers feed [review?, proceed?];
		# _local_head fakes the current commit; run_command / _page_file are observed.
		self.prompt = mock.patch.object(
			grimoire, "prompt_confirm", side_effect=answers
		).start()
		self.head = mock.patch.object(
			grimoire, "_local_head", return_value=head
		).start()
		self.git = mock.patch.object(grimoire, "run_command").start()
		self.page = mock.patch.object(grimoire, "_page_file").start()
		self.addCleanup(mock.patch.stopall)

	def test_no_pkgbuild_is_noop(self) -> None:
		# Nothing to review without a PKGBUILD -> never prompts, never views.
		(self.dir / "PKGBUILD").unlink()
		self._patch(answers=[])
		grimoire._review_pkgbuild(self.dir, "foo")
		self.prompt.assert_not_called()
		self.git.assert_not_called()
		self.page.assert_not_called()

	def test_decline_review_skips_view_and_builds(self) -> None:
		# Declining the review proceeds to build (no raise) without showing anything.
		self._patch(answers=[False])
		grimoire._review_pkgbuild(self.dir, "foo")
		self.git.assert_not_called()
		self.page.assert_not_called()

	def test_fresh_install_dumps_full_pkgbuild(self) -> None:
		# No diff_base -> whole PKGBUILD via the pager, not a git diff.
		self._patch(answers=[True, True])
		grimoire._review_pkgbuild(self.dir, "foo", None)
		self.page.assert_called_once_with(self.dir / "PKGBUILD")
		self.git.assert_not_called()

	def test_update_shows_diff_since_installed(self) -> None:
		# diff_base != head -> git diff base..head, paged by git itself; no full dump.
		self._patch(answers=[True, True], head="newsha")
		grimoire._review_pkgbuild(self.dir, "foo", "oldsha")
		self.page.assert_not_called()
		self.git.assert_called_once()
		args, kwargs = self.git.call_args
		self.assertEqual(
			args[0],
			["git", "-C", str(self.dir), "diff", "oldsha..newsha"],
		)
		self.assertFalse(kwargs["check"])

	def test_base_equal_head_falls_back_to_dump(self) -> None:
		# A rebuild at the same commit has no diff -> full PKGBUILD, not an empty diff.
		self._patch(answers=[True, True], head="samesha")
		grimoire._review_pkgbuild(self.dir, "foo", "samesha")
		self.page.assert_called_once()
		self.git.assert_not_called()

	def test_abort_after_review_raises(self) -> None:
		# Reviewing then declining to proceed aborts the install.
		self._patch(answers=[True, False])
		with self.assertRaises(grimoire.GrimoireErr):
			grimoire._review_pkgbuild(self.dir, "foo", "oldsha")


if __name__ == "__main__":
	unittest.main()
