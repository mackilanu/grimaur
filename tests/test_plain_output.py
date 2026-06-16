import contextlib
import io
import unittest
import unittest.mock
from pathlib import Path

from grimoireshim import grimoire

SAMPLE_SRCINFO = """\
pkgbase = brave-bin
\tpkgdesc = Web browser
\tpkgver = 1.81.9
\tpkgrel = 1
\tepoch = 1
\turl = https://brave.com
\tlicense = MPL2
\tprovides = brave
\tconflicts = brave
\tdepends = gtk3
\tdepends = nss
\toptdepends = cups: printing

pkgname = brave-bin
"""


def fields_dict(fields: list[tuple[str, str]]) -> dict[str, str]:
	return dict(fields)


class PlainSearchFormatTests(unittest.TestCase):
	def test_two_lines_pacman_shape(self) -> None:
		result = grimoire.SearchResult(
			name="brave-bin",
			version="1.81.9-1",
			description="Web browser",
			installed=True,
			score=0,
		)
		self.assertEqual(
			grimoire.format_search_result_plain(result),
			["aur/brave-bin 1.81.9-1 [installed]", "    Web browser"],
		)

	def test_missing_fields_keep_two_line_invariant(self) -> None:
		result = grimoire.SearchResult(
			name="foo", version=None, description=None, installed=False, score=5
		)
		self.assertEqual(
			grimoire.format_search_result_plain(result), ["aur/foo", "    "]
		)


class SrcinfoInfoFieldTests(unittest.TestCase):
	def test_fields_from_srcinfo(self) -> None:
		fields = fields_dict(grimoire.srcinfo_info_fields("brave-bin", SAMPLE_SRCINFO))
		self.assertEqual(fields["Name"], "brave-bin")
		self.assertEqual(fields["Version"], "1:1.81.9-1")
		self.assertEqual(fields["URL"], "https://brave.com")
		self.assertEqual(fields["Depends On"], "gtk3  nss")
		self.assertEqual(fields["Conflicts With"], "brave")


class ListRepoTests(unittest.TestCase):
	def test_aur_sl_shape(self) -> None:
		out = io.StringIO()
		with (
			unittest.mock.patch.object(grimoire, "_aur_enabled", return_value=True),
			unittest.mock.patch.object(
				grimoire,
				"aur_packages",
				return_value=[("foo", "1.0-1", "d"), ("bar", None, "d")],
			),
			unittest.mock.patch.object(
				grimoire, "installed_package_set", return_value={"bar"}
			),
			contextlib.redirect_stdout(out),
		):
			grimoire.list_repo_packages("AUR", Path("/unused"))
		# label matches the conf section (AUR), versions from the metadata dump,
		# "unknown-version" only when the dump has none.
		self.assertEqual(
			out.getvalue(),
			"AUR foo 1.0-1\nAUR bar unknown-version [installed]\n",
		)

	def test_empty_aur_list_is_an_error(self) -> None:
		with (
			unittest.mock.patch.object(grimoire, "_aur_enabled", return_value=True),
			unittest.mock.patch.object(grimoire, "aur_packages", return_value=[]),
			self.assertRaises(grimoire.GrimoireErr),
		):
			grimoire.list_repo_packages("AUR", Path("/unused"))

	def test_disabled_aur_returns_early(self) -> None:
		# [AUR] off: list --repo AUR prints a notice and does not touch the dump.
		out = io.StringIO()
		with (
			unittest.mock.patch.object(grimoire, "_aur_enabled", return_value=False),
			unittest.mock.patch.object(grimoire, "aur_packages") as dump,
			contextlib.redirect_stdout(out),
		):
			grimoire.list_repo_packages("AUR", Path("/unused"))
		dump.assert_not_called()
		self.assertEqual(out.getvalue(), "")

	def test_custom_repo_enumerates_with_versions(self) -> None:
		out = io.StringIO()
		results = [
			grimoire.SearchResult(
				name="foo", version="1.0-1", description=None, installed=False, score=0
			),
			grimoire.SearchResult(
				name="bar", version="2.0-1", description=None, installed=True, score=0
			),
		]
		with (
			unittest.mock.patch.object(
				grimoire,
				"_resolve_repo_for_package",
				return_value=("https://x/r.git", None, None, []),
			),
			unittest.mock.patch.object(
				grimoire, "search_packages_repo", return_value=results
			),
			unittest.mock.patch.object(
				grimoire, "installed_package_set", return_value={"bar"}
			),
			contextlib.redirect_stdout(out),
		):
			grimoire.list_repo_packages("POWER", Path("/unused"))
		self.assertEqual(
			out.getvalue(),
			"POWER foo 1.0-1\nPOWER bar 2.0-1 [installed]\n",
		)


class PrintInfoFieldsTests(unittest.TestCase):
	def test_colon_alignment(self) -> None:
		out = io.StringIO()
		with contextlib.redirect_stdout(out):
			grimoire.print_info_fields([("Name", "foo"), ("Depends On", "bar")])
		self.assertEqual(out.getvalue(), "Name       : foo\nDepends On : bar\n")


if __name__ == "__main__":
	unittest.main()
