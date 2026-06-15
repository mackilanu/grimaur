"""Integration tests for ensure_clone --repo-url ref checkout: a branch, tag, or
commit resolves identically on a fresh clone and on --refresh, building from a
nested subdir. Exercises a real local git repo via file:// (no network)."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire


def _git(repo: Path, *args: str) -> str:
	out = subprocess.run(
		[
			"git",
			"-C",
			str(repo),
			"-c",
			"user.email=t@t",
			"-c",
			"user.name=t",
			"-c",
			"commit.gpgsign=false",
			*args,
		],
		capture_output=True,
		text=True,
		check=True,
	)
	return out.stdout.strip()


def _write_pkgbuild(repo: Path, pkgver: int) -> None:
	(repo / "pkg").mkdir(exist_ok=True)
	(repo / "pkg" / "PKGBUILD").write_text(
		f"pkgname=foo\npkgver={pkgver}\npkgrel=1\narch=(any)\n"
	)


class EnsureCloneRefTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.src = self.root / "src"
		self.src.mkdir()
		# master: v1 (tagged v1.0) -> v2 ; dev branched off v2 -> v3
		_git(self.src, "init", "-q", "-b", "master")
		_write_pkgbuild(self.src, 1)
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "v1")
		_git(self.src, "tag", "v1.0")
		self.sha_v1 = _git(self.src, "rev-parse", "HEAD")
		_write_pkgbuild(self.src, 2)
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "v2")
		_git(self.src, "checkout", "-q", "-b", "dev")
		_write_pkgbuild(self.src, 3)
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "v3")
		_git(self.src, "checkout", "-q", "master")

		# default globals already False at import; pin them so a developer's
		# environment can't flip shallow clones on and break commit checkout.
		for name in ("SHALLOW_CLONE", "USE_SSH"):
			patcher = mock.patch.object(grimoire, name, False)
			patcher.start()
			self.addCleanup(patcher.stop)

	def _ensure(self, branch: str | None, dest: Path, *, refresh: bool = False) -> Path:
		build_dir: Path = grimoire.ensure_clone(
			"foo",
			dest,
			refresh=refresh,
			repo_url=f"file://{self.src}",
			branch=branch,
			subdir="pkg",
		)
		return build_dir

	def _fresh(self, branch: str | None) -> Path:
		# A clone is keyed by package name, so each fresh checkout needs its own
		# dest-root; switching ref in an existing clone would need --refresh.
		dest = Path(tempfile.mkdtemp(dir=self.root))
		return self._ensure(branch, dest)

	def _pkgver(self, build_dir: Path) -> str:
		return (build_dir / "PKGBUILD").read_text().split("pkgver=")[1].split("\n")[0]

	def test_subdir_is_the_returned_build_dir(self) -> None:
		dest = Path(tempfile.mkdtemp(dir=self.root))
		self.assertEqual(self._ensure("master", dest), dest / "foo" / "pkg")

	def test_branch_checks_out_branch_tip(self) -> None:
		self.assertEqual(self._pkgver(self._fresh("master")), "2")
		self.assertEqual(self._pkgver(self._fresh("dev")), "3")

	def test_tag_checks_out_tagged_commit(self) -> None:
		self.assertEqual(self._pkgver(self._fresh("v1.0")), "1")

	def test_commit_sha_checks_out_that_commit(self) -> None:
		build_dir = self._fresh(self.sha_v1)
		self.assertEqual(self._pkgver(build_dir), "1")
		head = _git(build_dir.parent, "rev-parse", "HEAD")
		self.assertEqual(head, self.sha_v1)

	def test_no_branch_uses_default_head(self) -> None:
		self.assertEqual(self._pkgver(self._fresh(None)), "2")

	def test_refresh_keeps_each_ref_pinned(self) -> None:
		# Second call exercises the fetch + reset-to-FETCH_HEAD refresh path.
		for ref, expected in (("master", "2"), ("dev", "3"), ("v1.0", "1")):
			with self.subTest(ref=ref):
				dest = Path(tempfile.mkdtemp(dir=self.root))
				self._ensure(ref, dest)
				build_dir = self._ensure(ref, dest, refresh=True)
				self.assertEqual(self._pkgver(build_dir), expected)

	def test_missing_subdir_raises(self) -> None:
		with self.assertRaises(grimoire.AurGitError):
			grimoire.ensure_clone(
				"foo",
				Path(tempfile.mkdtemp(dir=self.root)),
				refresh=False,
				repo_url=f"file://{self.src}",
				branch="master",
				subdir="does-not-exist",
			)


class UpdateRepoPrimitivesTests(unittest.TestCase):
	"""The repo-aware halves of `update`: VCS head via ls-remote, and the
	versioned check (resolve container -> clone w/ descend -> read .SRCINFO)."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.src = self.root / "src"
		self.src.mkdir()
		_git(self.src, "init", "-q", "-b", "master")
		pkg = self.src / "pkgs" / "foo"
		pkg.mkdir(parents=True)
		(pkg / "PKGBUILD").write_text("pkgname=foo\npkgver=2.5\npkgrel=1\narch=(any)\n")
		(pkg / ".SRCINFO").write_text(
			"pkgbase = foo\n\tpkgver = 2.5\n\tpkgrel = 1\n\tpkgdesc = t\n\npkgname = foo\n"
		)
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "v1")
		self.dest = self.root / "dest"

	def test_git_remote_head_matches_rev_parse(self) -> None:
		head = grimoire._git_remote_head(f"file://{self.src}", "master")
		self.assertEqual(head, _git(self.src, "rev-parse", "HEAD"))

	def test_git_remote_head_none_on_bad_url(self) -> None:
		self.assertIsNone(grimoire._git_remote_head("file:///nope/x.git", "master"))

	def test_versioned_check_reads_repo_srcinfo(self) -> None:
		# Mirror update's versioned path: a container subdir + package name descends
		# to pkgs/foo and the version comes from the repo's .SRCINFO, not the AUR.
		r_url, r_branch, r_subdir, r_fallbacks = grimoire._resolve_repo_for_package(
			"foo",
			alias=None,
			repo_url=f"file://{self.src}",
			branch="master",
			subdir="pkgs",
		)
		pkg_dir = grimoire.ensure_clone(
			"foo",
			self.dest,
			refresh=False,
			repo_url=r_url,
			branch=r_branch,
			subdir=r_subdir,
			repo_fallbacks=r_fallbacks,
		)
		self.assertEqual(pkg_dir, self.dest / "foo" / "pkgs" / "foo")
		version, _ = grimoire._parse_srcinfo_metadata(grimoire.read_srcinfo(pkg_dir))
		self.assertEqual(version, "2.5-1")


class OriginSwitchTests(unittest.TestCase):
	"""Switching a clone's source reclones from the new origin (offline file://)."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.dest = self.root / "dest"
		self.a = self.root / "a"
		self.b = self.root / "b"
		for repo, who in ((self.a, "a"), (self.b, "b")):
			repo.mkdir()
			_git(repo, "init", "-q", "-b", "master")
			(repo / "PKGBUILD").write_text(f"pkgname=foo\npkgver={who}\n")
			_git(repo, "add", "-A")
			_git(repo, "commit", "-qm", "x")
		for name in ("SHALLOW_CLONE", "USE_SSH"):
			patcher = mock.patch.object(grimoire, name, False)
			patcher.start()
			self.addCleanup(patcher.stop)

	def _ver(self, build_dir: Path) -> str:
		return (build_dir / "PKGBUILD").read_text().split("pkgver=")[1].split("\n")[0]

	def test_switching_source_reclones(self) -> None:
		d1 = grimoire.ensure_clone(
			"foo", self.dest, refresh=False, repo_url=f"file://{self.a}"
		)
		self.assertEqual(self._ver(d1), "a")
		# same dest/package, different source URL -> origin mismatch -> reclone from b
		d2 = grimoire.ensure_clone(
			"foo", self.dest, refresh=False, repo_url=f"file://{self.b}"
		)
		self.assertEqual(self._ver(d2), "b")

	def test_same_source_reuses(self) -> None:
		grimoire.ensure_clone(
			"foo", self.dest, refresh=False, repo_url=f"file://{self.a}"
		)
		d = grimoire.ensure_clone(
			"foo", self.dest, refresh=False, repo_url=f"file://{self.a}"
		)
		self.assertEqual(self._ver(d), "a")


class SearchRepoTests(unittest.TestCase):
	"""search --repo enumeration of a subdir-container repo (offline file://)."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.src = self.root / "src"
		self.src.mkdir()
		_git(self.src, "init", "-q", "-b", "master")
		for name, ver in (("foo", "1.0"), ("bar", "2.0")):
			d = self.src / "pkgs" / name
			d.mkdir(parents=True)
			(d / "PKGBUILD").write_text(f"pkgname={name}\npkgver={ver}\npkgrel=1\n")
			(d / ".SRCINFO").write_text(
				f"pkgbase = {name}\n\tpkgver = {ver}\n\tpkgrel = 1\n"
				f"\tpkgdesc = {name} desc\n\npkgname = {name}\n"
			)
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "init")
		patcher = mock.patch.object(
			grimoire, "installed_package_set", return_value=set()
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_enumerates_subdir_packages_with_metadata(self) -> None:
		results = grimoire.search_packages_repo(
			f"file://{self.src}",
			"master",
			"pkgs",
			regex=None,
			needle="",
			limit=None,
			source="VUR",
			dest_root=self.root / "dest",
		)
		by_name = {r.name: r for r in results}
		self.assertEqual(set(by_name), {"foo", "bar"})
		self.assertEqual(by_name["foo"].version, "1.0-1")
		self.assertEqual(by_name["bar"].description, "bar desc")
		self.assertEqual(by_name["foo"].source, "VUR")

	def test_needle_filters(self) -> None:
		results = grimoire.search_packages_repo(
			f"file://{self.src}",
			"master",
			"pkgs",
			regex=None,
			needle="foo",
			limit=None,
			source="VUR",
			dest_root=self.root / "dest",
		)
		self.assertEqual([r.name for r in results], ["foo"])

	def test_enum_clone_lands_under_dest_root_not_tmp(self) -> None:
		dest = self.root / "dest"
		grimoire.search_packages_repo(
			f"file://{self.src}",
			"master",
			"pkgs",
			regex=None,
			needle="",
			limit=None,
			source="VUR",
			dest_root=dest,
		)
		self.assertTrue((dest / ".searchrepo").is_dir())

	def test_source_label_in_plain_and_pretty(self) -> None:
		result = grimoire.SearchResult(
			name="foo",
			version="1.0-1",
			description="d",
			installed=False,
			score=0,
			source="VUR",
		)
		self.assertTrue(
			grimoire.format_search_result_plain(result)[0].startswith("VUR/foo")
		)
		self.assertIn("[https VUR]", grimoire.format_search_result(1, result)[0])

	def test_templated_alias_without_index_rejected(self) -> None:
		# No sync DB to fall back on -> templated alias has nothing to enumerate.
		with (
			mock.patch.object(grimoire, "_sync_db_packages", return_value=()),
			self.assertRaises(grimoire.AurGitError),
		):
			grimoire.search_packages_repo(
				"https://x/{pkg}.git",
				None,
				None,
				regex=None,
				needle="",
				limit=None,
				source="x",
				dest_root=self.root / "dest",
			)

	def test_templated_alias_enumerates_sync_db(self) -> None:
		# With a sync DB, a templated alias searches pacman's index, and each result
		# is labeled with its actual repo (extra/cachyos/...), like `pacman -Ss`.
		fake = (
			("amd-ucode", "1-1", "AMD microcode", "core"),
			("yay", "12-1", "AUR helper", "cachyos"),
		)
		with mock.patch.object(grimoire, "_sync_db_packages", return_value=fake):
			results = grimoire.search_packages_repo(
				"https://gitlab/{pkgbase}.git",
				None,
				None,
				regex=None,
				needle="ucode",
				limit=None,
				source="arch",
				dest_root=self.root / "dest",
			)
		self.assertEqual([r.name for r in results], ["amd-ucode"])
		# label is the real repo, not the alias, and marked as a local DB source
		self.assertEqual(results[0].source, "core")
		self.assertTrue(results[0].from_db)
		self.assertIn("[db core]", grimoire.format_search_result(1, results[0])[0])
		self.assertTrue(
			grimoire.format_search_result_plain(results[0])[0].startswith(
				"core/amd-ucode"
			)
		)


class SparseCloneTests(unittest.TestCase):
	"""A monorepo clone checks out only the target package's subtree; a solo repo
	(PKGBUILD at the root) checks out whole (offline file://)."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		for name in ("SHALLOW_CLONE", "USE_SSH"):
			patcher = mock.patch.object(grimoire, name, False)
			patcher.start()
			self.addCleanup(patcher.stop)

	def _flat(self) -> Path:
		src = self.root / "flat"
		src.mkdir()
		_git(src, "init", "-q", "-b", "master")
		for name in ("foo", "bar"):
			(src / name).mkdir()
			(src / name / "PKGBUILD").write_text(f"pkgname={name}\npkgver=1\n")
		_git(src, "add", "-A")
		_git(src, "commit", "-qm", "x")
		return src

	def test_flat_checks_out_only_target(self) -> None:
		src = self._flat()
		dest = self.root / "d1"
		build = grimoire.ensure_clone(
			"foo", dest, refresh=False, repo_url=f"file://{src}"
		)
		self.assertEqual(build, dest / "foo" / "foo")
		self.assertTrue((build / "PKGBUILD").is_file())
		# Sparse: the other package's dir is not materialized in the worktree.
		self.assertFalse((dest / "foo" / "bar").exists())

	def test_flat_miss_is_absent_without_checkout(self) -> None:
		# A package absent from a flat monorepo is detected via ls-tree (treeless clone),
		# not a full checkout: the source resolves as "not found" and leaves nothing.
		src = self._flat()
		dest = self.root / "dmiss"
		with self.assertRaises(grimoire.AurGitError) as ctx:
			grimoire._clone_any_source(
				"baz", dest, [(f"file://{src}", None, None, [])], refresh=False
			)
		self.assertIn("not found in any configured source", str(ctx.exception))
		self.assertFalse((dest / "baz").exists())

	def test_subdir_container_checks_out_only_target(self) -> None:
		src = self.root / "cont"
		src.mkdir()
		_git(src, "init", "-q", "-b", "master")
		for name in ("foo", "bar"):
			(src / "pkgs" / name).mkdir(parents=True)
			(src / "pkgs" / name / "PKGBUILD").write_text(f"pkgname={name}\npkgver=1\n")
		_git(src, "add", "-A")
		_git(src, "commit", "-qm", "x")
		dest = self.root / "d2"
		build = grimoire.ensure_clone(
			"foo", dest, refresh=False, repo_url=f"file://{src}", subdir="pkgs"
		)
		self.assertEqual(build, dest / "foo" / "pkgs" / "foo")
		self.assertFalse((dest / "foo" / "pkgs" / "bar").exists())

	def test_solo_repo_checks_out_whole_tree(self) -> None:
		# PKGBUILD at the root -> not a container; the whole tree (incl. sibling dirs)
		# must survive, so no sparse narrowing.
		src = self.root / "solo"
		src.mkdir()
		_git(src, "init", "-q", "-b", "master")
		(src / "PKGBUILD").write_text("pkgname=foo\npkgver=1\n")
		(src / "data").mkdir()
		(src / "data" / "patch.diff").write_text("x\n")
		_git(src, "add", "-A")
		_git(src, "commit", "-qm", "x")
		dest = self.root / "d3"
		build = grimoire.ensure_clone(
			"foo", dest, refresh=False, repo_url=f"file://{src}"
		)
		self.assertEqual(build, dest / "foo")
		self.assertTrue((build / "PKGBUILD").is_file())
		self.assertTrue((build / "data" / "patch.diff").is_file())


class FlatRepoSearchTests(unittest.TestCase):
	"""search enumeration of a flat repo: package dirs at the root, no subdir, a
	single branch (offline file://). Distinguished from branch-per-package by head
	count."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.src = self.root / "src"
		self.src.mkdir()
		_git(self.src, "init", "-q", "-b", "master")
		for name, ver in (("foo", "1.0"), ("bar", "2.0")):
			d = self.src / name
			d.mkdir()
			(d / "PKGBUILD").write_text(f"pkgname={name}\npkgver={ver}\npkgrel=1\n")
			(d / ".SRCINFO").write_text(
				f"pkgbase = {name}\n\tpkgver = {ver}\n\tpkgrel = 1\n"
				f"\tpkgdesc = {name} desc\n\npkgname = {name}\n"
			)
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "init")
		patcher = mock.patch.object(
			grimoire, "installed_package_set", return_value=set()
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_enumerates_root_packages(self) -> None:
		results = grimoire.search_packages_repo(
			f"file://{self.src}",
			None,
			None,
			regex=None,
			needle="",
			limit=None,
			source="FLAT",
			dest_root=self.root / "dest",
		)
		by_name = {r.name: r for r in results}
		self.assertEqual(set(by_name), {"foo", "bar"})
		self.assertEqual(by_name["bar"].version, "2.0-1")
		self.assertEqual(by_name["foo"].description, "foo desc")

	def test_extra_branches_do_not_break_flat_detection(self) -> None:
		# A flat repo may carry arch/variant branches (like archpower); the default
		# ref still has the package dirs, so it stays flat -- not branch-per-package.
		_git(self.src, "branch", "powerpc")
		_git(self.src, "branch", "riscv64")
		names = grimoire._repo_package_names(
			f"file://{self.src}", None, None, self.root / "scratch"
		)
		self.assertEqual({n for n, _ in names}, {"foo", "bar"})


class BranchPerPackageSearchTests(unittest.TestCase):
	"""A repo whose default ref has no package dirs but one branch per package falls
	back to ls-remote enumeration (offline file://)."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.src = self.root / "src"
		self.src.mkdir()
		_git(self.src, "init", "-q", "-b", "master")
		(self.src / "README").write_text("index branch, packages live on branches\n")
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "readme")
		for pkg in ("pkga", "pkgb"):
			_git(self.src, "branch", pkg)

	def test_falls_back_to_ls_remote(self) -> None:
		names = grimoire._repo_package_names(
			f"file://{self.src}", None, None, self.root / "scratch"
		)
		self.assertEqual({n for n, _ in names}, {"master", "pkga", "pkgb"})


class CloneAnySourceTests(unittest.TestCase):
	"""Cross-section fallback chain: try sources in order, first that clones a
	PKGBUILD wins; clone failures and PKGBUILD-less containers are skipped."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.dest = self.root / "dest"
		# `has`: foo's PKGBUILD at root. `lacks`: a git repo without it (container
		# miss). `bad`: a URL that never clones.
		self.has = self.root / "has"
		self.lacks = self.root / "lacks"
		for repo, files in (
			(self.has, {"PKGBUILD": "pkgname=foo\npkgver=1\n"}),
			(self.lacks, {"README": "no pkgbuild here\n"}),
		):
			repo.mkdir()
			_git(repo, "init", "-q", "-b", "master")
			for name, body in files.items():
				(repo / name).write_text(body)
			_git(repo, "add", "-A")
			_git(repo, "commit", "-qm", "x")
		self.bad = "file:///definitely/not/here.git"
		for name in ("SHALLOW_CLONE", "USE_SSH"):
			patcher = mock.patch.object(grimoire, name, False)
			patcher.start()
			self.addCleanup(patcher.stop)

	def _src(self, url: str) -> tuple[str, None, None, list]:
		return (url, None, None, [])

	def test_first_with_pkgbuild_wins(self) -> None:
		pkg_dir = grimoire._clone_any_source(
			"foo",
			self.dest,
			[self._src(f"file://{self.has}"), self._src(self.bad)],
			refresh=False,
		)
		self.assertTrue((pkg_dir / "PKGBUILD").is_file())

	def test_clone_failure_falls_through(self) -> None:
		pkg_dir = grimoire._clone_any_source(
			"foo",
			self.dest,
			[self._src(self.bad), self._src(f"file://{self.has}")],
			refresh=False,
		)
		self.assertTrue((pkg_dir / "PKGBUILD").is_file())

	def test_pkgbuildless_container_falls_through(self) -> None:
		# A source that clones but lacks the package is skipped for the next source.
		pkg_dir = grimoire._clone_any_source(
			"foo",
			self.dest,
			[self._src(f"file://{self.lacks}"), self._src(f"file://{self.has}")],
			refresh=False,
		)
		self.assertTrue((pkg_dir / "PKGBUILD").is_file())

	def test_all_sources_fail_raises(self) -> None:
		with self.assertRaises(grimoire.AurGitError) as ctx:
			grimoire._clone_any_source(
				"foo",
				self.dest,
				[self._src(self.bad), self._src("file:///also/missing.git")],
				refresh=False,
			)
		self.assertIn("not found in any configured source", str(ctx.exception))


class VerifyCommitTests(unittest.TestCase):
	"""--verify: a tagged HEAD verifies the tag, else the commit; must pass or abort
	(offline file://, no GPG key needed -- all targets here are unsigned)."""

	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.repo = Path(tmp.name) / "r"
		self.repo.mkdir()
		_git(self.repo, "init", "-q", "-b", "master")
		(self.repo / "PKGBUILD").write_text("pkgname=foo\npkgver=1\n")
		_git(self.repo, "add", "-A")
		_git(self.repo, "commit", "-qm", "unsigned")

	def test_unsigned_head_raises(self) -> None:
		# No ref -> commit path.
		with self.assertRaises(grimoire.AurGitError) as ctx:
			grimoire._verify_signature(self.repo, "foo")
		self.assertIn("signature verification failed", str(ctx.exception))
		self.assertIn("HEAD commit", str(ctx.exception))

	def test_ref_is_annotated_tag(self) -> None:
		_git(self.repo, "tag", "-a", "v1", "-m", "release")  # annotated
		_git(self.repo, "tag", "light")  # lightweight
		self.assertTrue(grimoire._ref_is_annotated_tag(self.repo, "v1"))
		self.assertFalse(grimoire._ref_is_annotated_tag(self.repo, "light"))
		self.assertFalse(grimoire._ref_is_annotated_tag(self.repo, "master"))

	def test_tag_ref_takes_tag_path(self) -> None:
		_git(self.repo, "tag", "-a", "v1", "-m", "release")  # annotated, unsigned
		with self.assertRaises(grimoire.AurGitError) as ctx:
			grimoire._verify_signature(self.repo, "foo", "v1")
		self.assertIn("tag v1", str(ctx.exception))

	def test_branch_ref_uses_commit_path(self) -> None:
		# A branch ref is not a tag object -> commit path (message names the commit).
		with self.assertRaises(grimoire.AurGitError) as ctx:
			grimoire._verify_signature(self.repo, "foo", "master")
		self.assertIn("HEAD commit", str(ctx.exception))

	def test_valid_signature_passes(self) -> None:
		# A good verify exit (0) returns without raising; mock the git call so the test
		# needs no GPG key. No ref -> commit path.
		with mock.patch.object(grimoire, "run_command", return_value=""):
			grimoire._verify_signature(self.repo, "foo")


if __name__ == "__main__":
	unittest.main()
