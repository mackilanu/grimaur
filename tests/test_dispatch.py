"""Multi-package dispatch: install / fetch / inspect / remove each accept several
packages and invoke their worker once per package. Workers are mocked; only the
argv -> per-package call wiring is under test."""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire

URL = "file:///tmp/does-not-matter.git"


class MultiPackageDispatchTests(unittest.TestCase):
	def setUp(self) -> None:
		self._tmp = tempfile.mkdtemp()
		self.dest = str(Path(self._tmp) / "cache")
		self._orig = os.environ.get("XDG_CONFIG_HOME")
		os.environ["XDG_CONFIG_HOME"] = self._tmp
		# Never trip the root guard regardless of who runs the suite.
		patcher = mock.patch.object(grimoire.os, "geteuid", return_value=1000)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self) -> None:
		if self._orig is None:
			os.environ.pop("XDG_CONFIG_HOME", None)
		else:
			os.environ["XDG_CONFIG_HOME"] = self._orig
		shutil.rmtree(self._tmp, ignore_errors=True)

	def _main(self, *argv: str) -> int:
		with contextlib.redirect_stdout(io.StringIO()):
			rc: int = grimoire.main(["--dest-root", self.dest, *argv])
		return rc

	def test_fetch_calls_worker_per_package(self) -> None:
		with mock.patch.object(grimoire, "fetch_package") as fetch:
			rc = self._main("fetch", "a", "b", "c", "--repo-url", URL)
		self.assertEqual(rc, 0)
		self.assertEqual([c.args[0] for c in fetch.call_args_list], ["a", "b", "c"])

	def test_verify_flag_flows_to_workers(self) -> None:
		with mock.patch.object(grimoire, "fetch_package") as fetch:
			self._main("fetch", "a", "--repo-url", URL, "--verify")
		self.assertTrue(fetch.call_args_list[0].kwargs["verify"])
		with mock.patch.object(grimoire, "install_package") as install:
			self._main("install", "a", "--repo-url", URL, "--verify")
		self.assertTrue(install.call_args_list[0].kwargs["verify"])

	def test_verify_defaults_off(self) -> None:
		with mock.patch.object(grimoire, "fetch_package") as fetch:
			self._main("fetch", "a", "--repo-url", URL)
		self.assertFalse(fetch.call_args_list[0].kwargs["verify"])

	def test_min_trust_implies_verify(self) -> None:
		# --min-trust alone turns on verification and carries the level through.
		with mock.patch.object(grimoire, "install_package") as install:
			self._main("install", "a", "--repo-url", URL, "--min-trust", "fully")
		kw = install.call_args_list[0].kwargs
		self.assertEqual(kw["min_trust"], "fully")
		self.assertTrue(kw["verify"])
		with mock.patch.object(grimoire, "fetch_package") as fetch:
			self._main("fetch", "a", "--repo-url", URL, "--min-trust", "marginal")
		kw = fetch.call_args_list[0].kwargs
		self.assertEqual(kw["min_trust"], "marginal")
		self.assertTrue(kw["verify"])

	def test_submod_flag_flows_to_workers(self) -> None:
		with mock.patch.object(grimoire, "fetch_package") as fetch:
			self._main("fetch", "a", "--repo-url", URL, "--submod")
		self.assertTrue(fetch.call_args_list[0].kwargs["submodules"])
		with mock.patch.object(grimoire, "install_package") as install:
			self._main("install", "a", "--repo-url", URL, "--submod")
		self.assertTrue(install.call_args_list[0].kwargs["submodules"])
		with mock.patch.object(grimoire, "fetch_package") as fetch:
			self._main("fetch", "a", "--repo-url", URL)
		self.assertFalse(fetch.call_args_list[0].kwargs["submodules"])

	def test_install_calls_worker_per_package_sharing_state(self) -> None:
		with mock.patch.object(grimoire, "install_package") as install:
			rc = self._main("install", "a", "b", "--repo-url", URL)
		self.assertEqual(rc, 0)
		self.assertEqual([c.args[0] for c in install.call_args_list], ["a", "b"])
		# Same dedup + preinstalled sets threaded through every package in the run.
		visited = [c.kwargs["visited"] for c in install.call_args_list]
		self.assertIs(visited[0], visited[1])
		pre = [c.kwargs["preinstalled_official"] for c in install.call_args_list]
		self.assertIs(pre[0], pre[1])

	def test_inspect_calls_worker_per_package(self) -> None:
		with mock.patch.object(grimoire, "inspect_package") as inspect:
			rc = self._main("inspect", "a", "b", "--repo-url", URL)
		self.assertEqual(rc, 0)
		self.assertEqual([c.args[0] for c in inspect.call_args_list], ["a", "b"])

	def test_remove_calls_worker_per_package(self) -> None:
		with mock.patch.object(grimoire, "remove_package") as remove:
			rc = self._main("remove", "a", "b")
		self.assertEqual(rc, 0)
		self.assertEqual([c.args[0] for c in remove.call_args_list], ["a", "b"])

	def test_remove_nothing_without_cache_errors(self) -> None:
		with mock.patch.object(grimoire, "remove_package") as remove:
			rc = self._main("remove")
		self.assertEqual(rc, 2)
		remove.assert_not_called()

	def test_single_package_still_works(self) -> None:
		with mock.patch.object(grimoire, "fetch_package") as fetch:
			rc = self._main("fetch", "solo", "--repo-url", URL)
		self.assertEqual(rc, 0)
		self.assertEqual(fetch.call_count, 1)
		self.assertEqual(fetch.call_args.args[0], "solo")


if __name__ == "__main__":
	unittest.main()
