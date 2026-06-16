# grimoire

<img align="left" src="./base/assets/grimoire_d.svg#gh-light-mode-only" width="80" alt="grimoire logo">
<img align="left" src="./base/assets/grimoire_l.svg#gh-dark-mode-only" width="80" alt="grimoire logo">

`grimoire` is a lightweight package builder for Arch. It searches, builds, and updates packages
because it drives `git` & `makepkg`, it can build [`PKGBUILD`](https://wiki.archlinux.org/title/PKGBUILD) from **any git source you point it at.**

<br clear="left">

## Install

### Deps
`sudo pacman -S --needed git base-devel`

### From Github/Python directly
   ```bash
   git clone https://github.com/mackilanu/grimaur
   cd grimaur
   ./grimoire <command> # try --help
   # or install globally makepkg -si
   ```

>[!TIP]
> You can use `grimoire fetch <package>` to inspect `PKGBUILD` and source code before
> manually installing using `makepkg` or similar.

Even see it directly: `python grimoire inspect base --target PKGBUILD`
Also accepts: `SRCINFO` and `info`

## Usage

### Search Packages
- `grimoire <term>` (or `grimoire search <term>`) lists matching packages.
   - Plain text or a regex `"pattern-*"`.
- `grimoire list` to see installed "foreign" packages recognized by `pacman -Qm`

### Inspect & Install & Remove Packages

`inspect`, `install`, `fetch`, and `remove` accept one or more packages (`grimoire install a b c`).

- `grimoire inspect <package>` shows description + all deps (make/check/optional)
- `grimoire install <package>` clones the repo, resolves dependencies, builds
   - Pass `--noconfirm` to skip prompts (install, update, remove, and search)
   - Pass `--use-ssh` use SSH instead of HTTPS
   - Pass `--submod` (install/fetch) to init the repo's git submodules after checkout.
- `grimoire remove <package>` to uninstall from pacman
- `grimoire clean` drops the search result cache (and completion cache)
   - `grimoire clean <package>` removes just that package's clone (leaves the install)
   - Pass `--clones` to remove every cloned package build tree

### Build from other sources

With no `--repo`, sources are tried in `repos.ini` order (top first); the first that has
the package wins, the rest are fallbacks. `repos.ini` is auto-seeded to `[ARCH]` official Gitlab.
Point at anything else that ships a `PKGBUILD` with `--repo-url`/`--repo` on
`install`, `fetch`, `inspect`, `search`, and `update`:
   - `--repo-url <url>` builds from a git URL (scheme optional: `provider.ext/u/r` works).
   - `--rev <branch|tag|commit>` / `--subdir <dir>` pick a revision, or a package nested in a monorepo
   - `repo --add <url> <name>` saves an alias; use it with `--repo <name>`.
   - Add more URLs under the same name for fallback mirrors. `--ls`/`--rm` to manage.
   - `{pkg}` (the package name) or `{pkgbase}` (its pkgbase ex: amd-ucode -> linux-firmware)

   ```bash
   grimoire repo --add 'provider.ext/user/repo/tree/master/pkgs' MYVUR
   grimoire install <pkg>
   ```
A bare `search <term>` queries **every** section in `repos.ini` and merges the results.
`--repo <name>` searches only this specific repo and precedes the `.conf`.

See [`repos.ini`](./repos.ini) for examples.

Section order is precedence: `install`/`fetch`/`inspect`/`update` walk sections top to
bottom and build from the first that has the package.

On first use, **auto-creates** `~/.config/grimoire/repos.ini` with `[ARCH]` as the default.

### Stay Updated

- `grimoire update` rebuilds every installed “foreign” package that has a newer release.
   - Pass `--global` to update system first, then AUR packages.
- `grimoire update <pkg1> <pkg2>` limits the update run to specific packages.
- `grimoire update --devel` Update all `*-git` packages aswell (needed for `grimoire-git` for example).

`update` re-pulls every tracked package already; no `--refresh` needed.

---

<details>
<summary>Additional Options & Scripting</summary>

### Additional Options

- Useful to build in `tmp/` pass `--dest-root` - (default: `$XDG_CACHE_HOME/grimoire`)
- `--refresh` (global) re-pulls existing clones and expires the search cache; applies to `fetch`/`install`/`inspect`/`search`.

### Scripting on top of `grimoire`:
   - `--no-color` disables colored terminal output
   - `grimoire search <term> --limit 10` limits results to the first N matches
   - `grimoire search <term> --no-interactive` lists results without prompting to install
   - `grimoire search <term> --plain` pacman `-Ss` style two-line output for scripting (best match first)
   - `grimoire inspect <pkg> --plain` pacman `-Si` style `Key : Value` output for scripting
   - `grimoire list --repo <name>` lists every package in a repo `REPO Pkg Version`

</details>

<details>
<summary>More info & cryptographic trust</summary>

### More info

- Respects `IgnorePkg = x y z` from `/etc/pacman.conf`
- Completions are also [available](./base/) and have cached search complete.

#### Sources/References:

- Arch Package [Guidelines](https://wiki.archlinux.org/title/Arch_package_guidelines)
- Man pages:
   - [git.1](https://www.kernel.org/pub/software/scm/git/docs/git.html)
   - [makepkg.8](https://man.archlinux.org/man/makepkg.8)
   - [PKGBUILD.5](https://man.archlinux.org/man/PKGBUILD.5)
   - [pacman.8](https://man.archlinux.org/man/pacman.8)
   - [vercmp.8](https://man.archlinux.org/man/vercmp.8)
   - [find-libprovides.1](https://man.archlinux.org/man/find-libprovides.1)
   - [updpkgsums.8](https://man.archlinux.org/man/updpkgsums.8)

Tools:
- `pacman-contrib` https://archlinux.org/packages/extra/x86_64/pacman-contrib/
- `devtools` https://archlinux.org/packages/extra/any/devtools/

Packaging examples [proto](https://gitlab.archlinux.org/pacman/pacman/-/tree/master/proto)

### Git-GPG Trust

- Pass `--verify` (`install`/`fetch`) to require a valid GPG signature before building.
If you point at an annotated tag (`--rev <tag>`) it runs `git verify-tag`, else `git verify-commit`
on the checked-out HEAD commit.

- Aborts if the target is unsigned, has a bad signature, or the signer's key isn't in your keyring:
`gpg --recv-keys <fingerprint>`.

- By default this checks signature *validity*, not key *trust* (a good signature from any key you
hold passes). To also gate on owner-trust, pass `--min-trust <level>` (implies `--verify`) at one of
3 levels: `marginal`, `fully`, or `ultimate`. Establish trust first (`gpg --edit-key <fpr>` → `trust`,
or import ownertrust); a freshly received key is untrusted and will be rejected.

</details>

---

<div align="center">

Made with ♡

[Star this repo](https://github.com/mackilanu/grimaur) · [Bugs/Features](https://github.com/mackilanu/grimaur/issues/new) · [Discussions](https://github.com/mackilanu/grimaur/discussions)

</div>
