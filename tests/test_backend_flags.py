import unittest
from unittest import mock

from grimoireshim import grimoire


class BackendTriStateTests(unittest.TestCase):
	def test_default_is_auto(self) -> None:
		args = grimoire.build_parser().parse_args(["list"])
		self.assertIsNone(args.aur_rpc)

	def test_aur_rpc_forces_rpc(self) -> None:
		args = grimoire.build_parser().parse_args(["--aur-rpc", "list"])
		self.assertTrue(args.aur_rpc)

	def test_git_mirror_forces_mirror(self) -> None:
		args = grimoire.build_parser().parse_args(["--git-mirror", "list"])
		self.assertFalse(args.aur_rpc)

	def test_last_flag_wins(self) -> None:
		args = grimoire.build_parser().parse_args(["--git-mirror", "--aur-rpc", "list"])
		self.assertTrue(args.aur_rpc)


class DisableAurRpcTests(unittest.TestCase):
	def test_forced_rpc_raises_instead_of_falling_back(self) -> None:
		with (
			mock.patch.object(grimoire, "FORCE_AUR_RPC", True),
			mock.patch.object(grimoire, "USE_AUR_RPC", True),
		):
			with self.assertRaises(grimoire.AurRpcForcedError):
				grimoire.disable_aur_rpc("timed out")
			self.assertTrue(grimoire.USE_AUR_RPC)

	def test_auto_mode_falls_back(self) -> None:
		with (
			mock.patch.object(grimoire, "FORCE_AUR_RPC", False),
			mock.patch.object(grimoire, "FORCE_GIT_MIRROR", False),
			mock.patch.object(grimoire, "USE_AUR_RPC", True),
			mock.patch.object(grimoire, "_RPC_FALLBACK_NOTIFIED", True),
		):
			grimoire.disable_aur_rpc("timed out")
			self.assertFalse(grimoire.USE_AUR_RPC)

	def test_forced_error_is_not_swallowed_as_fallback_signal(self) -> None:
		self.assertNotIsInstance(grimoire.AurRpcForcedError("x"), grimoire.AurGitError)


if __name__ == "__main__":
	unittest.main()
