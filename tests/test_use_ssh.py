"""Unit tests for --use-ssh URL rewriting + propagation in env var."""

import os
import re
import subprocess
import unittest
from pathlib import Path

from grimoireshim import grimoire

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "use-ssh-nested" / "PKGBUILD"


def _source_urls(pkgbuild: Path) -> list[str]:
	text = pkgbuild.read_text()
	match = re.search(r"source=\((.*?)\)", text, re.DOTALL)
	if not match:
		return []
	urls: list[str] = []
	for raw_token in re.findall(r'["\']([^"\']+)["\']', match.group(1)):
		token = raw_token.split("::", 1)[1] if "::" in raw_token else raw_token
		token = token.removeprefix("git+")
		urls.append(token)
	return urls


# Inline rewrite (grimoire's own clone): EVERY http(s) host rewrites -- a mapped host
# uses its override user, an unmapped host (example.com) defaults to git@.
INLINE = {
	"https://github.com/foo/bar.git": "ssh://git@github.com/foo/bar.git",
	"https://gitlab.com/baz/qux.git": "ssh://git@gitlab.com/baz/qux.git",
	"https://codeberg.org/abc/def.git": "ssh://git@codeberg.org/abc/def.git",
	"https://bitbucket.org/ws/repo.git": "ssh://git@bitbucket.org/ws/repo.git",
	"https://aur.archlinux.org/some-pkg.git": "ssh://aur@aur.archlinux.org/some-pkg.git",
	"https://example.com/not-rewritten.git": "ssh://git@example.com/not-rewritten.git",
}
# Child-process insteadOf (makepkg source fetches): only mapped hosts get a rule, so an
# unmapped host stays https.
ENV = {
	**{u: v for u, v in INLINE.items() if "example.com" not in u},
	"https://example.com/not-rewritten.git": "https://example.com/not-rewritten.git",
}


class SSHRewriteTests(unittest.TestCase):
	def test_fixture_covers_every_rewrite_host(self) -> None:
		urls = _source_urls(FIXTURE)
		hosts = {url.split("/")[2] for url in urls}
		for host in grimoire.SSH_REWRITE_HOSTS:
			self.assertIn(host, hosts, f"fixture missing source for {host}")

	def test_per_url_python_rewrite(self) -> None:
		# grimoire's own outer-clone rewrite: _maybe_ssh_rewrite rewrites every host.
		for url in _source_urls(FIXTURE):
			with self.subTest(url=url):
				self.assertEqual(grimoire._maybe_ssh_rewrite(url), INLINE[url])

	def test_unmapped_host_defaults_to_git_user(self) -> None:
		self.assertEqual(
			grimoire._maybe_ssh_rewrite("https://v15.next.forgejo.org/o/r.git"),
			"ssh://git@v15.next.forgejo.org/o/r.git",
		)

	def _isolated_env(self) -> dict[str, str]:
		# Strip user/system git config so tests aren't poisoned by personal
		# insteadOf rules; only our env-injected config remains.
		return {
			**os.environ,
			"GIT_CONFIG_GLOBAL": "/dev/null",
			"GIT_CONFIG_SYSTEM": "/dev/null",
			**grimoire._ssh_rewrite_git_env(),
		}

	def test_env_vars_register_insteadof_in_git(self) -> None:
		# The propagation path: env vars must register as live git config in any
		# child git process — which is what makepkg invokes on each source=().
		result = subprocess.run(
			["git", "config", "--list"],
			env=self._isolated_env(),
			capture_output=True,
			text=True,
			check=True,
		)
		out = result.stdout.lower()
		for host, user in grimoire.SSH_REWRITE_HOSTS.items():
			expected = f"url.ssh://{user}@{host}/.insteadof=https://{host}/"
			self.assertIn(expected, out, f"missing insteadOf rule for {host}")

	def test_git_actually_rewrites_with_env(self) -> None:
		# End-to-end: ask git to resolve a URL via the env-injected insteadOf.
		# `git ls-remote --get-url` echoes the post-rewrite URL without networking.
		for url, expected in ENV.items():
			result = subprocess.run(
				["git", "ls-remote", "--get-url", url],
				env=self._isolated_env(),
				capture_output=True,
				text=True,
				check=True,
			)
			with self.subTest(url=url):
				self.assertEqual(result.stdout.strip(), expected)


if __name__ == "__main__":
	unittest.main()
