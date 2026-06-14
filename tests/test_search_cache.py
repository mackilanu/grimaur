import contextlib
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request  # ensure loaded: grimaur imports it lazily, tests patch it
from pathlib import Path
from unittest import mock

from grimaurshim import grimaur


def _search_cache_key(pattern: str) -> str:
	query = urllib.parse.urlencode(
		{"v": "5", "type": "search", "arg": pattern}, doseq=True
	)
	return f"search/{hashlib.sha256(query.encode()).hexdigest()}.json"


class CacheHelperTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		patcher = mock.patch.object(grimaur, "CACHE_DIR", Path(tmp.name))
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_roundtrip(self) -> None:
		grimaur.cache_put("search/abc.json", '{"ok": 1}')
		self.assertEqual(grimaur.cache_get("search/abc.json", ttl=60), '{"ok": 1}')

	def test_miss_when_absent(self) -> None:
		self.assertIsNone(grimaur.cache_get("nope.json", ttl=60))

	def test_disabled_when_cache_dir_unset(self) -> None:
		with mock.patch.object(grimaur, "CACHE_DIR", None):
			grimaur.cache_put("search/abc.json", '{"ok": 1}')
			self.assertIsNone(grimaur.cache_get("search/abc.json", ttl=60))

	def test_miss_when_expired(self) -> None:
		grimaur.cache_put("packages.list", "foo\nbar")
		stale = time.time() - 120
		os.utime(grimaur.CACHE_DIR / "packages.list", (stale, stale))
		self.assertIsNone(grimaur.cache_get("packages.list", ttl=60))

	def test_clear_search_cache_removes_dir(self) -> None:
		# subdir, so the enclosing TemporaryDirectory survives the rmtree
		sub = grimaur.CACHE_DIR / ".searchcache"
		with mock.patch.object(grimaur, "CACHE_DIR", sub):
			grimaur.cache_put("search/abc.json", '{"ok": 1}')
			grimaur.clear_search_cache()
			self.assertFalse(sub.exists())
			# idempotent when already gone
			grimaur.clear_search_cache()

	def test_expired_entry_is_pruned(self) -> None:
		grimaur.cache_put("packages.list", "foo\nbar")
		path = grimaur.CACHE_DIR / "packages.list"
		stale = time.time() - 120
		os.utime(path, (stale, stale))
		grimaur.cache_get("packages.list", ttl=60)
		self.assertFalse(path.exists())


class CachedJsonTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		patcher = mock.patch.object(grimaur, "CACHE_DIR", Path(tmp.name))
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_fetches_once_then_serves_from_disk(self) -> None:
		fetch = mock.Mock(return_value=["foo", "bar"])
		first = grimaur.cached_json("packages.json", 60, fetch)
		second = grimaur.cached_json("packages.json", 60, fetch)
		self.assertEqual(first, ["foo", "bar"])
		self.assertEqual(second, ["foo", "bar"])
		fetch.assert_called_once()

	def test_none_result_is_not_cached(self) -> None:
		fetch = mock.Mock(return_value=None)
		self.assertIsNone(grimaur.cached_json("srcinfo/x.json", 60, fetch))
		self.assertIsNone(grimaur.cached_json("srcinfo/x.json", 60, fetch))
		self.assertEqual(fetch.call_count, 2)

	def test_corrupt_entry_refetches(self) -> None:
		grimaur.cache_put("k.json", "{not json")
		fetch = mock.Mock(return_value={"ok": 1})
		self.assertEqual(grimaur.cached_json("k.json", 60, fetch), {"ok": 1})
		fetch.assert_called_once()

	def test_zero_ttl_refetches_and_repopulates(self) -> None:
		# --refresh sets CACHE_TTL=0: every read expires, writes still land
		grimaur.cache_put("k.json", '{"stale": 1}')
		stale = time.time() - 1
		os.utime(grimaur.CACHE_DIR / "k.json", (stale, stale))
		fetch = mock.Mock(return_value={"fresh": 1})
		self.assertEqual(grimaur.cached_json("k.json", 0, fetch), {"fresh": 1})
		fetch.assert_called_once()
		self.assertEqual(
			json.loads((grimaur.CACHE_DIR / "k.json").read_text()), {"fresh": 1}
		)


class RpcSearchCacheTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		patcher = mock.patch.object(grimaur, "CACHE_DIR", Path(tmp.name))
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_served_from_cache_without_network(self) -> None:
		grimaur.cache_put(
			_search_cache_key("foo"),
			json.dumps({"type": "search", "results": [{"Name": "foo"}]}),
		)
		with mock.patch.object(
			grimaur.urllib.request, "urlopen", side_effect=AssertionError
		) as urlopen:
			results = grimaur.aur_rpc_search_results("foo")
		self.assertEqual([entry["Name"] for entry in results], ["foo"])
		urlopen.assert_not_called()

	def test_corrupt_cache_falls_through_to_network(self) -> None:
		grimaur.cache_put(_search_cache_key("foo"), "{not json")
		with mock.patch.object(
			grimaur.urllib.request,
			"urlopen",
			side_effect=urllib.error.URLError("offline"),
		) as urlopen:
			results = grimaur.aur_rpc_search_results("foo")
		self.assertEqual(results, [])
		urlopen.assert_called_once()


class NameSourceSelectionTests(unittest.TestCase):
	def test_gz_primary_skips_git(self) -> None:
		with (
			mock.patch.object(grimaur, "_fetch_names_gz", return_value=["foo"]) as gz,
			mock.patch.object(grimaur, "_fetch_names_git") as git,
		):
			self.assertEqual(grimaur._fetch_aur_package_names(), ["foo"])
		gz.assert_called_once()
		git.assert_not_called()

	def test_gz_failure_falls_back_to_git(self) -> None:
		stderr = io.StringIO()
		with (
			mock.patch.object(grimaur, "_fetch_names_gz", return_value=None),
			mock.patch.object(grimaur, "_fetch_names_git", return_value=["bar"]) as git,
			contextlib.redirect_stderr(stderr),
		):
			self.assertEqual(grimaur._fetch_aur_package_names(), ["bar"])
		git.assert_called_once()
		self.assertIn("git mirror", stderr.getvalue())

	def test_force_git_mirror_skips_gz(self) -> None:
		with (
			mock.patch.object(grimaur, "FORCE_GIT_MIRROR", True),
			mock.patch.object(grimaur, "_fetch_names_gz") as gz,
			mock.patch.object(grimaur, "_fetch_names_git", return_value=["baz"]),
		):
			self.assertEqual(grimaur._fetch_aur_package_names(), ["baz"])
		gz.assert_not_called()

	def test_fresh_names_write_completion_cache(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		# completion.cache lands in dest_root, sibling of .searchcache
		with (
			mock.patch.object(grimaur, "CACHE_DIR", Path(tmp.name) / ".searchcache"),
			mock.patch.object(grimaur, "_fetch_names_gz", return_value=["foo", "bar"]),
		):
			grimaur._fetch_aur_package_names_with_completion()
		self.assertEqual(
			(Path(tmp.name) / "completion.cache").read_text(), "foo\nbar\n"
		)

	def test_forced_rpc_raises_instead_of_git_fallback(self) -> None:
		with (
			mock.patch.object(grimaur, "FORCE_AUR_RPC", True),
			mock.patch.object(grimaur, "_fetch_names_gz", return_value=None),
			mock.patch.object(grimaur, "_fetch_names_git") as git,
			self.assertRaises(grimaur.AurRpcForcedError),
		):
			grimaur._fetch_aur_package_names()
		git.assert_not_called()


class GitSearchCacheTests(unittest.TestCase):
	def setUp(self) -> None:
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.cache_dir = Path(tmp.name)
		for target, value in (
			("CACHE_DIR", self.cache_dir),
			# pin the git path so the packages.gz fetch never hits the network
			("FORCE_GIT_MIRROR", True),
			("get_aur_remote", mock.Mock(return_value="https://aur.example")),
			("installed_package_set", mock.Mock(return_value=set())),
		):
			patcher = mock.patch.object(grimaur, target, value)
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_empty_mirror_output_is_not_cached(self) -> None:
		with mock.patch.object(grimaur, "run_command", return_value=""):
			results = grimaur.search_packages_git(regex=None, needle="foo", limit=None)
		self.assertEqual(results, [])
		self.assertFalse((self.cache_dir / "packages.json").exists())

	def test_metadata_failure_drops_entry_without_killing_search(self) -> None:
		ls_remote = "abc123\trefs/heads/foopkg\ndef456\trefs/heads/foolib\n"

		def srcinfo(package: str) -> tuple[str, str]:
			if package == "foopkg":
				raise grimaur.AurGitError("boom")
			return ("1.0", "desc")

		with (
			mock.patch.object(grimaur, "run_command", return_value=ls_remote),
			mock.patch.object(grimaur, "git_srcinfo_metadata", side_effect=srcinfo),
		):
			results = grimaur.search_packages_git(regex=None, needle="foo", limit=None)
		self.assertEqual([r.name for r in results], ["foolib"])


if __name__ == "__main__":
	unittest.main()
