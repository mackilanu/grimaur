"""Unit tests for --repo-url subdir/branch handling: forge URL parsing,
build-dir resolution, and arg precedence."""

import argparse
import io
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire

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
	# /raw/ links are accepted like tree/blob (same <ref>/<path>)
	"https://github.com/o/r/raw/master/pkg": (
		"https://github.com/o/r.git",
		"master",
		"pkg",
	),
	"https://github.com/o/r/raw/master/pkg/PKGBUILD": (
		"https://github.com/o/r.git",
		"master",
		"pkg",
	),
	"https://gitlab.com/o/r/-/raw/main/pkg/PKGBUILD": (
		"https://gitlab.com/o/r.git",
		"main",
		"pkg",
	),
	"https://codeberg.org/o/r/raw/branch/dev/aur/bar": (
		"https://codeberg.org/o/r.git",
		"dev",
		"aur/bar",
	),
	# Forgejo (self-hosted, Gitea scheme): the /src/{branch,tag,commit} handler is
	# host-agnostic, so any Forgejo/Gitea host works without special-casing.
	"https://v15.next.forgejo.org/o/r/src/branch/main/pkgs/foo": (
		"https://v15.next.forgejo.org/o/r.git",
		"main",
		"pkgs/foo",
	),
	"https://v15.next.forgejo.org/o/r/src/tag/v2": (
		"https://v15.next.forgejo.org/o/r.git",
		"v2",
		None,
	),
	# Bitbucket Cloud: /src/<ref>/<path> -- ref directly after the marker, no
	# branch/tag/commit segment (distinct from the Gitea scheme).
	"https://bitbucket.org/ws/repo/src/main/pkgs/foo": (
		"https://bitbucket.org/ws/repo.git",
		"main",
		"pkgs/foo",
	),
	"https://bitbucket.org/ws/repo/raw/main/pkg/PKGBUILD": (
		"https://bitbucket.org/ws/repo.git",
		"main",
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
				self.assertEqual(grimoire.parse_repo_url(url), expected)

	def test_schemeless_forge_url_gets_https(self) -> None:
		self.assertEqual(
			grimoire.parse_repo_url("github.com/h8d13/VUR/tree/master/pkgs"),
			("https://github.com/h8d13/VUR.git", "master", "pkgs"),
		)
		self.assertEqual(
			grimoire.parse_repo_url("github.com/o/r"),
			("https://github.com/o/r", None, None),
		)

	def test_schemeless_leaves_scp_and_ssh_untouched(self) -> None:
		for url in ("git@github.com:o/r.git", "ssh://git@github.com/o/r.git"):
			with self.subTest(url=url):
				self.assertEqual(grimoire.parse_repo_url(url), (url, None, None))

	def test_plain_urls_pass_through_unchanged(self) -> None:
		for url in PASSTHROUGH:
			with self.subTest(url=url):
				self.assertEqual(grimoire.parse_repo_url(url), (url, None, None))

	def test_slash_branch_is_misparsed_without_explicit_flags(self) -> None:
		# A branch name with a slash can't be told apart from the subpath, so the
		# first segment becomes the ref and the rest the subdir. Documents why
		# --rev/--subdir override exists.
		self.assertEqual(
			grimoire.parse_repo_url("https://github.com/o/r/tree/feature/x/pkg"),
			("https://github.com/o/r.git", "feature", "x/pkg"),
		)


class ResolveBuildDirTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		(self.root / "pkg").mkdir()

	def test_none_subdir_returns_clone_root(self) -> None:
		self.assertEqual(grimoire._resolve_build_dir(self.root, None), self.root)

	def test_existing_subdir_returns_nested_path(self) -> None:
		self.assertEqual(
			grimoire._resolve_build_dir(self.root, "pkg"), self.root / "pkg"
		)

	def test_missing_subdir_raises(self) -> None:
		with self.assertRaises(grimoire.GrimoireErr):
			grimoire._resolve_build_dir(self.root, "nope")

	def test_traversal_escaping_clone_root_raises(self) -> None:
		with self.assertRaises(grimoire.GrimoireErr):
			grimoire._resolve_build_dir(self.root, "../escape")


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
			grimoire._resolve_package_dir(self.root, None, "foo"), self.root
		)

	def test_root_pkgbuild_wins_over_nested(self) -> None:
		# A valid build dir is never overridden by a same-named nested package.
		self._pkgbuild("PKGBUILD")
		self._pkgbuild("foo", "PKGBUILD")
		self.assertEqual(
			grimoire._resolve_package_dir(self.root, None, "foo"), self.root
		)

	def test_container_descends_to_named_package(self) -> None:
		# Monorepo container: subdir has no PKGBUILD but <subdir>/<package> does.
		self._pkgbuild("pkgs", "foo", "PKGBUILD")
		self.assertEqual(
			grimoire._resolve_package_dir(self.root, "pkgs", "foo"),
			self.root / "pkgs" / "foo",
		)

	def test_explicit_subdir_at_package_no_descend(self) -> None:
		self._pkgbuild("pkgs", "foo", "PKGBUILD")
		self.assertEqual(
			grimoire._resolve_package_dir(self.root, "pkgs/foo", "foo"),
			self.root / "pkgs" / "foo",
		)

	def test_no_pkgbuild_anywhere_returns_resolved_dir(self) -> None:
		# No descend target -> unchanged (downstream errors as before).
		(self.root / "pkgs").mkdir()
		self.assertEqual(
			grimoire._resolve_package_dir(self.root, "pkgs", "foo"),
			self.root / "pkgs",
		)


class OfficialRepoRegexTests(unittest.TestCase):
	def test_matches_official_repos(self) -> None:
		for repo in (
			"core",
			"extra",
			"multilib",
			"core-testing",
			"extra-staging",
			"multilib-testing",
			"gnome-unstable",
			"kde-unstable",
		):
			with self.subTest(repo=repo):
				self.assertTrue(grimoire._OFFICIAL_REPO_RE.match(repo))

	def test_rejects_third_party_repos(self) -> None:
		for repo in ("cachyos", "cachyos-v3", "myrepo", "core-extra", "aur"):
			with self.subTest(repo=repo):
				self.assertIsNone(grimoire._OFFICIAL_REPO_RE.match(repo))


class ResolvePkgbaseTests(unittest.TestCase):
	def _make_db(self, sync: Path, name: str, descs: dict[str, str]) -> None:
		# descs: member-dir -> desc text. Write a gzip sync DB like pacman's.
		sync.mkdir(parents=True, exist_ok=True)
		with tarfile.open(sync / name, "w:gz") as tar:
			for member_dir, text in descs.items():
				raw = text.encode()
				info = tarfile.TarInfo(f"{member_dir}/desc")
				info.size = len(raw)
				tar.addfile(info, io.BytesIO(raw))

	def _resolve(self, base_dir: Path, package: str) -> str:
		grimoire._resolve_pkgbase.cache_clear()
		with mock.patch.object(grimoire, "_pacman_db_path", return_value=base_dir):
			return str(grimoire._resolve_pkgbase(package))

	def test_split_package_resolves_to_base(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			base = Path(tmp)
			self._make_db(
				base / "sync",
				"core.db",
				{
					"amd-ucode-20250101-1": "%NAME%\namd-ucode\n\n%BASE%\nlinux-firmware\n",
					"gcc-ada-14-1": "%NAME%\ngcc-ada\n\n%BASE%\ngcc\n",
					"gcc-14-1": "%NAME%\ngcc\n\n%BASE%\ngcc\n",
				},
			)
			# prefix collision: gcc-ada must not satisfy a lookup for gcc
			self.assertEqual(self._resolve(base, "amd-ucode"), "linux-firmware")
			self.assertEqual(self._resolve(base, "gcc"), "gcc")
			self.assertEqual(self._resolve(base, "gcc-ada"), "gcc")

	def test_unknown_package_falls_back_to_name(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			base = Path(tmp)
			self._make_db(
				base / "sync", "core.db", {"foo-1-1": "%NAME%\nfoo\n\n%BASE%\nfoo\n"}
			)
			self.assertEqual(self._resolve(base, "not-here"), "not-here")

	def test_no_sync_dir_falls_back_to_name(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			self.assertEqual(self._resolve(Path(tmp), "whatever"), "whatever")


class NormalizeGitUrlTests(unittest.TestCase):
	def test_https_ssh_scp_forms_match(self) -> None:
		forms = [
			"https://github.com/h8d13/VUR",
			"https://github.com/h8d13/VUR.git",
			"git@github.com:h8d13/VUR.git",
			"ssh://git@github.com/h8d13/VUR.git",
			"https://github.com/h8d13/VUR/",
		]
		normalized = {grimoire._normalize_git_url(f) for f in forms}
		self.assertEqual(normalized, {"github.com/h8d13/vur"})

	def test_different_repos_differ(self) -> None:
		self.assertNotEqual(
			grimoire._normalize_git_url("https://github.com/h8d13/VUR"),
			grimoire._normalize_git_url("https://github.com/h8d13/other"),
		)


class EnsureReposConfTests(unittest.TestCase):
	def setUp(self) -> None:
		self._tmp = tempfile.mkdtemp()
		self._orig = os.environ.get("XDG_CONFIG_HOME")
		os.environ["XDG_CONFIG_HOME"] = self._tmp
		self.conf = Path(self._tmp) / "grimoire" / "repos.ini"

	def tearDown(self) -> None:
		if self._orig is None:
			os.environ.pop("XDG_CONFIG_HOME", None)
		else:
			os.environ["XDG_CONFIG_HOME"] = self._orig
		shutil.rmtree(self._tmp, ignore_errors=True)

	def _write(self, text: str) -> None:
		self.conf.parent.mkdir(parents=True, exist_ok=True)
		self.conf.write_text(text)

	def test_ensure_repos_conf_seeds_arch_default(self) -> None:
		self.assertFalse(self.conf.exists())
		grimoire._ensure_repos_conf()
		self.assertTrue(self.conf.exists())
		# Seeded with [ARCH] first; [AUR] is a reserved toggle, present but off (opt-in).
		registry = grimoire.load_repo_registry()
		self.assertEqual(next(iter(registry)), "ARCH")
		self.assertIn("AUR", registry)
		self.assertFalse(grimoire._aur_enabled())

	def test_ensure_repos_conf_does_not_clobber(self) -> None:
		self._write("[VUR]\n  https://x/v\n")
		grimoire._ensure_repos_conf()
		self.assertEqual(self.conf.read_text(), "[VUR]\n  https://x/v\n")


class ResolveSourcesTests(unittest.TestCase):
	"""Ordered source chain: explicit flag collapses to one source, otherwise every
	repos.ini section top to bottom (conf order == precedence), AUR encoded as a
	None repo_url, templates resolved per package."""

	def setUp(self) -> None:
		self._tmp = tempfile.mkdtemp()
		self._orig = os.environ.get("XDG_CONFIG_HOME")
		os.environ["XDG_CONFIG_HOME"] = self._tmp
		self.conf = Path(self._tmp) / "grimoire" / "repos.ini"

	def tearDown(self) -> None:
		if self._orig is None:
			os.environ.pop("XDG_CONFIG_HOME", None)
		else:
			os.environ["XDG_CONFIG_HOME"] = self._orig
		shutil.rmtree(self._tmp, ignore_errors=True)

	def _write(self, text: str) -> None:
		self.conf.parent.mkdir(parents=True, exist_ok=True)
		self.conf.write_text(text)

	def _args(self, **kw: object) -> argparse.Namespace:
		base: dict[str, object] = {
			"repo": None,
			"repo_url": None,
			"rev": None,
			"subdir": None,
		}
		base.update(kw)
		return argparse.Namespace(**base)

	def test_explicit_url_is_single_source(self) -> None:
		self._write("[ARCH]\n  https://gitlab/x/{pkg}.git\n\n[VUR]\n  https://x/v\n")
		sources = grimoire._resolve_sources(
			self._args(repo_url="https://github.com/o/r.git"), "bash"
		)
		self.assertEqual(sources, [("https://github.com/o/r.git", None, None, [])])

	def test_no_conf_is_single_aur_backend(self) -> None:
		self.assertEqual(
			grimoire._resolve_sources(self._args(), "bash"),
			[(None, None, None, [])],
		)

	def test_chain_follows_conf_order(self) -> None:
		self._write(
			"[ARCH]\n  https://gitlab/x/{pkg}.git\n\n[VUR]\n  https://x/vur.git\n"
		)
		sources = grimoire._resolve_sources(self._args(), "bash")
		self.assertEqual(
			[s[0] for s in sources],
			["https://gitlab/x/bash.git", "https://x/vur.git"],
		)

	def test_aur_section_becomes_backend_marker_in_order(self) -> None:
		self._write("[AUR]\n  true\n\n[VUR]\n  https://x/vur.git\n")
		sources = grimoire._resolve_sources(self._args(), "bash")
		self.assertEqual(sources[0], (None, None, None, []))
		self.assertEqual(sources[1][0], "https://x/vur.git")

	def test_disabled_aur_excluded_from_chain(self) -> None:
		self._write("[AUR]\n  false\n\n[VUR]\n  https://x/vur.git\n")
		self.assertFalse(grimoire._aur_enabled())
		sources = grimoire._resolve_sources(self._args(), "bash")
		self.assertEqual([s[0] for s in sources], ["https://x/vur.git"])

	def test_explicit_repo_aur_works_even_when_disabled(self) -> None:
		# Explicit --repo AUR is a deliberate override: the built-in backend regardless
		# of the toggle (and never parsed as a URL alias).
		self._write("[AUR]\n  false\n\n[VUR]\n  https://x/vur.git\n")
		sources = grimoire._resolve_sources(self._args(repo="AUR"), "bash")
		self.assertEqual(sources, [(None, None, None, [])])

	def test_template_resolved_per_package(self) -> None:
		self._write("[ARCH]\n  https://gitlab/x/{pkg}.git\n")
		self.assertEqual(
			grimoire._resolve_sources(self._args(), "foo")[0][0],
			"https://gitlab/x/foo.git",
		)
		self.assertEqual(
			grimoire._resolve_sources(self._args(), "bar")[0][0],
			"https://gitlab/x/bar.git",
		)


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
		grimoire.add_repo_alias("vur", "https://github.com/h8d13/VUR.git")
		grimoire.add_repo_alias("vur", ARCHINSTOO_TREE)
		primary_url, branch, subdir, fallbacks = grimoire._resolve_repo_for_package(
			None, alias="vur", repo_url=None, branch=None, subdir=None
		)
		self.assertEqual(primary_url, "https://github.com/h8d13/VUR.git")
		self.assertIsNone(branch)
		self.assertIsNone(subdir)
		# Fallback is a tree URL, so its ref/subdir get parsed out.
		self.assertEqual(
			fallbacks,
			[("https://github.com/h8d13/archinstoo.git", "master", "archinstoo")],
		)

	def test_explicit_flags_override_every_mirror(self) -> None:
		grimoire.add_repo_alias("vur", "https://github.com/h8d13/VUR.git")
		grimoire.add_repo_alias("vur", ARCHINSTOO_TREE)
		_, branch, subdir, fallbacks = grimoire._resolve_repo_for_package(
			None, alias="vur", repo_url=None, branch="dev", subdir="pkg"
		)
		self.assertEqual((branch, subdir), ("dev", "pkg"))
		self.assertEqual(fallbacks[0][1:], ("dev", "pkg"))

	def test_unknown_alias_raises(self) -> None:
		with self.assertRaises(grimoire.GrimoireErr):
			grimoire._resolve_repo_for_package(
				None, alias="nope", repo_url=None, branch=None, subdir=None
			)

	def test_pkg_template_substituted_by_package_name(self) -> None:
		grimoire.add_repo_alias(
			"arch",
			"https://gitlab.archlinux.org/archlinux/packaging/packages/{pkg}.git",
		)
		primary_url, _, _, fallbacks = grimoire._resolve_repo_for_package(
			"bash", alias="arch", repo_url=None, branch=None, subdir=None
		)
		self.assertEqual(
			primary_url,
			"https://gitlab.archlinux.org/archlinux/packaging/packages/bash.git",
		)
		self.assertEqual(fallbacks, [])

	def test_ref_templates_pkg_for_branch_per_package(self) -> None:
		# `{pkg}`/`{pkgbase}` in the ref selects a branch-per-package layout over any
		# transport (a bare SSH URL has no forge `tree/{pkg}` shorthand). Transport and
		# repo layout are orthogonal -- this works regardless of ssh vs https.
		url, branch, _, _ = grimoire._resolve_repo_for_package(
			"foo", alias=None, repo_url="git@host:u/r.git", branch="{pkg}", subdir=None
		)
		self.assertEqual((url, branch), ("git@host:u/r.git", "foo"))
		# {pkgbase} in the ref too (sync-DB lookup mocked so the test needs no pacman).
		with mock.patch.object(
			grimoire, "_resolve_pkgbase", return_value="linux-firmware"
		):
			_, base_branch, _, _ = grimoire._resolve_repo_for_package(
				"amd-ucode",
				alias=None,
				repo_url="git@host:u/r.git",
				branch="{pkgbase}",
				subdir=None,
			)
		self.assertEqual(base_branch, "linux-firmware")

	def test_pkg_template_left_intact_without_package(self) -> None:
		# No package given (nothing to substitute) -> URL untouched.
		primary_url, _, _, _ = grimoire._resolve_repo_for_package(
			None,
			alias=None,
			repo_url="https://example.com/{pkg}.git",
			branch=None,
			subdir=None,
		)
		self.assertEqual(primary_url, "https://example.com/{pkg}.git")


class AddRemovePreserveCommentsTests(unittest.TestCase):
	def setUp(self) -> None:
		self._tmp = tempfile.mkdtemp()
		self._orig = os.environ.get("XDG_CONFIG_HOME")
		os.environ["XDG_CONFIG_HOME"] = self._tmp
		self.conf = Path(self._tmp) / "grimoire" / "repos.ini"
		self.conf.parent.mkdir(parents=True)
		self.conf.write_text(
			"# header\n[ARCH]\n  https://x/{pkgbase}.git\n\n#[AUR]\n#  https://aur/rpc/\n"
		)

	def tearDown(self) -> None:
		if self._orig is None:
			os.environ.pop("XDG_CONFIG_HOME", None)
		else:
			os.environ["XDG_CONFIG_HOME"] = self._orig
		shutil.rmtree(self._tmp, ignore_errors=True)

	def test_add_keeps_comments_and_commented_section(self) -> None:
		grimoire.add_repo_alias("VUR", "https://x/vur/pkgs")
		text = self.conf.read_text()
		self.assertIn("# header", text)
		self.assertIn("#[AUR]", text)
		self.assertEqual(
			grimoire.load_repo_registry().get("VUR"), ["https://x/vur/pkgs"]
		)

	def test_remove_keeps_comments(self) -> None:
		grimoire.add_repo_alias("VUR", "https://x/vur/pkgs")
		grimoire.remove_repo_alias("VUR")
		text = self.conf.read_text()
		self.assertIn("#[AUR]", text)
		self.assertNotIn("[VUR]", text)
		self.assertIn("ARCH", grimoire.load_repo_registry())


if __name__ == "__main__":
	unittest.main()
