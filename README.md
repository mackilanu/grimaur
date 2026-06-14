# grimaur

<img align="left" src="./base/assets/grimoire_d.svg#gh-light-mode-only" width="80" alt="grimaur logo">
<img align="left" src="./base/assets/grimoire_l.svg#gh-dark-mode-only" width="80" alt="grimaur logo">

`grimaur` is a lightweight package builder for Arch. It searches, builds, and updates
AUR packages (RPC API with **automatic fallback to the official git mirror**), and
because it just drives `makepkg`, it can build any `PKGBUILD` from any git source you
point it at.
<br clear="left">
## Install

### Deps
`sudo pacman -S --needed git base-devel`

### From Github/Python directly
   ```bash
   git clone https://github.com/mackilanu/grimaur
   cd grimaur
   ./grimaur <command> # try --help
   # or install globally makepkg -si
   ```

>[!TIP]
> You can use `grimaur fetch <package>` to inspect `PKGBUILD` and source code before
> manually installing using `makepkg` or similar.

Even see it directly: `python grimaur inspect brave-bin --target PKGBUILD`
Also accepts: `SRCINFO`

## Usage
### Search Packages
- `grimaur <term>` (or `grimaur search <term>`) lists matching packages.
   - Regex `"pattern-*"` automatically uses git mirror
   - Pass `--git-mirror` or `--aur-rpc` to force either.
- `grimaur list` to see installed "foreign" packages recognized by pacman -Qm

### Inspect & Install & Remove Packages

- `grimaur inspect <package> --full` Shows full depends
- `grimaur install <package>` clones the repo, resolves dependencies, builds with `makepkg`
   - Pass `--git-mirror` to skip AUR RPC
   - Pass `--use-ssh` use SSH instead of HTTPS
- `grimaur remove <package>` to uninstall from pacman
   - Pass `--clone` to delete the package's clone too
   - `grimaur remove --cache` drops the search result cache

### Build from other sources
The default source is the AUR. Point grimaur at anything else that ships a `PKGBUILD`
with `--repo-url`/`--repo` on `install`, `fetch`, `inspect`, `search`, and `update`:
- `--repo-url <url>` builds from a git URL (scheme optional: `github.com/u/r` works). A
  `tree`/`blob` link fills in the branch and subdir for you:
  `--repo-url https://provider.ext/<user>/<repo>/tree/<ref>/<subdir>`
- `--branch <ref>` / `--subdir <dir>` pick a ref, or a package nested in a monorepo
- `grimaur repo --add <url> <name>` saves an alias; use it with `--repo <name>`. Add more
  URLs under the same name for fallback mirrors. `--ls`/`--rm` to manage.
- `{pkg}` (the package name) or `{pkgbase}` (its pkgbase, looked up from the pacman sync
  DBs) in an alias URL select a repo-per-package forge. Arch's official packages live one
  repo each on GitLab, keyed by pkgbase, so `{pkgbase}` builds split packages too
  (`amd-ucode` -> `linux-firmware`):
   ```bash
   grimaur repo --add 'https://gitlab.archlinux.org/archlinux/packaging/packages/{pkgbase}.git' arch
   grimaur install <pkg> --repo arch   # builds an official package from source
   ```

The package name selects the source: a branch on the AUR mirror, or a repo/subdir via
`{pkg}`/`{pkgbase}` or monorepo layout. `search --repo <name>` lists a repo's packages
(one dir per package, or branches); templated aliases have no index so can't be searched.

### Stay Updated
- `grimaur update` rebuilds every installed “foreign” package that has a newer release.
   - Pass `--global` to update system first, then AUR packages
   - Pass `--global --system-only` for equivalent of `-Syu`
   - Pass `--global --index`, only sync package db `-Sy`
- `grimaur update <pkg1> <pkg2>` limits the update run to specific packages.
- `grimaur update --devel` Update all *-git packages aswell (needed for grimaur-git for example).
- Combine with `--refresh` to force a fresh pull of every tracked package.

### Additional Options

- Useful to build in `tmp/` pass `--dest-root` - (default: `$XDG_CACHE_HOME/grimaur` or `~/.cache/grimaur`)
- For automating updates `grimaur update`:
   - Pass `--global --download`, download updates without installing `-Syuw`
   - Pass `--global --install`, to be used with command above `-Su`
- Useful for scripting on top of Grimaur:
   - `--no-color` disables colored terminal output
   - `grimaur search <term> --limit 10` limits results to the first N matches
   - `grimaur search <term> --no-interactive` lists results without prompting to install
   - `grimaur search <term> --plain` pacman `-Ss` style two-line output for scripting (best match first)
   - `grimaur inspect <pkg> --plain` pacman `-Si` style `Key : Value` output for scripting
   - `grimaur list --aur` lists every AUR package, like yay/paru `-Sl aur`
- Force `grimaur fetch <package> --force` reclones even if the directory exists

### Details
- Respects `IgnorePkg = x y z` from `/etc/pacman.conf`
- Pass `--noconfirm` to skip prompts (install, update, remove, and search)
- Completions are also available and have cached search complete.

---
