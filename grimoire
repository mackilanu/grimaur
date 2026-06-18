#!/usr/bin/env python3
r"""grimoire: repos, fetch, inspect, build, search, list, update, install/remove/clean.

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

It was fully reworked following AUR malware SCA (13/06/26) to support any source...

ASCII: Donovan Baker
## /* SPDX-FileCopyrightText: 2026
# (O) Marcus A.
# (C) Eihdran L.

##  SPDX-License-Identifier: MIT */

Requirements: git, base-devel, pacman, and sudo/doas/run0/su.
"""

import argparse
import contextlib
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
from typing import TYPE_CHECKING, Final, Literal, NamedTuple, overload

if TYPE_CHECKING:
	from collections.abc import Callable, Iterable, Iterator, Sequence


__appname__: Final = "grimoire"
__version__: Final = "dev"


DEBUG: Final = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")


RESET: 	Final = "\033[0m"
BOLD: 	Final = "\033[1m"
GREEN: 	Final = "\033[32m"
CYAN: 	Final = "\033[36m"
YELLOW: Final = "\033[33m"
RED: 	Final = "\033[31m"
DIM: 	Final = "\033[2m"


GITHUB_RAW_BASE: 	Final = "https://raw.githubusercontent.com/archlinux/aur"
_VCS_SUFFIXES: 		Final = ("-git", "-vcs", "-svn", "-hg", "-bzr", "-darcs", "-cvs")


# GPG owner-trust levels accepted by --min-trust (git's gpg.minTrustLevel).
type TrustLevel = 	Literal["marginal", "fully", "ultimate"]
# What `inspect` can render.
type InspectTarget = 	Literal["info", "PKGBUILD", "SRCINFO"]


_ELEV_TOOLS: 		Final = ("sudo", "doas", "run0", "su")  # order matters here
_GLOBAL_VALUE_OPTIONS: 	Final = {"--dest-root"}


_CONF_NAME: Final = "repos.ini"


@dataclass
class _RuntimeConfig:
	# Process-wide runtime state, set once from argv in main() (replaces module globals
	# so there's no `global` indirection). cache_dir is dest_root/.searchcache (works in
	# chroots where HOME/XDG may not); inst_cache is the lazy, invalidatable pacman set.
	use_color: 	bool = False
	use_ssh: 	bool = False
	use_shallow: 	bool = False
	cache_dir: 	Path | None = None
	cache_ttl: 	int = 3600
	inst_cache: 	set[str] | None = None


CONFIG = _RuntimeConfig()


@dataclass(frozen=True, slots=True)
class DependencySet:
	depends:	set[str]
	makedepends: 	set[str]
	checkdepends: 	set[str]
	optdepends: 	set[str]

	@property
	def all_build_deps(self) -> set[str]:
		return self.depends | self.makedepends


@dataclass(frozen=True, slots=True)
class SearchResult:
	name: 		str
	version: 	str | None
	description: 	str | None
	installed: 	bool
	score: 		int
	# Display label for the source repo (alias/URL); None means the AUR.
	source: 	str | None = None
	# True when sourced from a local pacman sync DB (label as `db`, not a protocol).
	from_db: 	bool = False
	# Conf alias this result can be installed from (None = the AUR/default backend).
	# Distinct from `source`: sync-DB results display their pacman repo but install
	# via their alias (e.g. display "core", install via "ARCH").
	repo_alias: 	str | None = None


@dataclass(frozen=True, slots=True)
class UpdateCandidate:
	name: 			str
	installed_version: 	str | None
	target_version: 	str | None
	remote_head: 		str | None
	local_head: 		str | None


class RepoRef(NamedTuple):
	# One git mirror as (url, ref, subdir): ref is a branch/tag/commit, subdir selects
	# a package dir inside a monorepo. The unit of a fallback/candidate chain.
	url: 	str
	branch: str | None = None
	subdir: str | None = None


class UpdateProbe(NamedTuple):
	# What an update check learned about a package's upstream:
	# (remote_version, remote_head, local_head). All None means "not found".
	remote_version: str | None = None
	remote_head: 	str | None = None
	local_head: 	str | None = None


class UpdateSpec(NamedTuple):
	# One entry of the update source chain as (alias, url): a repos.ini section name
	# or an explicit --repo-url. (None, None) is the built-in AUR backend.
	alias: 	str | None = None
	url: 	str | None = None


class CloneSource(NamedTuple):
	# A resolved git source for one package: primary URL (None = built-in AUR
	# backend), ref, subdir, and ordered RepoRef fallbacks. Tuple-shaped so it still
	# unpacks as (repo_url, branch, subdir, repo_fallbacks).
	repo_url: 	str | None = None
	branch: 	str | None = None
	subdir: 	str | None = None
	repo_fallbacks: list[RepoRef] | None = None


class GrimoireErr(RuntimeError):
	"""Wraps fatal errors coming from the helper."""


_SRCINFO_KEYS: Final = {
	"depends",
	"makedepends",
	"checkdepends",
	"optdepends",
	"pkgname",
	"pkgbase",
	"pkgdesc",
}


_GLOBAL_FLAG_OPTIONS: Final = {
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
SSH_REWRITE_HOSTS: Final = {
	"github.com": "git",
	"gitlab.com": "git",
	"codeberg.org": "git",
	"bitbucket.org": "git",
	"aur.archlinux.org": "aur",
}

_DEFAULT_CONF: Final = """\
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

_PACMAN_AUTH_RE: 	Final = re.compile(r'^\s*PACMAN_AUTH\s*=\s*\(?\s*"?([^"\s)]+)"?')
_PACMAN_DBPATH_RE: 	Final = re.compile(r"^\s*DBPath\s*=\s*(\S+)")
_DEP_SPLIT_RE: 		Final = re.compile(r"[<>~=]+")
_DESC_FIELD_RE: 	Final = re.compile(r"%(\w+)%\n([^\n]*)")

# Third-party repos (cachyos, ...) have no recipe, exclude from the templated search.
_OFFICIAL_REPO_RE: Final = re.compile(
	r"^(core|extra|multilib)(-testing|-staging)?$|^(gnome|kde)-unstable$"
)
_HOSTISH_RE: Final = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+$", re.IGNORECASE)


def style(text: str, *codes: str) -> str:
	if not CONFIG.use_color or not codes:
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
	# str.endswith takes a tuple of suffixes directly -- no per-suffix loop needed.
	return name.endswith(_VCS_SUFFIXES)


def get_aur_remote() -> str:
	url = "https://github.com/archlinux/aur.git"
	return _remote_for(url)


def _aur_mirror_lsremote_cmd(*patterns: str) -> list[str]:
	return ["git", "ls-remote", "--heads", get_aur_remote(), *patterns]


def _lsremote_first_sha(output: str) -> str | None:
	for line in output.splitlines():
		parts = line.split()
		if parts:
			return parts[0]
	return None


def _lsremote_names(output: str) -> list[str]:
	# Short ref names from `git ls-remote` lines (`<sha>\t<ref>` -> last ref segment),
	# skipping lines that aren't exactly sha+ref.
	names: list[str] = []
	for line in output.splitlines():
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


def _iter_db_descs(db: Path, name_prefix: str | None) -> Iterator[dict[str, str]]:
	# Desc-field dict for every package in one sync-DB tarball; a corrupt/unreadable DB
	# yields nothing. name_prefix pre-filters members by dir (fast single-package path);
	# `r:*` autodetects compression.
	import tarfile

	with (
		contextlib.suppress(OSError, tarfile.TarError),
		tarfile.open(db, "r:*") as tar,
	):
		for member in tar:
			name = member.name
			if not name.endswith("/desc"):
				continue
			if name_prefix is not None and not name.startswith(name_prefix):
				continue
			extracted = tar.extractfile(member)
			if extracted is None:
				continue
			raw = extracted.read().decode("utf-8", "replace")
			yield dict(_DESC_FIELD_RE.findall(raw))


def _iter_sync_db_desc(
	name_prefix: str | None = None,
) -> Iterator[tuple[str, dict[str, str]]]:
	# (repo, desc-fields) for every package in the OFFICIAL Arch sync DBs. Third-party
	# repos (cachyos, a custom myrepo) have no Arch GitLab PKGBUILD, so they're skipped.
	sync = _pacman_db_path() / "sync"
	try:
		dbs = sorted(sync.glob("*.db"))
	except OSError:
		return
	for db in dbs:
		if not _OFFICIAL_REPO_RE.match(db.stem):
			continue
		for fields in _iter_db_descs(db, name_prefix):
			yield db.stem, fields


def _local_db_descs(
	name_prefix: str | None = None,
) -> Iterator[tuple[str, Path]]:
	# (pkgname, entry-dir) for each package in pacman's local db. Reading the dir
	# directly avoids a ~50ms subprocess. Entries are name-version-release dirs;
	# ALPM_DB_VERSION and other non-package files lack the two trailing -ver-rel parts.
	# name_prefix pre-filters by dir name (single-package lookups stay cheap).
	try:
		entries = (_pacman_db_path() / "local").iterdir()
	except OSError:
		return
	for entry in entries:
		name = entry.name
		if name_prefix is not None and not name.startswith(name_prefix):
			continue
		parts = name.rsplit("-", 2)
		if len(parts) == 3:
			yield parts[0], entry


def _local_db_pkgbase(package: str) -> str | None:
	# pkgname -> pkgbase from the LOCAL pacman db, covering foreign/AUR installs the sync
	# DBs don't list (e.g. fontobene-qt-qt6 -> fontobene-qt). desc carries %BASE% only
	# when it differs from the name. None when the package isn't installed locally.
	for name, entry in _local_db_descs(f"{package}-"):
		if name != package:
			continue
		try:
			raw = (entry / "desc").read_text()
		except OSError:
			return None
		return dict(_DESC_FIELD_RE.findall(raw)).get("BASE") or package
	return None


def _db_pkgbase(package: str) -> str | None:
	# pkgname -> pkgbase from the pacman DBs (each `desc` carries %BASE%): sync DBs for
	# official split packages (amd-ucode -> linux-firmware), then the local db for
	# foreign/AUR installs the sync DBs don't list. None when neither knows it.
	for _repo, fields in _iter_sync_db_desc(f"{package}-"):
		if fields.get("NAME") == package:
			return fields.get("BASE") or package
	return _local_db_pkgbase(package)


def _aur_rpc_pkgbase(package: str) -> str | None:
	# pkgname -> pkgbase from the AUR RPC: the only source for a split pkg that is neither
	# installed nor in the sync DBs (a fresh `install`). Best-effort -- any network/parse
	# failure or a miss returns None, so resolution stays offline-tolerant.
	from urllib.request import urlopen

	query = urllib.parse.urlencode({"arg[]": package})
	url = f"https://aur.archlinux.org/rpc/v5/info?{query}"
	if DEBUG:
		print(f"+ GET {url}", file=sys.stderr)
	try:
		with urlopen(url, timeout=10) as response:  # noqa: S310 - hardcoded https AUR endpoint
			data = json.loads(response.read().decode())
	except (OSError, ValueError):
		return None
	for entry in data.get("results", []):
		if entry.get("Name") == package:
			base = entry.get("PackageBase")
			return base if isinstance(base, str) and base else None
	return None


@cache
def _resolve_pkgbase(package: str) -> str:
	# DB-only pkgbase (no network), for the Arch GitLab {pkgbase} template -- a gitlab
	# package's base comes from the sync DBs, never the AUR. Falls back to the name.
	return _db_pkgbase(package) or package


@cache
def _aur_pkgbase(package: str) -> str:
	# Branch name on the AUR git mirror (branch-per-pkgbase): DBs first, then the AUR RPC
	# for an uninstalled split pkg. Used only at the mirror-access sites. Falls back to
	# the name (a non-split pkg, or an offline RPC miss -- the clone then reports absence).
	return _db_pkgbase(package) or _aur_rpc_pkgbase(package) or package


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


def _sync_db_signature() -> str | None:
	# A cache key for the sync DBs' current state: name+mtime+size per *.db. Changes on
	# `pacman -Sy`, so a list cached under it auto-invalidates when the DBs are refreshed.
	sync = _pacman_db_path() / "sync"
	try:
		dbs = sorted(sync.glob("*.db"))
	except OSError:
		return None
	parts: list[str] = []
	for db in dbs:
		try:
			st = db.stat()
		except OSError:
			continue
		parts.append(f"{db.name}:{int(st.st_mtime)}:{st.st_size}")
	return "|".join(parts) or None


def _sync_db_packages_cached() -> list[tuple[str, str | None, str | None, str]]:
	# search re-parses every sync-DB tarball otherwise (~0.5s of tarfile/gzip work on a
	# stock install); cache the enumerated list to disk so it survives across invocations,
	# keyed on _sync_db_signature so `pacman -Sy` (or --refresh, via cache_ttl=0) expires it.
	sig = _sync_db_signature()
	if sig is None:
		return list(_sync_db_packages())
	key = "syncdb/" + hashlib.sha256(sig.encode()).hexdigest()[:16] + ".json"
	return cached_json(key, CONFIG.cache_ttl, lambda: list(_sync_db_packages())) or []


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
	raise GrimoireErr("No privilege elevation tool found.")


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
	return _maybe_ssh_rewrite(url) if CONFIG.use_ssh else url


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


def _split_forge_path(
	parts: 		list[str],
	markers: 	Sequence[str],
	*,
	ref_offset: 	int,
	gate: 		Sequence[str] | None = None,
) -> tuple[list[str], str, list[str]] | None:
	# Find the first marker (idx >= 2 so <owner>/<repo> precede it), then read the ref at
	# parts[idx+ref_offset] and the remainder as the subpath. ref_offset is 1 when the ref
	# follows the marker directly (GitHub/Bitbucket), 2 when a {branch,tag,commit}-class
	# segment sits between (GitLab/Gitea); gate, if set, must match that middle segment.
	for marker in markers:
		if marker not in parts:
			continue
		i = parts.index(marker)
		if i < 2 or len(parts) <= i + ref_offset:
			continue
		if gate is not None and parts[i + 1] not in gate:
			continue
		return parts[:i], parts[i + ref_offset], parts[i + ref_offset + 1 :]
	return None


def parse_repo_url(url: str) -> RepoRef:
	# Expand a forge directory/file URL to (clone_url, ref, subdir) so --repo-url can
	# target a subdir. ref is taken as one path segment, so slash-branches need an
	# explicit --rev/--subdir. Non-forge URLs fall through unchanged.
	url = _ensure_scheme(url)
	parsed = urllib.parse.urlparse(url)
	if parsed.scheme not in ("http", "https"):
		return RepoRef(url, None, None)
	parts = [p for p in parsed.path.split("/") if p]

	def _rebuild(repo_parts: list[str], ref: str, sub: list[str]) -> RepoRef:
		base = f"{parsed.scheme}://{parsed.netloc}/" + "/".join(repo_parts)
		if not base.endswith(".git"):
			base += ".git"
		# A blob link usually points at the PKGBUILD itself; build in its dir.
		if sub and sub[-1] in ("PKGBUILD", ".SRCINFO"):
			sub = sub[:-1]
		return RepoRef(base, ref, ("/".join(sub) or None))

	# GitHub: /<owner>/<repo>/{tree,blob,raw}/<ref>/<subpath...>
	if parsed.netloc == "github.com":
		hit = _split_forge_path(parts, ("tree", "blob", "raw"), ref_offset=1)
		if hit:
			return _rebuild(*hit)
	# GitLab: /<owner>/<repo>/-/{tree,blob,raw}/<ref>/<subpath...>
	hit = _split_forge_path(parts, ("-",), ref_offset=2, gate=("tree", "blob", "raw"))
	if hit:
		return _rebuild(*hit)
	# Bitbucket Cloud: /<workspace>/<repo>/{src,raw}/<ref>/<subpath...> (ref directly
	# after the marker, no branch/tag/commit segment -- distinct from Gitea below).
	if parsed.netloc == "bitbucket.org":
		hit = _split_forge_path(parts, ("src", "raw"), ref_offset=1)
		if hit:
			return _rebuild(*hit)
	# Gitea/Codeberg/Forgejo: /<owner>/<repo>/{src,raw}/{branch,tag,commit}/<ref>/<subpath...>
	hit = _split_forge_path(
		parts, ("src", "raw"), ref_offset=2, gate=("branch", "tag", "commit")
	)
	if hit:
		return _rebuild(*hit)

	return RepoRef(url, None, None)


def _forge_raw_url(clone_url: str, ref: str, path: str) -> str | None:
	# Raw-file URL for an HTTP existence probe -- the inverse of parse_repo_url's tree/raw
	# parsing, for the forge hosts we recognise. None for anything else (self-hosted, unknown
	# host), so the caller stays correct by falling back to the git tree probe.
	parsed = urllib.parse.urlparse(clone_url)
	if parsed.scheme not in ("http", "https") or not parsed.netloc:
		return None
	repo = parsed.path.lstrip("/").rstrip("/").removesuffix(".git")
	if not repo:
		return None
	host = parsed.netloc
	if host == "github.com":
		# raw.githubusercontent.com/<repo>/<ref>/<path>: ref slot takes a branch/tag/sha.
		return f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
	if "gitlab" in host:
		# GitLab /-/raw/<ref>/ resolves any ref; ?ref_type only disambiguates a branch/tag
		# name clash, so omitting it keeps the existence check ref-type-agnostic.
		return f"https://{host}/{repo}/-/raw/{ref}/{path}"
	if host in ("bitbucket.org", "codeberg.org", "gitea.com"):
		# Bitbucket + Gitea/Forgejo share /raw/<ref>/; urlopen follows Gitea's 303 to the
		# canonical /raw/{branch,tag,commit}/ form, so this too stays ref-type-agnostic.
		return f"https://{host}/{repo}/raw/{ref}/{path}"
	return None


def _repo_registry_path() -> Path:
	return _xdg_config_home() / __appname__ / _CONF_NAME


def _ensure_repos_conf() -> None:
	# Seed a default repos.ini the first time a source is needed, so the default is
	# the official Arch repos (build from source) rather than the AUR. Best-effort:
	# if the write fails, resolution falls back to the built-in AUR.
	path = _repo_registry_path()
	if path.exists():
		return
	with contextlib.suppress(OSError):
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(_DEFAULT_CONF)


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
			"[AUR] is a reserved toggle (true/false); edit repos.ini to enable it.",
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
		lines.insert(end, f"{url}")
	else:
		if lines and lines[-1].strip():
			lines.append("")
		lines += [header, f"{url}"]
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
		raise GrimoireErr(
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


def _resolve_repo_for_package(
	package: 	str | None,
	*,
	alias: 		str | None,
	repo_url: 	str | None,
	branch: 	str | None,
	subdir: 	str | None,
) -> CloneSource:
	# --repo NAME expands to an ordered mirror list; --repo-url is a single URL.
	# (argparse keeps them mutually exclusive.) First URL is primary, rest fallbacks.
	# Keyed on a package name so update/search can resolve per package in a loop.
	if alias == "AUR":
		# Reserved: the built-in AUR git backend (branch-per-package), not a URL alias.
		# An explicit --repo AUR is a deliberate override -- it works regardless of the
		# [AUR] toggle (which only governs the default chain / search / list).
		return CloneSource(None, branch, subdir, [])
	if alias:
		urls = resolve_repo_alias(alias)
	elif repo_url:
		urls = [repo_url]
	else:
		return CloneSource(None, branch, subdir, [])

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

	def _resolve(raw: str) -> RepoRef:
		clone_url, parsed_branch, parsed_subdir = parse_repo_url(_sub(raw) or raw)
		# Explicit flags (templated too) win over whatever the URL encoded.
		return RepoRef(
			clone_url, _sub(branch) or parsed_branch, _sub(subdir) or parsed_subdir
		)

	primary_url, primary_branch, primary_subdir = _resolve(urls[0])
	fallbacks = [_resolve(raw) for raw in urls[1:]]
	return CloneSource(primary_url, primary_branch, primary_subdir, fallbacks)


def _resolve_sources(
	args: 		argparse.Namespace,
	package: 	str | None = None,
) -> list[CloneSource]:
	# Ordered source chain for a package op with no explicit --repo: every section in
	# repos.ini, top to bottom (conf order == precedence). The first source that can
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
	sources: list[CloneSource] = []
	for name in load_repo_registry():
		if name == "AUR":
			# Reserved toggle: include the built-in AUR backend only when enabled.
			if _aur_enabled():
				sources.append(CloneSource(None, branch, subdir, []))
		else:
			sources.append(
				_resolve_repo_for_package(
					package, alias=name, repo_url=None, branch=branch, subdir=subdir
				)
			)
	return sources or [CloneSource(None, branch, subdir, [])]


def _cache_get(key: str, ttl: int) -> str | None:
	if CONFIG.cache_dir is None:
		return None
	path = CONFIG.cache_dir / key
	try:
		if time.time() - path.stat().st_mtime > ttl:
			path.unlink(missing_ok=True)
			return None
		return path.read_text()
	except OSError:
		return None


def _atomic_write(path: Path, payload: str) -> None:
	with contextlib.suppress(OSError):
		path.parent.mkdir(parents=True, exist_ok=True)
		# pid-unique tmp so concurrent processes never interleave writes
		tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
		tmp.write_text(payload)
		tmp.replace(path)


def _cache_put(key: str, payload: str) -> None:
	if CONFIG.cache_dir is None:
		return
	_atomic_write(CONFIG.cache_dir / key, payload)


def _completion_cache_path() -> Path | None:
	if CONFIG.cache_dir is None:
		return None
	# Conventional yay-style location: dest_root/completion.cache,
	# sibling of .searchcache rather than inside it.
	return CONFIG.cache_dir.parent / "completion.cache"


def cached_json[T](key: str, ttl: int, fetch: Callable[[], T]) -> T | None:
	# The payload is JSON we wrote from a fetch() of type T, so a hit decodes straight back
	# to T (tuples round-trip to lists -- structurally identical for the row access callers
	# do). It's our own keyed, TTL'd cache, so the decoded value is trusted as-is.
	payload = _cache_get(key, ttl)
	if payload is not None:
		decoded: T | None
		try:
			decoded = json.loads(payload)
		except json.JSONDecodeError:
			decoded = None
		if decoded is not None:
			if DEBUG:
				print(f"+ cache hit {key}", file=sys.stderr)
			return decoded
	value = fetch()
	if value is not None:
		_cache_put(key, json.dumps(value))
	return value


def clear_search_cache() -> None:
	removed = False
	if CONFIG.cache_dir is not None and CONFIG.cache_dir.exists():
		shutil.rmtree(CONFIG.cache_dir)
		print(f"Removed search cache {CONFIG.cache_dir}")
		removed = True
	completion = _completion_cache_path()
	if completion is not None and completion.exists():
		completion.unlink()
		print(f"Removed completion cache {completion}")
		removed = True
	if not removed:
		print("No search cache to remove")


def clean_clones(dest_root: Path) -> None:
	# Remove every cloned package build tree under dest-root, leaving the caches alone
	# (those are files, or the .searchcache dir handled by clear_search_cache). Scratch
	# dirs (.searchrepo) are clones-adjacent and go too; all are re-created on demand.
	if not dest_root.exists():
		print("No clones to remove")
		return
	removed = 0
	for child in dest_root.iterdir():
		if child == CONFIG.cache_dir or not child.is_dir():
			continue
		shutil.rmtree(child, ignore_errors=True)
		removed += 1
	print(f"Removed {removed} clone(s) from {dest_root}" if removed else "No clones to remove")


def _remove_clone(package: str, dest_root: Path) -> None:
	# Drop one package's clone dir, leaving any install untouched. inspect/fetch create
	# clones too, so one can exist for a package that was never installed.
	package_dir = dest_root / package
	if package_dir.exists():
		print(f"Removing clone {package_dir}")
		shutil.rmtree(package_dir)
		print(f"Removed clone for {style(package, GREEN)}")
	else:
		print(f"No clone found at {package_dir}")


@overload
def run_command(
	cmd: Sequence[str],
	*,
	cwd: Path | None = ...,
	capture: Literal[False] = ...,
	check: bool = ...,
	env: dict[str, str] | None = ...,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_command(
	cmd: Sequence[str],
	*,
	cwd: Path | None = ...,
	capture: Literal[True],
	check: bool = ...,
	env: dict[str, str] | None = ...,
) -> str: ...


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
		raise GrimoireErr(f"Required command not found: {cmd[0]}") from exc
	except subprocess.CalledProcessError as exc:
		raise GrimoireErr(
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
		raise GrimoireErr(f"Subdirectory '{subdir}' escapes clone root {clone_root}")
	if not target.is_dir():
		raise GrimoireErr(f"Subdirectory '{subdir}' not found in clone at {clone_root}")
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
	except GrimoireErr:
		return False
	return bool(out.strip())


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
	except GrimoireErr:
		return None
	for line in out.splitlines():
		top = line.strip()
		if top and _tree_has(package_dir, ref, f"{top}/{package}/PKGBUILD"):
			return top
	return None


def _http_status(url: str) -> int | None:
	# Status of a HEAD request, or None on a network-level failure (offline, DNS, TLS).
	from urllib.request import Request, urlopen

	request = Request(url, method="HEAD")  # noqa: S310 - forge URL from user's source
	try:
		with urlopen(request, timeout=10) as response:  # noqa: S310 - forge URL from source
			status: int = response.status
			return status
	except urllib.error.HTTPError as exc:
		return exc.code
	except urllib.error.URLError:
		return None


def _remote_pkgbuild_present(
	url: str, ref: str | None, subdir: str | None, package: str
) -> bool | None:
	# Decide WITHOUT cloning whether `url` carries `package`, by HTTP-probing the forge raw
	# URL of each place its PKGBUILD could live (mirrors _build_subpath's layout + a root
	# solo). True = found, False = every candidate is a confirmed 404, None = can't tell
	# (no ref, a host we don't map, or any non-404 result) -> fall back to the git probe.
	if not ref:
		return None
	rels = (
		[f"{subdir}/{package}/PKGBUILD", f"{subdir}/PKGBUILD", "PKGBUILD"]
		if subdir
		else [f"{package}/PKGBUILD", "PKGBUILD"]
	)
	for rel in rels:
		raw = _forge_raw_url(url, ref, rel)
		if raw is None:
			return None
		status = _http_status(raw)
		if status is None or (status != 404 and not 200 <= status < 300):
			return None
		if 200 <= status < 300:
			return True
	return False


def _clone_with_fallback(
	package_dir: 	Path,
	candidates: 	Sequence[RepoRef],
	package: 	str,
) -> Path:
	# Try each (url, branch, subdir) mirror in order until one clones; the winning
	# mirror's own subdir resolves the build dir. Used only for a fresh clone.
	# On a known forge with a known ref, an HTTP HEAD on the candidate PKGBUILD URLs skips
	# the clone outright when they all 404 (_remote_pkgbuild_present). Otherwise clone
	# treeless (--filter=tree:0) + no-checkout so only commits arrive up front; `git
	# ls-tree` then lazily fetches just the target package's subtree, so a monorepo miss
	# costs only that probe -- detected over any git transport, no forge knowledge needed.
	# git falls back to a full clone when the server can't filter; a solo repo checks whole.
	errors: list[str] = []
	for index, (url, branch, subdir) in enumerate(candidates):
		if _remote_pkgbuild_present(url, branch, subdir, package) is False:
			# A known forge confirmed (over HTTP) that every candidate PKGBUILD path is a
			# 404: skip the clone entirely. The git tree probe below reaches the same
			# verdict, but only after fetching the repo.
			errors.append(f"{url}: no PKGBUILD for '{package}' (404)")
			if index + 1 < len(candidates):
				print(
					style(f"mirror lacks '{package}' ({url}); trying next...", YELLOW),
					file=sys.stderr,
				)
			continue
		remote_url = _remote_for(url)
		if package_dir.exists():
			shutil.rmtree(package_dir)
		clone_cmd = ["git", "clone", "--no-checkout", "--filter=tree:0"]
		if CONFIG.use_shallow:
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
				raise GrimoireErr(msg)
			if want:
				run_command(
					["git", "-C", str(package_dir), "sparse-checkout", "set", want]
				)
			_reset_git_worktree(package_dir, (ref,))
			return _resolve_package_dir(package_dir, subdir, package)
		except GrimoireErr as exc:
			errors.append(f"{url}: {exc}")
			if index + 1 < len(candidates):
				print(
					style(f"mirror failed ({url}); trying next...", YELLOW),
					file=sys.stderr,
				)
	if package_dir.exists():
		shutil.rmtree(package_dir)
	raise GrimoireErr("All mirrors failed:\n  " + "\n  ".join(errors))


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
	except GrimoireErr:
		return None
	return out.strip() or None


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
	package: 	str,
	dest_root: 	Path,
	source: 	CloneSource | None = None,
	*,
	refresh: 	bool = False,
	submodules: 	bool = False,
) -> Path:
	repo_url, branch, subdir, repo_fallbacks = source or CloneSource()
	dest_root.mkdir(parents=True, exist_ok=True)
	package_dir = dest_root / package

	# A leftover non-git directory in our own cache is junk -> recreate it.
	if package_dir.exists() and not (package_dir / ".git").is_dir():
		shutil.rmtree(package_dir)

	if repo_url:
		remote_url = 	_remote_for(repo_url)
		clone_extra: 	list[str] = []
		fetch_refspec: 	tuple[str, ...]
		reset_targets: 	tuple[str, ...]
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
		# No repo_url -> the AUR git mirror, one branch per PKGBASE (split packages
		# share a branch: fontobene-qt-qt6 lives on the fontobene-qt branch).
		base = 		_aur_pkgbase(package)
		remote_url = 	get_aur_remote()
		clone_extra = 	["--branch", base, "--single-branch"]
		fetch_refspec = (base,)
		reset_targets = (f"origin/{base}",)

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
			except GrimoireErr:
				# Corrupt worktree/index -> drop it and reclone from scratch.
				shutil.rmtree(package_dir)
				return ensure_clone(
					package,
					dest_root,
					CloneSource(repo_url, branch, subdir),
					refresh=False,
					submodules=submodules,
				)
		if submodules:
			_init_submodules(package_dir)
		return _resolve_package_dir(package_dir, subdir, package)

	if package_dir.exists():
		shutil.rmtree(package_dir)

	if repo_url:
		candidates = [RepoRef(repo_url, branch, subdir), *(repo_fallbacks or [])]
		build = _clone_with_fallback(package_dir, candidates, package)
		if submodules:
			_init_submodules(package_dir)
		return build

	clone_cmd = ["git", "clone", *clone_extra]
	if CONFIG.use_shallow:
		clone_cmd += ["--depth=1"]
	clone_cmd += [remote_url, str(package_dir)]
	print(style(f"==> cloning from {remote_url}", DIM))
	run_command(clone_cmd)

	if submodules:
		_init_submodules(package_dir)
	return _resolve_package_dir(package_dir, subdir, package)


def _clone_resolved(
	package: 	str,
	dest_root: 	Path,
	*,
	refresh: 	bool,
	submodules: 	bool = False,
	source: 	CloneSource | None = None,
	sources: 	Sequence[CloneSource] | None = None,
) -> Path:
	# Clone from a resolved chain (first source with a PKGBUILD wins) or a single
	# source; an absent single source is the bare AUR backend (CloneSource()).
	if sources is not None:
		return _clone_any_source(
			package, dest_root, sources, refresh=refresh, submodules=submodules
		)
	return ensure_clone(
		package, dest_root, source or CloneSource(), refresh=refresh, submodules=submodules
	)


def _reuse_existing_clone(
	package: 	str,
	dest_root: 	Path,
	sources: 	Sequence[CloneSource],
	*,
	submodules: 	bool,
) -> Path | None:
	# The chain shares one cache dir, so re-walking it lets an earlier source's ensure_clone
	# reclone -- and clobber -- the real owner each run. Find which source owns the existing
	# clone and reuse it through ensure_clone (its own origin-match path does the resolve +
	# submodules), skipping the walk. None -> no usable clone here, fall back to the walk.
	package_dir = dest_root / package
	if not (package_dir / ".git").is_dir():
		return None
	origin = _clone_origin(package_dir)
	if origin is None:
		return None
	norm = _normalize_git_url(origin)
	for src in sources:
		if src.repo_url is None:
			owns = _is_aur_origin(origin)
		else:
			owns = _normalize_git_url(src.repo_url) == norm
		if not owns:
			continue
		pkg_dir = ensure_clone(package, dest_root, src, refresh=False, submodules=submodules)
		return pkg_dir if (pkg_dir / "PKGBUILD").is_file() else None
	return None


def _clone_any_source(
	package: 	str,
	dest_root: 	Path,
	sources: 	Sequence[CloneSource],
	*,
	refresh: 	bool,
	submodules: 	bool = False,
) -> Path:
	if not refresh:
		reused = _reuse_existing_clone(
			package, dest_root, sources, submodules=submodules
		)
		if reused is not None:
			return reused

	# Walk the source chain in order; first that clones a dir holding a PKGBUILD wins.
	# A source whose clone fails (404) or lacks the package (subdir-container miss) is
	# skipped. If none yields a PKGBUILD but one cloned, return it so the caller raises
	# its own precise error; if nothing cloned at all, report every source that failed.
	errors: 	list[str] = []
	cloned: 	Path | None = None
	multiple = 	len(sources) > 1
	for index, src in enumerate(sources):
		label = src[0] or "AUR"
		try:
			pkg_dir = ensure_clone(
				package, dest_root, src, refresh=refresh, submodules=submodules
			)
		except GrimoireErr as exc:
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
	raise GrimoireErr(
		f"'{package}' not found in any configured source:\n  " + "\n  ".join(errors)
	)


def read_srcinfo(package_dir: Path) -> str:
	srcinfo_path = package_dir / ".SRCINFO"
	if srcinfo_path.exists():
		return srcinfo_path.read_text()
	# Fallback to generating on the fly
	output = run_command(["makepkg", "--printsrcinfo"], cwd=package_dir, capture=True)
	return output


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


def parse_dependencies(srcinfo_content: str) -> tuple[str | None, DependencySet]:
	pkgbase = 	""
	pkgdesc = 	None
	depends: 	set[str] = set()
	makedepends: 	set[str] = set()
	checkdepends: 	set[str] = set()
	optdepends: 	set[str] = set()

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
		raise GrimoireErr("Failed to parse pkgbase from .SRCINFO")
	return pkgdesc, DependencySet(depends, makedepends, checkdepends, optdepends)


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


def parse_srcinfo_metadata(srcinfo_content: str) -> tuple[str | None, str | None]:
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
		except GrimoireErr:
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
	raise GrimoireErr(
		f"Could not reset {package_dir.name} to any of: {', '.join(refs)}"
	)


def _ref_is_annotated_tag(package_dir: Path, ref: str) -> bool:
	# Whether `ref` names an annotated tag (a "tag" object -- the signable kind; a branch,
	# commit, or lightweight tag is a "commit"). Drives verify-tag vs verify-commit.
	try:
		out = run_command(
			["git", "-C", str(package_dir), "cat-file", "-t", ref], capture=True
		)
	except GrimoireErr:
		return False
	return out.strip() == "tag"


def _classify_verify_failure(output: str, min_trust: TrustLevel | None) -> str:
	# Tell apart a present-but-unverifiable signature from a genuinely unsigned target,
	# reading git's relayed gpg status. "No public key" means it IS signed (gpg saw the
	# signature) but the key is missing, not no signature at all. The actionable hint goes
	# on a second line so the message stays readable in a terminal.
	if "No public key" in output:
		key = re.search(r"key (?:ID )?([0-9A-Fa-f]{8,})", output)
		reason = "is signed, but the signer's public key is not in your keyring."
		if key:
			return f"{reason}\nImport it with 'gpg --recv-keys {key.group(1)}'."
		return reason
	if "BAD signature" in output:
		return "has a BAD signature (the target was altered after it was signed)."
	if min_trust and "Good signature" in output:
		return f"is signed with a valid key whose owner-trust is below '{min_trust}'."
	if "Signature made" not in output and "gpg:" not in output:
		return "is unsigned (no GPG signature found)."
	return "has a signature that could not be verified."


def _verify_signature(
	package_dir: 	Path,
	package: 	str,
	ref: 		str | None = None,
	min_trust: 	TrustLevel | None = None,
) -> None:
	# `--verify`: require a cryptographically valid GPG signature from a key in the caller's
	# keyring. When the requested ref is an annotated tag, verify that tag (covers projects
	# that sign releases, not every commit); otherwise verify the HEAD commit. By default
	# this checks signature validity, NOT key trust -- a good signature from any held key
	# passes (gpg only warns). With min_trust set (--min-trust), gpg.minTrustLevel makes git
	# also reject a valid signature whose owner-trust is below that level (the user must have
	# established that trust first). Fails on an unsigned target, a missing public key, a bad
	# signature, or insufficient trust. git's own "Good signature"/error lines stream through.
	prefix = ["git"]
	if min_trust:
		prefix += ["-c", f"gpg.minTrustLevel={min_trust}"]
	prefix += ["-C", str(package_dir)]
	if ref and _ref_is_annotated_tag(package_dir, ref):
		cmd = [*prefix, "verify-tag", ref]
		target = f"tag {ref}"
		print(style(f"==> git verify-tag {ref} ({package})", DIM))
	else:
		cmd = [*prefix, "verify-commit", "HEAD"]
		target = "the HEAD commit"
		print(style(f"==> git verify-commit HEAD ({package})", DIM))
	# git relays gpg's status to stderr; capture it to classify the failure precisely,
	# then stream it through so the user still sees gpg's own lines.
	proc = subprocess.run(  # noqa: S603 - cmd is built internally, not from untrusted input
		cmd, capture_output=True, text=True, check=False
	)
	gpg_output = (proc.stderr or "") + (proc.stdout or "")
	if gpg_output.strip():
		print(gpg_output.rstrip(), file=sys.stderr)
	if proc.returncode != 0:
		raise GrimoireErr(
			f"signature verification failed for '{package}': "
			f"{target} {_classify_verify_failure(gpg_output, min_trust)}"
		)


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
		raise GrimoireErr(
			"pacman command not found; this tool must run on Arch Linux"
		) from exc
	return proc.returncode == 0


def invalidate_inst_cache() -> None:
	CONFIG.inst_cache = None


def _list_local_db_packages() -> set[str] | None:
	# Installed package names straight from pacman's local db (None when it's unreadable
	# or empty, so the caller falls back to `pacman -Qq`).
	return {name for name, _ in _local_db_descs()} or None


def installed_package_set() -> set[str]:
	if CONFIG.inst_cache is None:
		CONFIG.inst_cache = _list_local_db_packages()
	if CONFIG.inst_cache is None:
		# we can still search without pacman installed.
		if shutil.which("pacman") is None:
			CONFIG.inst_cache = set()
		else:
			output = run_command(["pacman", "-Qq"], capture=True)
			CONFIG.inst_cache = set(output.split())
	return CONFIG.inst_cache


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
		except GrimoireErr:
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
	# VCS variants plus the -bin binary-repackage suffix.
	for suffix in (*_VCS_SUFFIXES, "-bin"):
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
	except GrimoireErr:
		return None
	providers = [line.strip() for line in output.splitlines() if line.strip()]
	if not providers:
		return None
	return providers[0]


def exists_in_aur_mirror(package: str) -> bool:
	if is_debug_package(package):
		return True
	# Branch-per-pkgbase: resolve a split pkgname to its base branch (DBs, then AUR RPC).
	try:
		output = run_command(
			_aur_mirror_lsremote_cmd(_aur_pkgbase(package)), capture=True
		)
	except GrimoireErr:
		return False
	return bool(output.strip())


def list_foreign_packages() -> dict[str, str]:
	try:
		output = run_command(["pacman", "-Qm"], capture=True, check=False)
	except GrimoireErr:
		return {}

	names: dict[str, str] = {}
	for line in output.splitlines():
		if not line.strip():
			continue
		parts = line.split()
		if len(parts) >= 2:
			names[parts[0]] = parts[1]
		else:
			names[parts[0]] = ""
	return names


def _local_head(package_dir: Path) -> str | None:
	if not (package_dir / ".git").is_dir():
		return None
	try:
		output = run_command(
			["git", "-C", str(package_dir), "rev-parse", "HEAD"], capture=True
		)
	except GrimoireErr:
		return None
	return output.strip() or None


def _git_remote_head(url: str, ref: str | None) -> str | None:
	try:
		output = run_command(
			["git", "ls-remote", _remote_for(url), ref or "HEAD"], capture=True
		)
	except GrimoireErr:
		return None
	return _lsremote_first_sha(output)


def _aur_remote_head(package: str) -> str | None:
	# Branch-per-pkgbase: a split pkgname's head lives on its base branch.
	try:
		output = run_command(
			_aur_mirror_lsremote_cmd(_aur_pkgbase(package)), capture=True
		)
	except GrimoireErr:
		return None
	return _lsremote_first_sha(output)


def get_installed_version(package: str) -> str | None:
	try:
		output = run_command(["pacman", "-Qi", package], capture=True)
	except GrimoireErr:
		return None
	for line in output.splitlines():
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
				"AUR is disabled. Set [AUR] = true in repos.ini to enable it.",
				file=sys.stderr,
			)
			return
		meta = aur_packages()
		if not meta:
			raise GrimoireErr("Could not fetch the AUR package list")
		rows: list[tuple[str, str | None]] = [(n, ver) for n, ver, _ in meta]
	else:
		url, branch, subdir, _ = _resolve_repo_for_package(
			None, alias=name, repo_url=None, branch=None, subdir=None
		)
		if url is None:
			raise GrimoireErr(f"Repo '{name}' has no listable URL")
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
	# Lazy import: urlopen pulls in http.client and is unused on a warm cache hit.
	# Import the name (not the package) so it doesn't shadow the top-level urllib.
	from urllib.request import urlopen

	# The mirror is branch-per-pkgbase; a split pkgname resolves to its base branch.
	safe_package = urllib.parse.quote(_aur_pkgbase(package))
	safe_path = path.lstrip("/")
	url = f"{GITHUB_RAW_BASE}/{safe_package}/{safe_path}"
	if DEBUG:
		print(f"+ GET {url}", file=sys.stderr)
	try:
		with urlopen(url, timeout=10) as response:  # noqa: S310 - url built from hardcoded https GitHub base
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
	version, description = parse_srcinfo_metadata(srcinfo)
	if not version:  # no version -> no usable metadata, treat as absent
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
	invalidate_inst_cache()


def collect_missing_official_packages(
	package: 	str,
	dest_root: 	Path,
	*,
	refresh: 	bool,
	visited: 	set[str] | None = None,
) -> tuple[set[str], set[str]]:
	visited = visited or set()
	if package in visited:
		return set(), set()
	visited.add(package)

	package_dir = ensure_clone(package, dest_root, refresh=refresh)
	_, deps = parse_dependencies(read_srcinfo(package_dir))

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
	package_dir: 	Path,
	*,
	noconfirm: 	bool,
	refresh: 	bool = False
) -> None:
	pkgbuild_path = package_dir / "PKGBUILD"
	if not pkgbuild_path.exists():
		raise GrimoireErr(f"PKGBUILD missing at {pkgbuild_path}")
	flags = "-sif" if refresh else "-si"
	cmd = ["makepkg", flags, "--needed"]
	if noconfirm:
		cmd.append("--noconfirm")
	print(f"Building {package_dir.name} with makepkg")
	extra_env = _ssh_rewrite_git_env() if CONFIG.use_ssh else {}
	run_command(cmd, cwd=package_dir, env={**os.environ, **extra_env})
	print(f"Built package artifacts remain under {package_dir}")
	invalidate_inst_cache()


def _classify_build_deps(
	deps: 		DependencySet,
	package: 	str
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
	aur_dependencies: 	set[str],
	virtual_providers: 	dict[str, set[str]]
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
		raise GrimoireErr("Installation aborted by user")


def install_package(
	package: 		str,
	dest_root: 		Path,
	*,
	refresh: 		bool,
	noconfirm: 		bool,
	visited: 		set[str] | None = None,
	preinstalled_official: 	set[str] | None = None,
	source: 		CloneSource | None = None,
	sources: 		Sequence[CloneSource] | None = None,
	update_to: 		str | None = None,
	verify: 		bool = False,
	min_trust: 		TrustLevel | None = None,
	submodules: 		bool = False,
	local_dir: 		Path | None = None,
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

	# A pre-fetched (possibly hand-edited) local tree builds in place; otherwise clone
	# from the source chain or AUR mirror. Either way deps come from its .SRCINFO.
	if local_dir is not None:
		package_dir = local_dir
	else:
		package_dir = _clone_resolved(
			package,
			dest_root,
			refresh=refresh,
			submodules=submodules,
			source=source,
			sources=sources,
		)
	if verify:
		branch = source.branch if source else None
		_verify_signature(package_dir, package, branch, min_trust)
	pkgdesc, deps = parse_dependencies(read_srcinfo(package_dir))
	print(f"==> {package}: {pkgdesc}" if pkgdesc else f"==> {package}")

	missing_official, aur_dependencies, unresolved, virtual_providers = (
		_classify_build_deps(deps, package)
	)

	if unresolved:
		missing_list = ", ".join(sorted(unresolved))
		raise GrimoireErr(f"Could not resolve providers for: {missing_list}")

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
			min_trust=min_trust,
			submodules=submodules,
		)

	build_and_install(package_dir, noconfirm=noconfirm, refresh=refresh)


def _find_pkgbuild_dir(clone_root: Path, package: str) -> Path | None:
	# A fetched clone holds the PKGBUILD at its root (AUR / solo repo) or one container
	# subdir down (VUR-style monorepo, e.g. pkgs/<pkg>/). The treeless clone materialises
	# only the target package's subtree, so the on-disk match is unambiguous; prefer the
	# dir named after the package if several exist (a full monorepo checkout).
	if (clone_root / "PKGBUILD").is_file():
		return clone_root
	matches = [
		p.parent
		for p in clone_root.rglob("PKGBUILD")
		if p.is_file() and ".git" not in p.parts
	]
	if not matches:
		return None
	return next((d for d in matches if d.name == package), matches[0])


def build_package(package: str, dest_root: Path, *, noconfirm: bool) -> None:
	# Build+install a previously fetched (and possibly hand-edited) local tree without
	# touching the remote. Regenerate .SRCINFO from the on-disk PKGBUILD first so the
	# normal dependency resolution sees local edits, then reuse the install path.
	clone_root = dest_root / package
	package_dir = _find_pkgbuild_dir(clone_root, package) if clone_root.is_dir() else None
	if package_dir is None:
		raise GrimoireErr(
			f"No fetched PKGBUILD for '{package}' under {clone_root}; "
			f"run 'grimoire fetch {package}' first"
		)
	srcinfo = run_command(["makepkg", "--printsrcinfo"], cwd=package_dir, capture=True)
	(package_dir / ".SRCINFO").write_text(srcinfo)
	install_package(
		package, dest_root, refresh=False, noconfirm=noconfirm, local_dir=package_dir
	)


def remove_package(package: str, *, noconfirm: bool) -> None:
	if not is_installed(package):
		print(f"Package {style(package, BOLD)} is not installed")
		return

	cmd: list[str] = ["pacman", "-Rns", package]
	if noconfirm:
		cmd.append("--noconfirm")

	print(f"Removing package {style(package, BOLD)}")
	try:
		run_command(_elevate(cmd))
		invalidate_inst_cache()
		print(f"Successfully removed {style(package, GREEN)}")
	except GrimoireErr as exc:
		print(f"Failed to remove package: {exc}", file=sys.stderr)


def get_ignored_packages() -> set[str]:
	ignored: set[str] = set()
	pacman_conf = Path("/etc/pacman.conf")

	if not pacman_conf.exists():
		return ignored

	content = pacman_conf.read_text()

	for raw_line in content.splitlines():
		line = raw_line.strip()

		if not line or line.startswith("#"):
			continue

		# Format: IgnorePkg = pkg1 pkg2 pkg3
		if line.startswith("IgnorePkg") and "=" in line:
			_, packages = line.split("=", 1)
			for pkg in packages.split():
				ignored.add(pkg.strip())

	return ignored


def _resolve_update_spec(
	package: 	str,
	alias: 		str | None,
	url: 		str | None,
	branch: 	str | None,
	subdir: 	str | None,
) -> CloneSource:
	# "AUR" section (or the no-conf default) is the built-in AUR backend: a None
	# repo_url, never run through the alias/URL parser.
	if alias == "AUR" or (alias is None and url is None):
		return CloneSource()
	return _resolve_repo_for_package(
		package, alias=alias, repo_url=url, branch=branch, subdir=subdir
	)


def _probe_aur_update(package: str, dest_root: Path) -> UpdateProbe | None:
	# (remote_version, remote_head, local_head) from the AUR, or None if absent.
	meta = git_srcinfo_metadata(package)
	rv = meta[0] if meta else None
	if rv and is_vcs_package(package):
		rv = None
	if rv is not None:
		return UpdateProbe(rv, None, None)
	rh = _aur_remote_head(package)
	if rh is None:
		return None
	return UpdateProbe(None, rh, _local_head(dest_root / package))


def _probe_git_update(
	package: 	str,
	dest_root: 	Path,
	source: 	CloneSource,
	*,
	refresh: 	bool,
) -> UpdateProbe | None:
	# As _probe_aur_update, against a git source: VCS pkgs compare the remote head,
	# versioned pkgs clone and read the .SRCINFO (no metadata API on a plain git host).
	s_url, s_branch, _, _ = source
	if s_url is None:
		return None
	if is_vcs_package(package):
		rh = _git_remote_head(s_url, s_branch)
		if rh is None:
			return None
		return UpdateProbe(None, rh, _local_head(dest_root / package))
	try:
		pkg_dir = ensure_clone(package, dest_root, source, refresh=refresh)
	except GrimoireErr:
		return None
	if not (pkg_dir / "PKGBUILD").is_file():
		return None
	rv = parse_srcinfo_metadata(read_srcinfo(pkg_dir))[0]
	return UpdateProbe(rv, None, None) if rv is not None else None


def _find_update_source(
	package: 	str,
	update_specs: 	list[UpdateSpec],
	dest_root: 	Path,
	*,
	refresh: 	bool,
	branch: 	str | None,
	subdir: 	str | None,
) -> tuple[CloneSource, UpdateProbe]:
	# Walk the source chain (conf order == precedence); return (winning source, probe)
	# for the first source that has the package, or raise LookupError if none does.
	for alias, url in update_specs:
		source = _resolve_update_spec(package, alias, url, branch, subdir)
		if source.repo_url is None:
			probe = _probe_aur_update(package, dest_root)
		else:
			probe = _probe_git_update(package, dest_root, source, refresh=refresh)
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
		invalidate_inst_cache()
	except GrimoireErr as exc:
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
		seen: 	set[str] = set()
		out: 	list[tuple[str, str | None]] = []
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
	repo: 		str | None,
	repo_url: 	str | None,
	update_specs: 	list[UpdateSpec],
) -> str:
	# What to call the source(s) in "not available via ..." notes.
	if repo or repo_url:
		return f"repo '{repo}'" if repo else "the custom repo"
	if update_specs in ([UpdateSpec(None, None)], [UpdateSpec("AUR", None)]):
		return "the AUR mirror"
	return "any configured source"


def _plan_updates(
	candidates: 	list[tuple[str, str | None]],
	update_specs: 	list[UpdateSpec],
	dest_root: 	Path,
	*,
	ignored: 	set[str],
	skip_devel: 	bool,
	refresh: 	bool,
	branch: 	str | None,
	subdir: 	str | None,
) -> tuple[list[UpdateCandidate], dict[str, CloneSource], list[str]]:
	# Resolve each candidate against the source chain and keep the ones with a newer
	# version/head. Returns (pending, winning-source-per-package, not-found).
	pending: list[UpdateCandidate] = []
	winning: dict[str, CloneSource] = {}
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
				local_head = _local_head(dest_root / package)
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
	selected: 	list[UpdateCandidate],
	winning_source: dict[str, CloneSource],
	dest_root: 	Path,
	*,
	refresh: 	bool,
	noconfirm: 	bool,
) -> None:
	# Rebuild each selected package from the source it was found in, sharing dedup and
	# official-dep state across the run.
	shared_visited: 		set[str] = set()
	shared_preinstalled_official: 	set[str] = set()
	for candidate in selected:
		source = winning_source.get(candidate.name, CloneSource())
		try:
			install_package(
				candidate.name,
				dest_root,
				refresh=refresh,
				noconfirm=noconfirm,
				visited=shared_visited,
				preinstalled_official=shared_preinstalled_official,
				source=source,
				update_to=_update_target_label(candidate),
			)
		except GrimoireErr as exc:
			print(f"error updating {candidate.name}: {exc}", file=sys.stderr)


def _print_missing_notes(missing: list[str], source_label: str) -> None:
	for package in missing:
		if is_debug_package(package):
			continue
		print(f"note: {package} is not available via {source_label}", file=sys.stderr)


def update_packages(
	dest_root: 	Path,
	*,
	refresh: 	bool,
	noconfirm: 	bool,
	update_system: 	bool,
	include_devel: 	bool,
	targets: 	Sequence[str] | None = None,
	repo: 		str | None = None,
	repo_url: 	str | None = None,
	branch: 	str | None = None,
	subdir: 	str | None = None,
) -> None:
	ignored = get_ignored_packages()

	if update_system and not _run_system_update(noconfirm=noconfirm):
		return

	candidates = _collect_update_candidates(targets)
	if candidates is None:
		return

	# Version-check each package against an ordered source chain (conf order ==
	# precedence): an explicit --repo/--repo-url is the only source, otherwise every
	# repos.ini section top to bottom, with the AUR backend as the section named "AUR"
	# (or the implicit source when there is no conf). The first source that has the
	# package decides its update and is reused for the rebuild; packages no source
	# carries fall to `missing`.
	if repo or repo_url:
		update_specs: list[UpdateSpec] = [UpdateSpec(repo, repo_url)]
	else:
		update_specs = [
			UpdateSpec(name, None) for name in load_repo_registry()
		] or [UpdateSpec(None, None)]

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
	regex: 	re.Pattern[str] | None,
	needle: str | None,
	limit: 	int | None,
) -> list[SearchResult]:
	return search_packages_git(regex=regex, needle=needle, limit=limit)


def _fetch_aur_meta() -> list[tuple[str, str | None, str | None]] | None:
	# Bulk AUR metadata dump: name + version + description for every package, one gzip.
	import gzip
	from urllib.request import urlopen

	url = "https://aur.archlinux.org/packages-meta-v1.json.gz"
	if DEBUG:
		print(f"+ GET {url}", file=sys.stderr)
	try:
		with urlopen(url, timeout=30) as response:  # noqa: S310 - hardcoded https AUR endpoint
			raw = json.loads(gzip.decompress(response.read()).decode())
	except (OSError, ValueError) as exc:
		if DEBUG:
			print(f"+ packages-meta failed: {exc}", file=sys.stderr)
		return None
	# raw is the packages-meta array (list of {Name, Version, Description}); iterate the
	# decoded value directly -- json.loads is typed Any, so entry.get stays usable without
	# narrowing it to list[Unknown]. A row is kept only when its Name is a string.
	rows = [
		(name, _str_or_none(entry.get("Version")), _str_or_none(entry.get("Description")))
		for entry in raw
		if isinstance((name := entry.get("Name")), str)
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
	names = _fetch_names_git() or []
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
	# (name, version, description) for every AUR package; [] on a failed fetch. Backed by
	# the search cache (aurmeta.json), so a warm call just returns the decoded list -- the
	# fetch callback fixes the row shape, no per-call re-validation.
	rows = cached_json(
		"aurmeta.json", CONFIG.cache_ttl, _fetch_aur_packages_with_completion
	)
	return rows or []


def is_regex(pattern: str) -> bool:
	regex_chars = r".*+?[]{}()^$|\\"
	return any(char in pattern for char in regex_chars)


def compute_match_score(
	name: 	str,
	*,
	regex: 	re.Pattern[str] | None,
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


def search_packages_git(
	*,
	regex: 	re.Pattern[str] | None,
	needle: str | None,
	limit: 	int | None,
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
	repo_url: 	str,
	branch: 	str | None,
	subdir: 	str | None,
	clone_dir: 	Path
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
		raise GrimoireErr(f"Subdirectory '{subdir}' not found in {repo_url}")
	names: list[tuple[str, Path | None]] = sorted(
		(p.parent.name, p.parent) for p in base.glob("*/PKGBUILD")
	)
	if names or subdir:
		return names
	# Root carried no package dirs -> one branch per package.
	output = run_command(["git", "ls-remote", "--heads", remote], capture=True)
	return sorted({(name, None) for name in _lsremote_names(output)})


def _enumerate_repo(
	repo_url: 	str,
	branch: 	str | None,
	subdir: 	str | None,
	dest_root: 	Path
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
		version: 	str | None = None
		description: 	str | None = None
		if srcinfo_dir is not None:
			srcinfo_path = srcinfo_dir / ".SRCINFO"
			if srcinfo_path.exists():
				version, description = parse_srcinfo_metadata(srcinfo_path.read_text())
		out.append((name, version, description))
	return out


def search_packages_repo(
	repo_url: 	str,
	branch: 	str | None,
	subdir: 	str | None,
	*,
	regex: 		re.Pattern[str] | None,
	needle: 	str | None,
	limit: 		int | None,
	source: 	str,
	dest_root: 	Path,
	alias: 		str | None = None,
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
		candidates = _sync_db_packages_cached()
		if not candidates:
			raise GrimoireErr(
				f"alias is templated ({repo_url}) and no pacman sync DB is available "
				"to enumerate it. Search needs an index (a subdir, branches, or sync DB)."
			)
	else:
		# Enumerate the repo (clone/ls-remote) but cache the result per source, so a
		# repeat search doesn't re-clone. --refresh expires it (cache_ttl=0).
		ckey = (
			"repolist/"
			+ hashlib.sha256(f"{repo_url}\n{branch}\n{subdir}".encode()).hexdigest()[
				:16
			]
			+ ".json"
		)
		listed = cached_json(
			ckey,
			CONFIG.cache_ttl,
			lambda: _enumerate_repo(repo_url, branch, subdir, dest_root),
		)
		for name, version, description in listed or []:
			candidates.append((name, version, description, source))

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
	protocol = "ssh" if CONFIG.use_ssh else "https"
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
	package: 		str,
	srcinfo_content: 	str,
	repo: 			str = "aur"
) -> list[tuple[str, str]]:
	pkgdesc, deps = parse_dependencies(srcinfo_content)

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
	package: 	str,
	description: 	str | None,
	deps: 		DependencySet,
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
	package: 	str,
	dest_root: 	Path,
	*,
	refresh: 	bool,
	target: 	InspectTarget,
	source: 	CloneSource | None = None,
	sources: 	Sequence[CloneSource] | None = None,
	plain: 		bool = False,
) -> None:
	package_dir = _clone_resolved(
		package, dest_root, refresh=refresh, source=source, sources=sources
	)
	if target == "PKGBUILD":
		pkgbuild_path = package_dir / "PKGBUILD"
		if not pkgbuild_path.exists():
			raise GrimoireErr(f"PKGBUILD not found at {pkgbuild_path}")
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
	pkgdesc, deps = parse_dependencies(srcinfo)
	_print_info_summary(package, pkgdesc, deps)


def fetch_package(
	package: 	str,
	dest_root: 	Path,
	*,
	refresh: 	bool,
	source: 	CloneSource | None = None,
	sources: 	Sequence[CloneSource] | None = None,
	verify: 	bool = False,
	min_trust: 	TrustLevel | None = None,
	submodules: 	bool = False,
) -> Path:
	package_dir = _clone_resolved(
		package,
		dest_root,
		refresh=refresh,
		submodules=submodules,
		source=source,
		sources=sources,
	)
	if verify:
		branch = source.branch if source else None
		_verify_signature(package_dir, package, branch, min_trust)
	print(f"Package fetched to {package_dir}")
	return package_dir


def _search_all_sources(
	alias: 		str | None,
	repo_url: 	str | None,
	*,
	regex: 		re.Pattern[str] | None,
	needle: 	str | None,
	limit: 		int | None,
	branch: 	str | None,
	subdir: 	str | None,
	dest_root: 	Path,
) -> list[SearchResult]:
	# Sources to search. An explicit --repo/--repo-url scopes to one; otherwise
	# search every section in repos.ini (merged, like `pacman -Ss`) so an
	# enabled alias shows up without --repo. (alias, url): alias "AUR" or
	# (None, None) means the AUR backend. Mirrors update's _plan_updates fan-out.
	if alias or repo_url:
		sources: list[UpdateSpec] = [UpdateSpec(alias, repo_url)]
	else:
		sources = [
			UpdateSpec(name, None)
			for name in load_repo_registry()
			if name != "AUR" or _aur_enabled()
		] or [UpdateSpec(None, None)]

	results: list[SearchResult] = []
	for src_alias, src_url in sources:
		if src_url is None and (src_alias is None or src_alias == "AUR"):
			results += search_packages(regex=regex, needle=needle, limit=limit)
			continue
		r_url, r_branch, r_subdir, _ = _resolve_repo_for_package(
			None, alias=src_alias, repo_url=src_url, branch=branch, subdir=subdir
		)
		if r_url is None:
			continue
		try:
			results += search_packages_repo(
				r_url,
				r_branch,
				r_subdir,
				regex=regex,
				needle=needle,
				limit=limit,
				source=src_alias or r_url,
				dest_root=dest_root,
				alias=src_alias,
			)
		except GrimoireErr as exc:
			# A source that can't enumerate (e.g. templated with no index) is
			# skipped in an aggregated search instead of failing the whole run.
			print(f"warning: {src_alias}: {exc}", file=sys.stderr)
	return results


def _install_search_picks(
	selected: 	list[SearchResult],
	dest_root: 	Path,
	*,
	explicit_url: 	str | None,
	branch: 	str | None,
	subdir: 	str | None,
	refresh: 	bool,
	noconfirm: 	bool,
) -> int:
	# Build each pick from the source it was found in (repo_alias/--repo-url), else
	# the AUR backend; share dedup/official-dep state across picks (cf. _rebuild_updates).
	print(style("Installing selected packages:", CYAN))
	for pkg in selected:
		label = style(pkg.name, BOLD)
		if pkg.version:
			label = f"{label} {style(pkg.version, GREEN)}"
		print(f"  {label}")

	exit_code = 0
	shared_visited: 		set[str] = set()
	shared_preinstalled_official: 	set[str] = set()
	for pkg in selected:
		psrc = CloneSource()
		if pkg.repo_alias:
			psrc = _resolve_repo_for_package(
				pkg.name, alias=pkg.repo_alias, repo_url=None, branch=branch, subdir=subdir
			)
		elif explicit_url:
			psrc = _resolve_repo_for_package(
				pkg.name, alias=None, repo_url=explicit_url, branch=branch, subdir=subdir
			)
		try:
			install_package(
				pkg.name,
				dest_root,
				refresh=refresh,
				noconfirm=noconfirm,
				visited=shared_visited,
				preinstalled_official=shared_preinstalled_official,
				source=psrc,
			)
		except GrimoireErr as exc:
			exit_code = 1
			print(f"error installing {pkg.name}: {exc}", file=sys.stderr)
	return exit_code


def build_parser() -> tuple[argparse.ArgumentParser, frozenset[str]]:
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
		"fetch", help="Clone a package locally"
	)
	fetch_parser.add_argument(
		"packages",
		nargs="+",
		metavar="package",
		help="Package name(s) to clone",
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
		"--min-trust",
		choices=("marginal", "fully", "ultimate"),
		help="Implies --verify and also require the signer's key to be trusted to this level (you must set ownertrust first)",
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
		"--min-trust",
		choices=("marginal", "fully", "ultimate"),
		help="Implies --verify and also require the signer's key to be trusted to this level (you must set ownertrust first)",
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

	clean_parser = subparsers.add_parser(
		"clean", help="Clear cached data from dest-root (search cache by default)"
	)
	clean_parser.add_argument(
		"packages",
		nargs="*",
		metavar="package",
		help="Remove only these packages' clones (leaves the install in place)",
	)
	clean_parser.add_argument(
		"--clones",
		action="store_true",
		help="Remove every cloned package build tree from dest-root",
	)

	build_cmd = subparsers.add_parser(
		"build",
		help="Build+install a fetched (and possibly hand-edited) package, no re-clone",
	)
	build_cmd.add_argument(
		"packages", nargs="+", metavar="package", help="Fetched package name(s) to build"
	)
	build_cmd.add_argument(
		"--noconfirm", action="store_true", help="Pass --noconfirm to pacman/makepkg"
	)

	update_parser = subparsers.add_parser(
		"update",
		help="Upgrade installed foreign packages by rebuilding them",
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
		"repo", help="Manage repo URL aliases in repos.ini"
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

	# Single source of truth for the command list (main's implicit-search hoist needs it).
	return parser, frozenset(subparsers.choices)


def main(argv: Sequence[str] | None = None) -> int:  # noqa: C901  argparse command dispatch
	# The single command-dispatch hub: intentionally large (cf. the C901 exemption above).
	# pylint: disable=too-many-branches,too-many-statements,too-many-locals,too-many-return-statements
	argv_list = list(argv if argv is not None else sys.argv[1:])
	parser, commands = build_parser()
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

	args = parser.parse_args(argv_list)

	dest_root = Path(args.dest_root).expanduser().resolve()
	refresh: bool = bool(args.refresh)

	CONFIG.cache_dir = dest_root / ".searchcache"
	if refresh:
		# --refresh means "give me fresh data": expire every read,
		# keep writing so the cache ends up repopulated.
		CONFIG.cache_ttl = 0
	CONFIG.use_color = not getattr(args, "no_color", False) and sys.stdout.isatty()
	CONFIG.use_ssh = bool(getattr(args, "use_ssh", False))
	CONFIG.use_shallow = bool(getattr(args, "shallow", False))
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

	# Seed a default repos.ini ([ARCH] + AUR toggle) on first use, so every command sees
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
				single = pkg_sources[0] if len(pkg_sources) == 1 else None
				fetch_package(
					package,
					dest_root,
					refresh=refresh,
					source=single,
					sources=None if single else pkg_sources,
					verify=args.verify or bool(args.min_trust),
					min_trust=args.min_trust,
					submodules=args.submod,
				)
		elif args.command == "install":
			# Share the dedup/official-dep state across every requested package so a
			# common dependency is built once for the whole run.
			install_visited: 	set[str] = set()
			install_preinstalled: 	set[str] = set()
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
						verify=args.verify or bool(args.min_trust),
						min_trust=args.min_trust,
						submodules=args.submod,
					)
					continue
				src = pkg_sources[0]
				if not src.repo_url:
					missing_official, unresolved = collect_missing_official_packages(
						package,
						dest_root,
						refresh=refresh,
					)
					if unresolved:
						missing_list = ", ".join(sorted(unresolved))
						raise GrimoireErr(
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
					source=src,
					verify=args.verify or bool(args.min_trust),
					min_trust=args.min_trust,
					submodules=args.submod,
				)
		elif args.command == "remove":
			if not args.packages:
				print("error: nothing to remove (specify a package)", file=sys.stderr)
				return 2
			for package in args.packages:
				remove_package(package, noconfirm=args.noconfirm)
		elif args.command == "clean":
			if args.packages and args.clones:
				print("error: pass packages or --clones, not both", file=sys.stderr)
				return 2
			if args.packages:
				for package in args.packages:
					_remove_clone(package, dest_root)
			elif args.clones:
				clean_clones(dest_root)
			else:
				clear_search_cache()
		elif args.command == "build":
			for package in args.packages:
				build_package(package, dest_root, noconfirm=args.noconfirm)
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
			explicit_alias = 	getattr(args, "repo", None)
			explicit_url = 		getattr(args, "repo_url", None)
			branch_arg = 		getattr(args, "rev", None)
			subdir_arg = 		getattr(args, "subdir", None)
			regex_obj: 		re.Pattern[str] | None = None
			needle: 		str | None = None
			use_regex = 		is_regex(args.pattern)
			if use_regex:
				try:
					regex_obj = re.compile(args.pattern)
				except re.error as exc:
					print(f"error: invalid regular expression: {exc}", file=sys.stderr)
					return 1
			else:
				needle = args.pattern.lower()

			results = _search_all_sources(
				explicit_alias,
				explicit_url,
				regex=regex_obj,
				needle=needle,
				limit=args.limit,
				branch=branch_arg,
				subdir=subdir_arg,
				dest_root=dest_root,
			)
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

			return _install_search_picks(
				selected,
				dest_root,
				explicit_url=explicit_url,
				branch=branch_arg,
				subdir=subdir_arg,
				refresh=refresh,
				noconfirm=args.noconfirm,
			)
		elif args.command == "inspect":
			target: InspectTarget = (
				"PKGBUILD"
				if args.target == "PKGBUILD"
				else ("SRCINFO" if args.target == "SRCINFO" else "info")
			)
			for package in args.packages:
				pkg_sources = _resolve_sources(args, package)
				single = pkg_sources[0] if len(pkg_sources) == 1 else None
				inspect_package(
					package,
					dest_root,
					refresh=refresh,
					target=target,
					source=single,
					sources=None if single else pkg_sources,
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
						print(f"{url}")
		else:
			parser.error("Unknown command")
	except GrimoireErr as exc:
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

#h8d13washere
# class _RuntimeConfig  :93
# class DependencySet  :109
#     def all_build_deps(self)  :116
# class SearchResult  :121
# class UpdateCandidate  :138
# class RepoRef  :146
# class UpdateProbe  :154
# class UpdateSpec  :162
# class CloneSource  :169
# class GrimoireErr  :179
# def style(text)  :246
# def prompt_confirm(message)  :252
# def is_debug_package(name)  :262
# def is_vcs_package(name)  :266
# def get_aur_remote()  :271
# def _aur_mirror_lsremote_cmd()  :276
# def _lsremote_first_sha(output)  :280
# def _lsremote_names(output)  :288
# def _xdg_config_home()  :299
# def _makepkg_conf_paths()  :303
# def _pacman_db_path()  :311
# def _iter_db_descs(db, name_prefix)  :323
# def _iter_sync_db_desc(name_prefix)  :346
# def _local_db_descs(name_prefix)  :363
# def _local_db_pkgbase(package)  :383
# def _db_pkgbase(package)  :398
# def _aur_rpc_pkgbase(package)  :408
# def _resolve_pkgbase(package)  :431
# def _aur_pkgbase(package)  :438
# def _sync_db_packages()  :446
# def _sync_db_signature()  :460
# def _sync_db_packages_cached()  :478
# def _read_pacman_auth()  :489
# def _get_elev()  :503
# def _elevate(cmd)  :513
# def _maybe_ssh_rewrite(url)  :522
# def _remote_for(url)  :537
# def _ssh_rewrite_git_env()  :543
# def _ensure_scheme(url)  :559
# def _split_forge_path(parts, markers, ref_offset, gate)  :574
# def parse_repo_url(url)  :597
#     def _rebuild(repo_parts, ref, sub)  :607
# def _forge_raw_url(clone_url, ref, path)  :641
# def _repo_registry_path()  :666
# def _ensure_repos_conf()  :670
# def load_repo_registry()  :682
# def _repos_section_end(lines, header_idx)  :704
# def add_repo_alias(name, url)  :716
# def remove_repo_alias(name)  :746
# def resolve_repo_alias(name)  :762
# def _aur_enabled()  :771
# def _resolve_repo_for_package(package, alias, repo_url, branch, subdir)  :782
#     def _sub(value)  :805
#     def _resolve(raw)  :820
# def _resolve_sources(args, package)  :832
# def _cache_get(key, ttl)  :867
# def _atomic_write(path, payload)  :880
# def _cache_put(key, payload)  :889
# def _completion_cache_path()  :895
# def cached_json(key, ttl, fetch)  :903
# def clear_search_cache()  :924
# def clean_clones(dest_root)  :939
# def _remove_clone(package, dest_root)  :955
# def run_command(cmd, cwd, capture, check, env)  :968
# def run_command(cmd, cwd, capture, check, env)  :979
# def run_command(cmd, cwd, capture, check, env)  :989
# def _resolve_build_dir(clone_root, subdir)  :1021
# def _resolve_package_dir(clone_root, subdir, package)  :1033
# def _tree_has(package_dir, ref, path)  :1047
# def _build_subpath(package_dir, ref, subdir, package)  :1061
# def _subdir_hint(package_dir, ref, package)  :1072
# def _http_status(url)  :1091
# def _remote_pkgbuild_present(url, ref, subdir, package)  :1106
# def _clone_with_fallback(package_dir, candidates, package)  :1132
# def _normalize_git_url(url)  :1199
# def _clone_origin(package_dir)  :1215
# def _is_aur_origin(origin)  :1226
# def _origin_label(package_dir)  :1232
# def _init_submodules(clone_root)  :1241
# def ensure_clone(package, dest_root, source, refresh, submodules)  :1254
# def _clone_resolved(package, dest_root, refresh, submodules, source, sources)  :1360
# def _reuse_existing_clone(package, dest_root, sources, submodules)  :1380
# def _clone_any_source(package, dest_root, sources, refresh, submodules)  :1410
# def read_srcinfo(package_dir)  :1462
# def _iter_srcinfo_kv(srcinfo_content)  :1471
# def _str_or_none(value)  :1482
# def _assemble_version(pkgver, pkgrel, epoch)  :1486
# def parse_dependencies(srcinfo_content)  :1503
# def _normalize_dep(dep_entry)  :1535
# def _pkgbase_guesses(dep)  :1544
# def parse_srcinfo_metadata(srcinfo_content)  :1555
# def _reset_git_worktree(package_dir, refs)  :1569
# def _ref_is_annotated_tag(package_dir, ref)  :1601
# def _classify_verify_failure(output, min_trust)  :1613
# def _verify_signature(package_dir, package, ref, min_trust)  :1633
# def _pacman_returns_zero(args)  :1674
# def invalidate_inst_cache()  :1690
# def _list_local_db_packages()  :1694
# def installed_package_set()  :1700
# def is_installed(package)  :1713
# def exists_in_sync_repo(package)  :1718
# def is_dependency_satisfied(dep)  :1722
# def package_provides(package)  :1727
# def _search_aur_candidates(dep, limit)  :1740
# def resolve_aur_dependency(dep)  :1767
#     def add_candidate(name)  :1773
# def resolve_official_dependency(dep)  :1809
# def exists_in_aur_mirror(package)  :1831
# def list_foreign_packages()  :1844
# def _local_head(package_dir)  :1862
# def _git_remote_head(url, ref)  :1874
# def _aur_remote_head(package)  :1884
# def get_installed_version(package)  :1895
# def list_installed_packages()  :1907
# def list_repo_packages(name, dest_root)  :1921
# def fetch_git_file(package, path)  :1967
# def git_srcinfo_metadata(package)  :1991
# def install_official_packages(packages, noconfirm)  :2001
# def collect_missing_official_packages(package, dest_root, refresh, visited)  :2014
# def build_and_install(package_dir, noconfirm, refresh)  :2060
# def _classify_build_deps(deps, package)  :2080
# def _confirm_aur_dependencies(aur_dependencies, virtual_providers)  :2110
# def install_package(package, dest_root, refresh, noconfirm, visited, preinstalled_official, source, sources, update_to, verify, min_trust, submodules, local_dir)  :2128
# def _find_pkgbuild_dir(clone_root, package)  :2218
# def build_package(package, dest_root, noconfirm)  :2235
# def remove_package(package, noconfirm)  :2253
# def get_ignored_packages()  :2271
# def _resolve_update_spec(package, alias, url, branch, subdir)  :2295
# def _probe_aur_update(package, dest_root)  :2311
# def _probe_git_update(package, dest_root, source, refresh)  :2325
# def _find_update_source(package, update_specs, dest_root, refresh, branch, subdir)  :2352
# def _run_system_update(noconfirm)  :2374
# def _collect_update_candidates(targets)  :2395
# def _update_target_label(candidate)  :2415
# def _update_source_label(repo, repo_url, update_specs)  :2424
# def _plan_updates(candidates, update_specs, dest_root, ignored, skip_devel, refresh, branch, subdir)  :2437
# def _rebuild_updates(selected, winning_source, dest_root, refresh, noconfirm)  :2493
# def _print_missing_notes(missing, source_label)  :2522
# def update_packages(dest_root, refresh, noconfirm, update_system, include_devel, targets, repo, repo_url, branch, subdir)  :2529
# def search_packages(regex, needle, limit)  :2605
# def _fetch_aur_meta()  :2614
# def _fetch_names_git()  :2640
# def _fetch_aur_packages()  :2645
# def _fetch_aur_packages_with_completion()  :2660
# def aur_packages()  :2672
# def is_regex(pattern)  :2682
# def compute_match_score(name, regex, needle)  :2687
# def search_packages_git(regex, needle, limit)  :2712
# def _repo_package_names(repo_url, branch, subdir, clone_dir)  :2744
# def _enumerate_repo(repo_url, branch, subdir, dest_root)  :2778
# def search_packages_repo(repo_url, branch, subdir, regex, needle, limit, source, dest_root, alias)  :2803
# def order_search_results(results)  :2873
# def format_search_result(index, result)  :2878
# def format_search_result_plain(result)  :2905
# def print_search_results(results)  :2917
# def interactive_select_updates(candidates)  :2925
# def parse_selection(selection, max_index)  :2961
# def interactive_select_results(results)  :2997
# def _join_values(values, sort)  :3023
# def _srcinfo_values(srcinfo_content, key)  :3028
# def srcinfo_info_fields(package, srcinfo_content, repo)  :3032
#     def first(key)  :3039
#     def join(values)  :3043
# def print_info_fields(fields)  :3063
# def _print_info_summary(package, description, deps)  :3069
# def inspect_package(package, dest_root, refresh, target, source, sources, plain)  :3091
# def fetch_package(package, dest_root, refresh, source, sources, verify, min_trust, submodules)  :3124
# def _search_all_sources(alias, repo_url, regex, needle, limit, branch, subdir, dest_root)  :3150
# def _install_search_picks(selected, dest_root, explicit_url, branch, subdir, refresh, noconfirm)  :3203
# def build_parser()  :3251
# def main(argv)  :3544
#############
