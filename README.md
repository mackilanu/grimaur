# grimoire

<img align="left" src="./base/assets/grimoire_d.svg#gh-light-mode-only" width="80" alt="grimoire logo">
<img align="left" src="./base/assets/grimoire_l.svg#gh-dark-mode-only" width="80" alt="grimoire logo">

`grimoire` is a lightweight package builder for Arch. It searches, builds, and updates packages
because it drives `git` & `makepkg`, it can build `PKGBUILD`s from **any git source you point it at.**

<br clear="left">

## Install

### Deps
`sudo pacman -S --needed git base-devel`

### From Github/Python directly
   ```bash
   git clone https://github.com/mackilanu/grimoire
   cd grimoire
   ./grimoire <command> # try --help
   # or install globally makepkg -si
   ```

>[!TIP]
> You can use `grimoire fetch <package>` to inspect `PKGBUILD` and source code before
> manually installing using `makepkg` or similar.

Even see it directly: `python grimoire inspect brave-bin --target PKGBUILD`
Also accepts: `SRCINFO`

## Usage

### Search Packages
- `grimoire <term>` (or `grimoire search <term>`) lists matching packages.
   - Plain text or a regex `"pattern-*"`.
- `grimoire list` to see installed "foreign" packages recognized by `pacman -Qm`

### Inspect & Install & Remove Packages

`inspect`, `install`, `fetch`, and `remove` accept one or more packages (`grimoire install a b c`).

- `grimoire inspect <package>` shows description + all deps (make/check/optional)
- `grimoire install <package>` clones the repo, resolves dependencies, builds with `makepkg`
   - Pass `--use-ssh` use SSH instead of HTTPS
- `grimoire remove <package>` to uninstall from pacman
   - Pass `--clone` to delete the package's clone too
   - `grimoire remove --cache` drops the search result cache

### Build from other sources

With no `--repo`, sources are tried in `repos.conf` order (top first); the first that has
the package wins, the rest are fallbacks. `repos.conf` is auto-seeded to `[ARCH]` official Gitlab.
Point at anything else that ships a `PKGBUILD` with `--repo-url`/`--repo` on
`install`, `fetch`, `inspect`, `search`, and `update`:
   - `--repo-url <url>` builds from a git URL (scheme optional: `provider.ext/u/r` works).
   - `--rev <branch|tag|commit>` / `--subdir <dir>` pick a revision, or a package nested in a monorepo
   - `repo --add <url> <name>` saves an alias; use it with `--repo <name>`.
   - Add more URLs under the same name for fallback mirrors. `--ls`/`--rm` to manage. Saved to `~/.config/grimoire/repos.conf`
   - `{pkg}` (the package name) or `{pkgbase}` (its pkgbase, looked up from the pacman sync DBs)

   ```bash
   grimoire repo --add 'github.com/h8d13/VUR/tree/master/pkgs' VUR
   grimoire install <pkg>
   ```
A bare `search <term>` queries **every** section in `repos.conf` and merges the results.
`--repo <name>` searches only this specific repo and precedes the `.conf`.

See [`repos.conf.example`](./repos.conf.example) for examples.

Section order is precedence: `install`/`fetch`/`inspect`/`update` walk sections top to
bottom and build from the first that has the package. On first use, **auto-creates**
`~/.config/grimoire/repos.conf` with `[ARCH]` as the default.

### Cryptographic trust

- Pass `--verify` (install/fetch) to require a valid GPG signature before building. If you point at an annotated tag (`--rev <tag>`) it runs `git verify-tag` on it (for projects that sign releases, not every commit); otherwise it runs `git verify-commit` on HEAD. Aborts if the target is unsigned, has a bad signature, or the signer's key isn't in your keyring:  `gpg --recv-keys <fingerprint>`. Checks signature validity, not key trust.



### Stay Updated

- `grimoire update` rebuilds every installed “foreign” package that has a newer release.
   - Pass `--global` to update system first, then AUR packages.
- `grimoire update <pkg1> <pkg2>` limits the update run to specific packages.
- `grimoire update --devel` Update all `*-git` packages aswell (needed for `grimoire-git` for example).

`update` re-pulls every tracked package already; no `--refresh` needed.

### Additional Options

- Useful to build in `tmp/` pass `--dest-root` - (default: `$XDG_CACHE_HOME/grimoire`)
- `--refresh` (global) re-pulls existing clones and expires the search cache; applies to `fetch`/`install`/`inspect`/`search`.
- Useful for scripting on top of `grimoire`:
   - `--no-color` disables colored terminal output
   - `grimoire search <term> --limit 10` limits results to the first N matches
   - `grimoire search <term> --no-interactive` lists results without prompting to install
   - `grimoire search <term> --plain` pacman `-Ss` style two-line output for scripting (best match first)
   - `grimoire inspect <pkg> --plain` pacman `-Si` style `Key : Value` output for scripting
   - `grimoire list --repo <name>` lists every package in a repo `REPO Pkg Version`

### Details
- Respects `IgnorePkg = x y z` from `/etc/pacman.conf`
- Pass `--noconfirm` to skip prompts (install, update, remove, and search)
- Completions are also [available](./base/) and have cached search complete.

---

<div align="center">

Made with ♡

[Star this repo](https://github.com/mackilanu/grimoire) · [Bugs/Features](https://github.com/mackilanu/grimoire/issues/new) · [Discussions](https://github.com/mackilanu/grimoire/discussions)

</div>
