# grimoire

<img align="left" src="./base/assets/grimoire_d.svg#gh-light-mode-only" width="80" alt="grimoire logo">
<img align="left" src="./base/assets/grimoire_l.svg#gh-dark-mode-only" width="80" alt="grimoire logo">

`grimoire` is a lightweight package builder for Arch. It searches, builds, and updates packages
because it just drives `makepkg`, it can build any `PKGBUILD` from any git source you point it at.
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
   - Regex `"pattern-*"` automatically uses git mirror
   - Pass `--git-mirror` or `--aur-rpc` to force either.
- `grimoire list` to see installed "foreign" packages recognized by pacman -Qm

### Inspect & Install & Remove Packages

- `grimoire inspect <package> --full` Shows full depends
- `grimoire install <package>` clones the repo, resolves dependencies, builds with `makepkg`
   - Pass `--git-mirror` to skip AUR RPC
   - Pass `--use-ssh` use SSH instead of HTTPS
- `grimoire remove <package>` to uninstall from pacman
   - Pass `--clone` to delete the package's clone too
   - `grimoire remove --cache` drops the search result cache

### Build from other sources
The default source is the top section of `repos.conf` (auto-seeded to `[ARCH]`; see below).
Point at anything else that ships a `PKGBUILD` with `--repo-url`/`--repo` on
`install`, `fetch`, `inspect`, `search`, and `update`:
   - `--repo-url <url>` builds from a git URL (scheme optional: `provider.ext/u/r` works).
   - `--branch <ref>` / `--subdir <dir>` pick a ref, or a package nested in a monorepo
   - `repo --add <url> <name>` saves an alias; use it with `--repo <name>`.
   - Add more URLs under the same name for fallback mirrors. `--ls`/`--rm` to manage. Saved to `~/.config/grimoire/repos.conf`
   - `{pkg}` (the package name) or `{pkgbase}` (its pkgbase, looked up from the pacman sync DBs)

   ```bash
   grimoire repo --add 'github.com/h8d13/VUR/tree/master/pkgs' VUR
   grimoire install <pkg>
   ```
A bare `search <term>` queries **every** section in `repos.conf` and merges the results.
`--repo <name>` searches only this repo.

See [`repos.conf.example`](./repos.conf.example) for examples.

The **first (top) section** in `repos.conf` is checked first:
On first use, **auto-creates** `~/.config/grimoire/repos.conf` with `[ARCH]` as the default.
AUR is opt-in (a commented `[AUR]` section with RPC + git-mirror URLs).

### Stay Updated
- `grimoire update` rebuilds every installed “foreign” package that has a newer release.
   - Pass `--global` to update system first, then AUR packages
   - Pass `--global --system-only` for equivalent of `-Syu`
   - Pass `--global --index`, only sync package db `-Sy`
- `grimoire update <pkg1> <pkg2>` limits the update run to specific packages.
- `grimoire update --devel` Update all *-git packages aswell (needed for grimoire-git for example).
- Combine with `--refresh` to force a fresh pull of every tracked package.

### Additional Options

- Useful to build in `tmp/` pass `--dest-root` - (default: `$XDG_CACHE_HOME/grimoire` or `~/.cache/grimoire`)
- For automating updates `grimoire update`:
   - Pass `--global --download`, download updates without installing `-Syuw`
   - Pass `--global --install`, to be used with command above `-Su`
- Useful for scripting on top of `grimoire`:
   - `--no-color` disables colored terminal output
   - `grimoire search <term> --limit 10` limits results to the first N matches
   - `grimoire search <term> --no-interactive` lists results without prompting to install
   - `grimoire search <term> --plain` pacman `-Ss` style two-line output for scripting (best match first)
   - `grimoire inspect <pkg> --plain` pacman `-Si` style `Key : Value` output for scripting
   - `grimoire list --aur` lists every AUR package, like yay/paru `-Sl aur`
- Force `grimoire fetch <package> --force` reclones even if the directory exists

### Details
- Respects `IgnorePkg = x y z` from `/etc/pacman.conf`
- Pass `--noconfirm` to skip prompts (install, update, remove, and search)
- Completions are also [available](./base/) and have cached search complete.

---
