"""Unit tests for --repo-url subdir/branch handling: forge URL parsing,
build-dir resolution, and arg precedence."""

import argparse
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from grimaurshim import grimaur

# Real archinstoo URLs (kept here, not in the README): a nested package whose
# PKGBUILD lives in a subdir, pinned by branch and by commit.
ARCHINSTOO_TREE = "https://github.com/h8d13/archinstoo/tree/master/archinstoo"
ARCHINSTOO_COMMIT = (
	"https://github.com/h8d13/archinstoo/tree/"
	"00dede458e8a8884bd16723bf750ac21edadd3ca/archinstoo"
)

PARSE_CASES = {
	# (clone_url, ref, subdir)
	ARCHINSTOO_TREE: (
		"https://github.com/h8d13/archinstoo.git",
		"master",
		"archinstoo",
	),
	ARCHINSTOO_COMMIT: (
		"https://github.com/h8d13/archinstoo.git",
		"00dede458e8a8884bd16723bf750ac21edadd3ca",
		"archinstoo",
	),
	# blob (file view) is accepted like tree; trailing slash ignored
	"https://github.com/o/r/blob/master/pkg/": (
		"https://github.com/o/r.git",
		"master",
		"pkg",
	),
	# a link straight to the PKGBUILD trims down to its directory
	"https://github.com/o/r/blob/master/pkg/PKGBUILD": (
		"https://github.com/o/r.git",
		"master",
		"pkg",
	),
	# PKGBUILD at the repo root -> no subdir
	"https://github.com/o/r/blob/master/PKGBUILD": (
		"https://github.com/o/r.git",
		"master",
		None,
	),
	# nested subpath preserved
	"https://github.com/o/r/tree/main/a/b/c": (
		"https://github.com/o/r.git",
		"main",
		"a/b/c",
	),
	# GitLab uses /-/tree and /-/blob
	"https://gitlab.com/o/r/-/tree/main/pkg/foo": (
		"https://gitlab.com/o/r.git",
		"main",
		"pkg/foo",
	),
	"https://gitlab.com/o/r/-/blob/main/pkg/PKGBUILD": (
		"https://gitlab.com/o/r.git",
		"main",
		"pkg",
	),
	# Gitea/Codeberg use /src/{branch,tag,commit}
	"https://codeberg.org/o/r/src/branch/dev/aur/bar": (
		"https://codeberg.org/o/r.git",
		"dev",
		"aur/bar",
	),
	"https://codeberg.org/o/r/src/tag/v1.0/pkg": (
		"https://codeberg.org/o/r.git",
		"v1.0",
		"pkg",
	),
	"https://codeberg.org/o/r/src/commit/" + "a" * 40 + "/pkg": (
		"https://codeberg.org/o/r.git",
		"a" * 40,
		"pkg",
	),
}

# URLs with no recognizable directory marker pass through untouched.
PASSTHROUGH = [
	"https://github.com/o/r.git",
	"https://github.com/o/r",
	"https://aur.archlinux.org/brave-bin.git",
	"git@github.com:o/r.git",
	"ssh://aur@aur.archlinux.org/some-pkg.git",
]


class ParseRepoUrlTests(unittest.TestCase):
	def test_forge_urls_split_into_clone_ref_subdir(self) -> None:
		for url, expected in PARSE_CASES.items():
			with self.subTest(url=url):
				self.assertEqual(grimaur.parse_repo_url(url), expected)

	def test_plain_urls_pass_through_unchanged(self) -> None:
		for url in PASSTHROUGH:
			with self.subTest(url=url):
				self.assertEqual(grimaur.parse_repo_url(url), (url, None, None))

	def test_slash_branch_is_misparsed_without_explicit_flags(self) -> None:
		# A branch name with a slash can't be told apart from the subpath, so the
		# first segment becomes the ref and the rest the subdir. Documents why
		# --branch/--subdir override exists.
		self.assertEqual(
			grimaur.parse_repo_url("https://github.com/o/r/tree/feature/x/pkg"),
			("https://github.com/o/r.git", "feature", "x/pkg"),
		)


class ResolveBuildDirTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		(self.root / "pkg").mkdir()

	def test_none_subdir_returns_clone_root(self) -> None:
		self.assertEqual(grimaur._resolve_build_dir(self.root, None), self.root)

	def test_existing_subdir_returns_nested_path(self) -> None:
		self.assertEqual(
			grimaur._resolve_build_dir(self.root, "pkg"), self.root / "pkg"
		)

	def test_missing_subdir_raises(self) -> None:
		with self.assertRaises(grimaur.AurGitError):
			grimaur._resolve_build_dir(self.root, "nope")

	def test_traversal_escaping_clone_root_raises(self) -> None:
		with self.assertRaises(grimaur.AurGitError):
			grimaur._resolve_build_dir(self.root, "../escape")


class ResolvePackageDirTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)

	def _pkgbuild(self, *parts: str) -> None:
		path = self.root.joinpath(*parts)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text("pkgname=x\n")

	def test_root_pkgbuild_stays_put(self) -> None:
		# Normal AUR-shape clone: PKGBUILD at root, no subdir -> return root.
		self._pkgbuild("PKGBUILD")
		self.assertEqual(
			grimaur._resolve_package_dir(self.root, None, "foo"), self.root
		)

	def test_root_pkgbuild_wins_over_nested(self) -> None:
		# A valid build dir is never overridden by a same-named nested package.
		self._pkgbuild("PKGBUILD")
		self._pkgbuild("foo", "PKGBUILD")
		self.assertEqual(
			grimaur._resolve_package_dir(self.root, None, "foo"), self.root
		)

	def test_container_descends_to_named_package(self) -> None:
		# Monorepo container: subdir has no PKGBUILD but <subdir>/<package> does.
		self._pkgbuild("pkgs", "foo", "PKGBUILD")
		self.assertEqual(
			grimaur._resolve_package_dir(self.root, "pkgs", "foo"),
			self.root / "pkgs" / "foo",
		)

	def test_explicit_subdir_at_package_no_descend(self) -> None:
		self._pkgbuild("pkgs", "foo", "PKGBUILD")
		self.assertEqual(
			grimaur._resolve_package_dir(self.root, "pkgs/foo", "foo"),
			self.root / "pkgs" / "foo",
		)

	def test_no_pkgbuild_anywhere_returns_resolved_dir(self) -> None:
		# No descend target -> unchanged (downstream errors as before).
		(self.root / "pkgs").mkdir()
		self.assertEqual(
			grimaur._resolve_package_dir(self.root, "pkgs", "foo"),
			self.root / "pkgs",
		)


class ResolveRepoTargetTests(unittest.TestCase):
	def test_tree_url_fills_ref_and_subdir(self) -> None:
		args = argparse.Namespace(repo_url=ARCHINSTOO_TREE, branch=None, subdir=None)
		self.assertEqual(
			grimaur._resolve_repo_target(args),
			("https://github.com/h8d13/archinstoo.git", "master", "archinstoo", []),
		)

	def test_explicit_flags_override_parsed(self) -> None:
		args = argparse.Namespace(
			repo_url=ARCHINSTOO_TREE, branch="dev", subdir="other"
		)
		self.assertEqual(
			grimaur._resolve_repo_target(args),
			("https://github.com/h8d13/archinstoo.git", "dev", "other", []),
		)

	def test_plain_repo_url_untouched(self) -> None:
		args = argparse.Namespace(
			repo_url="https://github.com/o/r.git", branch=None, subdir=None
		)
		self.assertEqual(
			grimaur._resolve_repo_target(args),
			("https://github.com/o/r.git", None, None, []),
		)

	def test_no_repo_url_returns_none(self) -> None:
		args = argparse.Namespace(repo_url=None, branch=None, subdir=None)
		self.assertEqual(grimaur._resolve_repo_target(args), (None, None, None, []))


class ResolveRepoAliasTargetTests(unittest.TestCase):
	def setUp(self) -> None:
		self._tmp = tempfile.mkdtemp()
		self._orig = os.environ.get("XDG_CONFIG_HOME")
		os.environ["XDG_CONFIG_HOME"] = self._tmp

	def tearDown(self) -> None:
		if self._orig is None:
			os.environ.pop("XDG_CONFIG_HOME", None)
		else:
			os.environ["XDG_CONFIG_HOME"] = self._orig
		shutil.rmtree(self._tmp, ignore_errors=True)

	def test_alias_first_is_primary_rest_are_fallbacks(self) -> None:
		grimaur.add_repo_alias("vur", "https://github.com/h8d13/VUR.git")
		grimaur.add_repo_alias("vur", ARCHINSTOO_TREE)
		args = argparse.Namespace(repo="vur", repo_url=None, branch=None, subdir=None)
		primary_url, branch, subdir, fallbacks = grimaur._resolve_repo_target(args)
		self.assertEqual(primary_url, "https://github.com/h8d13/VUR.git")
		self.assertIsNone(branch)
		self.assertIsNone(subdir)
		# Fallback is a tree URL, so its ref/subdir get parsed out.
		self.assertEqual(
			fallbacks,
			[("https://github.com/h8d13/archinstoo.git", "master", "archinstoo")],
		)

	def test_explicit_flags_override_every_mirror(self) -> None:
		grimaur.add_repo_alias("vur", "https://github.com/h8d13/VUR.git")
		grimaur.add_repo_alias("vur", ARCHINSTOO_TREE)
		args = argparse.Namespace(repo="vur", repo_url=None, branch="dev", subdir="pkg")
		_, branch, subdir, fallbacks = grimaur._resolve_repo_target(args)
		self.assertEqual((branch, subdir), ("dev", "pkg"))
		self.assertEqual(fallbacks[0][1:], ("dev", "pkg"))

	def test_unknown_alias_raises(self) -> None:
		args = argparse.Namespace(repo="nope", repo_url=None, branch=None, subdir=None)
		with self.assertRaises(grimaur.AurGitError):
			grimaur._resolve_repo_target(args)

	def test_pkg_template_substituted_by_package_name(self) -> None:
		grimaur.add_repo_alias(
			"arch",
			"https://gitlab.archlinux.org/archlinux/packaging/packages/{pkg}.git",
		)
		args = argparse.Namespace(
			repo="arch", repo_url=None, branch=None, subdir=None, package="bash"
		)
		primary_url, _, _, fallbacks = grimaur._resolve_repo_target(args)
		self.assertEqual(
			primary_url,
			"https://gitlab.archlinux.org/archlinux/packaging/packages/bash.git",
		)
		self.assertEqual(fallbacks, [])

	def test_pkg_template_left_intact_without_package(self) -> None:
		# No package on the namespace (e.g. nothing to substitute) -> URL untouched.
		args = argparse.Namespace(
			repo=None,
			repo_url="https://example.com/{pkg}.git",
			branch=None,
			subdir=None,
		)
		primary_url, _, _, _ = grimaur._resolve_repo_target(args)
		self.assertEqual(primary_url, "https://example.com/{pkg}.git")


if __name__ == "__main__":
	unittest.main()
