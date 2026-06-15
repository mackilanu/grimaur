#compdef grimoire
# file usr/share/zsh/site-functions/_grimoire

_grimoire() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    local -a global_opts
    global_opts=(
        '--dest-root[Directory to store cloned packages]:directory:_directories'
        '--refresh[Refresh existing clones before use]'
        '--no-color[Disable colored output]'
        '--use-ssh[Use SSH instead of HTTPS for git operations]'
        '--shallow[Use shallow clones (--depth=1); default is full history]'
        '(-v --version)'{-v,--version}'[Show version]'
    )

    # Source-selection flags shared by fetch / install / update / search / inspect
    local -a source_opts
    source_opts=(
        '--repo-url[Clone from custom Git URL]:url:'
        '--repo[Use a registered repo alias as the mirror list]:name:'
        '--subdir[Build from this subdirectory of the repo]:subdir:'
        '--rev[Git revision to check out: branch, tag, or commit]:rev:'
    )

    _arguments -C \
        $global_opts \
        '1: :->command' \
        '*:: :->args' \
        && return 0

    case $state in
        command)
            local -a commands
            commands=(
                'fetch:Clone the package branch locally'
                'install:Resolve dependencies and build/install a package'
                'remove:Remove an installed package'
                'update:Upgrade installed foreign packages'
                'search:Search packages via the configured backend'
                'inspect:Show PKGBUILD or dependency information'
                'list:List installed foreign (AUR) packages'
                'repo:Manage repo URL aliases in repos.conf'
            )
            _describe -t commands 'grimoire command' commands
            ;;
        args)
            case $line[1] in
                fetch)
                    _arguments \
                        $global_opts \
                        $source_opts \
                        '--verify[Require a valid GPG signature (git verify-tag/-commit; no trust check)]' \
                        '1:package:_grimoire_aur_packages'
                    ;;
                install)
                    _arguments \
                        $global_opts \
                        $source_opts \
                        '--noconfirm[Skip confirmation prompts]' \
                        '--verify[Require a valid GPG signature (git verify-tag/-commit; no trust check)]' \
                        '1:package:_grimoire_aur_packages'
                    ;;
                remove)
                    _arguments \
                        $global_opts \
                        '--noconfirm[Skip confirmation prompts]' \
                        "--clone[Also remove the package's clone]" \
                        '--cache[Remove the search result cache]' \
                        '1::package:_grimoire_foreign_packages'
                    ;;
                update)
                    _arguments \
                        $global_opts \
                        $source_opts \
                        '--noconfirm[Skip confirmation prompts]' \
                        '--devel[Include VCS/devel packages]' \
                        '--global[Update system packages first]' \
                        '*:packages:_grimoire_foreign_packages'
                    ;;
                search)
                    _arguments \
                        $global_opts \
                        $source_opts \
                        '--limit[Limit results]:number:(10 20 50 100)' \
                        '--no-interactive[Disable interactive selection]' \
                        '--noconfirm[Skip confirmation prompts]' \
                        '--plain[Plain pacman-style output for scripting]' \
                        '1:pattern:_grimoire_aur_packages'
                    ;;
                inspect)
                    _arguments \
                        $global_opts \
                        $source_opts \
                        '--target[Which data to show]:target:(info PKGBUILD SRCINFO)' \
                        '--plain[Plain pacman-style output for scripting]' \
                        '1:package:_grimoire_aur_packages'
                    ;;
                list)
                    _arguments \
                        $global_opts \
                        '--repo[List every package in repo NAME (e.g. AUR)]:repo:'
                    ;;
                repo)
                    _arguments \
                        $global_opts \
                        '--add[Register URL as a mirror under alias NAME]:url: :name:' \
                        '--rm[Remove alias NAME from the registry]:name:' \
                        '--ls[List registered aliases and their mirror URLs]'
                    ;;
            esac
            ;;
    esac
}

# Helper function to complete installed foreign packages
_grimoire_foreign_packages() {
    local -a packages
    packages=(${(f)"$(pacman -Qmq 2>/dev/null)"})
    _describe -t packages 'installed package' packages
}

# Complete AUR names from the cache grimoire writes alongside packages.json;
# prefix-grep instead of _describe: the full list is ~115k entries.
_grimoire_aur_packages() {
    local cache="${XDG_CACHE_HOME:-$HOME/.cache}/grimoire/completion.cache"
    if [[ -r "$cache" ]]; then
        local -a packages
        packages=(${(f)"$(grep -- "^${PREFIX}" "$cache" 2>/dev/null | head -200)"})
        compadd -a packages
    else
        (grimoire list --repo AUR >/dev/null 2>&1 &)
    fi
}

_grimoire "$@"
