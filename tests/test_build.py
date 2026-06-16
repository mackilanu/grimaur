"""`build` locates the PKGBUILD in a fetched clone across every repos.ini layout.

build runs after fetch, so it sees a clone on disk (treeless: only the target
package's subtree is materialised). _find_pkgbuild_dir must map each layout to the
right build dir without knowing the fetch-time --subdir.
"""

import tempfile
import unittest
from pathlib import Path

from grimoireshim import grimoire


class FindPkgbuildDirTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)

	def _pkgbuild(self, *parts: str) -> Path:
		# Create <root>/<parts...>/PKGBUILD and return its containing dir.
		d = self.root.joinpath(*parts)
		d.mkdir(parents=True, exist_ok=True)
		(d / "PKGBUILD").write_text("pkgname=foo\npkgver=1\n")
		return d

	def test_root_pkgbuild(self) -> None:
		# SOLO / branch-per-package / repo-per-package / AUR: PKGBUILD at the root.
		self._pkgbuild()
		self.assertEqual(grimoire._find_pkgbuild_dir(self.root, "foo"), self.root)

	def test_named_subdir(self) -> None:
		# FLAT (one dir per package at the root) / SOLO auto-descend into <pkg>/.
		want = self._pkgbuild("foo")
		self.assertEqual(grimoire._find_pkgbuild_dir(self.root, "foo"), want)

	def test_container_subdir(self) -> None:
		# VUR-style monorepo: <subdir>/<pkg>/PKGBUILD (the apc-git case).
		want = self._pkgbuild("pkgs", "foo")
		self.assertEqual(grimoire._find_pkgbuild_dir(self.root, "foo"), want)

	def test_unnamed_single_subdir(self) -> None:
		# Bare repo + --subdir <dir> where the dir isn't named after the package:
		# the treeless clone holds exactly one PKGBUILD, so it still resolves.
		want = self._pkgbuild("somewhere")
		self.assertEqual(grimoire._find_pkgbuild_dir(self.root, "foo"), want)

	def test_name_match_wins_over_others(self) -> None:
		# Full (non-treeless) checkout with several packages: prefer the named dir.
		self._pkgbuild("pkgs", "bar")
		want = self._pkgbuild("pkgs", "foo")
		self.assertEqual(grimoire._find_pkgbuild_dir(self.root, "foo"), want)

	def test_git_dir_is_ignored(self) -> None:
		# A PKGBUILD that happens to live under .git must never be picked.
		(self.root / ".git").mkdir()
		(self.root / ".git" / "PKGBUILD").write_text("x")
		self.assertIsNone(grimoire._find_pkgbuild_dir(self.root, "foo"))

	def test_missing_returns_none(self) -> None:
		self.assertIsNone(grimoire._find_pkgbuild_dir(self.root, "foo"))


if __name__ == "__main__":
	unittest.main()
