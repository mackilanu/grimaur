import contextlib
import io
import unittest
import unittest.mock

from grimoireshim import grimoire

SAMPLE_RPC_INFO = {
	"Name": "brave-bin",
	"Version": "1:1.81.9-1",
	"Description": "Web browser",
	"URL": "https://brave.com",
	"License": ["MPL2"],
	"Depends": ["gtk3", "nss"],
	"MakeDepends": [],
	"OptDepends": ["cups: printing"],
	"Conflicts": ["brave"],
	"Provides": ["brave"],
	"Maintainer": "someone",
	"NumVotes": 42,
	"Popularity": 1.2345,
	"FirstSubmitted": 1500000000,
	"LastModified": 1700000000,
	"OutOfDate": None,
}

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


class RpcInfoFieldTests(unittest.TestCase):
	def test_si_style_fields(self) -> None:
		fields = fields_dict(grimoire.rpc_info_fields(SAMPLE_RPC_INFO))
		self.assertEqual(fields["Repository"], "aur")
		self.assertEqual(fields["Version"], "1:1.81.9-1")
		self.assertEqual(fields["URL"], "https://brave.com")
		self.assertEqual(fields["Licenses"], "MPL2")
		self.assertEqual(fields["Depends On"], "gtk3  nss")
		self.assertEqual(fields["Make Deps"], "None")
		self.assertEqual(fields["Votes"], "42")
		self.assertEqual(fields["Popularity"], "1.23")
		self.assertEqual(fields["Out-of-date"], "No")
		self.assertEqual(fields["Last Modified"], "2023-11-14")

	def test_out_of_date_epoch_renders_as_date(self) -> None:
		info = dict(SAMPLE_RPC_INFO, OutOfDate=1700000000)
		fields = fields_dict(grimoire.rpc_info_fields(info))
		self.assertEqual(fields["Out-of-date"], "2023-11-14")


class SrcinfoInfoFieldTests(unittest.TestCase):
	def test_fields_from_srcinfo(self) -> None:
		fields = fields_dict(grimoire.srcinfo_info_fields("brave-bin", SAMPLE_SRCINFO))
		self.assertEqual(fields["Name"], "brave-bin")
		self.assertEqual(fields["Version"], "1:1.81.9-1")
		self.assertEqual(fields["URL"], "https://brave.com")
		self.assertEqual(fields["Depends On"], "gtk3  nss")
		self.assertEqual(fields["Conflicts With"], "brave")


class ListAurTests(unittest.TestCase):
	def test_sl_aur_shape(self) -> None:
		out = io.StringIO()
		with (
			unittest.mock.patch.object(
				grimoire, "aur_package_names", return_value=["foo", "bar"]
			),
			unittest.mock.patch.object(
				grimoire, "installed_package_set", return_value={"bar"}
			),
			contextlib.redirect_stdout(out),
		):
			grimoire.list_aur_packages()
		self.assertEqual(
			out.getvalue(),
			"aur foo unknown-version\naur bar unknown-version [installed]\n",
		)

	def test_empty_name_list_is_an_error(self) -> None:
		with (
			unittest.mock.patch.object(grimoire, "aur_package_names", return_value=[]),
			self.assertRaises(grimoire.AurGitError),
		):
			grimoire.list_aur_packages()


class PrintInfoFieldsTests(unittest.TestCase):
	def test_colon_alignment(self) -> None:
		out = io.StringIO()
		with contextlib.redirect_stdout(out):
			grimoire.print_info_fields([("Name", "foo"), ("Depends On", "bar")])
		self.assertEqual(out.getvalue(), "Name       : foo\nDepends On : bar\n")


if __name__ == "__main__":
	unittest.main()
