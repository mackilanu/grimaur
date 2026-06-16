"""update_packages version-check output: a versioned (semver/pkgrel) bump reports
old -> new from the repo .SRCINFO, and a VCS (*-git) package reports old -> short
git head. Drives a real file:// repo; the build step is mocked out."""

import contextlib
import io
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


class UpdateOutputTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.dest = self.root / "dest"
		self.src = self.root / "src"
		self.src.mkdir()
		_git(self.src, "init", "-q", "-b", "master")
		(self.src / "PKGBUILD").write_text(
			"pkgname=foo\npkgver=2\npkgrel=1\narch=(any)\n"
		)
		(self.src / ".SRCINFO").write_text(
			"pkgbase = foo\n\tpkgver = 2\n\tpkgrel = 1\n\tpkgdesc = t\n\npkgname = foo\n"
		)
		_git(self.src, "add", "-A")
		_git(self.src, "commit", "-qm", "v2")
		self.head = _git(self.src, "rev-parse", "HEAD")
		for name in ("use_shallow", "use_ssh"):
			patcher = mock.patch.object(grimoire.CONFIG, name, False)
			patcher.start()
			self.addCleanup(patcher.stop)
		ign = mock.patch.object(grimoire, "get_ignored_packages", return_value=set())
		ign.start()
		self.addCleanup(ign.stop)

	def _run_update(
		self, package: str, installed: str
	) -> tuple[str, list[dict[str, object]]]:
		calls: list[dict[str, object]] = []

		def _fake_install(pkg: str, dest: Path, **kw: object) -> None:
			calls.append({"pkg": pkg, **kw})

		buf = io.StringIO()
		with (
			mock.patch.object(grimoire, "install_package", _fake_install),
			mock.patch.object(
				grimoire, "get_installed_version", return_value=installed
			),
			contextlib.redirect_stdout(buf),
		):
			grimoire.update_packages(
				self.dest,
				refresh=False,
				noconfirm=True,
				update_system=False,
				include_devel=True,
				targets=[package],
				repo_url=f"file://{self.src}",
				branch="master",
			)
		return buf.getvalue(), calls

	def test_semver_bump_reports_old_to_new(self) -> None:
		out, calls = self._run_update("foo", "1-1")
		self.assertIn("foo 1-1 -> 2-1", out)
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0]["pkg"], "foo")
		self.assertEqual(calls[0]["update_to"], "2-1")

	def test_pkgrel_only_bump_detected(self) -> None:
		# Same pkgver, repo has -1 vs installed -2: still an update (string mismatch).
		out, _ = self._run_update("foo", "2-2")
		self.assertIn("foo 2-2 -> 2-1", out)

	def test_up_to_date_is_skipped(self) -> None:
		out, calls = self._run_update("foo", "2-1")
		self.assertIn("up to date", out)
		self.assertEqual(calls, [])

	def test_vcs_reports_short_git_head(self) -> None:
		out, calls = self._run_update("foo-git", "1-1")
		short = self.head[:7]
		self.assertIn(f"foo-git 1-1 -> {short}", out)
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0]["pkg"], "foo-git")
		self.assertEqual(calls[0]["update_to"], short)


if __name__ == "__main__":
	unittest.main()
