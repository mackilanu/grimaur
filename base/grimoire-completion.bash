# Bash completion for grimoire helper
# Source this file or place it in bash_completion.d to enable `grimoire` completions.

_grimoire_completion()
{
    local cur prev words cword
    if ! _init_completion -n = 2>/dev/null; then
        words=("${COMP_WORDS[@]}")
        cword="${COMP_CWORD}"
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
    fi

    # Global options (can appear anywhere before subcommand)
    local global_opts="--dest-root --refresh --no-color --use-ssh --shallow -v --version"

    # Find the subcommand (first non-option word after potential global options)
    local subcmd=""
    local subcmd_idx=0
    for ((i=1; i<${#words[@]}; i++)); do
        if [[ "${words[i]}" != -* ]] && [[ "${words[i]}" != "" ]]; then
            subcmd="${words[i]}"
            subcmd_idx=$i
            break
        fi
    done

    # Handle --dest-root value completion (directory path)
    if [[ "$prev" == "--dest-root" ]]; then
        mapfile -t COMPREPLY < <(compgen -d -- "$cur")
        return 0
    fi

    # If current word starts with -, complete options
    if [[ "$cur" == -* ]]; then
        local opts="$global_opts"

        case "$subcmd" in
            fetch)
                opts="$global_opts --force --repo-url --repo --subdir --branch"
                ;;
            install)
                opts="$global_opts --noconfirm --repo-url --repo --subdir --branch"
                ;;
            remove)
                opts="$global_opts --noconfirm --clone --cache"
                ;;
            update)
                opts="$global_opts --noconfirm --devel --repo-url --repo --subdir --branch --global"
                ;;
            search)
                opts="$global_opts --limit --no-interactive --noconfirm --plain --repo-url --repo --subdir --branch"
                ;;
            inspect)
                opts="$global_opts --target --repo-url --repo --subdir --branch --plain"
                ;;
            list)
                opts="$global_opts --aur"
                ;;
            repo)
                opts="$global_opts --add --rm --ls"
                ;;
            "")
                # No subcommand yet, only show global options
                opts="$global_opts"
                ;;
        esac

        mapfile -t COMPREPLY < <(compgen -W "$opts" -- "$cur")
        return 0
    fi

    # Handle --target value completion for inspect
    if [[ "$prev" == "--target" ]] && [[ "$subcmd" == "inspect" ]]; then
        mapfile -t COMPREPLY < <(compgen -W "info PKGBUILD SRCINFO" -- "$cur")
        return 0
    fi

    # Handle --limit value completion (just suggest some numbers)
    if [[ "$prev" == "--limit" ]]; then
        mapfile -t COMPREPLY < <(compgen -W "10 20 50 100" -- "$cur")
        return 0
    fi

    # If no subcommand yet, complete subcommands
    if [[ -z "$subcmd" ]]; then
        local subcmds="fetch install remove update search inspect list repo"
        mapfile -t COMPREPLY < <(compgen -W "$subcmds" -- "$cur")
        return 0
    fi

    # Complete package names based on subcommand
    case "$subcmd" in
        remove|update)
            # Complete with installed foreign packages
            local packages
            packages=$(pacman -Qmq 2>/dev/null)
            mapfile -t COMPREPLY < <(compgen -W "$packages" -- "$cur")
            ;;
        install|fetch|inspect|search)
            # Complete AUR names from the cache grimoire writes alongside
            # packages.json; seed it in the background on first use.
            local cache="${XDG_CACHE_HOME:-$HOME/.cache}/grimoire/completion.cache"
            if [[ -r "$cache" ]]; then
                mapfile -t COMPREPLY < <(grep -- "^$cur" "$cache" 2>/dev/null | head -200)
            else
                (grimoire list --repo AUR >/dev/null 2>&1 &)
            fi
            ;;
        *)
            # list, repo: no positional completion
            ;;
    esac
}

complete -F _grimoire_completion grimoire
