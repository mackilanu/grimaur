# Fish completion for grimoire helper
# Place in ~/.config/fish/completions/ or /usr/share/fish/vendor_completions.d/

set -l commands fetch install remove update search inspect list repo

# Complete AUR names from the cache grimoire writes alongside packages.json;
# seed it in the background on first use.
function __grimoire_aur_packages
    set -l cache_home $XDG_CACHE_HOME
    test -n "$cache_home"; or set cache_home ~/.cache
    set -l cache $cache_home/grimoire/completion.cache
    if test -r $cache
        grep -- "^"(commandline -ct) $cache 2>/dev/null | head -200
    else
        grimoire list --repo AUR >/dev/null 2>&1 &
        disown 2>/dev/null
    end
end

function __grimoire_foreign_packages
    pacman -Qmq 2>/dev/null
end

# No file completion by default; positionals are package names
complete -c grimoire -f

# Subcommands
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a fetch -d 'Clone the package branch locally'
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a install -d 'Resolve dependencies and build/install a package'
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a remove -d 'Remove an installed package'
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a update -d 'Upgrade installed foreign packages'
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a search -d 'Search packages via the configured backend'
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a inspect -d 'Show PKGBUILD or dependency information'
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a list -d 'List installed foreign (AUR) packages'
complete -c grimoire -n "not __fish_seen_subcommand_from $commands" -a repo -d 'Manage repo URL aliases in repos.conf'

# Global flags (valid before or after the subcommand)
complete -c grimoire -l dest-root -x -a "(__fish_complete_directories (commandline -ct))" -d 'Directory to store cloned packages'
complete -c grimoire -l refresh -d 'Refresh existing clones before use'
complete -c grimoire -l no-color -d 'Disable colored output'
complete -c grimoire -l use-ssh -d 'Use SSH instead of HTTPS for git operations'
complete -c grimoire -l shallow -d 'Use shallow clones (--depth=1)'
complete -c grimoire -s v -l version -d 'Show version'

# Source selection (fetch / install / update / search / inspect)
complete -c grimoire -n '__fish_seen_subcommand_from fetch install update search inspect' -l repo-url -x -d 'Clone from custom Git URL'
complete -c grimoire -n '__fish_seen_subcommand_from fetch install update search inspect' -l repo -x -d 'Use a registered repo alias as the mirror list'
complete -c grimoire -n '__fish_seen_subcommand_from fetch install update search inspect' -l subdir -x -d 'Build from this subdirectory of the repo'
complete -c grimoire -n '__fish_seen_subcommand_from fetch install update search inspect' -l rev -x -d 'Git revision to check out: branch, tag, or commit'

# --noconfirm (install / remove / update / search)
complete -c grimoire -n '__fish_seen_subcommand_from install remove update search' -l noconfirm -d 'Skip confirmation prompts'

# --verify (fetch / install)
complete -c grimoire -n '__fish_seen_subcommand_from fetch install' -l verify -d 'Require a valid GPG signature (git verify-tag/-commit; no trust check)'

# remove
complete -c grimoire -n '__fish_seen_subcommand_from remove' -l clone -d "Also remove the package's clone"
complete -c grimoire -n '__fish_seen_subcommand_from remove' -l cache -d 'Remove the search result cache'

# update
complete -c grimoire -n '__fish_seen_subcommand_from update' -l devel -d 'Include VCS/devel packages'
complete -c grimoire -n '__fish_seen_subcommand_from update' -l global -d 'Update system packages first'

# search
complete -c grimoire -n '__fish_seen_subcommand_from search' -l limit -x -a '10 20 50 100' -d 'Limit results'
complete -c grimoire -n '__fish_seen_subcommand_from search' -l no-interactive -d 'Disable interactive selection'
complete -c grimoire -n '__fish_seen_subcommand_from search inspect' -l plain -d 'Plain pacman-style output for scripting'

# inspect
complete -c grimoire -n '__fish_seen_subcommand_from inspect' -l target -x -a 'info PKGBUILD SRCINFO' -d 'Which data to show'

# list
complete -c grimoire -n '__fish_seen_subcommand_from list' -l repo -d 'List every package in repo NAME (e.g. AUR)'

# repo
complete -c grimoire -n '__fish_seen_subcommand_from repo' -l add -x -d 'Register URL as a mirror under alias NAME'
complete -c grimoire -n '__fish_seen_subcommand_from repo' -l rm -x -d 'Remove alias NAME from the registry'
complete -c grimoire -n '__fish_seen_subcommand_from repo' -l ls -d 'List registered aliases and their mirror URLs'

# Package positionals
complete -c grimoire -n '__fish_seen_subcommand_from install fetch inspect search' -a '(__grimoire_aur_packages)'
complete -c grimoire -n '__fish_seen_subcommand_from remove update' -a '(__grimoire_foreign_packages)' -d 'installed'
