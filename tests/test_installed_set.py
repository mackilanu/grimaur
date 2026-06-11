import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grimaurshim import grimaur


class DbPathParseTests(unittest.TestCase):
	def test_matches_dbpath_line(self):
		match = grimaur._PACMAN_DBPATH_RE.match("DBPath      = /custom/db/")
		self.assertEqual(match.group(1), "/custom/db/")

	def test_ignores_commented_dbpath(self):
		self.assertIsNone(grimaur._PACMAN_DBPATH_RE.match("#DBPath = /var/lib/pacman/"))


class ListLocalDbPackagesTests(unittest.TestCase):
	def setUp(self):
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.db_root = Path(tmp.name)
		(self.db_root / "local").mkdir()
		patcher = mock.patch.object(
			grimaur, "_pacman_db_path", return_value=self.db_root
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_parses_entries_and_skips_sentinel(self):
		for entry in ("firefox-128.0-1", "lib32-glibc-2.39-2", "ALPM_DB_VERSION"):
			(self.db_root / "local" / entry).mkdir()
		self.assertEqual(grimaur._list_local_db_packages(), {"firefox", "lib32-glibc"})

	def test_returns_none_when_dir_missing(self):
		(self.db_root / "local").rmdir()
		self.assertIsNone(grimaur._list_local_db_packages())

	def test_returns_none_when_empty(self):
		self.assertIsNone(grimaur._list_local_db_packages())


if __name__ == "__main__":
	unittest.main()
