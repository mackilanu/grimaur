"""Dependencies grimoire installs must be marked --asdeps so `pacman -Qdt` can
find them once unneeded; the requested package and anything already installed
keep their install reason (an explicit --asdeps would rewrite it)."""

import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire


class OfficialDepsTests(unittest.TestCase):
	def _run(self, packages: set[str], installed: set[str]) -> list[list[str]]:
		calls: list[list[str]] = []
		with (
			mock.patch.object(
				grimoire, "run_command", lambda cmd, **_: calls.append(list(cmd))
			),
			mock.patch.object(grimoire, "_elevate", lambda cmd: cmd),
			mock.patch.object(grimoire, "is_installed", lambda p: p in installed),
		):
			grimoire.install_official_packages(packages, noconfirm=True)
		return calls

	def test_fresh_deps_installed_asdeps(self) -> None:
		calls = self._run({"b", "a"}, installed=set())
		self.assertEqual(
			calls, [["pacman", "-S", "--needed", "--asdeps", "--noconfirm", "a", "b"]]
		)

	def test_installed_dep_keeps_its_reason(self) -> None:
		calls = self._run({"new", "old"}, installed={"old"})
		self.assertEqual(
			calls,
			[
				["pacman", "-S", "--needed", "--asdeps", "--noconfirm", "new"],
				["pacman", "-S", "--needed", "--noconfirm", "old"],
			],
		)

	def test_empty_is_noop(self) -> None:
		self.assertEqual(self._run(set(), installed=set()), [])


class AurDepsTests(unittest.TestCase):
	def _install(self, installed: set[str]) -> dict[str, bool]:
		# top -> auradep; record the as_dep each one is built with.
		built: dict[str, bool] = {}
		deps = {"top": {"auradep"}, "auradep": set()}

		def classify(
			_deps: object, package: str
		) -> tuple[set[str], set[str], set[str], dict[str, set[str]]]:
			return set(), deps[package], set(), {}

		def build(package_dir: Path, **kwargs: bool) -> None:
			built[package_dir.name] = kwargs["as_dep"]

		with (
			mock.patch.object(grimoire, "is_installed", lambda p: p in installed),
			mock.patch.object(grimoire, "get_installed_version", lambda _: "1"),
			mock.patch.object(
				grimoire, "_clone_resolved", lambda pkg, *_, **__: Path(pkg)
			),
			mock.patch.object(grimoire, "read_srcinfo", lambda _: ""),
			mock.patch.object(grimoire, "parse_dependencies", lambda _: ("", None)),
			mock.patch.object(grimoire, "_classify_build_deps", classify),
			mock.patch.object(grimoire, "_import_source_keys", lambda _: None),
			mock.patch.object(grimoire, "build_and_install", build),
		):
			grimoire.install_package(
				"top", Path("/nonexistent"), refresh=False, noconfirm=True
			)
		return built

	def test_dep_asdeps_target_explicit(self) -> None:
		self.assertEqual(self._install(set()), {"auradep": True, "top": False})

	def test_installed_dep_not_demoted(self) -> None:
		# e.g. rebuilt to satisfy a version constraint
		built = self._install({"auradep"})
		self.assertEqual(built, {"auradep": False, "top": False})


class MakepkgFlagTests(unittest.TestCase):
	def _argv(self, root: Path, *, as_dep: bool) -> list[str]:
		calls: list[list[str]] = []
		(root / "PKGBUILD").write_text("pkgname=foo\npkgver=1\n")
		with (
			mock.patch.object(
				grimoire, "run_command", lambda cmd, **_: calls.append(list(cmd))
			),
			mock.patch.object(grimoire, "_debug_pkgs_enabled", lambda: True),
			mock.patch.object(grimoire.CONFIG, "dest_root", root),
		):
			grimoire.build_and_install(root, noconfirm=True, as_dep=as_dep)
		return calls[-1]

	def test_asdeps_flag(self) -> None:
		import tempfile

		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			self.assertIn("--asdeps", self._argv(root, as_dep=True))
			self.assertNotIn("--asdeps", self._argv(root, as_dep=False))


if __name__ == "__main__":
	unittest.main()
