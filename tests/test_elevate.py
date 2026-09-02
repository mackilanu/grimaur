"""_elevate hands the privilege tool an absolute argv[0]. doas matches `cmd`
rules against the string as typed, so `doas pacman` never satisfies a
`cmd /usr/bin/pacman` rule; makepkg already passes the full path."""

import unittest
from unittest import mock

from grimoireshim import grimoire


class ElevateTests(unittest.TestCase):
	def setUp(self) -> None:
		for target, value in (
			(grimoire.os, "geteuid"),
			(grimoire, "_get_elev"),
		):
			patcher = mock.patch.object(target, value)
			patcher.start()
			self.addCleanup(patcher.stop)
		grimoire.os.geteuid.return_value = 1000

	def test_argv0_resolved_to_absolute_path(self) -> None:
		grimoire._get_elev.return_value = "doas"
		with mock.patch.object(
			grimoire.shutil, "which", return_value="/usr/bin/pacman"
		):
			cmd = grimoire._elevate(["pacman", "-S", "--needed", "pkg"])
		self.assertEqual(cmd, ["doas", "/usr/bin/pacman", "-S", "--needed", "pkg"])

	def test_unresolvable_argv0_kept(self) -> None:
		grimoire._get_elev.return_value = "sudo"
		with mock.patch.object(grimoire.shutil, "which", return_value=None):
			cmd = grimoire._elevate(["pacman", "-Syu"])
		self.assertEqual(cmd, ["sudo", "pacman", "-Syu"])

	def test_su_joins_resolved_command(self) -> None:
		grimoire._get_elev.return_value = "su"
		with mock.patch.object(
			grimoire.shutil, "which", return_value="/usr/bin/pacman"
		):
			cmd = grimoire._elevate(["pacman", "-Rns", "pkg"])
		self.assertEqual(cmd, ["su", "-c", "/usr/bin/pacman -Rns pkg", "root"])

	def test_root_passes_through(self) -> None:
		grimoire.os.geteuid.return_value = 0
		self.assertEqual(grimoire._elevate(["pacman", "-Syu"]), ["pacman", "-Syu"])


if __name__ == "__main__":
	unittest.main()
