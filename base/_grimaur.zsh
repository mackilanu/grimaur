#compdef grimaur 
# file usr/share/zsh/site-functions/_grimaur

_grimaur() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    local -a global_opts
    global_opts=(
        '--dest-root[Directory to store cloned packages]:directory:_directories'
        '--refresh[Refresh existing clones before use]'
        '--no-color[Disable colored output]'
        '--aur-rpc[Use AUR RPC API (default)]'
        '--git-mirror[Use git mirror instead of AUR RPC]'
        '--use-ssh[Use SSH instead of HTTPS for git operations]'
        '--shallow[Use shallow clones (--depth=1); default is full history]'
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
            )
            _describe -t commands 'grimaur command' commands
            ;;
        args)
            case $line[1] in
                fetch)
                    _arguments \
                        $global_opts \
                        '--force[Reclone even if directory exists]' \
                        '--repo-url[Clone from custom Git URL]:url:' \
                        '1:package:'
                    ;;
                install)
                    _arguments \
                        $global_opts \
                        '--noconfirm[Pass --noconfirm to pacman/makepkg]' \
                        '--repo-url[Clone from custom Git URL]:url:' \
                        '1:package:'
                    ;;
                remove)
                    _arguments \
                        $global_opts \
                        '--noconfirm[Pass --noconfirm to pacman]' \
                        '--remove-cache[Also remove the cached clone]' \
                        '1:package:_grimaur_foreign_packages'
                    ;;
                update)
                    _arguments \
                        $global_opts \
                        '--noconfirm[Pass --noconfirm to pacman/makepkg]' \
                        '--devel[Include VCS/devel packages]' \
                        '--global[Update official repositories with pacman -Syu first]' \
                        '--system-only[With --global, only update system packages and skip AUR updates]' \
                        '--index[With --global, only sync package databases (pacman -Sy)]' \
                        '--download[With --global, download updates without installing (pacman -Syuw)]' \
                        '--install[With --global, install already-downloaded packages (pacman -Su)]' \
                        '*:packages:_grimaur_foreign_packages'
                    ;;
                search)
                    _arguments \
                        $global_opts \
                        '--limit[Limit results]:number:(10 20 50 100)' \
                        '--no-interactive[Disable interactive selection]' \
                        '--noconfirm[Skip confirmation prompts]' \
                        '1:pattern:'
                    ;;
                inspect)
                    _arguments \
                        $global_opts \
                        '--target[Which data to show]:target:(info PKGBUILD SRCINFO)' \
                        '--full[Include make/check/optional dependencies]' \
                        '--repo-url[Inspect package from custom Git URL]:url:' \
                        '1:package:'
                    ;;
                list)
                    _arguments $global_opts
                    ;;
            esac
            ;;
    esac
}

# Helper function to complete installed foreign packages
_grimaur_foreign_packages() {
    local -a packages
    packages=(${(f)"$(pacman -Qmq 2>/dev/null)"})
    _describe -t packages 'installed package' packages
}

_grimaur "$@"
