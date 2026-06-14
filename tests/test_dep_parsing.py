"""Tests for SRCINFO dependency parsing.

Covers two coupled functions:
- `_normalize_dep`: strips repo qualifier (`extra:foo`) and version constraints (`foo>=1.0`) from a dep string.
- `parse_dependencies`: aggregates depends/makedepends/checkdepends through `_normalize_dep`, but deliberately keeps `optdepends` raw so descriptions ("foo: extra feature") survive. Easy to break that asymmetry.
"""

import unittest

from grimoireshim import grimoire


class NormalizeDepTests(unittest.TestCase):
	def test_plain(self) -> None:
		self.assertEqual(grimoire._normalize_dep("python"), "python")

	def test_preserves_dashes(self) -> None:
		self.assertEqual(grimoire._normalize_dep("lib32-glibc"), "lib32-glibc")

	def test_strips_each_version_operator(self) -> None:
		cases = [
			("python>=3.10", "python"),
			("python<=3.12", "python"),
			("python>3", "python"),
			("python<4", "python"),
			("python=3.10", "python"),
			("python~3.10", "python"),
		]
		for raw, want in cases:
			with self.subTest(raw=raw):
				self.assertEqual(grimoire._normalize_dep(raw), want)

	def test_strips_repo_qualifier(self) -> None:
		self.assertEqual(grimoire._normalize_dep("extra:python"), "python")
		self.assertEqual(grimoire._normalize_dep("extra:python>=3.10"), "python")

	def test_strips_outer_whitespace(self) -> None:
		self.assertEqual(grimoire._normalize_dep("  python  "), "python")

	def test_empty_in_empty_out(self) -> None:
		self.assertEqual(grimoire._normalize_dep(""), "")
		self.assertEqual(grimoire._normalize_dep("   "), "")

	def test_compound_operators(self) -> None:
		# Multiple version operators collapse to just the name.
		self.assertEqual(grimoire._normalize_dep("python>=3.10<4"), "python")


SAMPLE_SRCINFO = """\
pkgbase = examplepkg
	pkgdesc = An example package for tests
	pkgver = 1.0
	pkgrel = 2
	depends = python
	depends = extra:requests>=2.30
	depends =   whitespace-pkg
	makedepends = git
	makedepends = python-build>=1.0
	checkdepends = python-pytest
	optdepends = vim: required for editing
	optdepends = neovim: alternative editor with >=0.9
	# this comment line should be ignored
	weird-key-we-do-not-care-about = ignored

pkgname = examplepkg
"""


class ParseDependenciesTests(unittest.TestCase):
	def test_returns_pkgbase_and_desc(self) -> None:
		pkgbase, desc, _deps = grimoire.parse_dependencies(SAMPLE_SRCINFO)
		self.assertEqual(pkgbase, "examplepkg")
		self.assertEqual(desc, "An example package for tests")

	def test_depends_are_normalized(self) -> None:
		_pkgbase, _desc, deps = grimoire.parse_dependencies(SAMPLE_SRCINFO)
		self.assertEqual(
			deps.depends,
			{"python", "requests", "whitespace-pkg"},
		)

	def test_makedepends_and_checkdepends_normalized(self) -> None:
		_pkgbase, _desc, deps = grimoire.parse_dependencies(SAMPLE_SRCINFO)
		self.assertEqual(deps.makedepends, {"git", "python-build"})
		self.assertEqual(deps.checkdepends, {"python-pytest"})

	def test_optdepends_keep_descriptions_verbatim(self) -> None:
		# The whole point of the asymmetry: opt-deps include human-readable
		# descriptions, normalising them would destroy that.
		_pkgbase, _desc, deps = grimoire.parse_dependencies(SAMPLE_SRCINFO)
		self.assertEqual(
			deps.optdepends,
			{
				"vim: required for editing",
				"neovim: alternative editor with >=0.9",
			},
		)

	def test_missing_pkgbase_raises(self) -> None:
		with self.assertRaises(grimoire.AurGitError):
			grimoire.parse_dependencies("pkgname = nope\ndepends = python\n")

	def test_comments_and_blank_lines_ignored(self) -> None:
		srcinfo = "pkgbase = x\n\n# comment\n\tdepends = foo\n"
		_pkgbase, _desc, deps = grimoire.parse_dependencies(srcinfo)
		self.assertEqual(deps.depends, {"foo"})


if __name__ == "__main__":
	unittest.main()
