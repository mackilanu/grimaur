import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from grimoireshim import grimoire


class CacheHelperTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		patcher = mock.patch.object(grimoire.CONFIG, "cache_dir", Path(tmp.name))
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_roundtrip(self) -> None:
		grimoire._cache_put("search/abc.json", '{"ok": 1}')
		self.assertEqual(grimoire._cache_get("search/abc.json", ttl=60), '{"ok": 1}')

	def test_miss_when_absent(self) -> None:
		self.assertIsNone(grimoire._cache_get("nope.json", ttl=60))

	def test_disabled_when_cache_dir_unset(self) -> None:
		with mock.patch.object(grimoire.CONFIG, "cache_dir", None):
			grimoire._cache_put("search/abc.json", '{"ok": 1}')
			self.assertIsNone(grimoire._cache_get("search/abc.json", ttl=60))

	def test_miss_when_expired(self) -> None:
		grimoire._cache_put("packages.list", "foo\nbar")
		stale = time.time() - 120
		os.utime(grimoire.CONFIG.cache_dir / "packages.list", (stale, stale))
		self.assertIsNone(grimoire._cache_get("packages.list", ttl=60))

	def test_clear_search_cache_removes_dir(self) -> None:
		# subdir, so the enclosing TemporaryDirectory survives the rmtree
		sub = grimoire.CONFIG.cache_dir / ".searchcache"
		with mock.patch.object(grimoire.CONFIG, "cache_dir", sub):
			grimoire._cache_put("search/abc.json", '{"ok": 1}')
			grimoire.clear_search_cache()
			self.assertFalse(sub.exists())
			# idempotent when already gone
			grimoire.clear_search_cache()

	def test_expired_entry_is_pruned(self) -> None:
		grimoire._cache_put("packages.list", "foo\nbar")
		path = grimoire.CONFIG.cache_dir / "packages.list"
		stale = time.time() - 120
		os.utime(path, (stale, stale))
		grimoire._cache_get("packages.list", ttl=60)
		self.assertFalse(path.exists())


class CachedJsonTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		patcher = mock.patch.object(grimoire.CONFIG, "cache_dir", Path(tmp.name))
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_fetches_once_then_serves_from_disk(self) -> None:
		fetch = mock.Mock(return_value=["foo", "bar"])
		first = grimoire.cached_json("packages.json", 60, fetch)
		second = grimoire.cached_json("packages.json", 60, fetch)
		self.assertEqual(first, ["foo", "bar"])
		self.assertEqual(second, ["foo", "bar"])
		fetch.assert_called_once()

	def test_none_result_is_not_cached(self) -> None:
		fetch = mock.Mock(return_value=None)
		self.assertIsNone(grimoire.cached_json("srcinfo/x.json", 60, fetch))
		self.assertIsNone(grimoire.cached_json("srcinfo/x.json", 60, fetch))
		self.assertEqual(fetch.call_count, 2)

	def test_corrupt_entry_refetches(self) -> None:
		grimoire._cache_put("k.json", "{not json")
		fetch = mock.Mock(return_value={"ok": 1})
		self.assertEqual(grimoire.cached_json("k.json", 60, fetch), {"ok": 1})
		fetch.assert_called_once()

	def test_zero_ttl_refetches_and_repopulates(self) -> None:
		# --refresh sets CONFIG.cache_ttl=0: every read expires, writes still land
		grimoire._cache_put("k.json", '{"stale": 1}')
		stale = time.time() - 1
		os.utime(grimoire.CONFIG.cache_dir / "k.json", (stale, stale))
		fetch = mock.Mock(return_value={"fresh": 1})
		self.assertEqual(grimoire.cached_json("k.json", 0, fetch), {"fresh": 1})
		fetch.assert_called_once()
		self.assertEqual(
			json.loads((grimoire.CONFIG.cache_dir / "k.json").read_text()), {"fresh": 1}
		)


class NameSourceSelectionTests(unittest.TestCase):
	def test_meta_dump_primary_skips_git(self) -> None:
		with (
			mock.patch.object(
				grimoire, "_fetch_aur_meta", return_value=[("foo", "1-1", "d")]
			) as meta,
			mock.patch.object(grimoire, "_fetch_names_git") as git,
		):
			self.assertEqual(grimoire._fetch_aur_packages(), [("foo", "1-1", "d")])
		meta.assert_called_once()
		git.assert_not_called()

	def test_meta_failure_falls_back_to_git_names(self) -> None:
		stderr = io.StringIO()
		with (
			mock.patch.object(grimoire, "_fetch_aur_meta", return_value=None),
			mock.patch.object(
				grimoire, "_fetch_names_git", return_value=["bar"]
			) as git,
			contextlib.redirect_stderr(stderr),
		):
			self.assertEqual(grimoire._fetch_aur_packages(), [("bar", None, None)])
		git.assert_called_once()
		self.assertIn("git mirror", stderr.getvalue())

	def test_fresh_fetch_writes_completion_cache(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		# completion.cache (names only) lands in dest_root, sibling of .searchcache
		with (
			mock.patch.object(
				grimoire.CONFIG, "cache_dir", Path(tmp.name) / ".searchcache"
			),
			mock.patch.object(
				grimoire,
				"_fetch_aur_meta",
				return_value=[("foo", "1", None), ("bar", "2", None)],
			),
		):
			grimoire._fetch_aur_packages_with_completion()
		self.assertEqual(
			(Path(tmp.name) / "completion.cache").read_text(), "foo\nbar\n"
		)


class GitSearchCacheTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.cache_dir = Path(tmp.name)
		for obj, target, value in (
			(grimoire.CONFIG, "cache_dir", self.cache_dir),
			(grimoire, "installed_package_set", mock.Mock(return_value=set())),
		):
			patcher = mock.patch.object(obj, target, value)
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_matches_carry_meta_version_and_description(self) -> None:
		meta = [
			("foopkg", "1.0-1", "a foo"),
			("foolib", "2.0-1", "a lib"),
			("bar", "3-1", "x"),
		]
		with mock.patch.object(grimoire, "_fetch_aur_meta", return_value=meta):
			results = grimoire.search_packages_git(regex=None, needle="foo", limit=None)
		by_name = {r.name: r for r in results}
		self.assertEqual(set(by_name), {"foopkg", "foolib"})
		self.assertEqual(by_name["foopkg"].version, "1.0-1")
		self.assertEqual(by_name["foolib"].description, "a lib")

	def test_no_packages_returns_empty_and_caches_nothing(self) -> None:
		with (
			mock.patch.object(grimoire, "_fetch_aur_meta", return_value=None),
			mock.patch.object(grimoire, "_fetch_names_git", return_value=None),
		):
			results = grimoire.search_packages_git(regex=None, needle="zzz", limit=None)
		self.assertEqual(results, [])
		self.assertFalse((self.cache_dir / "aurmeta.json").exists())


if __name__ == "__main__":
	unittest.main()
