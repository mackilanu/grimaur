# Fish completion for grimoire helper
# Place in ~/.config/fish/completions/ or /usr/share/fish/vendor_completions.d/

set -l commands fetch install remove update search inspect list

# Complete AUR names from the cache grimoire writes alongside packages.json;
# seed it in the background on first use.
function __grimaur_aur_packages
    set -l cache_home $XDG_CACHE_HOME
    test -n "$cache_home"; or set cache_home ~/.cache
    set -l cache $cache_home/grimoire/completion.cache
    if test -r $cache
        grep -- "^"(commandline -ct) $cache 2>/dev/null | head -200
    else
        grimoire list --aur >/dev/null 2>&1 &
        disown 2>/dev/null
    end
end

function __grimaur_foreign_packages
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

# Global flags (valid before or after the subcommand)
complete -c grimoire -l dest-root -x -a "(__fish_complete_directories (commandline -ct))" -d 'Directory to store cloned packages'
complete -c grimoire -l refresh -d 'Refresh existing clones before use'
complete -c grimoire -l no-color -d 'Disable colored output'
complete -c grimoire -l aur-rpc -d 'Force AUR RPC; no git-mirror fallback'
complete -c grimoire -l git-mirror -d 'Use git mirror instead of AUR RPC'
complete -c grimoire -l use-ssh -d 'Use SSH instead of HTTPS for git operations'
complete -c grimoire -l shallow -d 'Use shallow clones (--depth=1)'
complete -c grimoire -l version -d 'Show version'

# fetch
complete -c grimoire -n '__fish_seen_subcommand_from fetch' -l force -d 'Reclone even if directory exists'
complete -c grimoire -n '__fish_seen_subcommand_from fetch install inspect' -l repo-url -x -d 'Clone from custom Git URL'

# install / remove / update / search
complete -c grimoire -n '__fish_seen_subcommand_from install remove update search' -l noconfirm -d 'Skip confirmation prompts'
complete -c grimoire -n '__fish_seen_subcommand_from remove' -l clone -d "Also remove the package's clone"
complete -c grimoire -n '__fish_seen_subcommand_from remove' -l cache -d 'Remove the search result cache'
complete -c grimoire -n '__fish_seen_subcommand_from update' -l devel -d 'Include VCS/devel packages'
complete -c grimoire -n '__fish_seen_subcommand_from update' -l global -d 'Update official repositories first'
complete -c grimoire -n '__fish_seen_subcommand_from update' -l system-only -d 'With --global, skip AUR updates'
complete -c grimoire -n '__fish_seen_subcommand_from update' -l index -d 'With --global, only sync databases'
complete -c grimoire -n '__fish_seen_subcommand_from update' -l download -d 'With --global, download without installing'
complete -c grimoire -n '__fish_seen_subcommand_from update' -l install -d 'With --global, install downloaded updates'

# search
complete -c grimoire -n '__fish_seen_subcommand_from search' -l limit -x -a '10 20 50 100' -d 'Limit results'
complete -c grimoire -n '__fish_seen_subcommand_from search' -l no-interactive -d 'Disable interactive selection'
complete -c grimoire -n '__fish_seen_subcommand_from search inspect' -l plain -d 'Plain pacman-style output for scripting'

# inspect
complete -c grimoire -n '__fish_seen_subcommand_from inspect' -l target -x -a 'info PKGBUILD SRCINFO' -d 'Which data to show'
complete -c grimoire -n '__fish_seen_subcommand_from inspect' -l full -d 'Include make/check/optional dependencies'

# list
complete -c grimoire -n '__fish_seen_subcommand_from list' -l aur -d 'List every AUR package (like -Sl aur)'

# Package positionals
complete -c grimoire -n '__fish_seen_subcommand_from install fetch inspect search' -a '(__grimaur_aur_packages)'
complete -c grimoire -n '__fish_seen_subcommand_from remove update' -a '(__grimaur_foreign_packages)' -d 'installed'
