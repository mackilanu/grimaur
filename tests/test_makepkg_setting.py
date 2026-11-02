"""[MAKEPKG] swaps the makepkg used for builds and .SRCINFO (with its own lib/);
packages a custom makepkg built but -i didn't install are listed, never installed."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire


class _ConfFixture(unittest.TestCase):
	def setUp(self) -> None:
		self.tmp = Path(tempfile.mkdtemp())
		self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
		self.conf: dict[str, list[str]] = {}
		patcher = mock.patch.object(grimoire, "load_repo_registry", lambda: self.conf)
		patcher.start()
		self.addCleanup(patcher.stop)
		env = mock.patch.dict(os.environ)
		env.start()
		self.addCleanup(env.stop)
		os.environ.pop("MAKEPKG_LIBRARY", None)

	def _fork(self, *, lib: bool = True) -> Path:
		root = self.tmp / "fork"
		root.mkdir()
		exe = root / "makepkg"
		exe.write_text("#!/bin/sh\n")
		exe.chmod(0o755)
		if lib:
			(root / "lib").mkdir()
		return root


class MakepkgResolutionTests(_ConfFixture):
	def test_unset_is_system_makepkg(self) -> None:
		self.assertEqual(grimoire._makepkg(), ("makepkg", {}))
		self.conf["MAKEPKG"] = ["false"]
		self.assertEqual(grimoire._makepkg(), ("makepkg", {}))

	def test_checkout_dir_exports_its_lib(self) -> None:
		root = self._fork()
		self.conf["MAKEPKG"] = [str(root)]
		self.assertEqual(
			grimoire._makepkg(),
			(str(root / "makepkg"), {"MAKEPKG_LIBRARY": str(root / "lib")}),
		)

	def test_executable_path_without_lib(self) -> None:
		root = self._fork(lib=False)
		self.conf["MAKEPKG"] = [str(root / "makepkg")]
		self.assertEqual(grimoire._makepkg(), (str(root / "makepkg"), {}))

	def test_user_makepkg_library_wins(self) -> None:
		root = self._fork()
		self.conf["MAKEPKG"] = [str(root)]
		os.environ["MAKEPKG_LIBRARY"] = "/mine"
		self.assertEqual(grimoire._makepkg(), (str(root / "makepkg"), {}))

	def test_bad_path_is_an_error(self) -> None:
		self.conf["MAKEPKG"] = [str(self.tmp / "nope")]
		with self.assertRaisesRegex(grimoire.GrimoireErr, r"\[MAKEPKG\]"):
			grimoire._makepkg()

	def test_reserved_name_is_not_a_repo(self) -> None:
		self.conf["MAKEPKG"] = [str(self._fork())]
		with self.assertRaisesRegex(grimoire.GrimoireErr, "reserved"):
			grimoire.resolve_repo_alias("MAKEPKG")
		self.assertNotIn("MAKEPKG", grimoire._source_sections())


class BuildCallSiteTests(_ConfFixture):
	def setUp(self) -> None:
		super().setUp()
		self.root = self._fork()
		self.conf["MAKEPKG"] = [str(self.root)]
		self.pkgdir = self.tmp / "foo"
		self.pkgdir.mkdir()
		(self.pkgdir / "PKGBUILD").write_text("pkgname=foo\n")
		self.calls: list[tuple[list[str], dict[str, str]]] = []
		patcher = mock.patch.object(grimoire.CONFIG, "dest_root", self.tmp)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _fake_run(self, listed: str = ""):  # type: ignore[no-untyped-def]
		def run(cmd: list[str], **kwargs: object) -> str:
			env = kwargs.get("env")
			self.calls.append((list(cmd), dict(env) if isinstance(env, dict) else {}))
			return listed if "--packagelist" in cmd else ""

		return run

	def test_build_and_srcinfo_use_the_fork_and_its_lib(self) -> None:
		exe = str(self.root / "makepkg")
		with (
			mock.patch.object(grimoire, "run_command", self._fake_run()),
			mock.patch.object(grimoire, "_debug_pkgs_enabled", lambda: True),
		):
			grimoire.build_and_install(self.pkgdir, noconfirm=True)
			grimoire.read_srcinfo(self.pkgdir)  # no .SRCINFO -> generated
		argv0s = [c[0][0] for c in self.calls]
		self.assertEqual(set(argv0s), {exe})
		for _, env in self.calls:
			self.assertEqual(env.get("MAKEPKG_LIBRARY"), str(self.root / "lib"))

	def test_uninstalled_splits_listed_not_installed(self) -> None:
		out = self.tmp / "out"
		out.mkdir()
		main = out / "foo-1-1-x86_64.pkg.tar.zst"
		docs = out / "foo-docs-1:2.0-1-any.pkg.tar.zst"
		pyc = out / "foo-pyc-opt-1-1-any.pkg.tar.zst"  # listed, never built
		main.touch()
		docs.touch()
		listed = f"{main}\n{docs}\n{pyc}\n"
		printed: list[str] = []
		with (
			mock.patch.object(grimoire, "run_command", self._fake_run(listed)),
			mock.patch.object(grimoire, "_debug_pkgs_enabled", lambda: True),
			mock.patch.object(grimoire, "is_installed", lambda n: n == "foo"),
			mock.patch(
				"builtins.print", lambda *a, **_: printed.append(" ".join(map(str, a)))
			),
		):
			grimoire.build_and_install(self.pkgdir, noconfirm=True)
		build = self.calls[0][0]
		self.assertNotIn("--packagelist", build)
		self.assertTrue(any(str(docs) in line for line in printed))
		self.assertFalse(any(str(main) in line or str(pyc) in line for line in printed))
		# nothing besides the one makepkg build ran an install
		self.assertEqual(sum("-si" in c[0] for c in self.calls), 1)


if __name__ == "__main__":
	unittest.main()
