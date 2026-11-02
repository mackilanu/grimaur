"""AUR pkgname -> pkgbase without per-package requests: the local db (free), then
the cached packages-meta index (the AUR's own name -> base list, same download as
search). Git -- which maps base -> names but never name -> base -- is only the
offline fallback, and there a branch must actually build the name."""

import fnmatch
import io
import json
import unittest
from unittest import mock

from grimoireshim import grimoire

SHA = "0" * 40


class _MirrorFixture(unittest.TestCase):
	index: dict[str, str] | None = None

	def setUp(self) -> None:
		for fn in (
			grimoire._aur_pkgbase,
			grimoire._aur_branch_exists,
			grimoire._aur_branch_builds,
			grimoire.resolve_aur_dependency,
			grimoire.package_provides,
		):
			fn.cache_clear()
		self.branches: set[str] = set()
		self.local: dict[str, str] = {}
		self.lsremote_calls: list[list[str]] = []
		self.fetched: list[str] = []
		self.srcinfo: dict[str, str] = {}

		def fake_run(cmd: list[str], **_: object) -> str:
			if cmd[:3] != ["git", "ls-remote", "--heads"]:
				raise AssertionError(cmd)
			patterns = cmd[4:]
			self.lsremote_calls.append(patterns)
			refs = [f"refs/heads/{b}" for b in sorted(self.branches)]
			# git ls-remote matches a pattern against the ref's tail.
			hits = [
				r
				for r in refs
				if not patterns
				or any(
					fnmatch.fnmatchcase(r, p) or fnmatch.fnmatchcase(r, f"*/{p}")
					for p in patterns
				)
			]
			return "".join(f"{SHA}\t{r}\n" for r in hits)

		def fake_fetch(branch: str, path: str) -> str | None:
			self.fetched.append(branch)
			return self.srcinfo.get(branch)

		for name, value in (
			("run_command", fake_run),
			("_aur_index", lambda: self.index),
			("_local_db_pkgbase", self.local.get),
			("fetch_git_file", fake_fetch),
			(
				"_aur_mirror_lsremote_cmd",
				lambda *p: ["git", "ls-remote", "--heads", "M", *p],
			),
		):
			patcher = mock.patch.object(grimoire, name, value)
			patcher.start()
			self.addCleanup(patcher.stop)

	def _branch(self, base: str, *names: str) -> None:
		self.branches.add(base)
		self.srcinfo[base] = f"pkgbase = {base}\n" + "".join(
			f"\npkgname = {n}\n" for n in names or (base,)
		)


class IndexedTests(_MirrorFixture):
	def setUp(self) -> None:
		super().setUp()
		# real AUR shapes: pidgin is split from pidgin-gtkui while branch `pidgin`
		# builds libpurple/finch; `gone` is a deleted package whose branch lingers.
		self.index = {
			"yay": "yay",
			"fontobene-qt-qt6": "fontobene-qt",
			"pidgin": "pidgin-gtkui",
			"libpurple": "pidgin",
			"libfoo-git": "libfoo-git",
		}
		self._branch("gone")

	def test_index_resolves_bases_with_no_network(self) -> None:
		self.assertEqual(grimoire._aur_pkgbase("yay"), "yay")
		self.assertEqual(grimoire._aur_pkgbase("fontobene-qt-qt6"), "fontobene-qt")
		self.assertEqual(grimoire._aur_pkgbase("pidgin"), "pidgin-gtkui")
		self.assertTrue(grimoire.exists_in_aur_mirror("fontobene-qt-qt6"))
		self.assertEqual((self.lsremote_calls, self.fetched), ([], []))

	def test_stale_branch_is_not_a_package(self) -> None:
		self.assertFalse(grimoire.exists_in_aur_mirror("gone"))

	def test_local_db_wins_for_installed(self) -> None:
		self.local["mine"] = "my-base"
		self.assertEqual(grimoire._aur_pkgbase("mine"), "my-base")

	def test_dependency_guesses_filtered_by_index(self) -> None:
		self._branch("libfoo-git")
		self.srcinfo["libfoo-git"] += "\tprovides = libfoo\n"
		self.assertEqual(grimoire.resolve_aur_dependency("libfoo"), "libfoo-git")
		self.assertEqual(self.fetched, ["libfoo-git"])  # no fetch for absent guesses
		self.assertEqual(self.lsremote_calls, [])


class OfflineTests(_MirrorFixture):
	index = None  # packages-meta unreachable

	def test_non_split_confirmed_by_branch(self) -> None:
		self._branch("foo")
		self.assertTrue(grimoire.exists_in_aur_mirror("foo"))
		self.assertEqual(grimoire._aur_pkgbase("foo"), "foo")

	def test_branch_that_builds_other_pkgs_is_rejected(self) -> None:
		self._branch("pidgin", "libpurple", "finch")
		self.assertFalse(grimoire.exists_in_aur_mirror("pidgin"))

	def test_installed_split_uses_local_base_branch(self) -> None:
		self._branch("fontobene-qt", "fontobene-qt-qt5", "fontobene-qt-qt6")
		self.local["fontobene-qt-qt6"] = "fontobene-qt"
		self.assertTrue(grimoire.exists_in_aur_mirror("fontobene-qt-qt6"))

	def test_dependency_guesses_batched_in_one_lsremote(self) -> None:
		self._branch("libfoo-git")
		self.srcinfo["libfoo-git"] += "\tprovides = libfoo\n"
		self.assertEqual(grimoire.resolve_aur_dependency("libfoo"), "libfoo-git")
		self.assertEqual(self.fetched, ["libfoo-git"])
		# the dep's own lookup + every guess in one call
		self.assertEqual(len(self.lsremote_calls), 2)


class IndexParsingTests(unittest.TestCase):
	def test_dump_yields_rows_and_bases(self) -> None:
		import gzip

		dump = [
			{"Name": "a", "PackageBase": "a", "Version": "1-1", "Description": "d"},
			{"Name": "a-qt6", "PackageBase": "a", "Version": "1-1"},
			{"Name": 5},
		]
		body = gzip.compress(json.dumps(dump).encode())
		resp = mock.MagicMock()
		resp.__enter__.return_value = io.BytesIO(body)
		with mock.patch("urllib.request.urlopen", return_value=resp):
			meta = grimoire._download_aur_meta()
		self.assertIsNotNone(meta)
		rows, index = meta or ([], {})
		self.assertEqual(rows, [("a", "1-1", "d"), ("a-qt6", "1-1", None)])
		self.assertEqual(index, {"a": "a", "a-qt6": "a"})


if __name__ == "__main__":
	unittest.main()
