"""Build-time overrides ride a generated makepkg.conf overlay.

Env-var CFLAGS can't work: makepkg's load_makepkg_config only preserves a fixed
allowlist (PKGDEST..CARCH) and the conf files assign CFLAGS/OPTIONS
unconditionally. The overlay replays makepkg's config chain then appends the
overrides (--native compiler flags, the [DEBUG-PKGS] OPTIONS switch), and
build_and_install always passes it via `makepkg --config`. `nativeflags` prints
the expanded (machine-pinned) equivalents parsed from gcc/rustc output.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire

# Abbreviated from real `gcc -### -E - -march=native -mtune=native` stderr
# (gcc 16): mixed quoting, --param pairs, and the trailing `-dumpbase -`.
GCC_TRACE = """\
Using built-in specs.
COLLECT_GCC=gcc
Target: x86_64-pc-linux-gnu
gcc version 16.0.0 (GCC)
COLLECT_GCC_OPTIONS='-E' '-march=native' '-mtune=native'
 /usr/lib/gcc/x86_64-pc-linux-gnu/16/cc1 -E -quiet - "-march=alderlake" -mmmx \
-mavx2 -mno-sse4a --param "l1-cache-size=48" "-mtune=alderlake" -dumpbase -
"""

# Abbreviated from real `rustc -C target-cpu=native --print cfg` stdout,
# plus a synthetic crt-static line (some targets list it; it must be dropped).
RUSTC_CFG = """\
debug_assertions
panic="unwind"
target_arch="x86_64"
target_feature="adx"
target_feature="aes"
target_feature="crt-static"
target_feature="sse4.1"
target_has_atomic="64"
unix
"""


class ParseNativeFlagsTests(unittest.TestCase):
	def test_cc1_line_yields_flags_only(self) -> None:
		flags = grimoire._parse_cc1_flags(GCC_TRACE)
		if flags is None:
			self.fail("no flags parsed from cc1 line")
		self.assertTrue(flags.startswith("-march=alderlake"))
		self.assertIn("--param l1-cache-size=48", flags)
		self.assertIn("-mtune=alderlake", flags)
		# driver noise and the -dumpbase pair must not leak into CFLAGS
		self.assertNotIn("cc1", flags)
		self.assertNotIn("-quiet", flags)
		self.assertNotIn("-dumpbase", flags)
		self.assertNotIn('"', flags)

	def test_no_cc1_line_is_none(self) -> None:
		self.assertIsNone(grimoire._parse_cc1_flags("Using built-in specs.\n"))

	def test_rust_features_comma_plus_form(self) -> None:
		self.assertEqual(
			grimoire._parse_rust_features(RUSTC_CFG),
			"-Ctarget-feature=+adx,+aes,+sse4.1",
		)

	def test_rust_no_features_is_none(self) -> None:
		self.assertIsNone(grimoire._parse_rust_features("unix\n"))


class MakepkgOverlayTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.root = Path(tmp.name)
		self.addCleanup(setattr, grimoire.CONFIG, "native", False)
		self.addCleanup(setattr, grimoire.CONFIG, "dest_root", None)

	def _overlay(self, *, native: bool, debug: bool) -> str:
		with mock.patch.object(grimoire, "_debug_pkgs_enabled", lambda: debug):
			conf: Path = grimoire._write_makepkg_overlay(self.root, native=native)
		self.assertEqual(conf, self.root / "grimoire.makepkg.conf")
		return conf.read_text()

	def test_overlay_sources_chain_then_appends(self) -> None:
		text = self._overlay(native=True, debug=False)
		# makepkg skips /etc and user confs for a non-default --config file, so
		# the overlay must replay them itself, in makepkg's order, BEFORE the
		# appends (appended -march wins over the conf's -march=x86-64).
		order = [
			text.index("source /etc/makepkg.conf"),
			text.index("/etc/makepkg.conf.d/"),
			text.index("pacman/makepkg.conf"),
			text.index("$HOME/.makepkg.conf"),
			text.index('CFLAGS+=" -march=native -mtune=native"'),
			text.index('CXXFLAGS+=" -march=native -mtune=native"'),
			text.index('RUSTFLAGS+=" -C target-cpu=native"'),
			text.index("OPTIONS+=(!debug)"),
		]
		self.assertEqual(order, sorted(order))

	def test_no_native_keeps_flags_out(self) -> None:
		text = self._overlay(native=False, debug=False)
		self.assertNotIn("-march=native", text)
		self.assertIn("source /etc/makepkg.conf", text)

	def test_debug_toggle_drives_options_append(self) -> None:
		# OPTIONS is last-wins in makepkg, so the append is what decides, either way.
		self.assertIn("OPTIONS+=(!debug)", self._overlay(native=False, debug=False))
		self.assertIn("OPTIONS+=(debug)", self._overlay(native=False, debug=True))

	def _build(self, *, debug: bool) -> list[list[str]]:
		# makepkg itself is stubbed: what's under test is the argv and the
		# artifact pruning around it.
		(self.root / "PKGBUILD").write_text("pkgname=foo\npkgver=1\n")
		calls: list[list[str]] = []

		def fake_run(cmd: list[str], **kwargs: object) -> None:
			calls.append(list(cmd))

		grimoire.CONFIG.dest_root = self.root
		with (
			mock.patch.object(grimoire, "run_command", fake_run),
			mock.patch.object(grimoire, "_debug_pkgs_enabled", lambda: debug),
		):
			grimoire.build_and_install(self.root, noconfirm=True)
		return calls

	def test_build_always_passes_the_overlay(self) -> None:
		calls = self._build(debug=False)
		self.assertEqual(calls[-1][0], "makepkg")
		idx = calls[-1].index("--config")
		self.assertEqual(calls[-1][idx + 1], str(self.root / "grimoire.makepkg.conf"))

	def test_stale_debug_artifact_is_pruned(self) -> None:
		# makepkg installs <pkg>-debug-<ver> on file existence alone, so !debug
		# does not cover a tree that still holds one from an earlier build.
		keep = self.root / "foo-1-1-x86_64.pkg.tar.zst"
		stale = self.root / "foo-debug-1-1-x86_64.pkg.tar.zst"
		keep.touch()
		stale.touch()
		self._build(debug=False)
		self.assertFalse(stale.exists())
		self.assertTrue(keep.exists())

	def test_stale_debug_artifact_kept_when_enabled(self) -> None:
		stale = self.root / "foo-debug-1-1-x86_64.pkg.tar.zst"
		stale.touch()
		self._build(debug=True)
		self.assertTrue(stale.exists())


class NativeParserTests(unittest.TestCase):
	def test_native_is_global_and_hoistable(self) -> None:
		parser, commands = grimoire.build_parser()
		self.assertIn("nativeflags", commands)
		self.assertIn("--native", grimoire._GLOBAL_FLAG_OPTIONS)
		args = parser.parse_args(["--native", "install", "foo"])
		self.assertTrue(args.native)


if __name__ == "__main__":
	unittest.main()
