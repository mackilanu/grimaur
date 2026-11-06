"""--head: build a release PKGBUILD from upstream's default branch.

The planner picks which source entry to swap (a pinned git+ source, a forge
release archive, or url= as the repo), _head_buildfile renders the `makepkg -p`
overlay. The overlay itself is exercised in bash against a fixture PKGBUILD:
makepkg isn't needed to check the array surgery, the pkgver() scheme, or that
the release functions still see the release pkgver after makepkg's rewrite.
"""

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire


def _srcinfo(*lines: str, pkgver: str = "1.2.3", url: str = "") -> str:
	head = ["pkgbase = foo", f"\tpkgver = {pkgver}", "\tpkgrel = 1"]
	if url:
		head.append(f"\turl = {url}")
	return "\n".join([*head, *(f"\t{line}" for line in lines), "", "pkgname = foo"])


class PlanTests(unittest.TestCase):
	def test_github_archive_drops_its_signature(self) -> None:
		plan = grimoire._plan_head(
			_srcinfo(
				"source = foo-1.2.3.tar.gz::https://github.com/o/foo/archive/v1.2.3.tar.gz",
				"source = foo-1.2.3.tar.gz.sig::https://github.com/o/foo/archive/v1.2.3.tar.gz.sig",
				"source = fix.patch",
			)
		)
		if plan is None:
			self.fail("no plan for a github archive")
		self.assertEqual(plan.slot, 0)
		self.assertEqual(plan.entry, "foo::git+https://github.com/o/foo")
		self.assertEqual(plan.drop, [1])
		# the dir the release functions cd into resolves onto the clone
		self.assertIn("foo-1.2.3", plan.links)
		self.assertNotIn("foo", plan.links)

	def test_pinned_git_is_unpinned_and_keeps_its_dir(self) -> None:
		plan = grimoire._plan_head(
			_srcinfo("source = git+https://github.com/o/fzf.git#tag=v1.2.3?signed")
		)
		if plan is None:
			self.fail("no plan for a pinned git source")
		self.assertEqual(plan.entry, "fzf::git+https://github.com/o/fzf.git")
		self.assertEqual(plan.src_name, "fzf")
		self.assertEqual(plan.links, [])

	def test_homepage_names_the_repo_for_a_registry_tarball(self) -> None:
		plan = grimoire._plan_head(
			_srcinfo(
				"source = https://files.pythonhosted.org/packages/source/f/foo/foo-1.2.3.tar.gz",
				url="https://github.com/o/foo/tree/main",
			)
		)
		if plan is None:
			self.fail("url= fallback found nothing")
		self.assertEqual(plan.entry, "foo::git+https://github.com/o/foo")

	def test_gitlab_subgroup_and_codeload(self) -> None:
		gitlab = grimoire._forge_repo_from_archive(
			"https://gitlab.com/g/sub/foo/-/archive/v1/foo-v1.tar.gz"
		)
		self.assertEqual(gitlab, "https://gitlab.com/g/sub/foo")
		codeload = grimoire._forge_repo_from_archive(
			"https://codeload.github.com/o/foo/tar.gz/refs/tags/v1"
		)
		self.assertEqual(codeload, "https://github.com/o/foo")

	def test_unrelated_tarballs_are_not_upstream(self) -> None:
		# no pkgver in the URL (a vendored blob) and a non-forge homepage: nothing to track
		srcinfo = _srcinfo(
			"source = https://github.com/o/vendored/archive/abc123.tar.gz",
			url="https://foo.example.org",
		)
		self.assertIsNone(grimoire._plan_head(srcinfo))


FIXTURE_PKGBUILD = """\
pkgname=foo
pkgver=1.2.3
pkgrel=1
_tag=v$pkgver
source=("foo-$pkgver.tar.gz::https://github.com/o/foo/archive/$_tag.tar.gz"
	"foo-$pkgver.tar.gz.sig::https://github.com/o/foo/archive/$_tag.tar.gz.sig"
	fix.patch)
sha256sums=(aaa bbb ccc)

build() {
	cd "$pkgname-$pkgver"
	echo "build $pkgver $_tag $(basename "$(pwd -P)")"
}
"""


class BuildfileRuntimeTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		(self.root / "PKGBUILD").write_text(FIXTURE_PKGBUILD)
		(self.root / "src" / "foo").mkdir(parents=True)
		srcinfo = _srcinfo(
			"source = foo-1.2.3.tar.gz::https://github.com/o/foo/archive/v1.2.3.tar.gz",
			"source = foo-1.2.3.tar.gz.sig::https://github.com/o/foo/archive/v1.2.3.tar.gz.sig",
			"source = fix.patch",
			"sha256sums = aaa",
			"sha256sums = bbb",
			"sha256sums = ccc",
		)
		(self.root / ".SRCINFO").write_text(srcinfo)
		buildfile = grimoire._write_head_buildfile(self.root)
		if buildfile is None:
			self.fail("no buildfile written")
		self.buildfile = buildfile

	def _bash(self, script: str) -> str:
		# makepkg's own globals: startdir (where -p resolves) and srcdir.
		env = f"startdir={self.root}; srcdir={self.root}/src; cd {self.root}/src\n"
		out = subprocess.run(
			["bash", "-ec", env + textwrap.dedent(script)],
			capture_output=True,
			text=True,
			check=False,
		)
		self.assertEqual(out.returncode, 0, out.stderr)
		return out.stdout

	def test_arrays_swap_source_and_drop_signature(self) -> None:
		out = self._bash(f"""
			source {self.buildfile}
			printf '%s\\n' "${{source[@]}}" -- "${{sha256sums[@]}}" -- "${{makedepends[@]}}"
		""")
		self.assertEqual(
			out.split(),
			[
				"foo::git+https://github.com/o/foo",
				"fix.patch",
				"--",
				"SKIP",
				"ccc",
				"--",
				"git",
			],
		)

	def test_functions_keep_release_pkgver_after_makepkg_rewrite(self) -> None:
		# Mirror makepkg's update_pkgver: rewrite the buildfile's pkgver= line, re-source.
		out = self._bash(f"""
			source {self.buildfile}
			sed -i 's/^pkgver=.*/pkgver=1.2.4.r2.gabcdef0/' {self.buildfile}
			source {self.buildfile}
			echo "global $pkgver"
			build
		""")
		self.assertEqual(
			out.splitlines(), ["global 1.2.4.r2.gabcdef0", "build 1.2.3 v1.2.3 foo"]
		)

	def test_pkgver_scheme(self) -> None:
		repo = self.root / "src" / "foo"
		git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
		subprocess.run([*git, "init", "-q"], check=True)
		cases = (("v1.0", "1.2.3"), ("v1.2.4", "1.2.4"), ("weird-tag", "1.2.3"))
		for tag, base in cases:
			with self.subTest(tag=tag):
				subprocess.run(
					[*git, "commit", "-q", "--allow-empty", "-m", tag], check=True
				)
				subprocess.run([*git, "tag", tag], check=True)
				for i in range(2):
					subprocess.run(
						[*git, "commit", "-q", "--allow-empty", "-m", str(i)],
						check=True,
					)
				sha = subprocess.run(
					[*git, "rev-parse", "--short=7", "HEAD"],
					capture_output=True,
					text=True,
					check=True,
				).stdout.strip()
				out = self._bash(f"source {self.buildfile}; pkgver")
				self.assertEqual(out, f"{base}.r2.g{sha}")


class BuildIntegrationTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.addCleanup(setattr, grimoire.CONFIG, "dest_root", None)
		grimoire.CONFIG.dest_root = self.root
		(self.root / ".SRCINFO").write_text(
			_srcinfo("source = git+https://github.com/o/foo.git#tag=v1.2.3")
		)

	def _argv(self, pkgbuild: str, *, head: bool) -> list[str]:
		(self.root / "PKGBUILD").write_text(pkgbuild)
		calls: list[list[str]] = []

		def fake_run(cmd: list[str], **kwargs: object) -> None:
			calls.append(list(cmd))

		with mock.patch.object(grimoire, "run_command", fake_run):
			grimoire.build_and_install(self.root, noconfirm=True, head=head)
		return calls[-1]

	def test_head_passes_the_buildfile(self) -> None:
		argv = self._argv("pkgname=foo\npkgver=1.2.3\n", head=True)
		self.assertEqual(argv[argv.index("-p") + 1], grimoire._HEAD_BUILDFILE)
		self.assertTrue((self.root / grimoire._HEAD_BUILDFILE).is_file())

	def test_vcs_pkgbuild_builds_as_is(self) -> None:
		argv = self._argv("pkgname=foo-git\npkgver=r1\npkgver() { :; }\n", head=True)
		self.assertNotIn("-p", argv)

	def test_no_head_no_buildfile(self) -> None:
		argv = self._argv("pkgname=foo\npkgver=1.2.3\n", head=False)
		self.assertNotIn("-p", argv)

	def test_head_is_global_and_hoistable(self) -> None:
		parser, _ = grimoire.build_parser()
		self.assertIn("--head", grimoire._GLOBAL_FLAG_OPTIONS)
		self.assertTrue(parser.parse_args(["--head", "install", "foo"]).head)


def _git(repo: Path, *args: str) -> str:
	out = subprocess.run(
		["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
		capture_output=True,
		text=True,
		check=True,
	)
	return out.stdout.strip()


class UpdateHeadTests(unittest.TestCase):
	# A --head build carries its commit in the version; update must neither "update"
	# it back to the release on a bare mismatch nor miss a moved upstream HEAD.
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		root = Path(tmp.name)
		self.dest = root / "dest"
		self.upstream = root / "upstream"
		self.pkg = root / "pkg"
		for repo in (self.upstream, self.pkg):
			repo.mkdir()
			_git(repo, "init", "-q", "-b", "master")
		_git(self.upstream, "commit", "-q", "--allow-empty", "-m", "v2")
		_git(self.upstream, "tag", "v2")
		_git(self.upstream, "commit", "-q", "--allow-empty", "-m", "after")
		self.built = _git(self.upstream, "rev-parse", "--short=7", "HEAD")
		(self.pkg / "PKGBUILD").write_text("pkgname=foo\npkgver=2\npkgrel=1\n")
		(self.pkg / ".SRCINFO").write_text(
			_srcinfo(f"source = git+file://{self.upstream}#tag=v2", pkgver="2")
		)
		_git(self.pkg, "add", "-A")
		_git(self.pkg, "commit", "-qm", "2-1")
		for name, value in (("use_shallow", False), ("use_ssh", False)):
			patcher = mock.patch.object(grimoire.CONFIG, name, value)
			patcher.start()
			self.addCleanup(patcher.stop)
		ign = mock.patch.object(grimoire, "get_ignored_packages", return_value=set())
		ign.start()
		self.addCleanup(ign.stop)

	def _update(self, installed: str, *, head: bool) -> list[str]:
		calls: list[str] = []

		def fake_install(pkg: str, dest: Path, **kw: object) -> None:
			calls.append(pkg)

		with (
			mock.patch.object(grimoire.CONFIG, "head", head),
			mock.patch.object(grimoire, "install_package", fake_install),
			mock.patch.object(
				grimoire, "get_installed_version", return_value=installed
			),
		):
			grimoire.update_packages(
				self.dest,
				refresh=False,
				noconfirm=True,
				update_system=False,
				include_devel=False,
				targets=["foo"],
				repo_url=f"file://{self.pkg}",
				branch="master",
			)
		return calls

	def test_head_build_is_not_downgraded_to_the_release(self) -> None:
		self.assertEqual(self._update(f"2.r1.g{self.built}-1", head=False), [])

	def test_unmoved_upstream_is_up_to_date(self) -> None:
		self.assertEqual(self._update(f"2.r1.g{self.built}-1", head=True), [])

	def test_moved_upstream_rebuilds(self) -> None:
		_git(self.upstream, "commit", "-q", "--allow-empty", "-m", "new")
		self.assertEqual(self._update(f"2.r1.g{self.built}-1", head=True), ["foo"])

	def test_newer_release_wins_without_head(self) -> None:
		self.assertEqual(self._update("1.r5.gabcdef0-1", head=False), ["foo"])


if __name__ == "__main__":
	unittest.main()
