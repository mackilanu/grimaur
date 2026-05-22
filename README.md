# grimaur

<img align="left" src="./base/assets/grimoire_d.svg#gh-light-mode-only" width="80" alt="grimaur logo">
<img align="left" src="./base/assets/grimoire_l.svg#gh-dark-mode-only" width="80" alt="grimaur logo">

`grimaur` is a lightweight AUR helper that searches, builds, and updates AUR packages. It uses the AUR RPC
API and **automatically falls back to the official git mirror when the endpoint is unavailable.**

<br clear="left">

> [!TIP]
> When the AUR is down, for example: `grimaur <package> --git-mirror` bypasses the RPC entirely, this ensures 100% uptime. **Regex** implies git mirror by default between `""`.

## Install

### Deps
`sudo pacman -S --needed git base-devel`

#### Directly from the AUR
   ```bash
   git clone https://aur.archlinux.org/grimaur-git.git
   cd grimaur-git
   makepkg -si
   ```

#### From the git mirror
   ```bash
   git clone --branch grimaur-git --single-branch https://github.com/archlinux/aur.git grimaur-git
   cd grimaur-git
   makepkg -si
   ```

#### From Python directly
   ```bash
   git clone https://github.com/ryk4rd/grimaur
   cd grimaur
   chmod +x grimaur
   ./grimaur <command>
   ```

## Usage
### Search Packages
- `grimaur <term>` (or `grimaur search <term>`) lists matching packages and lets you pick one to install.
   - Regex "pattern-*"` automatically uses git mirror
   - Pass `--git-mirror` when endpoint is down
- `grimaur list` to see installed "foreign" packages recognized by pacman -Qm

>[!NOTE]
> You can use `grimaur fetch <package>` to inspect `PKGBUILD` and source code before manually installing using `makepkg` or similar.

Even see it directly: `python grimaur inspect brave-bin --target PKGBUILD` Also accepts: `SRCINFO`

### Inspect & Install & Remove Packages

- `grimaur inspect <package> --full` Shows full depends
- `grimaur install <package>` clones the repo, resolves dependencies, builds with `makepkg`
   - Pass `--git-mirror` to skip AUR RPC
   - Pass `--use-ssh` use SSH instead of HTTPS
- `grimaur remove <package>` to uninstall from pacman
   - Pass `--remove-cache` to delete cached files too
-  `grimaur install/fetch/inspect mypkg --repo-url <url>` to use custom URL instead

### Stay Updated
- `grimaur update` rebuilds every installed “foreign” package that has a newer release.
   - Pass `--global` to update system first, then AUR packages
   - Pass `--global --system-only` for equivalent of `-Syu`
   - Pass `--global --index`, only sync package db `-Sy`

- `grimaur update <pkg1> <pkg2>` limits the update run to specific packages.
- `grimaur update --devel` Update all *-git packages aswell (needed for grimaur-git for example).
- Combine with `--refresh` to force a fresh pull of every tracked package.

### Additional Options

- Useful to build in `tmp/` pass `--dest-root` - (default: `~/.cache/aurgit`) 
- For automating updates `grimaur update`:
   - Pass `--global --download`, download updates without installing `-Syuw`
   - Pass `--global --install`, to be used with command above `-Su`
- Useful for scripting on top of Grimaur
   - `--no-color` disables colored terminal output 
   - `grimaur search <term> --limit 10` limits results to the first N matches 
   - `grimaur search <term> --no-interactive` lists results without prompting to install
- Force `grimaur fetch <package> --force` reclones even if the directory exists
- Complete example: `python grimaur --use-ssh search "brave.*-bin" --no-interactive`

### Details
- Respects `IgnorePkg = x y z` from `/etc/pacman.conf`
- Pass `--noconfirm` to skip prompts (install, update, remove, and search)

---
