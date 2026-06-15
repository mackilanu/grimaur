#!/usr/bin/env python3
r"""grimoire: Fetch, inspect, search, list, update, and install, remove.

It natively speaks all things `makepkg`. And works outside of AUR using `git`.
I.e: Private software colletions, Public organizations repositories, ...
What is defined as VUR (Virtual User Repo).
Or official Arch Linux packages from their Gitlab.

Recursively resolve and install dependencies by building packages locally with makepkg.
Official repository dependencies are installed with pacman when they are missing.

	In a single truth python file.

      __...--~~~~~-._   _.-~~~~~--...__
    //               `V'               \\
   //                 |                 \\
  //__...--~~~~~~-._  |  _.-~~~~~~--...__\\
 //__.....----~~~~._\ | /_.~~~~----.....__\\
====================\\|//====================

                grimoire 0.1.3

ASCII: Donovan Baker
## /* SPDX-FileCopyrightText: 2026
# (O) Marcus A.
# (C) Eihdran L.

##  SPDX-License-Identifier: MIT */

Requirements: git, base-devel, pacman, and sudo/doas/run0/su.
"""

import argparse
import hashlib
import heapq
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from collections.abc import Callable, Iterable, Iterator, Sequence

__appname__ = "grimoire"
__version__ = "dev"


RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
USE_COLOR = False


GITHUB_RAW_BASE = "https://raw.githubusercontent.com/archlinux/aur"
_VCS_SUFFIXES = ("-git", "-vcs", "-svn", "-hg", "-bzr", "-darcs", "-cvs")
_COMMON_AUR_SUFFIXES = ("-bin",)

USE_SSH = False
SHALLOW_CLONE = False
DEBUG = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
# Set by main() to dest_root/.searchcache (same convention as the .tmp
# fallback: dest_root works even in chroots where HOME/XDG may not).
CACHE_DIR: Path | None = None
CACHE_TTL = 3600


_INSTALLED_CACHE: set[str] | None = None
_ELEV_TOOLS = ("sudo", "doas", "run0", "su")  # order matters here
_GLOBAL_VALUE_OPTIONS = {"--dest-root"}


_PACMAN_AUTH_RE = re.compile(r'^\s*PACMAN_AUTH\s*=\s*\(?\s*"?([^"\s)]+)"?')
_PACMAN_DBPATH_RE = re.compile(r"^\s*DBPath\s*=\s*(\S+)")
_DEP_SPLIT_RE = re.compile(r"[<>~=]+")
_DESC_FIELD_RE = re.compile(r"%(\w+)%\n([^\n]*)")
# Third-party repos (cachyos, ...) have no recipe, exclude from the templated search.
_OFFICIAL_REPO_RE = re.compile(
	r"^(core|extra|multilib)(-testing|-staging)?$|^(gnome|kde)-unstable$"
)
_HOSTISH_RE = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+$", re.IGNORECASE)


_SRCINFO_KEYS = {
	"depends",
	"makedepends",
	"checkdepends",
	"optdepends",
	"pkgname",
	"pkgbase",
	"pkgdesc",
}


_GLOBAL_FLAG_OPTIONS = {
	"--refresh",
	"--no-color",
	"--use-ssh",
	"--shallow",
	"--version",
	"-v",
}

# SSH user overrides per host. --use-ssh rewrites https://<host>/<path> ->
# ssh://<user>@<host>/<path>(.git); an unlisted host defaults to user "git" (the universal
# forge convention -- GitHub/GitLab/Gitea/Forgejo/Bitbucket all use it), so the only entry
# strictly needed is a host whose user differs (aur.archlinux.org -> "aur"). The listed
# hosts are also mirrored as child-process insteadOf rules (which the git@-default cannot
# cover), so the common forges stay enumerated here.
SSH_REWRITE_HOSTS = {
	"github.com": "git",
	"gitlab.com": "git",
	"codeberg.org": "git",
	"bitbucket.org": "git",
	"aur.archlinux.org": "aur",
}


_CONF_NAME = "repos.conf"
# Written on first use when no repos.conf exists. Default source is [ARCH] (build
# official packages from source); the AUR is opt-in (commented out).
_DEFAULT_REPOS_CONF = """\
# Example grimoire config. Manage with `grimoire repo`.
# Top takes precedence. Spaces do not matter.
# Template support: {pkg} = package name, {pkgbase} = its pkgbase
# (Ie: amd-ucode -> linux-firmware)

# Insert a custom repo here. Examples can be found in the repo.

# Default: Arch's official packages.
[ARCH]
  https://gitlab.archlinux.org/archlinux/packaging/packages/{pkgbase}.git

# Off by default (AUR is opt-in).
[AUR]
  false
"""


@dataclass(frozen=True)
class DependencySet:
	depends: set[str]
	makedepends: set[str]
	checkdepends: set[str]
	optdepends: set[str]

	@property
	def all_build_deps(self) -> set[str]:
		return self.depends | self.makedepends


@dataclass(frozen=True)
class SearchResult:
	name: str
	version: str | None
	description: str | None
	installed: bool
	score: int
	# Display label for the source repo (alias/URL); None means the AUR.
	source: str | None = None
	# True when sourced from a local pacman sync DB (label as `db`, not a protocol).
	from_db: bool = False
	# Conf alias this result can be installed from (None = the AUR/default backend).
	# Distinct from `source`: sync-DB results display their pacman repo but install
	# via their alias (e.g. display "core", install via "ARCH").
	repo_alias: str | None = None


@dataclass(frozen=True)
class UpdateCandidate:
	name: str
	installed_version: str | None
	target_version: str | None
	remote_head: str | None
	local_head: str | None


class AurGitError(RuntimeError):
	"""Wraps fatal errors coming from the helper."""


def get_aur_remote() -> str:
	url = "https://github.com/archlinux/aur.git"
	return _remote_for(url)


def _aur_mirror_lsremote_cmd(*patterns: str) -> list[str]:
	return ["git", "ls-remote", "--heads", get_aur_remote(), *patterns]


def _lsremote_first_sha(output: object) -> str | None:
	for line in str(output).splitlines():
		parts = line.split()
		if parts:
			return parts[0]
	return None


def _lsremote_names(output: object) -> list[str]:
	# Short ref names from `git ls-remote` lines (`<sha>\t<ref>` -> last ref segment),
	# skipping lines that aren't exactly sha+ref.
	names: list[str] = []
	for line in str(output).splitlines():
		parts = line.split()
		if len(parts) == 2:
			names.append(parts[1].split("/")[-1])
	return names


def _xdg_config_home() -> Path:
	return Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))


def _makepkg_conf_paths() -> tuple[Path, ...]:
	return (
		_xdg_config_home() / "pacman/makepkg.conf",
		Path.home() / ".makepkg.conf",
		Path("/etc/makepkg.conf"),
	)


def _pacman_db_path() -> Path:
	try:
		content = Path("/etc/pacman.conf").read_text()
	except OSError:
		return Path("/var/lib/pacman")
	for line in content.splitlines():
		match = _PACMAN_DBPATH_RE.match(line)
		if match:
			return Path(match.group(1))
	return Path("/var/lib/pacman")


def _iter_sync_db_desc(
	name_prefix: str | None = None,
) -> Iterator[tuple[str, dict[str, str]]]:
	# Walk the pacman sync DBs yielding (repo, desc-fields) for every package `desc`
	# entry. DBs may be gzip (Arch) or zstd (CachyOS); `r:*` autodetects. name_prefix
	# skips members whose dir doesn't start with it before the parse (fast path for a
	# single-package lookup).
	import tarfile

	sync = _pacman_db_path() / "sync"
	try:
		dbs = sorted(sync.glob("*.db"))
	except OSError:
		return
	for db in dbs:
		repo = db.stem
		if not _OFFICIAL_REPO_RE.match(repo):
			continue
		try:
			with tarfile.open(db, "r:*") as tar:
				for member in tar:
					name = member.name
					if not name.endswith("/desc"):
						continue
					if name_prefix is not None and not name.startswith(name_prefix):
						continue
					extracted = tar.extractfile(member)
					if extracted is None:
						continue
					yield (
						repo,
						dict(
							_DESC_FIELD_RE.findall(
								extracted.read().decode("utf-8", "replace")
							)
						),
					)
		except OSError, tarfile.TarError:
			continue


@cache
def _resolve_pkgbase(package: str) -> str:
	# pkgname -> pkgbase via the pacman sync DBs (each `desc` carries %BASE%). Lets a
	# pkgbase-keyed forge (Arch GitLab, the AUR) be reached by package name even for
	# split packages (amd-ucode -> linux-firmware). Falls back to the name if unknown.
	for _repo, fields in _iter_sync_db_desc(f"{package}-"):
		if fields.get("NAME") == package:
			return fields.get("BASE") or package
	return package


@cache
def _sync_db_packages() -> tuple[tuple[str, str | None, str | None, str], ...]:
	# Every package in the pacman sync DBs as (name, version, desc, repo). The index
	# for the {pkgbase} templated search (the Arch GitLab has no listing). repo is the
	# DB name (core/extra/cachyos/...) so results read like `pacman -Ss`; official
	# repos build from the alias's source, third-party repos are skipped through RE.
	# (see the search install loop). Every repo copy is listed (no dedup). gzip + zstd.
	out: list[tuple[str, str | None, str | None, str]] = []
	for repo, fields in _iter_sync_db_desc():
		name = fields.get("NAME")
		if name:
			out.append((name, fields.get("VERSION"), fields.get("DESC"), repo))
	return tuple(out)


def _read_pacman_auth() -> str | None:
	for path in _makepkg_conf_paths():
		try:
			content = path.read_text()
		except OSError:
			continue
		for line in content.splitlines():
			match = _PACMAN_AUTH_RE.match(line)
			if match:
				return match.group(1)
	return None


@cache
def _get_elev() -> str:
	preferred = _read_pacman_auth()
	if preferred and shutil.which(preferred):
		return preferred
	for tool in _ELEV_TOOLS:
		if shutil.which(tool):
			return tool
	raise AurGitError("No privilege elevation tool found.")


def _elevate(cmd: list[str]) -> list[str]:
	if os.geteuid() == 0:
		return cmd
	tool = _get_elev()
	if tool == "su":
		return ["su", "-c", shlex.join(cmd), "root"]
	return [tool, *cmd]


def _maybe_ssh_rewrite(url: str) -> str:
	parsed = urllib.parse.urlparse(url)
	if parsed.scheme not in ("http", "https") or not parsed.netloc:
		return url
	# Default to user "git" for any forge (Forgejo/Gitea/Bitbucket/...); only a host with
	# a non-git ssh user needs a SSH_REWRITE_HOSTS override (e.g. aur.archlinux.org).
	user = SSH_REWRITE_HOSTS.get(parsed.netloc, "git")
	path = parsed.path.lstrip("/").rstrip("/")
	if not path:
		return f"ssh://{user}@{parsed.netloc}"
	if not path.endswith(".git"):
		path += ".git"
	return f"ssh://{user}@{parsed.netloc}/{path}"


def _remote_for(url: str) -> str:
	return _maybe_ssh_rewrite(url) if USE_SSH else url


# Mirror SSH_REWRITE_HOSTS as git insteadOf rules via GIT_CONFIG_* env vars
# this make the ssh only rule persist even if invoked by a child PKGBUILD/process
def _ssh_rewrite_git_env() -> dict[str, str]:
	pairs: list[tuple[str, str]] = [
		(
			f"url.ssh://{user}@{host}/.insteadOf",
			f"{scheme}://{host}/",
		)
		for host, user in SSH_REWRITE_HOSTS.items()
		for scheme in ("https", "http")
	]
	env = {"GIT_CONFIG_COUNT": str(len(pairs))}
	for i, (key, value) in enumerate(pairs):
		env[f"GIT_CONFIG_KEY_{i}"] = key
		env[f"GIT_CONFIG_VALUE_{i}"] = value
	return env


def _ensure_scheme(url: str) -> str:
	# Let users drop the scheme ("github.com/h8d13/VUR"): if the first segment looks
	# like a hostname, assume https. Leaves scp-form (git@host:path), ssh://, file://,
	# and local paths untouched.
	u = url.strip()
	if "://" in u:
		return u
	first = u.split("/", 1)[0]
	if "@" in first or ":" in first:  # scp-form or has a port/user -> leave to git
		return u
	if _HOSTISH_RE.match(first):
		return "https://" + u
	return u


def parse_repo_url(url: str) -> tuple[str, str | None, str | None]:
	# Expand a forge directory/file URL to (clone_url, ref, subdir) so --repo-url can
	# target a subdir. ref is taken as one path segment, so slash-branches need an
	# explicit --rev/--subdir. Non-forge URLs fall through unchanged.
	url = _ensure_scheme(url)
	parsed = urllib.parse.urlparse(url)
	if parsed.scheme not in ("http", "https"):
		return url, None, None
	parts = [p for p in parsed.path.split("/") if p]

	def _rebuild(
		repo_parts: list[str], ref: str, sub: list[str]
	) -> tuple[str, str, str | None]:
		base = f"{parsed.scheme}://{parsed.netloc}/" + "/".join(repo_parts)
		if not base.endswith(".git"):
			base += ".git"
		# A blob link usually points at the PKGBUILD itself; build in its dir.
		if sub and sub[-1] in ("PKGBUILD", ".SRCINFO"):
			sub = sub[:-1]
		return base, ref, ("/".join(sub) or None)

	# GitHub: /<owner>/<repo>/{tree,blob,raw}/<ref>/<subpath...>
	if parsed.netloc == "github.com":
		for marker in ("tree", "blob", "raw"):
			if marker in parts:
				i = parts.index(marker)
				if i >= 2 and len(parts) > i + 1:
					return _rebuild(parts[:i], parts[i + 1], parts[i + 2 :])
	# GitLab: /<owner>/<repo>/-/{tree,blob,raw}/<ref>/<subpath...>
	if "-" in parts:
		d = parts.index("-")
		if d >= 2 and len(parts) > d + 2 and parts[d + 1] in ("tree", "blob", "raw"):
			return _rebuild(parts[:d], parts[d + 2], parts[d + 3 :])
	# Bitbucket Cloud: /<workspace>/<repo>/{src,raw}/<ref>/<subpath...> (ref directly
	# after the marker, no branch/tag/commit segment -- distinct from Gitea below).
	if parsed.netloc == "bitbucket.org":
		for marker in ("src", "raw"):
			if marker in parts:
				i = parts.index(marker)
				if i >= 2 and len(parts) > i + 1:
					return _rebuild(parts[:i], parts[i + 1], parts[i + 2 :])
	# Gitea/Codeberg/Forgejo: /<owner>/<repo>/{src,raw}/{branch,tag,commit}/<ref>/<subpath...>
	for marker in ("src", "raw"):
		if marker in parts:
			i = parts.index(marker)
			if (
				i >= 2
				and len(parts) > i + 2
				and parts[i + 1] in ("branch", "tag", "commit")
			):
				return _rebuild(parts[:i], parts[i + 2], parts[i + 3 :])

	return url, None, None


def _repo_registry_path() -> Path:
	return _xdg_config_home() / __appname__ / _CONF_NAME


def _ensure_repos_conf() -> None:
	# Seed a default repos.conf the first time a source is needed, so the default is
	# the official Arch repos (build from source) rather than the AUR. Best-effort:
	# if the write fails, resolution falls back to the built-in AUR.
	path = _repo_registry_path()
	if path.exists():
		return
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(_DEFAULT_REPOS_CONF)
	except OSError:
		pass


def load_repo_registry() -> dict[str, list[str]]:
	# Sectioned name->URLs map. A `[name]` header opens a section; each following
	# non-empty, non-comment line is one mirror URL (order = clone priority).
	path = _repo_registry_path()
	try:
		content = path.read_text()
	except OSError:
		return {}
	registry: dict[str, list[str]] = {}
	current: str | None = None
	for raw in content.splitlines():
		line = raw.strip()
		if not line or line.startswith("#"):
			continue
		if line.startswith("[") and line.endswith("]"):
			current = line[1:-1].strip()
			registry.setdefault(current, [])
		elif current is not None:
			registry[current].append(line)
	return registry


def _repos_section_end(lines: list[str], header_idx: int) -> int:
	# Index just past the URL lines of the section at header_idx (stops at a blank
	# line, a comment, or the next [section]).
	j = header_idx + 1
	while j < len(lines):
		s = lines[j].strip()
		if not s or s.startswith("#") or s.startswith("["):
			break
		j += 1
	return j


def add_repo_alias(name: str, url: str) -> None:
	# Edit the file textually so comments and commented-out sections survive.
	if name == "AUR":
		print(
			"[AUR] is a reserved toggle (true/false); edit repos.conf to enable it.",
			file=sys.stderr,
		)
		return
	path = _repo_registry_path()
	try:
		lines = path.read_text().splitlines()
	except OSError:
		lines = []
	header = f"[{name}]"
	idx = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)
	if idx is not None:
		end = _repos_section_end(lines, idx)
		if any(lines[k].strip() == url for k in range(idx + 1, end)):
			print(f"'{url}' already registered under [{name}]", file=sys.stderr)
			return
		lines.insert(end, f"  {url}")
	else:
		if lines and lines[-1].strip():
			lines.append("")
		lines += [header, f"  {url}"]
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("\n".join(lines) + "\n")
	print(f"Added '{url}' to [{name}] in {path}")


def remove_repo_alias(name: str) -> None:
	path = _repo_registry_path()
	try:
		lines = path.read_text().splitlines()
	except OSError:
		lines = []
	header = f"[{name}]"
	idx = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)
	if idx is None:
		print(f"No alias '{name}' in {path}", file=sys.stderr)
		return
	del lines[idx : _repos_section_end(lines, idx)]
	path.write_text("\n".join(lines) + ("\n" if lines else ""))
	print(f"Removed alias '{name}'")


def resolve_repo_alias(name: str) -> list[str]:
	urls = load_repo_registry().get(name)
	if not urls:
		raise AurGitError(
			f"Unknown repo alias '{name}'. Add one with --repo-add URL {name}"
		)
	return urls


def _aur_enabled() -> bool:
	# [AUR] is a reserved toggle section -- a true/false value, not a URL list. It turns
	# the built-in AUR git backend on for the DEFAULT chain, search, and `list --repo AUR`.
	# An explicit `--repo AUR` is a deliberate override and ignores this. Absent or a
	# falsey/empty token = off (AUR is opt-in); a legacy URL value reads as on.
	vals = load_repo_registry().get("AUR")
	if not vals:
		return False
	return vals[0].strip().lower() not in ("false", "no", "off", "0", "disabled")


def _default_repo() -> str | None:
	# The source used when no --repo/--repo-url is given: the first section in
	# repos.conf (priority order, top wins), or None for the built-in AUR when there
	# is no config. A disabled [AUR] is skipped so it can't become the default.
	for name in load_repo_registry():
		if name == "AUR" and not _aur_enabled():
			continue
		return name
	return None


def style(text: str, *codes: str) -> str:
	if not USE_COLOR or not codes:
		return text
	return "".join(codes) + text + RESET


def prompt_confirm(message: str) -> bool:
	if not sys.stdin.isatty():
		return False
	try:
		response = input(message)
	except EOFError:
		return False
	return response.strip().lower() in {"y", "yes"}


def is_debug_package(name: str) -> bool:
	return name.endswith("-debug")


def is_vcs_package(name: str) -> bool:
	return any(name.endswith(suffix) for suffix in _VCS_SUFFIXES)


def cache_get(key: str, ttl: int) -> str | None:
	if CACHE_DIR is None:
		return None
	path = CACHE_DIR / key
	try:
		if time.time() - path.stat().st_mtime > ttl:
			path.unlink(missing_ok=True)
			return None
		return path.read_text()
	except OSError:
		return None


def _atomic_write(path: Path, payload: str) -> None:
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		# pid-unique tmp so concurrent processes never interleave writes
		tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
		tmp.write_text(payload)
		tmp.replace(path)
	except OSError:
		pass


def cache_put(key: str, payload: str) -> None:
	if CACHE_DIR is None:
		return
	_atomic_write(CACHE_DIR / key, payload)


def _completion_cache_path() -> Path | None:
	if CACHE_DIR is None:
		return None
	# Conventional yay-style location: dest_root/completion.cache,
	# sibling of .searchcache rather than inside it.
	return CACHE_DIR.parent / "completion.cache"


def cached_json(key: str, ttl: int, fetch: Callable[[], object]) -> object:
	payload = cache_get(key, ttl)
	if payload is not None:
		try:
			value = json.loads(payload)
		except json.JSONDecodeError:
			value = None
		if value is not None:
			if DEBUG:
				print(f"+ cache hit {key}", file=sys.stderr)
			return value
	value = fetch()
	if value is not None:
		cache_put(key, json.dumps(value))
	return value


def clear_search_cache() -> None:
	removed = False
	if CACHE_DIR is not None and CACHE_DIR.exists():
		shutil.rmtree(CACHE_DIR)
		print(f"Removed search cache {CACHE_DIR}")
		removed = True
	completion = _completion_cache_path()
	if completion is not None and completion.exists():
		completion.unlink()
		print(f"Removed completion cache {completion}")
		removed = True
	if not removed:
		print("No search cache to remove")


def run_command(
	cmd: Sequence[str],
	*,
	cwd: Path | None = None,
	capture: bool = False,
	check: bool = True,
	env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | str:
	if DEBUG:
		cwd_hint = f" (cwd={cwd})" if cwd else ""
		print(f"+ {' '.join(cmd)}{cwd_hint}", file=sys.stderr)
	try:
		completed = subprocess.run(  # noqa: S603 - cmd is built internally, not from untrusted input
			list(cmd),
			cwd=str(cwd) if cwd else None,
			check=check,
			text=True,
			capture_output=capture,
			env=env,
		)
	except FileNotFoundError as exc:  # e.g. git not installed
		raise AurGitError(f"Required command not found: {cmd[0]}") from exc
	except subprocess.CalledProcessError as exc:
		raise AurGitError(
			f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}\n{exc.stderr or ''}"
		) from exc

	if capture:
		return completed.stdout
	return completed


def _resolve_build_dir(clone_root: Path, subdir: str | None) -> Path:
	if not subdir:
		return clone_root
	root = clone_root.resolve()
	target = (clone_root / subdir).resolve()
	if target != root and root not in target.parents:
		raise AurGitError(f"Subdirectory '{subdir}' escapes clone root {clone_root}")
	if not target.is_dir():
		raise AurGitError(f"Subdirectory '{subdir}' not found in clone at {clone_root}")
	return target


def _resolve_package_dir(clone_root: Path, subdir: str | None, package: str) -> Path:
	# Monorepo convention: a container holds one subdir per package named after it
	# (the subdir analogue of the AUR mirror keying packages by branch). When the
	# resolved dir has no PKGBUILD but <dir>/<package> does, descend into it, so
	# `--repo <container-alias> install <pkg>` finds <subdir>/<pkg> automatically.
	build_dir = _resolve_build_dir(clone_root, subdir)
	if (build_dir / "PKGBUILD").is_file():
		return build_dir
	nested = build_dir / package
	if (nested / "PKGBUILD").is_file():
		return nested
	return build_dir


def _tree_has(package_dir: Path, ref: str, path: str) -> bool:
	# Whether `path` exists in `ref`'s tree, without a worktree. On a --filter=tree:0
	# clone this lazily fetches only the trees along `path` (provider-agnostic: any git
	# transport, no forge knowledge).
	try:
		out = run_command(
			["git", "-C", str(package_dir), "ls-tree", "--name-only", ref, path],
			capture=True,
		)
	except AurGitError:
		return False
	return bool(str(out).strip())


def _build_subpath(
	package_dir: Path, ref: str, subdir: str | None, package: str
) -> str | None:
	# The subtree holding the PKGBUILD, for a sparse checkout: <subdir>/<pkg>, <subdir>,
	# or <pkg> (flat). None means the PKGBUILD is at the build root (solo) -> whole tree.
	for cand in [f"{subdir}/{package}", subdir] if subdir else [package]:
		if cand and _tree_has(package_dir, ref, f"{cand}/PKGBUILD"):
			return cand
	return None


def _subdir_hint(package_dir: Path, ref: str, package: str) -> str | None:
	# On a no-PKGBUILD miss, look one level down: a subdir-container holds <dir>/<pkg>/
	# PKGBUILD. Returns the container dir to suggest via --subdir, or None. Bounded to the
	# top-level dirs (one ls-tree each), never a recursive scan -- so a tree:0 clone stays
	# cheap even on a big monorepo.
	try:
		out = run_command(
			["git", "-C", str(package_dir), "ls-tree", "-d", "--name-only", ref],
			capture=True,
		)
	except AurGitError:
		return None
	for line in str(out).splitlines():
		top = line.strip()
		if top and _tree_has(package_dir, ref, f"{top}/{package}/PKGBUILD"):
			return top
	return None


def _clone_with_fallback(
	package_dir: Path,
	candidates: Sequence[tuple[str, str | None, str | None]],
	package: str,
) -> Path:
	# Try each (url, branch, subdir) mirror in order until one clones; the winning
	# mirror's own subdir resolves the build dir. Used only for a fresh clone.
	# Clone treeless (--filter=tree:0) + no-checkout so only commits arrive up front;
	# `git ls-tree` then lazily fetches just the target package's subtree. A monorepo that
	# lacks the package costs only that probe -- no full clone, no checkout -- and the miss
	# is detected provider-agnostically (any git transport, no forge knowledge). git
	# transparently falls back to a full clone when the server can't filter; a solo repo
	# (PKGBUILD at the root) checks out whole.
	errors: list[str] = []
	for index, (url, branch, subdir) in enumerate(candidates):
		remote_url = _remote_for(url)
		if package_dir.exists():
			shutil.rmtree(package_dir)
		clone_cmd = ["git", "clone", "--no-checkout", "--filter=tree:0"]
		if SHALLOW_CLONE:
			clone_cmd += ["--depth=1"]
		clone_cmd += [remote_url, str(package_dir)]
		try:
			print(style(f"==> cloning from {remote_url}", DIM))
			run_command(clone_cmd)
			if branch:
				run_command(["git", "-C", str(package_dir), "fetch", "origin", branch])
			ref = "FETCH_HEAD" if branch else "HEAD"
			want = _build_subpath(package_dir, ref, subdir, package)
			if want is None and not _tree_has(package_dir, ref, "PKGBUILD"):
				# No package subtree and no root PKGBUILD -> this mirror lacks the
				# package. Skip before any checkout (a monorepo miss stays cheap).
				# If it's actually a subdir-container, point at the right --subdir.
				hint = _subdir_hint(package_dir, ref, package)
				msg = f"no PKGBUILD for '{package}'"
				if hint and hint != subdir:
					msg += f" (found under {hint}/ -- pass --subdir {hint})"
				raise AurGitError(msg)
			if want:
				run_command(
					["git", "-C", str(package_dir), "sparse-checkout", "set", want]
				)
			_reset_git_worktree(package_dir, (ref,))
			return _resolve_package_dir(package_dir, subdir, package)
		except AurGitError as exc:
			errors.append(f"{url}: {exc}")
			if index + 1 < len(candidates):
				print(
					style(f"mirror failed ({url}); trying next...", YELLOW),
					file=sys.stderr,
				)
	if package_dir.exists():
		shutil.rmtree(package_dir)
	raise AurGitError("All mirrors failed:\n  " + "\n  ".join(errors))


def _normalize_git_url(url: str) -> str:
	# Canonical host/path so https, ssh://, and scp-form (git@host:path) of the same
	# repo compare equal -- git's own insteadOf rewrites mean a clone's stored origin
	# may differ in scheme/user from the URL we asked for.
	u = url.strip()
	if "://" not in u and "@" in u and ":" in u:
		u = u.split("@", 1)[1].replace(":", "/", 1)
	else:
		if "://" in u:
			u = u.split("://", 1)[1]
		if "@" in u.split("/", 1)[0]:
			u = u.split("@", 1)[1]
	u = u.rstrip("/").removesuffix(".git")
	return u.lower()


def _clone_origin(package_dir: Path) -> str | None:
	try:
		out = run_command(
			["git", "-C", str(package_dir), "remote", "get-url", "origin"],
			capture=True,
		)
	except AurGitError:
		return None
	return str(out).strip() or None


def _is_aur_origin(origin: str) -> bool:
	# An AUR clone (the GitHub git mirror, archlinux/aur). Lets an AUR invocation detect
	# (and replace) a clone left behind by a custom --repo run instead of the wrong source.
	return "archlinux/aur" in origin


def _origin_label(package_dir: Path) -> str:
	# Source label for `inspect --plain`'s Repository field: the clone's actual host
	# (e.g. gitlab.archlinux.org), or "aur" for the AUR mirror / unknown origin.
	origin = _clone_origin(package_dir)
	if origin is None or _is_aur_origin(origin):
		return "aur"
	return _normalize_git_url(origin).split("/", 1)[0]


def _init_submodules(clone_root: Path) -> None:
	# `--submod`: populate the repo's git submodules after checkout (off by default, like
	# git and makepkg themselves). No-op unless the clone has a .gitmodules at its root.
	# Submodules outside a sparse checkout stay unpopulated -- git skips gitlinks not in
	# the worktree, which is the right behaviour for a monorepo subdir build.
	if not (clone_root / ".gitmodules").is_file():
		return
	print(style("==> updating submodules", DIM))
	run_command(
		["git", "-C", str(clone_root), "submodule", "update", "--init", "--recursive"]
	)


def ensure_clone(
	package: str,
	dest_root: Path,
	*,
	refresh: bool = False,
	repo_url: str | None = None,
	branch: str | None = None,
	subdir: str | None = None,
	repo_fallbacks: list[tuple[str, str | None, str | None]] | None = None,
	submodules: bool = False,
) -> Path:
	dest_root.mkdir(parents=True, exist_ok=True)
	package_dir = dest_root / package

	# A leftover non-git directory in our own cache is junk -> recreate it.
	if package_dir.exists() and not (package_dir / ".git").is_dir():
		shutil.rmtree(package_dir)

	if repo_url:
		remote_url = _remote_for(repo_url)
		clone_extra: list[str] = []
		fetch_refspec: tuple[str, ...]
		reset_targets: tuple[str, ...]
		if branch:
			# A bare commit SHA is rejected by `git clone --branch`, so clone the
			# default head and check the ref out afterwards instead. Fetching the
			# ref then resetting to FETCH_HEAD resolves a branch, tag, or reachable
			# commit uniformly (origin/<ref> only exists for branches).
			fetch_refspec = (branch,)
			reset_targets = ("FETCH_HEAD",)
		else:
			fetch_refspec = ()
			reset_targets = ("origin/HEAD",)
	else:
		# No repo_url -> the AUR git mirror, one branch per package.
		remote_url = get_aur_remote()
		clone_extra = ["--branch", package, "--single-branch"]
		fetch_refspec = (package,)
		reset_targets = (f"origin/{package}",)

	reuse_existing = package_dir.exists() and (package_dir / ".git").is_dir()
	if reuse_existing:
		# Don't reuse a clone whose origin no longer matches the requested source:
		# an old AUR clone reused under --repo (or vice versa) would otherwise be
		# fetched/resolved against the wrong tree. Mismatch -> fall through, reclone.
		origin = _clone_origin(package_dir)
		if repo_url:
			accepted = {
				_normalize_git_url(u)
				for u in [repo_url, *(c[0] for c in (repo_fallbacks or []))]
			}
			reuse_existing = (
				origin is not None and _normalize_git_url(origin) in accepted
			)
		elif origin and not _is_aur_origin(origin):
			reuse_existing = False

	if reuse_existing:
		if refresh:
			fetch_cmd = [
				"git",
				"-C",
				str(package_dir),
				"fetch",
				"origin",
				*fetch_refspec,
			]
			run_command(fetch_cmd)
			try:
				_reset_git_worktree(package_dir, reset_targets)
			except AurGitError:
				# Corrupt worktree/index -> drop it and reclone from scratch.
				shutil.rmtree(package_dir)
				return ensure_clone(
					package,
					dest_root,
					refresh=False,
					repo_url=repo_url,
					branch=branch,
					subdir=subdir,
					submodules=submodules,
				)
		if submodules:
			_init_submodules(package_dir)
		return _resolve_package_dir(package_dir, subdir, package)

	if package_dir.exists():
		shutil.rmtree(package_dir)

	if repo_url:
		candidates = [(repo_url, branch, subdir), *(repo_fallbacks or [])]
		build = _clone_with_fallback(package_dir, candidates, package)
		if submodules:
			_init_submodules(package_dir)
		return build

	clone_cmd = ["git", "clone", *clone_extra]
	if SHALLOW_CLONE:
		clone_cmd += ["--depth=1"]
	clone_cmd += [remote_url, str(package_dir)]
	print(style(f"==> cloning from {remote_url}", DIM))
	run_command(clone_cmd)

	if submodules:
		_init_submodules(package_dir)
	return _resolve_package_dir(package_dir, subdir, package)


def read_srcinfo(package_dir: Path) -> str:
	srcinfo_path = package_dir / ".SRCINFO"
	if srcinfo_path.exists():
		return srcinfo_path.read_text()
	# Fallback to generating on the fly
	output = run_command(["makepkg", "--printsrcinfo"], cwd=package_dir, capture=True)
	return str(output)


def _iter_srcinfo_kv(srcinfo_content: str) -> Iterator[tuple[str, str]]:
	# Yield (key, value) for each `key = value` line of a .SRCINFO, stripped, skipping
	# blanks and comments. makepkg always emits the spaced form.
	for raw_line in srcinfo_content.splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = (part.strip() for part in line.split("=", 1))
		yield key, value


def _str_or_none(value: object) -> str | None:
	return value if isinstance(value, str) else None


def _assemble_version(
	pkgver: str | None, pkgrel: str | None, epoch: str | None
) -> str | None:
	# Compose epoch:pkgver-pkgrel, suppressing an absent/zero epoch. None when nothing
	# version-like is present.
	if not (pkgver or pkgrel or epoch):
		return None
	parts: list[str] = []
	if epoch and epoch not in {"", "0"}:
		parts.append(f"{epoch}:")
	if pkgver:
		parts.append(pkgver)
	if pkgrel and pkgver:
		parts.append(f"-{pkgrel}")
	return "".join(parts) or None


def parse_dependencies(srcinfo_content: str) -> tuple[str, str | None, DependencySet]:
	pkgbase = ""
	pkgdesc = None
	depends: set[str] = set()
	makedepends: set[str] = set()
	checkdepends: set[str] = set()
	optdepends: set[str] = set()

	for key, value in _iter_srcinfo_kv(srcinfo_content):
		if key not in _SRCINFO_KEYS:
			continue
		if key == "pkgbase" and not pkgbase:
			pkgbase = value
			continue
		if key == "pkgdesc" and not pkgdesc:
			pkgdesc = value
			continue
		if key == "optdepends":
			optdepends.add(value)
			continue
		if key == "depends":
			depends.update([_normalize_dep(value)])
		elif key == "makedepends":
			makedepends.update([_normalize_dep(value)])
		elif key == "checkdepends":
			checkdepends.update([_normalize_dep(value)])

	if not pkgbase:
		raise AurGitError("Failed to parse pkgbase from .SRCINFO")
	return (
		pkgbase,
		pkgdesc,
		DependencySet(depends, makedepends, checkdepends, optdepends),
	)


def _normalize_dep(dep_entry: str) -> str:
	dep_entry = dep_entry.strip()
	if not dep_entry:
		return dep_entry
	dep_entry = dep_entry.split(":", 1)[-1]  # strip repo qualifier if present
	dep_entry = _DEP_SPLIT_RE.split(dep_entry)[0]
	return dep_entry.strip()


def _pkgbase_guesses(dep: str) -> list[str]:
	parts = dep.split("-")
	guesses: list[str] = []
	# Walk backwards dropping the last segment each time (foo-bar-baz -> foo-bar, foo)
	for index in range(len(parts) - 1, 0, -1):
		candidate = "-".join(parts[:index])
		if candidate:
			guesses.append(candidate)
	return guesses


def _parse_srcinfo_metadata(srcinfo_content: str) -> tuple[str | None, str | None]:
	pkgver = pkgrel = epoch = description = None
	for key, value in _iter_srcinfo_kv(srcinfo_content):
		if key == "pkgver" and not pkgver:
			pkgver = value
		elif key == "pkgrel" and not pkgrel:
			pkgrel = value
		elif key == "epoch" and not epoch:
			epoch = value
		elif key == "pkgdesc" and not description:
			description = value
	return _assemble_version(pkgver, pkgrel, epoch), description


def _reset_git_worktree(package_dir: Path, refs: Sequence[str]) -> None:
	for ref in refs:
		try:
			run_command(
				[
					"git",
					"-C",
					str(package_dir),
					"rev-parse",
					"--verify",
					ref,
				],
				capture=True,
			)
		except AurGitError:
			continue
		run_command(
			[
				"git",
				"-C",
				str(package_dir),
				"reset",
				"--hard",
				ref,
			]
		)
		return
	raise AurGitError(
		f"Could not reset {package_dir.name} to any of: {', '.join(refs)}"
	)


def _ref_is_annotated_tag(package_dir: Path, ref: str) -> bool:
	# Whether `ref` names an annotated tag (a "tag" object -- the signable kind; a branch,
	# commit, or lightweight tag is a "commit"). Drives verify-tag vs verify-commit.
	try:
		out = run_command(
			["git", "-C", str(package_dir), "cat-file", "-t", ref], capture=True
		)
	except AurGitError:
		return False
	return str(out).strip() == "tag"


def _verify_signature(package_dir: Path, package: str, ref: str | None = None) -> None:
	# `--verify`: require a cryptographically valid GPG signature from a key in the caller's
	# keyring. When the requested ref is an annotated tag, verify that tag (covers projects
	# that sign releases, not every commit); otherwise verify the HEAD commit. Either way
	# this checks signature validity, NOT key trust -- a good signature from any held key
	# passes (gpg only warns). Fails on an unsigned target, a missing public key, or a bad
	# signature. git's own "Good signature"/error lines stream through.
	if ref and _ref_is_annotated_tag(package_dir, ref):
		cmd = ["git", "-C", str(package_dir), "verify-tag", ref]
		target = f"tag {ref}"
		print(style(f"==> git verify-tag {ref} ({package})", DIM))
	else:
		cmd = ["git", "-C", str(package_dir), "verify-commit", "HEAD"]
		target = "the HEAD commit"
		print(style(f"==> git verify-commit HEAD ({package})", DIM))
	try:
		run_command(cmd)
	except AurGitError as exc:
		raise AurGitError(
			f"signature verification failed for '{package}': {target} is unsigned, has a "
			"bad signature, or the signer's key is not in your GPG keyring"
		) from exc


def is_regex(pattern: str) -> bool:
	regex_chars = r".*+?[]{}()^$|\\"
	return any(char in pattern for char in regex_chars)


def compute_match_score(
	name: str,
	*,
	regex: re.Pattern[str] | None,
	needle: str | None,
) -> int | None:
	if regex is not None:
		match = regex.search(name)
		if not match:
			return None
		start = match.start()
		span = match.end() - match.start()
	else:
		if needle is None:
			raise ValueError("needle required when regex is None")
		lowered = name.lower()
		idx = lowered.find(needle)
		if idx == -1:
			return None
		start = idx
		span = len(needle)
	# Lower score is better match
	return start * 1000 + len(name) - span


def _pacman_returns_zero(args: Sequence[str]) -> bool:
	try:
		proc = subprocess.run(  # noqa: S603 - args are built internally, not from untrusted input
			list(args),
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
			text=True,
			check=False,
		)
	except FileNotFoundError as exc:
		raise AurGitError(
			"pacman command not found; this tool must run on Arch Linux"
		) from exc
	return proc.returncode == 0


def invalidate_installed_cache() -> None:
	global _INSTALLED_CACHE
	_INSTALLED_CACHE = None


def _list_local_db_packages() -> set[str] | None:
	# Reading pacman's local db directory directly avoids a ~50ms subprocess.
	# Entries are name-version-release dirs; ALPM_DB_VERSION has no dashes.
	try:
		entries = [entry.name for entry in (_pacman_db_path() / "local").iterdir()]
	except OSError:
		return None
	packages: set[str] = set()
	for entry in entries:
		parts = entry.rsplit("-", 2)
		if len(parts) == 3:
			packages.add(parts[0])
	return packages or None


def installed_package_set() -> set[str]:
	global _INSTALLED_CACHE
	if _INSTALLED_CACHE is None:
		_INSTALLED_CACHE = _list_local_db_packages()
	if _INSTALLED_CACHE is None:
		# we can still search without pacman installed.
		if shutil.which("pacman") is None:
			_INSTALLED_CACHE = set()
		else:
			output = run_command(["pacman", "-Qq"], capture=True)
			_INSTALLED_CACHE = set(str(output).split())
	return _INSTALLED_CACHE


def is_installed(package: str) -> bool:
	return package in installed_package_set()


@cache
def exists_in_sync_repo(package: str) -> bool:
	return _pacman_returns_zero(["pacman", "-Si", package])


def is_dependency_satisfied(dep: str) -> bool:
	return _pacman_returns_zero(["pacman", "-T", dep])


@cache
def package_provides(package: str) -> set[str] | None:
	provides: set[str] = set()
	srcinfo = fetch_git_file(package, ".SRCINFO")
	if not srcinfo:
		return provides or None
	for key, value in _iter_srcinfo_kv(srcinfo):
		if key in ("pkgname", "provides"):
			normalized = _normalize_dep(value)
			if normalized:
				provides.add(normalized)
	return provides


def _search_aur_candidates(dep: str, *, limit: int = 25) -> list[str]:
	# Match against the AUR mirror's branch names (one branch per package).
	patterns = [
		f"refs/heads/{dep}",
		f"refs/heads/{dep}-*",
		f"refs/heads/*-{dep}",
	]
	if len(dep) >= 3:
		patterns.append(f"refs/heads/*{dep}*")
	seen: set[str] = set()
	results: list[str] = []
	for pattern in patterns:
		try:
			output = run_command(_aur_mirror_lsremote_cmd(pattern), capture=True)
		except AurGitError:
			continue
		for name in _lsremote_names(output):
			if not name or name in seen:
				continue
			seen.add(name)
			results.append(name)
			if len(results) >= limit:
				return results
	return results


@cache
def resolve_aur_dependency(dep: str) -> str | None:
	if exists_in_aur_mirror(dep):
		return dep
	candidates: list[str] = []
	seen: set[str] = set()

	def add_candidate(name: str) -> None:
		if not name or name in seen:
			return
		seen.add(name)
		candidates.append(name)

	add_candidate(dep)
	for suffix in (*_VCS_SUFFIXES, *_COMMON_AUR_SUFFIXES):
		add_candidate(f"{dep}{suffix}")
	for base_candidate in _pkgbase_guesses(dep):
		add_candidate(base_candidate)
	for candidate in candidates:
		provides = package_provides(candidate)
		if not provides:
			continue
		if dep in provides:
			return candidate
	search_terms = [dep, *(_pkgbase_guesses(dep))]
	seen_search: set[str] = set()
	for term in search_terms:
		if term in seen_search:
			continue
		seen_search.add(term)
		for candidate in _search_aur_candidates(term):
			if candidate in seen:
				continue
			seen.add(candidate)
			provides = package_provides(candidate)
			if not provides:
				continue
			if dep in provides:
				return candidate
	return None


def resolve_official_dependency(dep: str) -> str | None:
	if exists_in_sync_repo(dep):
		return dep
	try:
		output = run_command(
			[
				"pacman",
				"-Sp",
				"--print-format",
				"%n",
				dep,
			],
			capture=True,
		)
	except AurGitError:
		return None
	providers = [line.strip() for line in str(output).splitlines() if line.strip()]
	if not providers:
		return None
	return providers[0]


def exists_in_aur_mirror(package: str) -> bool:
	if is_debug_package(package):
		return True
	try:
		output = run_command(_aur_mirror_lsremote_cmd(package), capture=True)
	except AurGitError:
		return False
	return bool(str(output).strip())


def list_foreign_packages() -> dict[str, str]:
	try:
		output = run_command(["pacman", "-Qm"], capture=True, check=False)
	except AurGitError:
		return {}

	names: dict[str, str] = {}
	for line in str(output).splitlines():
		if not line.strip():
			continue
		parts = line.split()
		if len(parts) >= 2:
			names[parts[0]] = parts[1]
		else:
			names[parts[0]] = ""
	return names


def get_local_head(package_dir: Path) -> str | None:
	if not (package_dir / ".git").is_dir():
		return None
	try:
		output = run_command(
			["git", "-C", str(package_dir), "rev-parse", "HEAD"], capture=True
		)
	except AurGitError:
		return None
	return str(output).strip() or None


def _git_remote_head(url: str, ref: str | None) -> str | None:
	try:
		output = run_command(
			["git", "ls-remote", _remote_for(url), ref or "HEAD"], capture=True
		)
	except AurGitError:
		return None
	return _lsremote_first_sha(output)


def get_remote_head(package: str) -> str | None:
	try:
		output = run_command(_aur_mirror_lsremote_cmd(package), capture=True)
	except AurGitError:
		return None
	return _lsremote_first_sha(output)


def get_installed_version(package: str) -> str | None:
	try:
		output = run_command(["pacman", "-Qi", package], capture=True)
	except AurGitError:
		return None
	for line in str(output).splitlines():
		if line.lower().startswith("version"):
			_, value = line.split(":", 1)
			return value.strip()
	return None


def list_installed_packages() -> None:
	foreign = list_foreign_packages()

	if not foreign:
		print("No foreign packages installed")
		return

	print(style(f"Installed foreign packages ({len(foreign)}):", CYAN))

	for name in sorted(foreign.keys()):
		version = foreign[name]
		print(f"  {style(name, BOLD)} {style(version, GREEN)}")


def list_repo_packages(name: str, dest_root: Path) -> None:
	# pacman -Sl <repo> shape: "<repo> <name> <version> [installed]". "AUR" reads the
	# bulk metadata dump; any other alias is enumerated like a search with an empty term.
	installed = installed_package_set()
	if name == "AUR":
		if not _aur_enabled():
			print(
				"AUR is disabled. Set [AUR] = true in repos.conf to enable it.",
				file=sys.stderr,
			)
			return
		meta = aur_packages()
		if not meta:
			raise AurGitError("Could not fetch the AUR package list")
		rows: list[tuple[str, str | None]] = [(n, ver) for n, ver, _ in meta]
	else:
		url, branch, subdir, _ = _resolve_repo_for_package(
			None, alias=name, repo_url=None, branch=None, subdir=None
		)
		if url is None:
			raise AurGitError(f"Repo '{name}' has no listable URL")
		results = search_packages_repo(
			url,
			branch,
			subdir,
			regex=None,
			needle="",
			limit=-1,
			source=name,
			dest_root=dest_root,
			alias=name,
		)
		rows = [(r.name, r.version) for r in results]
	lines = [
		f"{name} {n} {ver or 'unknown-version'}"
		+ (" [installed]" if n in installed else "")
		for n, ver in rows
	]
	try:
		sys.stdout.write("\n".join(lines) + "\n")
	except BrokenPipeError:
		# Reader (e.g. `| head`) closed the pipe; mute the fd so the
		# interpreter's exit flush does not raise a second time.
		os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def fetch_git_file(package: str, path: str) -> str | None:
	# Lazy import: pulls in http.client and is unused on a warm cache hit.
	import urllib.request

	safe_package = urllib.parse.quote(package)
	safe_path = path.lstrip("/")
	url = f"{GITHUB_RAW_BASE}/{safe_package}/{safe_path}"
	if DEBUG:
		print(f"+ GET {url}", file=sys.stderr)
	try:
		with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - url built from hardcoded https GitHub base
			if response.status != 200:
				return None
			data: bytes = response.read()
	except urllib.error.URLError:
		return None
	try:
		return data.decode()
	except UnicodeDecodeError:
		return None


def git_srcinfo_metadata(package: str) -> tuple[str, str | None] | None:
	srcinfo = fetch_git_file(package, ".SRCINFO")
	if not srcinfo:
		return None
	version, description = _parse_srcinfo_metadata(srcinfo)
	if not version:  # Changed: only check version since it's required
		return None
	return version, description


def install_official_packages(packages: Iterable[str], *, noconfirm: bool) -> None:
	pkgs = sorted(set(packages))
	if not pkgs:
		return
	cmd: list[str] = ["pacman", "-S", "--needed"]
	if noconfirm:
		cmd.append("--noconfirm")
	cmd.extend(pkgs)
	print(f"Installing official packages: {' '.join(pkgs)}")
	run_command(_elevate(cmd))
	invalidate_installed_cache()


def collect_missing_official_packages(
	package: str,
	dest_root: Path,
	*,
	refresh: bool,
	visited: set[str] | None = None,
) -> tuple[set[str], set[str]]:
	visited = visited or set()
	if package in visited:
		return set(), set()
	visited.add(package)

	package_dir = ensure_clone(package, dest_root, refresh=refresh)
	_, _, deps = parse_dependencies(read_srcinfo(package_dir))

	missing_official: set[str] = set()
	unresolved: set[str] = set()

	for dep in sorted(deps.all_build_deps):
		if dep == package:
			continue
		if is_dependency_satisfied(dep):
			continue
		provider = resolve_official_dependency(dep)
		if provider:
			missing_official.add(provider)
			continue
		aur_provider = resolve_aur_dependency(dep)
		if aur_provider:
			child_missing, child_unresolved = collect_missing_official_packages(
				aur_provider,
				dest_root,
				refresh=refresh,
				visited=visited,
			)
			missing_official.update(child_missing)
			unresolved.update(child_unresolved)
			continue
		if _pacman_returns_zero(["pacman", "-Sp", dep]):
			missing_official.add(dep)
			continue
		unresolved.add(dep)

	return missing_official, unresolved


def build_and_install(
	package_dir: Path, *, noconfirm: bool, refresh: bool = False
) -> None:
	pkgbuild_path = package_dir / "PKGBUILD"
	if not pkgbuild_path.exists():
		raise AurGitError(f"PKGBUILD missing at {pkgbuild_path}")
	flags = "-sif" if refresh else "-si"
	cmd = ["makepkg", flags, "--needed"]
	if noconfirm:
		cmd.append("--noconfirm")
	print(f"Building {package_dir.name} with makepkg")
	extra_env = _ssh_rewrite_git_env() if USE_SSH else {}
	run_command(cmd, cwd=package_dir, env={**os.environ, **extra_env})
	print(f"Built package artifacts remain under {package_dir}")
	invalidate_installed_cache()


def _classify_build_deps(
	deps: DependencySet, package: str
) -> tuple[set[str], set[str], set[str], dict[str, set[str]]]:
	# Sort each build dep into already-satisfied (dropped), official, AUR (with the
	# virtual-provider it satisfies), or unresolved.
	missing_official: set[str] = set()
	aur_dependencies: set[str] = set()
	unresolved: set[str] = set()
	virtual_providers: dict[str, set[str]] = {}
	for dep in sorted(deps.all_build_deps):
		if dep == package or is_dependency_satisfied(dep):
			continue
		provider = resolve_official_dependency(dep)
		if provider:
			missing_official.add(provider)
			continue
		aur_provider = resolve_aur_dependency(dep)
		if aur_provider:
			aur_dependencies.add(aur_provider)
			if aur_provider != dep:
				virtual_providers.setdefault(aur_provider, set()).add(dep)
			continue
		if _pacman_returns_zero(["pacman", "-Sp", dep]):
			missing_official.add(dep)
			continue
		unresolved.add(dep)
	return missing_official, aur_dependencies, unresolved, virtual_providers


def _confirm_aur_dependencies(
	aur_dependencies: set[str], virtual_providers: dict[str, set[str]]
) -> None:
	# List the AUR deps about to be built and abort the install if the user declines.
	print(style("The following AUR dependencies are required:", CYAN))
	for dep_pkg in sorted(aur_dependencies):
		provides = virtual_providers.get(dep_pkg)
		if provides:
			print(f"  {dep_pkg} (provides {', '.join(sorted(provides))})")
		else:
			print(f"  {dep_pkg}")
	if not prompt_confirm(
		style("Proceed with building these dependencies? [y/N]: ", YELLOW)
	):
		raise AurGitError("Installation aborted by user")


def install_package(
	package: str,
	dest_root: Path,
	*,
	refresh: bool,
	noconfirm: bool,
	visited: set[str] | None = None,
	preinstalled_official: set[str] | None = None,
	repo_url: str | None = None,
	branch: str | None = None,
	subdir: str | None = None,
	repo_fallbacks: list[tuple[str, str | None, str | None]] | None = None,
	sources: Sequence[
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		]
	]
	| None = None,
	update_to: str | None = None,
	verify: bool = False,
	submodules: bool = False,
) -> None:
	visited = visited or set()
	if package in visited:
		return
	visited.add(package)

	if is_installed(package):
		installed_ver = get_installed_version(package)
		if update_to:
			print(f"Updating {style(package, BOLD)} ({installed_ver} -> {update_to})")
		else:
			print(
				f"Package {style(package, BOLD)} is already installed ({installed_ver})"
			)
			if not noconfirm and not prompt_confirm(
				style("Reinstall? [y/N]: ", YELLOW)
			):
				print("Cancelled installation.")
				return

	if preinstalled_official is None:
		preinstalled_official = set()

	# Clone from the source chain or the AUR mirror (repo_url None), then read deps
	# from the cloned .SRCINFO.
	if sources is not None:
		package_dir = _clone_any_source(
			package, dest_root, sources, refresh=refresh, submodules=submodules
		)
	else:
		package_dir = ensure_clone(
			package,
			dest_root,
			refresh=refresh,
			repo_url=repo_url,
			branch=branch,
			subdir=subdir,
			repo_fallbacks=repo_fallbacks,
			submodules=submodules,
		)
	if verify:
		_verify_signature(package_dir, package, branch)
	_, pkgdesc, deps = parse_dependencies(read_srcinfo(package_dir))
	print(f"==> {package}: {pkgdesc}" if pkgdesc else f"==> {package}")

	missing_official, aur_dependencies, unresolved, virtual_providers = (
		_classify_build_deps(deps, package)
	)

	if unresolved:
		missing_list = ", ".join(sorted(unresolved))
		raise AurGitError(f"Could not resolve providers for: {missing_list}")

	if missing_official:
		to_install = missing_official - preinstalled_official
		if to_install:
			install_official_packages(to_install, noconfirm=noconfirm)
			preinstalled_official.update(to_install)

	if aur_dependencies and not noconfirm:
		_confirm_aur_dependencies(aur_dependencies, virtual_providers)

	for aur_dep in sorted(aur_dependencies):
		install_package(
			aur_dep,
			dest_root,
			refresh=refresh,
			noconfirm=noconfirm,
			visited=visited,
			preinstalled_official=preinstalled_official,
			verify=verify,
			submodules=submodules,
		)

	build_and_install(package_dir, noconfirm=noconfirm, refresh=refresh)


def remove_package(
	package: str,
	dest_root: Path,
	*,
	noconfirm: bool,
	remove_clone: bool,
) -> None:
	# Clone removal first: inspect/fetch also create clones, so one can
	# exist for a package that was never installed.
	if remove_clone:
		package_dir = dest_root / package
		if package_dir.exists():
			print(f"Removing clone {package_dir}")
			shutil.rmtree(package_dir)
			print(f"Removed clone for {style(package, GREEN)}")
		else:
			print(f"No clone found at {package_dir}")

	if not is_installed(package):
		print(f"Package {style(package, BOLD)} is not installed")
		return

	# Remove with pacman -Rns
	cmd: list[str] = ["pacman", "-Rns", package]
	if noconfirm:
		cmd.append("--noconfirm")

	print(f"Removing package {style(package, BOLD)}")
	try:
		run_command(_elevate(cmd))
		invalidate_installed_cache()
		print(f"Successfully removed {style(package, GREEN)}")
	except AurGitError as exc:
		print(f"Failed to remove package: {exc}", file=sys.stderr)


def get_ignored_packages() -> set[str]:
	ignored: set[str] = set()
	pacman_conf = Path("/etc/pacman.conf")

	if not pacman_conf.exists():
		return ignored

	content = pacman_conf.read_text()

	for raw_line in content.splitlines():
		line = raw_line.strip()

		# Skip comments and empty lines
		if not line or line.startswith("#"):
			continue

		# Look for IgnorePkg lines
		# Format: IgnorePkg = pkg1 pkg2 pkg3
		if line.startswith("IgnorePkg") and "=" in line:
			_, packages = line.split("=", 1)
			for pkg in packages.split():
				ignored.add(pkg.strip())

	return ignored


def _resolve_update_spec(
	package: str,
	alias: str | None,
	url: str | None,
	branch: str | None,
	subdir: str | None,
) -> tuple[
	str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
]:
	# "AUR" section (or the no-conf default) is the built-in AUR backend: a None
	# repo_url, never run through the alias/URL parser.
	if alias == "AUR" or (alias is None and url is None):
		return None, None, None, []
	return _resolve_repo_for_package(
		package, alias=alias, repo_url=url, branch=branch, subdir=subdir
	)


def _probe_aur_update(
	package: str, dest_root: Path
) -> tuple[str | None, str | None, str | None] | None:
	# (remote_version, remote_head, local_head) from the AUR, or None if absent.
	meta = git_srcinfo_metadata(package)
	rv = meta[0] if meta else None
	if rv and is_vcs_package(package):
		rv = None
	if rv is not None:
		return rv, None, None
	rh = get_remote_head(package)
	if rh is None:
		return None
	return None, rh, get_local_head(dest_root / package)


def _probe_git_update(
	package: str,
	dest_root: Path,
	source: tuple[
		str, str | None, str | None, list[tuple[str, str | None, str | None]]
	],
	*,
	refresh: bool,
) -> tuple[str | None, str | None, str | None] | None:
	# As _probe_aur_update, against a git source: VCS pkgs compare the remote head,
	# versioned pkgs clone and read the .SRCINFO (no metadata API on a plain git host).
	s_url, s_branch, s_subdir, s_fallbacks = source
	if is_vcs_package(package):
		rh = _git_remote_head(s_url, s_branch)
		if rh is None:
			return None
		return None, rh, get_local_head(dest_root / package)
	try:
		pkg_dir = ensure_clone(
			package,
			dest_root,
			refresh=refresh,
			repo_url=s_url,
			branch=s_branch,
			subdir=s_subdir,
			repo_fallbacks=s_fallbacks,
		)
	except AurGitError:
		return None
	if not (pkg_dir / "PKGBUILD").is_file():
		return None
	rv = _parse_srcinfo_metadata(read_srcinfo(pkg_dir))[0]
	return (rv, None, None) if rv is not None else None


def _find_update_source(
	package: str,
	update_specs: list[tuple[str | None, str | None]],
	dest_root: Path,
	*,
	refresh: bool,
	branch: str | None,
	subdir: str | None,
) -> tuple[
	tuple[str | None, str | None, str | None, list[tuple[str, str | None, str | None]]],
	tuple[str | None, str | None, str | None],
]:
	# Walk the source chain (conf order == precedence); return (winning source, probe)
	# for the first source that has the package, or raise LookupError if none does.
	for alias, url in update_specs:
		source = _resolve_update_spec(package, alias, url, branch, subdir)
		s_url = source[0]
		if s_url is None:
			probe = _probe_aur_update(package, dest_root)
		else:
			git_source = (s_url, source[1], source[2], source[3])
			probe = _probe_git_update(package, dest_root, git_source, refresh=refresh)
		if probe is not None:
			return source, probe
	raise LookupError(package)


def _run_system_update(*, noconfirm: bool) -> bool:
	# Run the pacman half of `update --global` (-Syu). Returns False when the caller
	# should stop: the user declined to continue after a failed system update.
	cmd = ["pacman", "-Syu"]
	if noconfirm:
		cmd.append("--noconfirm")

	print(style("Updating system packages first...", CYAN))
	try:
		run_command(_elevate(cmd))
		invalidate_installed_cache()
	except AurGitError as exc:
		print(f"System update failed: {exc}", file=sys.stderr)
		if not noconfirm and not prompt_confirm(
			style("Continue with AUR updates? [y/N]: ", YELLOW)
		):
			return False

	return True


def _collect_update_candidates(
	targets: Sequence[str] | None,
) -> list[tuple[str, str | None]] | None:
	# (name, installed_version) for each package to check. None when there is nothing
	# to do (no foreign packages), already reported.
	if targets:
		seen: set[str] = set()
		out: list[tuple[str, str | None]] = []
		for pkg in targets:
			if pkg not in seen:
				seen.add(pkg)
				out.append((pkg, get_installed_version(pkg)))
		return out
	foreign = list_foreign_packages()
	if not foreign:
		print("No foreign packages reported by pacman -Qm")
		return None
	return list(foreign.items())


def _update_target_label(candidate: UpdateCandidate) -> str:
	# Human/`update_to` label for the version a candidate moves to.
	if candidate.target_version:
		return candidate.target_version
	if candidate.remote_head:
		return candidate.remote_head[:7]
	return "newer"


def _update_source_label(
	repo: str | None,
	repo_url: str | None,
	update_specs: list[tuple[str | None, str | None]],
) -> str:
	# What to call the source(s) in "not available via ..." notes.
	if repo or repo_url:
		return f"repo '{repo}'" if repo else "the custom repo"
	if update_specs in ([(None, None)], [("AUR", None)]):
		return "the AUR mirror"
	return "any configured source"


def _plan_updates(
	candidates: list[tuple[str, str | None]],
	update_specs: list[tuple[str | None, str | None]],
	dest_root: Path,
	*,
	ignored: set[str],
	skip_devel: bool,
	refresh: bool,
	branch: str | None,
	subdir: str | None,
) -> tuple[
	list[UpdateCandidate],
	dict[
		str,
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		],
	],
	list[str],
]:
	# Resolve each candidate against the source chain and keep the ones with a newer
	# version/head. Returns (pending, winning-source-per-package, not-found).
	pending: list[UpdateCandidate] = []
	winning: dict[
		str,
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		],
	] = {}
	missing: list[str] = []
	for package, installed_version in candidates:
		if is_debug_package(package):
			continue
		if package in ignored:
			print(f"Skipping {package} (in IgnorePkg)", file=sys.stderr)
			continue
		if skip_devel and is_vcs_package(package):
			continue
		try:
			source, (remote_version, remote_head, local_head) = _find_update_source(
				package,
				update_specs,
				dest_root,
				refresh=refresh,
				branch=branch,
				subdir=subdir,
			)
		except LookupError:
			missing.append(package)
			continue
		winning[package] = source
		if installed_version and remote_version and installed_version == remote_version:
			continue
		if remote_head:
			if local_head is None:
				local_head = get_local_head(dest_root / package)
			if local_head and local_head == remote_head:
				continue
		pending.append(
			UpdateCandidate(
				name=package,
				installed_version=installed_version,
				target_version=remote_version,
				remote_head=remote_head,
				local_head=local_head,
			)
		)
	return pending, winning, missing


def _rebuild_updates(
	selected: list[UpdateCandidate],
	winning_source: dict[
		str,
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		],
	],
	dest_root: Path,
	*,
	refresh: bool,
	noconfirm: bool,
) -> None:
	# Rebuild each selected package from the source it was found in, sharing dedup and
	# official-dep state across the run.
	shared_visited: set[str] = set()
	shared_preinstalled_official: set[str] = set()
	for candidate in selected:
		r_url, r_branch, r_subdir, r_fallbacks = winning_source.get(
			candidate.name, (None, None, None, [])
		)
		try:
			install_package(
				candidate.name,
				dest_root,
				refresh=refresh,
				noconfirm=noconfirm,
				visited=shared_visited,
				preinstalled_official=shared_preinstalled_official,
				repo_url=r_url,
				branch=r_branch,
				subdir=r_subdir,
				repo_fallbacks=r_fallbacks,
				update_to=_update_target_label(candidate),
			)
		except AurGitError as exc:
			print(f"error updating {candidate.name}: {exc}", file=sys.stderr)


def _print_missing_notes(missing: list[str], source_label: str) -> None:
	for package in missing:
		if is_debug_package(package):
			continue
		print(f"note: {package} is not available via {source_label}", file=sys.stderr)


def update_packages(
	dest_root: Path,
	*,
	refresh: bool,
	noconfirm: bool,
	update_system: bool,
	include_devel: bool,
	targets: Sequence[str] | None = None,
	repo: str | None = None,
	repo_url: str | None = None,
	branch: str | None = None,
	subdir: str | None = None,
) -> None:
	ignored = get_ignored_packages()

	if update_system and not _run_system_update(noconfirm=noconfirm):
		return

	candidates = _collect_update_candidates(targets)
	if candidates is None:
		return

	# Version-check each package against an ordered source chain (conf order ==
	# precedence): an explicit --repo/--repo-url is the only source, otherwise every
	# repos.conf section top to bottom, with the AUR backend as the section named "AUR"
	# (or the implicit source when there is no conf). The first source that has the
	# package decides its update and is reused for the rebuild; packages no source
	# carries fall to `missing`.
	if repo or repo_url:
		update_specs: list[tuple[str | None, str | None]] = [(repo, repo_url)]
	else:
		update_specs = [(name, None) for name in load_repo_registry()] or [(None, None)]

	pending_updates, winning_source, missing = _plan_updates(
		candidates,
		update_specs,
		dest_root,
		ignored=ignored,
		skip_devel=not include_devel and not targets,
		refresh=refresh,
		branch=branch,
		subdir=subdir,
	)
	source_label = _update_source_label(repo, repo_url, update_specs)

	if not pending_updates:
		print("All packages are up to date.")
		_print_missing_notes(missing, source_label)
		return

	for index, candidate in enumerate(pending_updates, start=1):
		from_version = candidate.installed_version or "?"
		print(
			f"{index}) {candidate.name} {from_version} -> {_update_target_label(candidate)}"
		)

	interactive = sys.stdin.isatty() and sys.stdout.isatty()
	if interactive:
		selected_candidates = interactive_select_updates(pending_updates)
		if not selected_candidates:
			return
	else:
		selected_candidates = pending_updates

	_rebuild_updates(
		selected_candidates,
		winning_source,
		dest_root,
		refresh=refresh,
		noconfirm=noconfirm,
	)
	_print_missing_notes(missing, source_label)


def search_packages(
	*,
	regex: re.Pattern[str] | None,
	needle: str | None,
	limit: int | None,
) -> list[SearchResult]:
	return search_packages_git(regex=regex, needle=needle, limit=limit)


def _fetch_aur_meta() -> list[tuple[str, str | None, str | None]] | None:
	# Bulk AUR metadata dump: name + version + description for every package, one gzip.
	import gzip
	import urllib.request

	url = "https://aur.archlinux.org/packages-meta-v1.json.gz"
	if DEBUG:
		print(f"+ GET {url}", file=sys.stderr)
	try:
		with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - hardcoded https AUR endpoint
			data = json.loads(gzip.decompress(response.read()).decode())
	except (OSError, ValueError) as exc:
		if DEBUG:
			print(f"+ packages-meta failed: {exc}", file=sys.stderr)
		return None
	rows = [
		(
			entry["Name"],
			_str_or_none(entry.get("Version")),
			_str_or_none(entry.get("Description")),
		)
		for entry in (data if isinstance(data, list) else [])
		if isinstance(entry, dict) and isinstance(entry.get("Name"), str)
	]
	return rows or None


def _fetch_names_git() -> list[str] | None:
	output = run_command(_aur_mirror_lsremote_cmd(), capture=True)
	return _lsremote_names(output) or None


def _fetch_aur_packages() -> list[tuple[str, str | None, str | None]] | None:
	# The metadata dump is canonical (names + versions + descriptions in one fetch).
	# The git mirror's branch list is the names-only fallback when the dump is down.
	rows = _fetch_aur_meta()
	if rows:
		return rows
	names = _fetch_names_git()
	if not names:
		return None
	print(
		"AUR metadata dump unavailable; using git mirror name list...", file=sys.stderr
	)
	return [(name, None, None) for name in names]


def _fetch_aur_packages_with_completion() -> (
	list[tuple[str, str | None, str | None]] | None
):
	rows = _fetch_aur_packages()
	if rows:
		# Plain-text name list for the shell completions (newline list greps fast).
		path = _completion_cache_path()
		if path is not None:
			_atomic_write(path, "\n".join(row[0] for row in rows) + "\n")
	return rows


def aur_packages() -> list[tuple[str, str | None, str | None]]:
	# (name, version, description) for every AUR package. None on a failed fetch so a
	# transient hiccup is never cached for an hour; cache hits come back as JSON lists.
	rows = cached_json("aurmeta.json", CACHE_TTL, _fetch_aur_packages_with_completion)
	out: list[tuple[str, str | None, str | None]] = []
	for row in rows if isinstance(rows, list) else []:
		if isinstance(row, list | tuple) and row and isinstance(row[0], str):
			ver = _str_or_none(row[1]) if len(row) > 1 else None
			desc = _str_or_none(row[2]) if len(row) > 2 else None
			out.append((row[0], ver, desc))
	return out


def search_packages_git(
	*,
	regex: re.Pattern[str] | None,
	needle: str | None,
	limit: int | None,
) -> list[SearchResult]:
	# Score every AUR package by name; version/description come straight from the bulk
	# metadata dump, so there is no per-package fetch.
	if limit is None:
		limit = 50
	scored: list[tuple[int, tuple[str, str | None, str | None]]] = []
	for row in aur_packages():
		score = compute_match_score(row[0], regex=regex, needle=needle)
		if score is not None:
			scored.append((score, row))
	if limit >= 0:
		scored = heapq.nsmallest(limit, scored, key=lambda item: (item[0], item[1][0]))
	else:
		scored.sort(key=lambda item: (item[0], item[1][0]))
	installed = installed_package_set()
	return [
		SearchResult(
			name=row[0],
			version=row[1],
			description=row[2],
			installed=row[0] in installed,
			score=score,
		)
		for score, row in scored
	]


def _repo_package_names(
	repo_url: str, branch: str | None, subdir: str | None, clone_dir: Path
) -> list[tuple[str, Path | None]]:
	# Enumerate a custom repo's packages -> (name, srcinfo_dir). Layouts:
	#   subdir-container : one dir per package under <subdir> (glob <subdir>/*/PKGBUILD).
	#   flat            : one dir per package at the repo root (glob */PKGBUILD).
	#   branch-per-package: one branch per package (read off `git ls-remote`).
	# Clone the default (or --rev) ref and list its package dirs. If the working tree
	# has none and no --subdir was given, fall back to branch-per-package via ls-remote.
	# This distinguishes flat from branch-per-package by what the ref actually contains
	# (head count can't: a flat repo may carry a few arch/variant branches). Templated
	# ({pkg}) aliases have no index and are rejected by the caller.
	remote = _remote_for(repo_url)
	clone_cmd = ["git", "clone", "--depth=1"]
	if branch:
		clone_cmd += ["--branch", branch]
	clone_cmd += [remote, str(clone_dir)]
	run_command(clone_cmd)
	base = clone_dir / subdir if subdir else clone_dir
	if subdir and not base.is_dir():
		raise AurGitError(f"Subdirectory '{subdir}' not found in {repo_url}")
	names: list[tuple[str, Path | None]] = sorted(
		(p.parent.name, p.parent) for p in base.glob("*/PKGBUILD")
	)
	if names or subdir:
		return names
	# Root carried no package dirs -> one branch per package.
	output = run_command(["git", "ls-remote", "--heads", remote], capture=True)
	return sorted({(name, None) for name in _lsremote_names(output)})


def _enumerate_repo(
	repo_url: str, branch: str | None, subdir: str | None, dest_root: Path
) -> list[tuple[str, str | None, str | None]]:
	# Clone (subdir layout) or ls-remote (branch layout) a custom repo and return
	# (name, version, description) per package. Wrapped in cached_json by the caller,
	# so this only runs on a cache miss. Clones into a scratch dir under dest-root.
	clone_dir = dest_root / ".searchrepo"
	dest_root.mkdir(parents=True, exist_ok=True)
	if clone_dir.exists():
		shutil.rmtree(clone_dir)
	out: list[tuple[str, str | None, str | None]] = []
	for name, srcinfo_dir in _repo_package_names(repo_url, branch, subdir, clone_dir):
		version: str | None = None
		description: str | None = None
		if srcinfo_dir is not None:
			srcinfo_path = srcinfo_dir / ".SRCINFO"
			if srcinfo_path.exists():
				version, description = _parse_srcinfo_metadata(srcinfo_path.read_text())
		out.append((name, version, description))
	return out


def search_packages_repo(
	repo_url: str,
	branch: str | None,
	subdir: str | None,
	*,
	regex: re.Pattern[str] | None,
	needle: str | None,
	limit: int | None,
	source: str,
	dest_root: Path,
	alias: str | None = None,
) -> list[SearchResult]:
	if limit is None:
		limit = 50
	installed = installed_package_set()
	# (name, version, description, source) candidates from whichever index applies.
	# source = the pacman repo for sync-DB results (extra/cachyos/...) so a templated
	# search reads like `pacman -Ss`; the alias name for an enumerable repo.
	candidates: list[tuple[str, str | None, str | None, str]] = []
	from_db = "{pkg}" in repo_url or "{pkgbase}" in repo_url
	if from_db:
		# A template has no per-alias listing; fall back to the pacman sync DBs (the
		# Arch GitLab case). Genuinely indexless aliases still error.
		candidates = list(_sync_db_packages())
		if not candidates:
			raise AurGitError(
				f"alias is templated ({repo_url}) and no pacman sync DB is available "
				"to enumerate it. Search needs an index (a subdir, branches, or sync DB)."
			)
	else:
		# Enumerate the repo (clone/ls-remote) but cache the result per source, so a
		# repeat search doesn't re-clone. --refresh expires it (CACHE_TTL=0).
		ckey = (
			"repolist/"
			+ hashlib.sha256(f"{repo_url}\n{branch}\n{subdir}".encode()).hexdigest()[
				:16
			]
			+ ".json"
		)
		listed = cached_json(
			ckey,
			CACHE_TTL,
			lambda: _enumerate_repo(repo_url, branch, subdir, dest_root),
		)
		for entry in listed if isinstance(listed, list) else []:
			if isinstance(entry, (list, tuple)) and len(entry) == 3:
				candidates.append((entry[0], entry[1], entry[2], source))

	results: list[SearchResult] = []
	for name, version, description, item_source in candidates:
		score = compute_match_score(name, regex=regex, needle=needle)
		if score is None:
			continue
		results.append(
			SearchResult(
				name=name,
				version=version,
				description=description,
				installed=name in installed,
				score=score,
				source=item_source,
				from_db=from_db,
				repo_alias=alias,
			)
		)
	results.sort(key=lambda result: (result.score, result.name))
	if limit >= 0:
		results = results[:limit]
	return results


def order_search_results(results: Sequence[SearchResult]) -> list[SearchResult]:
	# Lower score = better match; return ascending order (best last when reversed later).
	return sorted(results, key=lambda result: (result.score, result.name))


def format_search_result(index: int, result: SearchResult) -> list[str]:
	index_label = style(f"{index:>2})", CYAN)
	main_parts: list[str] = [style(result.name, BOLD)]
	if result.version:
		main_parts.append(style(result.version, GREEN))
	if result.installed:
		main_parts.append(style("[installed]", GREEN))
	protocol = "ssh" if USE_SSH else "https"
	if result.from_db:
		# Listed from a local pacman sync DB, not fetched over a protocol.
		meta_bits: list[str] = [f"db {result.source}"]
	elif result.source is not None:
		meta_bits = [f"{protocol} {result.source}"]
	else:
		meta_bits = [f"{protocol} git mirror"]
	line = f"{index_label} {' '.join(main_parts)}"
	if meta_bits:
		line += f" {style('[' + ', '.join(meta_bits) + ']', DIM)}"
	lines = [line]
	if result.description:
		# Limit description to 120 characters
		desc = result.description
		if len(desc) > 120:
			desc = desc[:117] + "..."
		lines.append(f"    {style(desc, DIM)}")
	return lines


def format_search_result_plain(result: SearchResult) -> list[str]:
	# pacman -Ss shape for scripting: "<repo>/name version [installed]" plus an
	# indented description line, always two lines per package. <repo> is the custom
	# source label when set, else "aur".
	line = f"{result.source or 'aur'}/{result.name}"
	if result.version:
		line += f" {result.version}"
	if result.installed:
		line += " [installed]"
	return [line, f"    {result.description or ''}"]


def print_search_results(results: Sequence[SearchResult]) -> None:
	total = len(results)
	for pos, result in enumerate(results):
		display_index = total - pos
		for line in format_search_result(display_index, result):
			print(line)


def format_update_candidate(index: int, candidate: UpdateCandidate) -> list[str]:
	index_label = style(f"{index:>2})", CYAN)
	name_part = style(candidate.name, BOLD)
	current_version = candidate.installed_version or "?"
	if candidate.target_version:
		target_label = candidate.target_version
	elif candidate.remote_head:
		target_label = f"{candidate.remote_head[:7]}"
	else:
		target_label = "unknown"
	change = f"{current_version} -> {target_label}"
	meta_bits: list[str] = []
	if candidate.remote_head and not candidate.target_version:
		meta_bits.append("git commit")
	line = f"{index_label} {name_part} {style(change, GREEN)}"
	if meta_bits:
		line += f" {style('[' + ', '.join(meta_bits) + ']', DIM)}"
	return [line]


def interactive_select_updates(
	candidates: Sequence[UpdateCandidate],
) -> list[UpdateCandidate]:
	if not candidates:
		return []
	prompt_text = style(
		"Select packages to update (Enter for all, q to quit): ",
		YELLOW,
	)
	total = len(candidates)
	while True:
		try:
			raw = input(prompt_text)
		except EOFError:
			return list(candidates)
		if not raw.strip():
			return list(candidates)
		parsed = parse_selection(raw, total)
		if parsed is None:
			print(style("Invalid selection. Please try again.", YELLOW))
			continue
		if not parsed:
			return []
		selected: list[UpdateCandidate] = []
		for value in parsed:
			index = value - 1
			if index < 0 or index >= total:
				selected = []
				break
			selected.append(candidates[index])
		if not selected and parsed:
			print(style("Invalid selection. Please try again.", YELLOW))
			continue
		return selected


def parse_selection(selection: str, max_index: int) -> list[int] | None:
	selection = selection.strip().lower()
	if not selection:
		return []
	if selection in {"q", "quit"}:
		return []
	if selection in {"a", "all"}:
		return list(range(1, max_index + 1))
	chosen: set[int] = set()
	tokens = re.split(r"[\s,]+", selection)
	for token in tokens:
		if not token:
			continue
		if "-" in token:
			start_str, end_str = token.split("-", 1)
			try:
				start = int(start_str)
				end = int(end_str)
			except ValueError:
				return None
			if start > end:
				start, end = end, start
			if start < 1 or end > max_index:
				return None
			chosen.update(range(start, end + 1))
			continue
		try:
			value = int(token)
		except ValueError:
			return None
		if value < 1 or value > max_index:
			return None
		chosen.add(value)
	return sorted(chosen)


def interactive_select_results(results: Sequence[SearchResult]) -> list[SearchResult]:
	if not results:
		return []
	total = len(results)
	prompt_text = style(
		"Select packages to install (e.g. 1 3-5, a for all, q to quit): ",
		YELLOW,
	)
	while True:
		try:
			raw = input(prompt_text)
		except EOFError:
			return []
		parsed = parse_selection(raw, total)
		if parsed is None:
			print(style("Invalid selection. Please try again.", YELLOW))
			continue
		if not parsed:
			return []
		selected: list[SearchResult] = []
		for value in parsed:
			index = total - value
			selected.append(results[index])
		return selected


def _join_values(values: Iterable[str], *, sort: bool = False) -> str:
	items = sorted(values) if sort else list(values)
	return "  ".join(items) if items else "None"


def _srcinfo_values(srcinfo_content: str, key: str) -> list[str]:
	return [v for k, v in _iter_srcinfo_kv(srcinfo_content) if k == key and v]


def srcinfo_info_fields(
	package: str, srcinfo_content: str, repo: str = "aur"
) -> list[tuple[str, str]]:
	_, pkgdesc, deps = parse_dependencies(srcinfo_content)

	def first(key: str) -> str | None:
		values = _srcinfo_values(srcinfo_content, key)
		return values[0] if values else None

	def join(values: Iterable[str]) -> str:
		return _join_values(values, sort=True)

	version = _assemble_version(first("pkgver"), first("pkgrel"), first("epoch"))
	return [
		("Repository", repo),
		("Name", package),
		("Version", version or "None"),
		("Description", pkgdesc or "None"),
		("URL", first("url") or "None"),
		("Licenses", join(_srcinfo_values(srcinfo_content, "license"))),
		("Provides", join(_srcinfo_values(srcinfo_content, "provides"))),
		("Depends On", join(deps.depends)),
		("Make Deps", join(deps.makedepends)),
		("Check Deps", join(deps.checkdepends)),
		("Optional Deps", join(deps.optdepends)),
		("Conflicts With", join(_srcinfo_values(srcinfo_content, "conflicts"))),
	]


def print_info_fields(fields: list[tuple[str, str]]) -> None:
	width = max(len(key) for key, _ in fields)
	for key, value in fields:
		print(f"{key:<{width}} : {value}")


def _print_info_summary(
	package: str,
	description: str | None,
	deps: DependencySet,
) -> None:
	print(f"Package: {package}")
	if description:
		print(f"Description: {description}")
	for label, values in (
		("Depends", deps.depends),
		("Make depends", deps.makedepends),
		("Check depends", deps.checkdepends),
		("Optional", deps.optdepends),
	):
		if values:
			print(f"{label}:")
			for dep in sorted(values):
				print(f"  {dep}")
		else:
			print(f"{label}: (none)")


def inspect_package(
	package: str,
	dest_root: Path,
	*,
	refresh: bool,
	target: str,
	repo_url: str | None = None,
	branch: str | None = None,
	subdir: str | None = None,
	repo_fallbacks: list[tuple[str, str | None, str | None]] | None = None,
	sources: Sequence[
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		]
	]
	| None = None,
	plain: bool = False,
) -> None:
	if sources is not None:
		package_dir = _clone_any_source(package, dest_root, sources, refresh=refresh)
	else:
		package_dir = ensure_clone(
			package,
			dest_root,
			refresh=refresh,
			repo_url=repo_url,
			branch=branch,
			subdir=subdir,
			repo_fallbacks=repo_fallbacks,
		)
	if target == "PKGBUILD":
		pkgbuild_path = package_dir / "PKGBUILD"
		if not pkgbuild_path.exists():
			raise AurGitError(f"PKGBUILD not found at {pkgbuild_path}")
		print(pkgbuild_path.read_text())
		return
	if target == "SRCINFO":
		print(read_srcinfo(package_dir))
		return

	srcinfo = read_srcinfo(package_dir)
	if plain:
		print_info_fields(
			srcinfo_info_fields(package, srcinfo, _origin_label(package_dir))
		)
		return
	_, pkgdesc, deps = parse_dependencies(srcinfo)
	_print_info_summary(package, pkgdesc, deps)


def fetch_package(
	package: str,
	dest_root: Path,
	*,
	refresh: bool,
	repo_url: str | None = None,
	branch: str | None = None,
	subdir: str | None = None,
	repo_fallbacks: list[tuple[str, str | None, str | None]] | None = None,
	sources: Sequence[
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		]
	]
	| None = None,
	verify: bool = False,
	submodules: bool = False,
) -> Path:
	if sources is not None:
		package_dir = _clone_any_source(
			package, dest_root, sources, refresh=refresh, submodules=submodules
		)
	else:
		package_dir = ensure_clone(
			package,
			dest_root,
			refresh=refresh,
			repo_url=repo_url,
			branch=branch,
			subdir=subdir,
			repo_fallbacks=repo_fallbacks,
			submodules=submodules,
		)
	if verify:
		_verify_signature(package_dir, package, branch)
	print(f"Package fetched to {package_dir}")
	return package_dir


def _capitalize_help_action(parser: argparse.ArgumentParser) -> None:
	for action in parser._actions:
		if isinstance(action, argparse._HelpAction):
			action.help = "Show this help message and exit"


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Build Arch packages from any git source (official Arch packages by default; AUR opt-in)"
	)
	parser.add_argument(
		"-v",
		"--version",
		action="version",
		version=f"{__appname__} {__version__} - MIT 2026.",
		help="Show version and exit",
	)
	default_dest = str(Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")) / __appname__)
	parser.add_argument(
		"--dest-root",
		default=default_dest,
		help="Directory to store cloned packages "
		"(default: $XDG_CACHE_HOME/grimoire or ~/.cache/grimoire)",
	)
	parser.add_argument(
		"--refresh", action="store_true", help="Refresh existing clones before use"
	)
	parser.add_argument(
		"--no-color",
		action="store_true",
		help="Disable coloured output",
	)
	parser.add_argument(
		"--use-ssh",
		action="store_true",
		help="Use SSH instead of HTTPS for git operations",
	)
	parser.add_argument(
		"--shallow",
		action="store_true",
		help="Use shallow clones (--depth=1); default is full history",
	)
	subparsers = parser.add_subparsers(dest="command")

	fetch_parser = subparsers.add_parser(
		"fetch", help="Clone the package branch locally"
	)
	fetch_parser.add_argument(
		"packages",
		nargs="+",
		metavar="package",
		help="Package name(s) / branch to clone",
	)
	fetch_src = fetch_parser.add_mutually_exclusive_group()
	fetch_src.add_argument("--repo-url", help="Clone from custom Git URL")
	fetch_src.add_argument(
		"--repo",
		metavar="NAME",
		help="Use a registered repo alias as the mirror list (see 'grimoire repo --ls')",
	)
	fetch_parser.add_argument(
		"--subdir",
		help="Build from this subdirectory of the repo (relative to clone root)",
	)
	fetch_parser.add_argument(
		"--rev", help="Git revision to check out: branch, tag, or commit"
	)
	fetch_parser.add_argument(
		"--verify",
		action="store_true",
		help="Require a valid GPG signature: verify-tag if HEAD is a tag, else verify-commit (no trust check)",
	)
	fetch_parser.add_argument(
		"--submod",
		action="store_true",
		help="Init the repo's git submodules after checkout (git submodule update --init --recursive)",
	)

	install_parser = subparsers.add_parser(
		"install", help="Resolve dependencies and build/install a package"
	)
	install_parser.add_argument(
		"packages", nargs="+", metavar="package", help="Package name(s) to install"
	)
	install_parser.add_argument(
		"--noconfirm", action="store_true", help="Pass --noconfirm to pacman/makepkg"
	)
	install_src = install_parser.add_mutually_exclusive_group()
	install_src.add_argument("--repo-url", help="Clone from custom Git URL")
	install_src.add_argument(
		"--repo",
		metavar="NAME",
		help="Use a registered repo alias as the mirror list (see 'grimoire repo --ls')",
	)
	install_parser.add_argument(
		"--subdir",
		help="Build from this subdirectory of the repo (relative to clone root)",
	)
	install_parser.add_argument(
		"--rev", help="Git revision to check out: branch, tag, or commit"
	)
	install_parser.add_argument(
		"--verify",
		action="store_true",
		help="Require a valid GPG signature: verify-tag if HEAD is a tag, else verify-commit (no trust check)",
	)
	install_parser.add_argument(
		"--submod",
		action="store_true",
		help="Init the repo's git submodules after checkout (git submodule update --init --recursive)",
	)

	remove_parser = subparsers.add_parser("remove", help="Remove an installed package")
	remove_parser.add_argument(
		"packages", nargs="*", metavar="package", help="Package name(s) to remove"
	)
	remove_parser.add_argument(
		"--noconfirm", action="store_true", help="Pass --noconfirm to pacman"
	)
	remove_parser.add_argument(
		"--clone",
		action="store_true",
		help="Also remove the package's clone from dest-root",
	)
	remove_parser.add_argument(
		"--cache",
		action="store_true",
		help="Remove the search result cache (.searchcache) from dest-root",
	)

	update_parser = subparsers.add_parser(
		"update",
		help="Upgrade installed foreign packages by rebuilding them from the mirror",
	)
	update_parser.add_argument(
		"packages",
		nargs="*",
		help="Specific foreign package names to update (default: all from pacman -Qm)",
	)
	update_parser.add_argument(
		"--noconfirm", action="store_true", help="Pass --noconfirm to pacman/makepkg"
	)
	update_parser.add_argument(
		"--devel",
		action="store_true",
		help="Include VCS/devel packages (e.g. *-git) when checking for updates",
	)
	update_src = update_parser.add_mutually_exclusive_group()
	update_src.add_argument(
		"--repo-url", help="Check/rebuild updates from a custom Git URL"
	)
	update_src.add_argument(
		"--repo",
		metavar="NAME",
		help="Check/rebuild updates from a registered repo alias (see 'grimoire repo --ls')",
	)
	update_parser.add_argument(
		"--subdir",
		help="Build from this subdirectory of the repo (relative to clone root)",
	)
	update_parser.add_argument(
		"--rev", help="Git revision to check out: branch, tag, or commit"
	)
	update_parser.add_argument(
		"--global",
		action="store_true",
		help="Update system packages (pacman -Syu) before updating AUR packages",
	)
	search_parser = subparsers.add_parser(
		"search", help="Search packages via the configured backend"
	)
	search_parser.add_argument(
		"pattern", help="Substring or regex to match against package names"
	)
	search_parser.add_argument(
		"--limit", type=int, help="Limit results to the first N matches"
	)
	search_parser.add_argument(
		"--no-interactive",
		action="store_true",
		help="Disable interactive selection and only list results",
	)
	search_parser.add_argument(
		"--noconfirm",
		action="store_true",
		help="Skip confirmation prompts when installing from search",
	)
	search_parser.add_argument(
		"--plain",
		action="store_true",
		help="pacman -Ss style output (best match first) for scripting; "
		"implies --no-interactive",
	)
	search_src = search_parser.add_mutually_exclusive_group()
	search_src.add_argument(
		"--repo-url", help="Search a custom Git repo instead of the AUR"
	)
	search_src.add_argument(
		"--repo",
		metavar="NAME",
		help="Search a registered repo alias instead of the AUR (see 'grimoire repo --ls')",
	)
	search_parser.add_argument(
		"--subdir",
		help="Package container subdir in the repo (one dir per package)",
	)
	search_parser.add_argument(
		"--rev", help="Git revision to search: branch, tag, or commit"
	)

	inspect_parser = subparsers.add_parser(
		"inspect", help="Show PKGBUILD or dependency information"
	)
	inspect_parser.add_argument(
		"packages", nargs="+", metavar="package", help="Package name(s) to inspect"
	)
	inspect_parser.add_argument(
		"--target",
		choices=["info", "PKGBUILD", "SRCINFO"],
		default="info",
		help="Which data to show (default: info)",
	)
	inspect_src = inspect_parser.add_mutually_exclusive_group()
	inspect_src.add_argument("--repo-url", help="Inspect package from custom Git URL")
	inspect_src.add_argument(
		"--repo",
		metavar="NAME",
		help="Use a registered repo alias as the mirror list (see 'grimoire repo --ls')",
	)
	inspect_parser.add_argument(
		"--subdir",
		help="Inspect this subdirectory of the repo (relative to clone root)",
	)
	inspect_parser.add_argument(
		"--rev", help="Git revision to check out: branch, tag, or commit"
	)
	inspect_parser.add_argument(
		"--plain",
		action="store_true",
		help="pacman -Si style 'Key : Value' output for scripting (info target only)",
	)
	list_parser = subparsers.add_parser("list", help="List installed foreign packages")
	list_parser.add_argument(
		"--repo",
		metavar="NAME",
		help="List every package in repo NAME (use AUR for the AUR), like pacman -Sl <repo>",
	)

	repo_parser = subparsers.add_parser(
		"repo", help="Manage repo URL aliases in repos.conf"
	)
	repo_group = repo_parser.add_mutually_exclusive_group()
	repo_group.add_argument(
		"--add",
		nargs=2,
		metavar=("URL", "NAME"),
		help="Register URL as a mirror under alias NAME (repeat to add fallbacks)",
	)
	repo_group.add_argument(
		"--rm",
		metavar="NAME",
		help="Remove alias NAME from the registry",
	)
	repo_group.add_argument(
		"--ls",
		action="store_true",
		help="List registered aliases and their mirror URLs",
	)

	_capitalize_help_action(parser)
	for subparser in subparsers.choices.values():
		_capitalize_help_action(subparser)

	return parser


def _resolve_repo_for_package(
	package: str | None,
	*,
	alias: str | None,
	repo_url: str | None,
	branch: str | None,
	subdir: str | None,
) -> tuple[
	str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
]:
	# --repo NAME expands to an ordered mirror list; --repo-url is a single URL.
	# (argparse keeps them mutually exclusive.) First URL is primary, rest fallbacks.
	# Keyed on a package name so update/search can resolve per package in a loop.
	if alias == "AUR":
		# Reserved: the built-in AUR git backend (branch-per-package), not a URL alias.
		# An explicit --repo AUR is a deliberate override -- it works regardless of the
		# [AUR] toggle (which only governs the default chain / search / list).
		return None, branch, subdir, []
	if alias:
		urls = resolve_repo_alias(alias)
	elif repo_url:
		urls = [repo_url]
	else:
		return None, branch, subdir, []

	def _sub(value: str | None) -> str | None:
		# Substitute `{pkg}`/`{pkgbase}` so one alias can template per package. In the URL
		# path it selects a repo-per-package forge (e.g. the Arch GitLab); in the ref it
		# selects a branch-per-package layout over ANY transport (e.g. `--rev {pkg}` on a
		# bare SSH URL, where the forge `tree/{pkg}` shorthand isn't available). `{pkgbase}`
		# resolves to the pkgbase first, so split packages (amd-ucode -> linux-firmware)
		# hit the right repo/branch.
		if not (value and package):
			return value
		if "{pkgbase}" in value:
			value = value.replace("{pkgbase}", _resolve_pkgbase(package))
		if "{pkg}" in value:
			value = value.replace("{pkg}", package)
		return value

	def _resolve(raw: str) -> tuple[str, str | None, str | None]:
		clone_url, parsed_branch, parsed_subdir = parse_repo_url(_sub(raw) or raw)
		# Explicit flags (templated too) win over whatever the URL encoded.
		return clone_url, _sub(branch) or parsed_branch, _sub(subdir) or parsed_subdir

	primary_url, primary_branch, primary_subdir = _resolve(urls[0])
	fallbacks = [_resolve(raw) for raw in urls[1:]]
	return primary_url, primary_branch, primary_subdir, fallbacks


def _resolve_repo_target(
	args: argparse.Namespace,
) -> tuple[
	str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
]:
	alias = getattr(args, "repo", None)
	repo_url = getattr(args, "repo_url", None)
	# No explicit source -> trust the conf: use its top section as the default.
	# "AUR" (or no conf) means the built-in AUR backend (alias stays None).
	if not alias and not repo_url:
		default = _default_repo()
		if default is not None and default != "AUR":
			alias = default
	return _resolve_repo_for_package(
		getattr(args, "package", None),
		alias=alias,
		repo_url=repo_url,
		branch=getattr(args, "rev", None),
		subdir=getattr(args, "subdir", None),
	)


def _resolve_sources(
	args: argparse.Namespace,
	package: str | None = None,
) -> list[
	tuple[str | None, str | None, str | None, list[tuple[str, str | None, str | None]]]
]:
	# Ordered source chain for a package op with no explicit --repo: every section in
	# repos.conf, top to bottom (conf order == precedence). The first source that can
	# clone a PKGBUILD wins; later ones are fallbacks. An explicit --repo/--repo-url
	# collapses to a single source. A section named "AUR" (or no conf at all) is the
	# built-in AUR backend, encoded as a None repo_url. `package` resolves {pkg} /
	# {pkgbase} templates per package (multi-package install/fetch resolves in a loop).
	alias = getattr(args, "repo", None)
	repo_url = getattr(args, "repo_url", None)
	branch = getattr(args, "rev", None)
	subdir = getattr(args, "subdir", None)
	if alias or repo_url:
		return [
			_resolve_repo_for_package(
				package, alias=alias, repo_url=repo_url, branch=branch, subdir=subdir
			)
		]
	sources: list[
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		]
	] = []
	for name in load_repo_registry():
		if name == "AUR":
			# Reserved toggle: include the built-in AUR backend only when enabled.
			if _aur_enabled():
				sources.append((None, branch, subdir, []))
		else:
			sources.append(
				_resolve_repo_for_package(
					package, alias=name, repo_url=None, branch=branch, subdir=subdir
				)
			)
	return sources or [(None, branch, subdir, [])]


def _clone_any_source(
	package: str,
	dest_root: Path,
	sources: Sequence[
		tuple[
			str | None, str | None, str | None, list[tuple[str, str | None, str | None]]
		]
	],
	*,
	refresh: bool,
	submodules: bool = False,
) -> Path:
	# Walk the source chain in order; first that clones a dir holding a PKGBUILD wins.
	# A source whose clone fails (404) or lacks the package (subdir-container miss) is
	# skipped. If none yields a PKGBUILD but one cloned, return it so the caller raises
	# its own precise error; if nothing cloned at all, report every source that failed.
	errors: list[str] = []
	cloned: Path | None = None
	multiple = len(sources) > 1
	for index, (repo_url, branch, subdir, fallbacks) in enumerate(sources):
		label = repo_url or "AUR"
		try:
			pkg_dir = ensure_clone(
				package,
				dest_root,
				refresh=refresh,
				repo_url=repo_url,
				branch=branch,
				subdir=subdir,
				repo_fallbacks=fallbacks,
				submodules=submodules,
			)
		except AurGitError as exc:
			errors.append(f"{label}: {exc}")
			if multiple and index + 1 < len(sources):
				print(
					style(f"source failed ({label}); trying next...", YELLOW),
					file=sys.stderr,
				)
			continue
		if (pkg_dir / "PKGBUILD").is_file():
			return pkg_dir
		cloned = pkg_dir
		errors.append(f"{label}: no PKGBUILD for '{package}'")
		if multiple and index + 1 < len(sources):
			print(
				style(f"source lacks '{package}' ({label}); trying next...", YELLOW),
				file=sys.stderr,
			)
	if cloned is not None:
		return cloned
	raise AurGitError(
		f"'{package}' not found in any configured source:\n  " + "\n  ".join(errors)
	)


def main(argv: Sequence[str] | None = None) -> int:  # noqa: C901  argparse command dispatch
	argv_list = list(argv if argv is not None else sys.argv[1:])
	commands = {
		"fetch",
		"install",
		"remove",
		"update",
		"search",
		"inspect",
		"list",
		"repo",
	}
	# Hoist global flags so they can appear after the subcommand too
	# (e.g. `grimoire update --refresh` instead of only `grimoire --refresh update`).
	if argv_list:
		implicit_search = (
			not argv_list[0].startswith("-") and argv_list[0] not in commands
		)
		reordered: list[str] = []
		remaining: list[str] = []
		i = 0
		while i < len(argv_list):
			item = argv_list[i]
			if item == "--":
				remaining.extend(argv_list[i:])
				break
			if item in _GLOBAL_FLAG_OPTIONS or any(
				item.startswith(f"{opt}=") for opt in _GLOBAL_VALUE_OPTIONS
			):
				reordered.append(item)
			elif item in _GLOBAL_VALUE_OPTIONS:
				reordered.append(item)
				if i + 1 < len(argv_list):
					reordered.append(argv_list[i + 1])
					i += 1
			else:
				remaining.append(item)
			i += 1
		if implicit_search:
			argv_list = [*reordered, "search", *remaining]
		elif reordered:
			argv_list = reordered + remaining

	parser = build_parser()
	args = parser.parse_args(argv_list)

	dest_root = Path(args.dest_root).expanduser().resolve()
	refresh: bool = bool(args.refresh)

	global USE_COLOR, USE_SSH, SHALLOW_CLONE, CACHE_DIR, CACHE_TTL
	CACHE_DIR = dest_root / ".searchcache"
	if refresh:
		# --refresh means "give me fresh data": expire every read,
		# keep writing so the cache ends up repopulated.
		CACHE_TTL = 0
	USE_COLOR = not getattr(args, "no_color", False) and sys.stdout.isatty()
	USE_SSH = bool(getattr(args, "use_ssh", False))
	SHALLOW_CLONE = bool(getattr(args, "shallow", False))
	# Never block on an interactive git auth prompt (e.g. a 404 clone of a templated
	# URL); fail fast instead. Configured credential helpers still work.
	os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")

	if os.geteuid() == 0:
		print(
			style(
				"error: do not run grimoire as root. see man makepkg "
				"pacman elevation is handled auto via PACMAN_AUTH in makepkg.conf "
				"re-run as a regular user",
				RED,
			),
			file=sys.stderr,
		)
		return 1

	if args.command is None:
		parser.print_help()
		return 0

	# Seed a default repos.conf ([ARCH] + AUR toggle) on first use, so every command sees
	# the official default base. Idempotent: no-ops once the conf exists. Runs after the
	# no-command/help return so a bare `grimoire` doesn't create a conf.
	_ensure_repos_conf()

	# fallback when /tmp is not writable, use our default + .tmp.
	current_tmp = os.environ.get("TMPDIR") or "/tmp"  # noqa: S108 - standard TMPDIR default, writability checked below
	if not os.access(current_tmp, os.W_OK):
		fallback_tmp = dest_root / ".tmp"
		fallback_tmp.mkdir(parents=True, exist_ok=True)
		os.environ["TMPDIR"] = str(fallback_tmp)
		print(
			style(
				f"{current_tmp} not writable; using {fallback_tmp} as TMPDIR",
				YELLOW,
			),
			file=sys.stderr,
		)

	try:
		if args.command == "fetch":
			for package in args.packages:
				pkg_sources = _resolve_sources(args, package)
				if len(pkg_sources) == 1:
					repo_url, branch, subdir, repo_fallbacks = pkg_sources[0]
					fetch_package(
						package,
						dest_root,
						refresh=refresh,
						repo_url=repo_url,
						branch=branch,
						subdir=subdir,
						repo_fallbacks=repo_fallbacks,
						verify=args.verify,
						submodules=args.submod,
					)
				else:
					fetch_package(
						package,
						dest_root,
						refresh=refresh,
						sources=pkg_sources,
						verify=args.verify,
						submodules=args.submod,
					)
		elif args.command == "install":
			# Share the dedup/official-dep state across every requested package so a
			# common dependency is built once for the whole run.
			install_visited: set[str] = set()
			install_preinstalled: set[str] = set()
			for package in args.packages:
				pkg_sources = _resolve_sources(args, package)
				if len(pkg_sources) > 1:
					install_package(
						package,
						dest_root,
						refresh=refresh,
						noconfirm=args.noconfirm,
						visited=install_visited,
						preinstalled_official=install_preinstalled,
						sources=pkg_sources,
						verify=args.verify,
						submodules=args.submod,
					)
					continue
				repo_url, branch, subdir, repo_fallbacks = pkg_sources[0]
				if not repo_url:
					missing_official, unresolved = collect_missing_official_packages(
						package,
						dest_root,
						refresh=refresh,
					)
					if unresolved:
						missing_list = ", ".join(sorted(unresolved))
						raise AurGitError(
							f"Could not resolve providers for: {missing_list}"
						)
					if missing_official:
						install_official_packages(
							missing_official,
							noconfirm=args.noconfirm,
						)
					install_preinstalled.update(missing_official)
				install_package(
					package,
					dest_root,
					refresh=refresh,
					noconfirm=args.noconfirm,
					visited=install_visited,
					preinstalled_official=install_preinstalled,
					repo_url=repo_url,
					branch=branch,
					subdir=subdir,
					repo_fallbacks=repo_fallbacks,
					verify=args.verify,
					submodules=args.submod,
				)
		elif args.command == "remove":
			if args.cache:
				clear_search_cache()
			if args.packages:
				for package in args.packages:
					remove_package(
						package,
						dest_root,
						noconfirm=args.noconfirm,
						remove_clone=args.clone,
					)
			elif not args.cache:
				print(
					"error: nothing to remove (specify a package or --cache)",
					file=sys.stderr,
				)
				return 2
		elif args.command == "update":
			update_packages(
				dest_root,
				refresh=True,
				noconfirm=args.noconfirm,
				include_devel=bool(getattr(args, "devel", False)),
				update_system=bool(getattr(args, "global", False)),
				targets=args.packages or None,
				repo=getattr(args, "repo", None),
				repo_url=getattr(args, "repo_url", None),
				branch=getattr(args, "rev", None),
				subdir=getattr(args, "subdir", None),
			)
		elif args.command == "search":
			explicit_alias = getattr(args, "repo", None)
			explicit_url = getattr(args, "repo_url", None)
			branch_arg = getattr(args, "rev", None)
			subdir_arg = getattr(args, "subdir", None)
			regex_obj: re.Pattern | None = None
			needle: str | None = None
			use_regex = is_regex(args.pattern)
			if use_regex:
				try:
					regex_obj = re.compile(args.pattern)
				except re.error as exc:
					print(f"error: invalid regular expression: {exc}", file=sys.stderr)
					return 1
			else:
				needle = args.pattern.lower()

			# Sources to search. An explicit --repo/--repo-url scopes to one; otherwise
			# search every section in repos.conf (merged, like `pacman -Ss`) so an
			# enabled alias shows up without --repo. (alias, url): alias "AUR" or
			# (None, None) means the AUR backend.
			if explicit_alias or explicit_url:
				sources: list[tuple[str | None, str | None]] = [
					(explicit_alias, explicit_url)
				]
			else:
				sources = [
					(name, None)
					for name in load_repo_registry()
					if name != "AUR" or _aur_enabled()
				] or [(None, None)]

			results: list[SearchResult] = []
			for src_alias, src_url in sources:
				if src_url is None and (src_alias is None or src_alias == "AUR"):
					results += search_packages(
						regex=regex_obj, needle=needle, limit=args.limit
					)
					continue
				r_url, r_branch, r_subdir, _ = _resolve_repo_for_package(
					None,
					alias=src_alias,
					repo_url=src_url,
					branch=branch_arg,
					subdir=subdir_arg,
				)
				if r_url is None:
					continue
				try:
					results += search_packages_repo(
						r_url,
						r_branch,
						r_subdir,
						regex=regex_obj,
						needle=needle,
						limit=args.limit,
						source=src_alias or r_url,
						dest_root=dest_root,
						alias=src_alias,
					)
				except AurGitError as exc:
					# A source that can't enumerate (e.g. templated with no index) is
					# skipped in an aggregated search instead of failing the whole run.
					print(f"warning: {src_alias}: {exc}", file=sys.stderr)

			if not results:
				print("No matches found", file=sys.stderr)
				return 1

			cap = args.limit if (args.limit is not None and args.limit >= 0) else 50
			ordered_results = order_search_results(results)[:cap]
			if args.plain:
				for result in ordered_results:
					for line in format_search_result_plain(result):
						print(line)
				return 0
			display_results = list(reversed(ordered_results))
			print(style("Search results (best matches last):", CYAN))
			print_search_results(display_results)

			interactive = (
				not args.no_interactive and sys.stdin.isatty() and sys.stdout.isatty()
			)
			if not interactive:
				return 0

			selected = interactive_select_results(display_results)
			if not selected:
				print(style("No packages selected.", DIM))
				return 0

			print(style("Installing selected packages:", CYAN))
			for pkg in selected:
				label = style(pkg.name, BOLD)
				if pkg.version:
					label = f"{label} {style(pkg.version, GREEN)}"
				print(f"  {label}")

			exit_code = 0
			shared_visited: set[str] = set()
			shared_preinstalled_official: set[str] = set()
			for pkg in selected:
				# Otherwise build each pick from the source it was found in.
				p_url: str | None = None
				p_branch: str | None = None
				p_subdir: str | None = None
				p_fallbacks: list[tuple[str, str | None, str | None]] = []
				if pkg.repo_alias:
					p_url, p_branch, p_subdir, p_fallbacks = _resolve_repo_for_package(
						pkg.name,
						alias=pkg.repo_alias,
						repo_url=None,
						branch=branch_arg,
						subdir=subdir_arg,
					)
				elif explicit_url:
					p_url, p_branch, p_subdir, p_fallbacks = _resolve_repo_for_package(
						pkg.name,
						alias=None,
						repo_url=explicit_url,
						branch=branch_arg,
						subdir=subdir_arg,
					)
				try:
					install_package(
						pkg.name,
						dest_root,
						refresh=refresh,
						noconfirm=args.noconfirm,
						visited=shared_visited,
						preinstalled_official=shared_preinstalled_official,
						repo_url=p_url,
						branch=p_branch,
						subdir=p_subdir,
						repo_fallbacks=p_fallbacks,
					)
				except AurGitError as exc:
					exit_code = 1
					print(f"error installing {pkg.name}: {exc}", file=sys.stderr)
			return exit_code
		elif args.command == "inspect":
			target = (
				"PKGBUILD"
				if args.target == "PKGBUILD"
				else ("SRCINFO" if args.target == "SRCINFO" else "info")
			)
			for package in args.packages:
				pkg_sources = _resolve_sources(args, package)
				if len(pkg_sources) == 1:
					repo_url, branch, subdir, repo_fallbacks = pkg_sources[0]
					inspect_package(
						package,
						dest_root,
						refresh=refresh,
						target=target,
						repo_url=repo_url,
						branch=branch,
						subdir=subdir,
						repo_fallbacks=repo_fallbacks,
						plain=args.plain,
					)
				else:
					inspect_package(
						package,
						dest_root,
						refresh=refresh,
						target=target,
						sources=pkg_sources,
						plain=args.plain,
					)
		elif args.command == "list":
			if args.repo:
				list_repo_packages(args.repo, dest_root)
			else:
				list_installed_packages()
		elif args.command == "repo":
			if args.add:
				url, name = args.add
				add_repo_alias(name, url)
			elif args.rm:
				remove_repo_alias(args.rm)
			else:
				registry = load_repo_registry()
				if not registry:
					print(
						f"No aliases registered in {_repo_registry_path()}",
						file=sys.stderr,
					)
					return 0
				for name, urls in registry.items():
					if name == "AUR":
						state = "enabled" if _aur_enabled() else "disabled"
						print(f"[AUR] (built-in mirror, {state})")
						continue
					print(f"[{name}]")
					for url in urls:
						print(f"  {url}")
		else:
			parser.error("Unknown command")
	except AurGitError as exc:
		print(f"error: {exc}", file=sys.stderr)
		if DEBUG:
			import traceback

			traceback.print_exc(file=sys.stderr)
		return 1

	return 0


if __name__ == "__main__":
	try:
		sys.exit(main())
	except KeyboardInterrupt:
		print("\n" + style("Interrupted by user", YELLOW), file=sys.stderr)
		sys.exit(130)
